"""Workflow invariant check (StegVerse-org/.github#160 issuecomment-6353130407, section 2 rank 6; C1, C3, I9).

A deterministic, stdlib-only verifier. Lowest supported operating mode: E0 (ecosystem only, no LLM;
#160 issuecomment-6354238464). It replaces LLM invariant audits with a check that can be made a
required pull_request check. It never reads a clock, the network or a secret, and it changes nothing.

Rules (each refusal carries the six fields; the first refusal in file/line order is ``first_refusal``):

  WORKFLOW_DISPATCH_TRIGGER_PRESENT   a workflow ``on:`` names workflow_dispatch or repository_dispatch
  SCHEDULE_TRIGGER_PRESENT            a workflow ``on:`` names schedule (cron)
  EXTERNAL_POLLING_PRESENT            a workflow run step loops on sleep (while/until/for ... sleep)
  EXTERNAL_MACHINE_PREREQUISITE       runs-on self-hosted; a systemd unit file (.service/.timer/.socket/.path);
                                      a run step that enables or starts a service (systemctl/launchctl/crontab)
  NEW_THIRD_PARTY_ACTION              a ``uses:`` that is not a local action or the pinned allowlist, or is
                                      not pinned to a 40-hex commit (diff mode: only uses new at head)
  NEW_THIRD_PARTY_IMPORT              a Python import that is neither stdlib nor a module of this repository
                                      (diff mode: only imports new at head); a changed dependency manifest;
                                      a new pip/npm install in a run step
  CLOCK_READ_IN_RECEIPT               a Python call to time.time/time.time_ns/datetime.now/utcnow/today/date.today
                                      in a resident-runtime, org-kernel or tvc source file, or ``date +%s`` in a run step
  AI_SESSION_GATE_PRESENT             an AI_SESSION_GATE name in a workflow, or as a Python identifier

Modes:
  --base B --head H   pull_request mode: only files changed in B..H, read at H; "new" is relative to B.
                      Exit 1 when any refusal is found (usable as a required check).
  --all               census of the whole tree at HEAD; prints every finding, exit 0 (a report, not a gate).
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "stegverse.workflow-invariant-check/v1"
LOWEST_SUPPORTED_MODE = "E0"
CHECK_ID = "WORKFLOW_INVARIANTS_HOLD"
ENTRYPOINT = ".github/workflows/workflow-invariant-check.yml (pull_request) / resident-runtime/workflow_invariant_check.py"
GOAL = "ENTERPRISE-HOST-PROVIDER-ERADICATION-001 (StegVerse-org/.github#166)"
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")

# Actions already used across the federation, pinned by commit (M-P9, StegVerse-org/.github#215).
ALLOWED_ACTION_OWNERS = ("actions/",)
ALLOWED_REUSABLE_PREFIXES = ("StegVerse-org/.github/.github/workflows/",)
SHA40 = re.compile(r"^[0-9a-f]{40}$")
# First-party federation packages (StegVerse-org/StegVerse-SDK is checked out into ./sdk and installed from that path).
FIRST_PARTY_PACKAGES = frozenset({"stegverse"})

RULES: dict[str, dict[str, str]] = {
    "WORKFLOW_DISPATCH_TRIGGER_PRESENT": {
        "failed_predicate": "ACTIONS_BY_MANIFEST_STATE_TRANSITION_TRIGGER_ONLY",
        "required_evidence_or_repair": "replace the trigger with pull_request, push or workflow_run; a request trigger is a human or LLM gate",
        "next_attempt": "the next push to the PR head"},
    "SCHEDULE_TRIGGER_PRESENT": {
        "failed_predicate": "ACTIONS_BY_MANIFEST_STATE_TRANSITION_TRIGGER_ONLY",
        "required_evidence_or_repair": "remove the schedule; drive the work from the state transition that makes it due",
        "next_attempt": "the next push to the PR head"},
    "EXTERNAL_POLLING_PRESENT": {
        "failed_predicate": "NO_POLLING",
        "required_evidence_or_repair": "remove the sleep loop; consume the transition (workflow_run, push) that produces the awaited state",
        "next_attempt": "the next push to the PR head"},
    "EXTERNAL_MACHINE_PREREQUISITE": {
        "failed_predicate": "NO_ALWAYS_ON_RECEIVER_OR_HOST",
        "required_evidence_or_repair": "serve the work as a transition-scoped job on a hosted runner; delete the unit or self-hosted runner",
        "next_attempt": "the next push to the PR head"},
    "NEW_THIRD_PARTY_ACTION": {
        "failed_predicate": "NO_NEW_DEPENDENCIES",
        "required_evidence_or_repair": "use a local action, an actions/* action pinned to a 40-hex commit, or a StegVerse-org/.github reusable workflow pinned to a 40-hex commit",
        "next_attempt": "the next push to the PR head"},
    "NEW_THIRD_PARTY_IMPORT": {
        "failed_predicate": "NO_NEW_DEPENDENCIES",
        "required_evidence_or_repair": "use the standard library or a module of this repository; no new package install or dependency manifest change",
        "next_attempt": "the next push to the PR head"},
    "CLOCK_READ_IN_RECEIPT": {
        "failed_predicate": "EPOCH_IS_SUPPLIED_NEVER_READ_FROM_A_CLOCK",
        "required_evidence_or_repair": "take the epoch from the ledger head or a supplied hb_epoch (org-kernel supplied_epoch_failure)",
        "next_attempt": "the next push to the PR head"},
    "AI_SESSION_GATE_PRESENT": {
        "failed_predicate": "NO_AI_SESSION_GATE",
        "required_evidence_or_repair": "remove AI_SESSION_GATE; admission binds sessions from push receipts",
        "next_attempt": "the next push to the PR head"},
}

DISPATCH_TRIGGERS = ("workflow_dispatch", "repository_dispatch")
CLOCK_CALLS = {("time", "time"), ("time", "time_ns"), ("datetime", "now"), ("datetime", "utcnow"),
               ("datetime", "today"), ("date", "today")}
CLOCK_SCOPES = ("resident-runtime/", "org-kernel/", "tvc", "TVC")
UNIT_SUFFIXES = (".service", ".timer", ".socket", ".path")
DEPENDENCY_MANIFESTS = ("requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py", "setup.cfg",
                        "Pipfile", "Pipfile.lock", "poetry.lock", "package.json", "package-lock.json", "yarn.lock",
                        "go.mod", "Cargo.toml", "Gemfile")
SERVICE_RUN = re.compile(r"\b(systemctl\s+(enable|start|restart)|launchctl\s+(load|bootstrap)|crontab\s)")
INSTALL_RUN = re.compile(r"\b(pip3?\s+install|python3?\s+-m\s+pip\s+install|npm\s+(install|i|ci)\b|yarn\s+add|apt-get\s+install|gem\s+install|go\s+get)\b")
LOCAL_INSTALL = re.compile(r"install\s+(--[a-z-]+\s+)*(-e\s+)?\.{1,2}/\S*\s*$")  # this repository's own package
CLOCK_RUN = re.compile(r"\bdate\s+[^\n|;]*\+%s")
SLEEP = re.compile(r"\bsleep\s+[0-9$]")
LOOP_OPEN = re.compile(r"^\s*(while|until|for)\b")


def finding(code: str, path: str, line: int, detail: str) -> dict[str, Any]:
    rule = RULES[code]
    return {"disposition": "FAIL_CLOSED", "failure_code": code, "failed_predicate": rule["failed_predicate"],
            "required_evidence_or_repair": rule["required_evidence_or_repair"], "retry_entrypoint": ENTRYPOINT,
            "owning_existing_goal": GOAL, "next_attempt": rule["next_attempt"], "path": path, "line": line,
            "detail": detail}


# -- workflow text (no YAML dependency: GitHub's trigger and step keys are read by indentation) ----------

def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _strip_comment(line: str) -> str:
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def trigger_lines(text: str) -> list[tuple[int, str]]:
    """(line number, trigger name) for every event named under the top-level ``on:`` key."""
    lines = text.splitlines()
    out: list[tuple[int, str]] = []
    for i, raw in enumerate(lines):
        line = _strip_comment(raw)
        m = re.match(r"^(on|\"on\"|'on'|true):\s*(.*)$", line)
        if not m:
            continue
        rest = m.group(2).strip()
        if rest:  # on: push   |   on: [push, workflow_dispatch]
            for name in re.split(r"[\s,\[\]]+", rest):
                if name:
                    out.append((i + 1, name.strip("'\"")))
            return out
        child = None
        for j in range(i + 1, len(lines)):
            sub = _strip_comment(lines[j])
            if not sub.strip():
                continue
            if _indent(sub) == 0:
                break
            if child is None:
                child = _indent(sub)
            if _indent(sub) != child:
                continue
            body = sub.strip()
            if body.startswith("- "):  # on:\n  - push
                out.append((j + 1, body[2:].strip().strip("'\"")))
                continue
            key = re.match(r"^([A-Za-z_]+)\s*:", body)
            if key:
                out.append((j + 1, key.group(1)))
        return out
    return out


def run_blocks(text: str) -> list[tuple[int, list[str]]]:
    """(first line number, lines) of every ``run:`` step body."""
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        m = re.match(r"^(\s*)(-\s+)?run:\s*(.*)$", lines[i])
        if m:
            base = len(m.group(1)) + (len(m.group(2)) if m.group(2) else 0)
            rest = m.group(3).strip()
            if rest and rest[0] not in "|>":
                out.append((i + 1, [rest]))
                i += 1
                continue
            body, j = [], i + 1
            while j < len(lines) and (not lines[j].strip() or _indent(lines[j]) > base):
                body.append(lines[j])
                j += 1
            out.append((i + 2, body))
            i = j
            continue
        i += 1
    return out


def uses_lines(text: str) -> list[tuple[int, str]]:
    out = []
    for i, raw in enumerate(text.splitlines()):
        m = re.match(r"^\s*(-\s+)?uses:\s*(\S+)", _strip_comment(raw))
        if m:
            out.append((i + 1, m.group(2).strip("'\"")))
    return out


def action_problem(ref: str) -> str | None:
    if ref.startswith("./"):
        return None
    name, _, pin = ref.partition("@")
    if not (any(name.startswith(p) for p in ALLOWED_ACTION_OWNERS) or any(name.startswith(p) for p in ALLOWED_REUSABLE_PREFIXES)):
        return "not a local action, an actions/* action or a StegVerse-org/.github reusable workflow"
    if not SHA40.match(pin):
        return "not pinned to a 40-hex commit"
    return None


def check_workflow(path: str, text: str, base_text: str | None) -> list[dict[str, Any]]:
    out = []
    for line, name in trigger_lines(text):
        if name in DISPATCH_TRIGGERS:
            out.append(finding("WORKFLOW_DISPATCH_TRIGGER_PRESENT", path, line, f"on: {name}"))
        elif name == "schedule":
            out.append(finding("SCHEDULE_TRIGGER_PRESENT", path, line, "on: schedule"))
    for i, raw in enumerate(text.splitlines()):
        line = _strip_comment(raw)
        if re.match(r"^\s*runs-on:.*\bself-hosted\b", line):
            out.append(finding("EXTERNAL_MACHINE_PREREQUISITE", path, i + 1, "runs-on self-hosted"))
        if re.search(r"\bAI_SESSION_GATE\b", line):
            out.append(finding("AI_SESSION_GATE_PRESENT", path, i + 1, "AI_SESSION_GATE"))
    base_uses = {u for _, u in uses_lines(base_text)} if base_text is not None else set()
    for line, ref in uses_lines(text):
        problem = action_problem(ref)
        if problem and ref not in base_uses:
            out.append(finding("NEW_THIRD_PARTY_ACTION", path, line, f"uses {ref}: {problem}"))
    base_runs = "\n".join("\n".join(b) for _, b in run_blocks(base_text)) if base_text is not None else ""
    for start, body in run_blocks(text):
        depth_loop = None
        for k, raw in enumerate(body):
            line = _strip_comment(raw)
            n = start + k
            if LOOP_OPEN.match(line):
                depth_loop = n
            if SLEEP.search(line) and (depth_loop is not None or re.search(r"\b(while|until)\b", line)):
                out.append(finding("EXTERNAL_POLLING_PRESENT", path, n, line.strip()))
            if re.match(r"^\s*done\b", line):
                depth_loop = None
            if SERVICE_RUN.search(line):
                out.append(finding("EXTERNAL_MACHINE_PREREQUISITE", path, n, line.strip()))
            if INSTALL_RUN.search(line) and not LOCAL_INSTALL.search(line) and line.strip() not in base_runs:
                out.append(finding("NEW_THIRD_PARTY_IMPORT", path, n, line.strip()))
            if CLOCK_RUN.search(line):
                out.append(finding("CLOCK_READ_IN_RECEIPT", path, n, line.strip()))
    return out


# -- python sources -------------------------------------------------------------------------------------

def _local_modules(root_files: Iterable[str]) -> set[str]:
    """Every module or package name this repository itself provides (any .py stem, any directory on a path)."""
    mods = set()
    for f in root_files:
        p = Path(f)
        if p.suffix == ".py":
            mods.add(p.stem)
        for part in p.parts[:-1]:
            mods.add(part.replace("-", "_"))
            mods.add(part)
    return mods


def _imports(tree: ast.AST) -> list[tuple[int, str]]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name.split(".")[0]) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            out.append((node.lineno, node.module.split(".")[0]))
    return out


def check_python(path: str, text: str, base_text: str | None, local: set[str]) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    out = []
    base_imports: set[str] = set()
    if base_text is not None:
        try:
            base_imports = {m for _, m in _imports(ast.parse(base_text))}
        except SyntaxError:
            pass
    stdlib = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}
    for line, mod in _imports(tree):
        if mod not in stdlib and mod not in local and mod not in FIRST_PARTY_PACKAGES and mod not in base_imports:
            out.append(finding("NEW_THIRD_PARTY_IMPORT", path, line, f"import {mod}"))
    in_scope = any(path.startswith(s) or ("/" + s) in path for s in CLOCK_SCOPES) and "/tests/" not in "/" + path \
        and not Path(path).name.startswith("test_")
    for node in ast.walk(tree):
        if in_scope and isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            name = owner.attr if isinstance(owner, ast.Attribute) else owner.id if isinstance(owner, ast.Name) else None
            if (name, node.func.attr) in CLOCK_CALLS:
                out.append(finding("CLOCK_READ_IN_RECEIPT", path, node.lineno, f"{name}.{node.func.attr}()"))
        if isinstance(node, ast.Name) and node.id == "AI_SESSION_GATE":
            out.append(finding("AI_SESSION_GATE_PRESENT", path, node.lineno, "AI_SESSION_GATE identifier"))
    return out


def check_file(path: str, text: str | None, base_text: str | None, local: set[str]) -> list[dict[str, Any]]:
    name = Path(path).name
    out = []
    if path.endswith(UNIT_SUFFIXES) and text is not None and re.search(r"^\[(Unit|Service|Timer|Socket|Path|Install)\]", text, re.M):
        out.append(finding("EXTERNAL_MACHINE_PREREQUISITE", path, 1, "systemd unit file"))
    if text is None:
        return out
    if name in DEPENDENCY_MANIFESTS and text != base_text:
        out.append(finding("NEW_THIRD_PARTY_IMPORT", path, 1, "dependency manifest changed"))
    if path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml")):
        out += check_workflow(path, text, base_text)
    elif path.endswith(".py"):
        out += check_python(path, text, base_text, local)
    return out


# -- git ------------------------------------------------------------------------------------------------

def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def _show(root: Path, rev: str, path: str) -> str | None:
    p = subprocess.run(["git", "-C", str(root), "show", f"{rev}:{path}"], capture_output=True)
    if p.returncode:
        return None
    try:
        return p.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def evaluate(root: Path, base: str | None, head: str) -> dict[str, Any]:
    files = [f for f in _git(root, "ls-tree", "-r", "--name-only", head).splitlines()]
    local = _local_modules(files)
    if base:
        changed = [f for f in _git(root, "diff", "--name-only", "--no-renames", "--diff-filter=AMRT", base, head).splitlines()]
    else:
        changed = files
    findings = []
    for path in sorted(changed):
        findings += check_file(path, _show(root, head, path), _show(root, base, path) if base else None, local)
    findings.sort(key=lambda f: (f["path"], f["line"], f["failure_code"]))
    body = {"schema": SCHEMA, "check": CHECK_ID, "lowest_supported_mode": LOWEST_SUPPORTED_MODE,
            "mode": "PULL_REQUEST_DIFF" if base else "TREE_CENSUS", "base": base, "head": head,
            "files_evaluated": len(changed), "findings": findings,
            "disposition": "ALLOW" if not findings else "FAIL_CLOSED"}
    if findings:
        first = findings[0]
        body["first_refusal"] = {k: first[k] for k in SIX_FIELDS}
    body["result_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    return body


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--base")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--all", action="store_true", help="tree census at --head; report only, exit 0")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    root = Path(a.root)
    if not a.all and not a.base:
        ap.error("--base is required unless --all")
    head = _git(root, "rev-parse", "--verify", a.head + "^{commit}").strip()
    base = None if a.all else _git(root, "rev-parse", "--verify", a.base + "^{commit}").strip()
    result = evaluate(root, base, head)
    text = json.dumps(result, indent=2, sort_keys=True)
    if a.out:
        Path(a.out).write_text(text + "\n")
    print(text)
    return 0 if a.all or result["disposition"] == "ALLOW" else 1


if __name__ == "__main__":
    sys.exit(main())
