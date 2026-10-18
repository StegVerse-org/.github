#!/usr/bin/env python3
"""`RESIDENT_RUNTIME_CONVERGENCE` -- bring one organization's resident-runtime
surface to a pinned StegVerse-org baseline, by manifest, on the record.

The egress module, its tests and its workflow drifted separately in each
organization's `.github` repository. Porting a fix by hand into six different
files is six improvisations. This transition does the same thing six times
from one manifest:

1. **Pin.** The manifest names the baseline (repository, commit, and for each
   converged file its path, sha256 and git blob sha) and, per organization, the
   target commit and the sha256 each target file had when the manifest was
   written. A target or baseline that no longer matches is FAIL_CLOSED, never
   converged on a guess.
2. **Evidence.** For every converged file the before and after sha256 and a
   unified diff are written as bytes into the evidence directory. Every hunk the
   target has and the baseline does not is classified (declared parameter,
   comment or docstring only, org-specific, divergent code) and every top-level
   symbol is compared by name.
3. **No silent deletion.** A hunk that is not a declared parameter and not
   comment-only would be deleted by convergence. Unless the manifest lists it
   (by sha256 of its text) as reconciled, the organization is FAIL_CLOSED
   `ORG_SPECIFIC_BEHAVIOUR_UNRECONCILED` with the hunks named.
4. **Closure.** The converged files load other files by repository-relative
   path. That closure is computed from the baseline bytes, and a closure file
   the target lacks is FAIL_CLOSED `BASELINE_DEPENDENCY_CLOSURE_ABSENT`.
5. **Converge.** The baseline bytes are written, with only the manifest's
   declared per-organization parameter lines substituted (for example
   `OWNER_REPOSITORY`). By default this happens in a sandbox copy of the
   target; `--apply` writes into the target checkout itself.
6. **Test.** The manifest's test modules run against the converged tree with
   both ledger roots pointed into a temporary directory, so no run writes
   durable ledger state.
7. **Receipt.** The result is one `stegverse.repo-transition-receipt/v1` body:
   `RESIDENT_RUNTIME_CONVERGED` on ALLOW, `RESIDENT_RUNTIME_CONVERGENCE_REFUSED`
   otherwise, both recorded. It is appended only with `--append`, through the
   repository's own `.stegverse/transition-ledger/emit.py::append`, to the
   ledger root the materializer supplies, and only with a supplied heartbeat
   epoch (the shared supplied-epoch rule: no clock is read).

Nothing here polls, waits on a receiver, reads the network or dispatches
anything. Every non-ALLOW carries the six ORRD fields.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]

OPERATION_ID = "RESIDENT_RUNTIME_CONVERGENCE"
MANIFEST_SCHEMA = "stegverse.resident-runtime-convergence-manifest/v1"
RESULT_SCHEMA = "stegverse.resident-runtime-convergence-result/v1"
EVIDENCE_SCHEMA = "stegverse.resident-runtime-convergence-evidence/v1"
RECEIPT_SCHEMA = "stegverse.repo-transition-receipt/v1"
INTENDED_ACTION = "CONVERGE_AN_ORGANIZATION_RESIDENT_RUNTIME_SURFACE_TO_ITS_BASELINE"
CONVERGED_CLASS = "RESIDENT_RUNTIME_CONVERGED"
REFUSED_CLASS = "RESIDENT_RUNTIME_CONVERGENCE_REFUSED"
RETRY_ENTRYPOINT = "resident-runtime/resident_runtime_convergence.py::converge"
DEFAULT_MANIFEST = "resident-runtime/resident-runtime-convergence-manifest.json"

ALLOW = "ALLOW"
DENY = "DENY"
FAIL_CLOSED = "FAIL_CLOSED"

# Failure codes, one per predicate, so no reader mistakes one refusal for another.
MANIFEST_INVALID = "CONVERGENCE_MANIFEST_INVALID"
ORG_NOT_DECLARED = "CONVERGENCE_TARGET_NOT_DECLARED"
BASELINE_MISMATCH = "CONVERGENCE_BASELINE_BYTES_NOT_AT_PIN"
TARGET_DRIFTED = "CONVERGENCE_TARGET_DRIFTED_SINCE_MANIFEST"
ORG_SPECIFIC = "ORG_SPECIFIC_BEHAVIOUR_UNRECONCILED"
CLOSURE_ABSENT = "BASELINE_DEPENDENCY_CLOSURE_ABSENT"
TESTS_FAILED = "BASELINE_EGRESS_TESTS_FAIL_ON_CONVERGED_TREE"
RECONCILIATION_INVALID = "CONVERGENCE_RECONCILIATION_INCOMPLETE"
EXTENSION_INVALID = "ORG_EXTENSION_NOT_AT_PIN"
CLOSURE_CONFLICT = "CLOSURE_ADDITION_WOULD_OVERWRITE_AN_ORG_FILE"
CONFIG_UNDECIDABLE = "ORG_CONFIG_KEY_UNDECIDABLE"
CLOSE_PORT_PENDING = "INTR_CLOSE_PORT_PENDING"
ORG_REGRESSED = "ORG_BEHAVIOUR_REGRESSED_BY_CONVERGENCE"
CLOSURE_DIVERGENT = "BASELINE_CLOSURE_FILE_DIVERGENT"
HB_EPOCH_NOT_SUPPLIED = "HB_EPOCH_NOT_SUPPLIED"
HB_EPOCH_INVALID = "HB_EPOCH_INVALID"
HB_ANCHOR_EPOCH = 32

#: Hunk classes. Only the first two may be overwritten without a reconciliation.
PARAMETER = "DECLARED_PARAMETER"
COSMETIC = "COMMENT_OR_DOCSTRING_ONLY"
ORG_SPECIFIC_HUNK = "ORG_SPECIFIC_BEHAVIOUR"
DIVERGENT = "DIVERGENT_CODE"

PATH_LITERAL = re.compile(r"""["']((?:[\w.-]+/)+[\w.-]+\.(?:py|json|ya?ml|md))["']""")


class ConvergenceRefused(Exception):
    def __init__(self, failure_code: str, failed_predicate: str, required: str, next_attempt: str,
                 detail: Any = None) -> None:
        super().__init__(failure_code)
        self.failure_code = failure_code
        self.failed_predicate = failed_predicate
        self.required = required
        self.next_attempt = next_attempt
        self.detail = detail


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canon(value)).hexdigest()


def fail_closed(failure_code: str, failed_predicate: str, required: str, owning_goal: str,
                next_attempt: str, detail: Any = None) -> dict[str, Any]:
    """The six ORRD L61 fields, never a bare BLOCKED."""
    record = {
        "disposition": FAIL_CLOSED,
        "failure_code": failure_code,
        "failed_predicate": failed_predicate,
        "required_evidence_or_repair": required,
        "retry_entrypoint": RETRY_ENTRYPOINT,
        "owning_existing_goal": owning_goal,
        "next_attempt": next_attempt,
    }
    if detail is not None:
        record["detail"] = detail
    return record


# --------------------------------------------------------------------- manifest

def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = []
    if manifest.get("schema") != MANIFEST_SCHEMA:
        problems.append("schema")
    base = manifest.get("baseline") or {}
    for key in ("repository", "commit", "files"):
        if not base.get(key):
            problems.append("baseline." + key)
    for role, entry in (base.get("files") or {}).items():
        for key in ("path", "sha256", "git_blob_sha"):
            if not isinstance(entry, dict) or not entry.get(key):
                problems.append(f"baseline.files.{role}.{key}")
    if not isinstance(manifest.get("targets"), dict) or not manifest["targets"]:
        problems.append("targets")
    if not manifest.get("owning_existing_goal"):
        problems.append("owning_existing_goal")
    if problems:
        raise ConvergenceRefused(MANIFEST_INVALID, "CONVERGENCE_MANIFEST_DECLARES_BASELINE_TARGETS_AND_GOAL",
                                 "repair the manifest fields named in detail",
                                 "rerun once the manifest validates", detail=problems)
    return manifest


def parameter_values(manifest: Mapping[str, Any], organization: str) -> dict[str, str]:
    target = manifest["targets"][organization]
    values = {"organization": organization,
              "repository": target.get("repository", organization + "/.github")}
    values.update(target.get("parameters") or {})
    return values


def render(baseline: bytes, path: str, manifest: Mapping[str, Any], values: Mapping[str, str]) -> bytes:
    """Baseline bytes with only the declared parameter lines substituted."""
    text = baseline.decode("utf-8")
    for parameter in manifest.get("parameters") or []:
        if parameter["path"] != path:
            continue
        line = parameter["baseline_line"]
        if text.count(line) != 1:
            raise ConvergenceRefused(BASELINE_MISMATCH, "DECLARED_PARAMETER_LINE_OCCURS_EXACTLY_ONCE_IN_BASELINE",
                                     f"the manifest parameter line for {path} must occur once in the baseline",
                                     "rerun after the manifest parameter is corrected", detail=line)
        text = text.replace(line, parameter["template"].format(**values))
    return text.encode("utf-8")


def normalize(target: bytes, path: str, manifest: Mapping[str, Any], values: Mapping[str, str]) -> bytes:
    """Target bytes with the declared parameter lines put back to the baseline spelling."""
    text = target.decode("utf-8", errors="replace")
    for parameter in manifest.get("parameters") or []:
        if parameter["path"] == path:
            text = text.replace(parameter["template"].format(**values), parameter["baseline_line"])
    return text.encode("utf-8")


# --------------------------------------------------------------------- evidence

def _cosmetic_lines(source: str) -> set[int]:
    """1-based lines that carry only comments, blanks or docstrings."""
    lines = source.splitlines()
    cosmetic = {i + 1 for i, line in enumerate(lines) if not line.strip() or line.strip().startswith("#")}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return cosmetic
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(getattr(body[0], "value", None), ast.Constant) \
                and isinstance(body[0].value.value, str):
            cosmetic.update(range(body[0].lineno, body[0].end_lineno + 1))
    return cosmetic


def top_level_symbols(source: str) -> dict[str, str]:
    """Top-level name -> sha256 of its source segment (functions, classes, assignments)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    lines = source.splitlines(keepends=True)
    out: dict[str, str] = {}
    for node in tree.body:
        names: list[str] = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        segment = "".join(lines[start - 1:node.end_lineno])
        for name in names:
            out[name] = sha256_bytes(segment.encode("utf-8"))
    return out


def classify_hunks(base: bytes, target: bytes, path: str, organization: str,
                   reconciled: set[str]) -> list[dict[str, Any]]:
    """Every hunk the target has that the baseline does not, with its class."""
    base_lines = base.decode("utf-8", errors="replace").splitlines(keepends=True)
    target_text = target.decode("utf-8", errors="replace")
    target_lines = target_text.splitlines(keepends=True)
    is_python = path.endswith(".py")
    cosmetic = _cosmetic_lines(target_text) if is_python else {
        i + 1 for i, line in enumerate(target_lines) if not line.strip() or line.strip().startswith("#")}
    org_tokens = {organization, organization.lower(), organization.lower().replace("-", "_")}
    defined_in_base = set(top_level_symbols(base.decode("utf-8", errors="replace"))) if is_python else set()
    hunks = []
    matcher = difflib.SequenceMatcher(a=base_lines, b=target_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal" or j1 == j2:
            continue  # a pure deletion in the target is restored by convergence, not deleted
        added = target_lines[j1:j2]
        text = "".join(added)
        line_numbers = range(j1 + 1, j2 + 1)
        new_defs = sorted(set(re.findall(r"^(?:def|class)\s+(\w+)", text, re.M)) - defined_in_base)
        if all(n in cosmetic for n in line_numbers):
            kind = COSMETIC
        elif new_defs or any(tok in text for tok in org_tokens):
            kind = ORG_SPECIFIC_HUNK
        else:
            kind = DIVERGENT
        digest = sha256_bytes(text.encode("utf-8"))
        hunks.append({
            "path": path, "class": kind,
            "baseline_lines": [i1 + 1, i2] if i2 > i1 else None,
            "target_lines": [j1 + 1, j2],
            "added_line_count": j2 - j1, "removed_line_count": i2 - i1,
            "hunk_sha256": digest,
            "new_top_level_definitions": new_defs,
            "mentions_organization": any(tok in text for tok in org_tokens),
            "reconciled": digest in reconciled,
        })
    return hunks


def dependency_closure(baseline_root: Path, seeds: list[str]) -> list[str]:
    """Repository-relative files the seeds name, transitively through Python files."""
    seen: set[str] = set()
    queue = list(seeds)
    while queue:
        current = queue.pop()
        file = baseline_root / current
        if not file.is_file():
            continue
        text = file.read_text(encoding="utf-8", errors="replace")
        for found in PATH_LITERAL.findall(text):
            if found in seen or found in seeds or not (baseline_root / found).is_file():
                continue
            seen.add(found)
            if found.endswith(".py"):
                queue.append(found)
    return sorted(seen)


def is_org_owned(path: str, manifest: Mapping[str, Any]) -> bool:
    return any(re.fullmatch(pattern, path) for pattern in manifest.get("org_owned_closure_patterns") or [])


# --------------------------------------------------------------------- tests

def run_tests(tree: Path, modules: list[str], timeout: int) -> dict[str, Any]:
    """Run the baseline test modules against `tree`, ledgers in a temporary directory."""
    with tempfile.TemporaryDirectory(prefix="convergence-ledgers-") as ledgers:
        env = dict(os.environ)
        env["STEGVERSE_REPO_LEDGER_ROOT"] = str(Path(ledgers) / "repo-ledger")
        env["STEGVERSE_ORG_LEDGER_ROOT"] = str(Path(ledgers) / "org-ledger")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            proc = subprocess.run([sys.executable, "-m", "unittest", *modules], cwd=tree, env=env,
                                  capture_output=True, text=True, timeout=timeout)
            output, returncode = proc.stdout + proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") + (exc.stderr or "") if isinstance(exc.stdout, str) else ""
            returncode = None
    ran = re.findall(r"^Ran (\d+) tests?", output, re.M)
    status = re.findall(r"^(OK|FAILED)(?: \(([^)]*)\))?", output, re.M)
    counts = {k: int(v) for k, v in re.findall(r"(failures|errors|skipped)=(\d+)", status[-1][1])} if status else {}
    error_kinds = sorted({m for m in re.findall(r"^(\w+(?:Error|Exception)):", output, re.M)})
    return {
        "modules": modules, "returncode": returncode, "timed_out": returncode is None,
        "tests_run": int(ran[-1]) if ran else 0,
        "failures": counts.get("failures", 0), "errors": counts.get("errors", 0),
        "skipped": counts.get("skipped", 0),
        "passed": returncode == 0 and bool(status) and status[-1][0] == "OK",
        "error_kinds": error_kinds,
        "output_sha256": sha256_bytes(output.encode("utf-8")),
        "output": output,
    }


# --------------------------------------------------------------------- receipt

def receipt_body(manifest: Mapping[str, Any], organization: str, result: Mapping[str, Any],
                 hb_epoch: int | None) -> dict[str, Any]:
    """The repository receipt body this transition appends, in the ledger's own shape."""
    transition_class = CONVERGED_CLASS if result["disposition"] == ALLOW else REFUSED_CLASS
    evidence = {
        "operation_id": OPERATION_ID, "intended_action": INTENDED_ACTION,
        "organization": organization,
        "target_repository": manifest["targets"][organization].get("repository"),
        "target_commit": manifest["targets"][organization].get("commit"),
        "baseline_repository": manifest["baseline"]["repository"],
        "baseline_commit": manifest["baseline"]["commit"],
        "manifest_sha256": result["manifest_sha256"],
        "disposition": result["disposition"],
        "files": result["files"],
        "evidence_manifest_sha256": result.get("evidence_manifest_sha256"),
        "tests": {k: v for k, v in (result.get("tests") or {}).items() if k != "output"},
        "refusals": result["refusals"],
        "materialization": "APPLIED_TO_TARGET" if result.get("applied") else "SANDBOX_ONLY",
    }
    predecessor = sha({"organization": organization,
                       "files": {f["path"]: f["before_sha256"] for f in result["files"]}})
    successor = sha({"organization": organization,
                     "files": {f["path"]: (f["after_sha256"] if result["disposition"] == ALLOW
                                           else f["before_sha256"]) for f in result["files"]}})
    return {
        "schema": RECEIPT_SCHEMA,
        "repository": manifest["targets"][organization].get("repository"),
        "transition_id": f"{OPERATION_ID}:{organization}:{result['manifest_sha256'][7:23]}",
        "transition_class": transition_class,
        "predecessor_state_sha256": predecessor,
        "successor_state_sha256": successor,
        "evidence": evidence,
        "authority_effect": "NONE",
        "hb_epoch_supplied": hb_epoch,
    }


def epoch_refusal(hb_epoch: Any, owning_goal: str) -> dict[str, Any] | None:
    if hb_epoch is None:
        return fail_closed(HB_EPOCH_NOT_SUPPLIED, "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH",
                           "supply --hb-epoch from the carrier; no clock is read", owning_goal,
                           "rerun the append with the supplied epoch; nothing was appended")
    if isinstance(hb_epoch, bool) or not isinstance(hb_epoch, int) or hb_epoch < HB_ANCHOR_EPOCH:
        return fail_closed(HB_EPOCH_INVALID, "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH",
                           f"supply an integer epoch at or above {HB_ANCHOR_EPOCH}", owning_goal,
                           "rerun the append with a valid epoch; nothing was appended")
    return None


def append_receipt(body: Mapping[str, Any], ledger_repo_root: Path) -> dict[str, Any]:
    """Append through the repository's own emitter, to the ledger root the materializer supplied."""
    spec = importlib.util.spec_from_file_location(
        "convergence_repo_emit", Path(ledger_repo_root) / ".stegverse/transition-ledger/emit.py")
    emitter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(emitter)
    return emitter.append(body["transition_id"], body["transition_class"],
                          body["predecessor_state_sha256"], body["successor_state_sha256"],
                          body["evidence"], body["authority_effect"], body["hb_epoch_supplied"],
                          idempotent_on=("manifest_sha256", "disposition"))


# --------------------------------------------------------------------- reconciliation

def enclosing_symbols(source: str, first: int, last: int) -> list[str]:
    """Top-level symbols whose source range (decorators included) overlaps [first, last]."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found = []
    for node in tree.body:
        start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        if start > last or node.end_lineno < first:
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.append(node.name)
        elif isinstance(node, ast.Assign):
            found.extend(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found.append(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            found.append("<import>")
        else:
            found.append("<statement>")
    return found


def reconciliation_entries(target: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """`reconciled_hunk_sha256` as {digest: entry}; a bare list is read as undocumented entries."""
    declared = target.get("reconciled_hunk_sha256") or {}
    if isinstance(declared, list):
        return {d: {} for d in declared}
    return dict(declared)


def build_extension(target_text: str, organization: str, commit: str, symbols: list[str],
                    imports: list[str]) -> bytes:
    """The declared org-specific symbols, carried byte for byte from the target, in its order.

    Appended after the baseline bytes, so the baseline part of the converged
    module is unchanged and a definition here overrides the baseline one of the
    same name at import (module globals bind late).
    """
    if not symbols and not imports:
        return b""
    tree = ast.parse(target_text)
    lines = target_text.splitlines(keepends=True)
    wanted = set(symbols)
    segments = []
    for node in tree.body:
        names: list[str] = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        if not wanted.intersection(names):
            continue
        start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        while start > 1 and lines[start - 2].lstrip().startswith("#"):
            start -= 1  # the comment that documents the definition travels with it
        segments.append("".join(lines[start - 1:node.end_lineno]).rstrip("\n") + "\n")
    carried: set[str] = set()
    for segment in segments:
        for definition, assigned in re.findall(r"^(?:def|class)\s+(\w+)|^(\w+)\s*[:=]", segment, re.M):
            carried.add(definition or assigned)
    missing = wanted - carried
    if missing:
        raise ConvergenceRefused(EXTENSION_INVALID, "EVERY_DECLARED_EXTENSION_SYMBOL_IS_DEFINED_IN_THE_TARGET",
                                 "remove or correct the extension symbols named in detail",
                                 "rerun once the extension names only target-defined symbols",
                                 detail=sorted(missing))
    header = (
        "\n\n# " + "-" * 75 + "\n"
        f"# Organization extension: {organization}. Declared in\n"
        "# resident-runtime/resident-runtime-convergence-manifest.json (targets."
        f"{organization}.extension)\n"
        f"# and carried byte for byte from {organization}/.github@{commit[:8]} by RESIDENT_RUNTIME_CONVERGENCE.\n"
        "# Everything above this block is the StegVerse-org baseline, declared parameters aside.\n"
        "# A definition here overrides the baseline definition of the same name.\n"
        "# " + "-" * 75 + "\n"
    )
    body = "".join(line.rstrip("\n") + "\n" for line in imports)
    body += "\n\n".join(segments)
    return (header + ("\n" if imports else "") + body).encode("utf-8")


def json_pointer_get(document: Any, pointer: str) -> tuple[bool, Any]:
    current = document
    for part in [p for p in pointer.split("/") if p]:
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def json_pointer_set(document: dict[str, Any], pointer: str, value: Any) -> None:
    parts = [p for p in pointer.split("/") if p]
    current = document
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def parse_test_failures(output: str) -> list[dict[str, Any]]:
    """Each `ERROR:`/`FAIL:` block of unittest output, with its traceback text."""
    blocks = re.split(r"^=+\n", output, flags=re.M)
    failures = []
    for block in blocks:
        match = re.match(r"(ERROR|FAIL): (\S+) \(([^)]*)\)", block)
        if not match:
            continue
        traceback = block.split("-" * 70, 1)[1] if "-" * 70 in block else block
        traceback = traceback.split("\n" + "-" * 70, 1)[0]
        last = [l for l in traceback.strip().splitlines() if l.strip()]
        failures.append({"kind": match.group(1), "test": match.group(3) or match.group(2),
                         "exception": last[-1][:300] if last else "", "traceback": traceback})
    return failures


def attribute_failure(failure: Mapping[str, Any], rules: Mapping[str, Any]) -> str:
    """Which declared cause a failing test is attributed to, by its traceback alone."""
    text = failure["traceback"]
    for pattern in rules.get("pending_close_port_traceback_patterns") or []:
        if re.search(pattern, text, re.M):
            return "PENDING_INTR_CLOSE_PORT"
    for key in rules.get("undecidable_config_keys") or []:
        if key in text:
            return "UNDECIDABLE_ORG_CONFIG_KEY"
    exception = failure.get("exception") or ""
    named = set(re.findall(r"has no attribute '(\w+)'", exception)) | set(re.findall(r"^KeyError: '(\w+)'$", exception))
    called = set(re.findall(r"(\w+)\(\) (?:got an unexpected keyword|takes \d+|missing \d+ required)", exception))
    for path, row in (rules.get("divergent_closure") or {}).items():
        if named & set(row.get("missing_baseline_symbols") or []) or called & set(row.get("signature_differs") or []):
            return "DIVERGENT_CLOSURE_FILE:" + path
    for path in rules.get("org_owned_different") or []:
        if path in exception:
            return "DIVERGENT_CLOSURE_FILE:" + path  # the organization's own registry or config answers differently
    frames = re.findall(r'^\s*File "([^"]+)", line \d+, in \w+', text, re.M)
    for path in rules.get("different_closure_files") or []:
        if frames and frames[-1].endswith("/" + path):
            return "DIVERGENT_CLOSURE_FILE:" + path  # raised inside the organization's own revision of the file
    return "UNATTRIBUTED"


def api_divergence(baseline_source: str, target_source: str) -> dict[str, list[str]]:
    """Top-level names a baseline closure file defines that the target's lacks, and functions whose signature differs."""
    def table(source: str) -> dict[str, str]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return {}
        out = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[node.name] = ast.dump(node.args, include_attributes=False)
            elif isinstance(node, ast.ClassDef):
                out[node.name] = "class"
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        out[t.id] = "value"
        return out
    base, target = table(baseline_source), table(target_source)
    return {"missing_baseline_symbols": sorted(set(base) - set(target)),
            "signature_differs": sorted(n for n in set(base) & set(target)
                                        if base[n] not in ("class", "value") and base[n] != target[n])}


def run_command(tree: Path, argv: list[str], timeout: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="convergence-ledgers-") as ledgers:
        env = dict(os.environ)
        env["STEGVERSE_REPO_LEDGER_ROOT"] = str(Path(ledgers) / "repo-ledger")
        env["STEGVERSE_ORG_LEDGER_ROOT"] = str(Path(ledgers) / "org-ledger")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        argv = [sys.executable if a == "{python}" else a for a in argv]
        try:
            proc = subprocess.run(argv, cwd=tree, env=env, capture_output=True, text=True, timeout=timeout)
            output, returncode = proc.stdout + proc.stderr, proc.returncode
        except subprocess.TimeoutExpired:
            output, returncode = "", None
    ran = re.findall(r"^Ran (\d+) tests?", output, re.M)
    return {"argv": argv[1:] if argv and argv[0] == sys.executable else argv, "returncode": returncode,
            "passed": returncode == 0, "tests_run": int(ran[-1]) if ran else None,
            "output_sha256": sha256_bytes(output.encode("utf-8")), "output": output}


# --------------------------------------------------------------------- transition

def converge(manifest_path: Path, organization: str, target_root: Path, baseline_root: Path,
             out_dir: Path, *, apply: bool = False, run_test_step: bool = True,
             timeout: int = 900) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    manifest_sha = "sha256:" + sha256_bytes(Path(manifest_path).read_bytes())
    goal = manifest["owning_existing_goal"]
    out_dir = Path(out_dir) / organization
    evidence_dir = out_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA, "operation_id": OPERATION_ID, "organization": organization,
        "manifest_sha256": manifest_sha, "disposition": None, "files": [], "hunks": [],
        "symbols": {}, "closure": [], "closure_added": [], "config_added": [], "extension": None,
        "reconciliation": {}, "refusals": [], "tests": None, "org_tests": [], "applied": False,
    }
    if organization not in manifest["targets"]:
        result["refusals"].append(fail_closed(
            ORG_NOT_DECLARED, "ORGANIZATION_IS_A_DECLARED_CONVERGENCE_TARGET",
            f"declare {organization} under targets in the manifest", goal,
            "rerun once the target is declared"))
        result["disposition"] = FAIL_CLOSED
        return result
    target = manifest["targets"][organization]
    values = parameter_values(manifest, organization)
    entries = reconciliation_entries(target)
    reconciled = set(entries)
    extension_decl = target.get("extension") or {}
    rendered: dict[str, bytes] = {}
    module_path = (manifest["baseline"]["files"].get("module") or {}).get("path")

    # 1. pins, evidence and hunks
    for role, entry in manifest["baseline"]["files"].items():
        path = entry["path"]
        base_bytes = (Path(baseline_root) / path).read_bytes() if (Path(baseline_root) / path).is_file() else None
        if base_bytes is None or sha256_bytes(base_bytes) != entry["sha256"] \
                or git_blob_sha(base_bytes) != entry["git_blob_sha"]:
            result["refusals"].append(fail_closed(
                BASELINE_MISMATCH, "BASELINE_FILE_BYTES_MATCH_MANIFEST_PIN",
                f"check out {manifest['baseline']['repository']}@{manifest['baseline']['commit']} as the baseline root",
                goal, "rerun against the pinned baseline checkout", detail={"path": path}))
            continue
        target_file = Path(target_root) / path
        before = target_file.read_bytes() if target_file.is_file() else None
        before_sha = sha256_bytes(before) if before is not None else None
        expected = (target.get("before_sha256") or {}).get(path, "ABSENT")
        if (before_sha or "ABSENT") != expected:
            result["refusals"].append(fail_closed(
                TARGET_DRIFTED, "TARGET_FILE_BYTES_MATCH_MANIFEST_BEFORE_PIN",
                f"re-record before_sha256 for {path} in the manifest from {target.get('repository')} main and re-run the evidence step",
                goal, "rerun on the manifest revision that pins the current target bytes",
                detail={"path": path, "expected": expected, "observed": before_sha or "ABSENT"}))
        prefix = render(base_bytes, path, manifest, values)
        after = prefix
        if path == module_path and before is not None and (extension_decl.get("module_symbols")
                                                             or extension_decl.get("module_imports")):
            ext = build_extension(before.decode("utf-8"), organization, target.get("commit", ""),
                                  list(extension_decl.get("module_symbols") or []),
                                  list(extension_decl.get("module_imports") or []))
            ext_sha = sha256_bytes(ext)
            result["extension"] = {"path": path, "symbols": list(extension_decl.get("module_symbols") or []),
                                   "imports": list(extension_decl.get("module_imports") or []),
                                   "sha256": ext_sha, "lines": ext.count(b"\n")}
            if extension_decl.get("module_sha256") != ext_sha:
                result["refusals"].append(fail_closed(
                    EXTENSION_INVALID, "ORG_EXTENSION_BYTES_MATCH_MANIFEST_PIN",
                    f"pin targets.{organization}.extension.module_sha256 to the extension the declared symbols produce",
                    goal, "rerun once the extension pin matches",
                    detail={"expected": extension_decl.get("module_sha256"), "observed": ext_sha}))
            (evidence_dir / "organization_extension.py.fragment").write_bytes(ext)
            after = prefix + ext
        rendered[path] = after
        normalized_before = normalize(before, path, manifest, values) if before is not None else None
        diff = "".join(difflib.unified_diff(
            (before or b"").decode("utf-8", errors="replace").splitlines(keepends=True),
            after.decode("utf-8").splitlines(keepends=True),
            fromfile=f"a/{path} ({organization} {target.get('commit', '')[:8]})",
            tofile=f"b/{path} (baseline {manifest['baseline']['commit'][:8]} rendered)"))
        diff_name = path.replace("/", "__") + ".diff"
        (evidence_dir / diff_name).write_text(diff, encoding="utf-8")
        if before is not None:
            (evidence_dir / (path.replace("/", "__") + ".before")).write_bytes(before)
        result["files"].append({
            "role": role, "path": path,
            "before_sha256": before_sha or "ABSENT",
            "before_lines": before.count(b"\n") if before is not None else 0,
            "after_sha256": sha256_bytes(after), "after_lines": after.count(b"\n"),
            "baseline_prefix_normalized_sha256": sha256_bytes(normalize(prefix, path, manifest, values)),
            "after_normalized_sha256": sha256_bytes(normalize(after, path, manifest, values)),
            "baseline_sha256": entry["sha256"],
            "byte_identical_to_baseline": after == base_bytes,
            "already_converged": before == after,
            "diff_file": diff_name, "diff_lines": diff.count("\n"),
            "diff_sha256": sha256_bytes(diff.encode("utf-8")),
        })
        if normalized_before is not None:
            hunks = classify_hunks(base_bytes, normalized_before, path, organization, reconciled)
            text = normalized_before.decode("utf-8", errors="replace")
            for hunk in hunks:
                hunk["symbols"] = enclosing_symbols(text, *hunk["target_lines"]) if path.endswith(".py") else []
            result["hunks"].extend(hunks)
            if path.endswith(".py"):
                b_syms = top_level_symbols(base_bytes.decode("utf-8"))
                t_syms = top_level_symbols(text)
                result["symbols"][path] = {
                    "only_in_target": sorted(set(t_syms) - set(b_syms)),
                    "only_in_baseline": sorted(set(b_syms) - set(t_syms)),
                    "changed": sorted(n for n in set(t_syms) & set(b_syms) if t_syms[n] != b_syms[n]),
                    "identical": sorted(n for n in set(t_syms) & set(b_syms) if t_syms[n] == b_syms[n]),
                }

    # 2. no silent deletion, and a port is only a port if the extension carries it
    unreconciled = [h for h in result["hunks"]
                    if h["class"] in (ORG_SPECIFIC_HUNK, DIVERGENT) and not h["reconciled"]]
    carried = set(extension_decl.get("module_symbols") or [])
    carried_workflows = {w.get("source_path") for w in extension_decl.get("workflows") or []}
    not_carried, undocumented = [], []
    counts = {"ported": 0, "superseded": 0}
    for hunk in result["hunks"]:
        entry = entries.get(hunk["hunk_sha256"])
        if entry is None:
            continue
        decision = entry.get("decision")
        if decision not in ("ported", "superseded") or not entry.get("reason") or not entry.get("evidence"):
            undocumented.append(hunk["hunk_sha256"])
            continue
        counts[decision] += 1
        if decision == "ported":
            names = [s for s in hunk.get("symbols") or [] if not s.startswith("<")]
            if hunk["path"].endswith(".py"):
                rest = set(names) - carried
                if hunk["path"] != module_path or not set(names) & carried \
                        or not rest <= set(entry.get("superseded_symbols") or []):
                    not_carried.append(hunk["hunk_sha256"])
            elif hunk["path"] not in carried_workflows:
                not_carried.append(hunk["hunk_sha256"])
    result["reconciliation"] = {"ported": counts["ported"], "superseded": counts["superseded"],
                                "unreconciled": len(unreconciled), "undocumented": len(undocumented),
                                "ported_but_not_carried": len(not_carried)}
    if unreconciled:
        org_specific = [h for h in unreconciled if h["class"] == ORG_SPECIFIC_HUNK]
        result["refusals"].append(fail_closed(
            ORG_SPECIFIC, "EVERY_NON_PARAMETER_NON_COSMETIC_TARGET_HUNK_IS_RECONCILED",
            "for each hunk named in detail: record it under targets." + organization + ".reconciled_hunk_sha256 "
            "as ported (carried by the extension) or superseded (with the baseline symbol that supersedes it); "
            "convergence never deletes it silently",
            goal, "rerun converge once every listed hunk_sha256 is reconciled in the manifest",
            detail={"org_specific_hunks": len(org_specific),
                    "divergent_code_hunks": len(unreconciled) - len(org_specific),
                    "new_top_level_definitions": sorted({d for h in unreconciled for d in h["new_top_level_definitions"]}),
                    "hunk_sha256": [h["hunk_sha256"] for h in unreconciled]}))
    if undocumented or not_carried:
        result["refusals"].append(fail_closed(
            RECONCILIATION_INVALID, "EVERY_RECONCILIATION_IS_DOCUMENTED_AND_EVERY_PORT_IS_CARRIED",
            "give each listed entry a decision, reason and evidence; list each ported hunk's symbols in "
            "extension.module_symbols (or its workflow in extension.workflows)",
            goal, "rerun once the reconciliation entries are complete",
            detail={"undocumented": undocumented, "ported_but_not_carried": not_carried}))

    # 3. converge, in a sandbox unless applying
    with tempfile.TemporaryDirectory(prefix=f"convergence-{organization}-") as sandbox:
        original = Path(sandbox) / "original"
        shutil.copytree(target_root, original, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        tree = Path(target_root) if apply else Path(sandbox) / "tree"
        if not apply:
            shutil.copytree(original, tree)
        blocked = any(r["failure_code"] in (BASELINE_MISMATCH, TARGET_DRIFTED, ORG_SPECIFIC,
                                            RECONCILIATION_INVALID, EXTENSION_INVALID)
                      for r in result["refusals"])
        writes: dict[str, bytes] = dict(rendered)
        # 3a. preserved org workflows, renamed so the baseline workflow can take the original path
        for workflow in extension_decl.get("workflows") or []:
            source = original / workflow["source_path"]
            if not source.is_file():
                result["refusals"].append(fail_closed(
                    EXTENSION_INVALID, "PRESERVED_WORKFLOW_EXISTS_IN_THE_TARGET",
                    f"correct extension.workflows source_path {workflow['source_path']}", goal,
                    "rerun once the preserved workflow source exists"))
                continue
            text = source.read_text(encoding="utf-8")
            text = re.sub(r"^name: .*$", "name: " + workflow["name"], text, count=1, flags=re.M)
            data = text.encode("utf-8")
            if workflow.get("sha256") != sha256_bytes(data):
                result["refusals"].append(fail_closed(
                    EXTENSION_INVALID, "PRESERVED_WORKFLOW_BYTES_MATCH_MANIFEST_PIN",
                    f"pin extension.workflows[{workflow['dest_path']}].sha256", goal,
                    "rerun once the preserved workflow pin matches",
                    detail={"expected": workflow.get("sha256"), "observed": sha256_bytes(data)}))
            writes[workflow["dest_path"]] = data
        # 3b. absent closure files, as exact baseline bytes; an existing file is never overwritten
        for addition in target.get("closure_additions") or []:
            path = addition["path"]
            base_file = Path(baseline_root) / path
            data = base_file.read_bytes() if base_file.is_file() else None
            if data is None or sha256_bytes(data) != addition["sha256"]:
                result["refusals"].append(fail_closed(
                    BASELINE_MISMATCH, "CLOSURE_ADDITION_BYTES_MATCH_MANIFEST_PIN",
                    f"pin closure_additions[{path}] to the baseline bytes", goal,
                    "rerun against the pinned baseline", detail={"path": path}))
                continue
            if (original / path).exists():
                result["refusals"].append(fail_closed(
                    CLOSURE_CONFLICT, "CLOSURE_ADDITION_IS_ABSENT_IN_THE_TARGET",
                    f"{path} exists in the target; it is that organization's file and is not overwritten. "
                    "Remove the addition from the manifest", goal, "rerun once the manifest no longer adds it",
                    detail={"path": path}))
                continue
            writes[path] = data
            result["closure_added"].append({"path": path, "sha256": addition["sha256"],
                                            "git_blob_sha": git_blob_sha(data)})
        # 3c. org config keys, only from declared baseline values, only where the target lacks them
        for addition in target.get("config_additions") or []:
            path, pointer = addition["path"], addition["pointer"]
            base_doc = json.loads((Path(baseline_root) / path).read_text(encoding="utf-8"))
            found, value = json_pointer_get(base_doc, pointer)
            if found:
                for field, template in (addition.get("parameterized_fields") or {}).items():
                    if isinstance(value, dict) and field in value:
                        value = {**value, field: template.format(**values)}
            identities = manifest.get("baseline_identity_strings") or []
            text_value = json.dumps(value, sort_keys=True)
            if not found or sha(value) != addition.get("value_sha256") \
                    or any(i in text_value for i in identities):
                result["refusals"].append(fail_closed(
                    CONFIG_UNDECIDABLE, "ORG_CONFIG_ADDITION_IS_A_PINNED_ORG_NEUTRAL_BASELINE_VALUE",
                    f"{path}{pointer}: pin value_sha256 to the baseline value with declared parameters, "
                    "or leave the key to the organization", goal, "rerun once the addition is decidable",
                    detail={"path": path, "pointer": pointer, "observed_value_sha256": sha(value) if found else None}))
                continue
            doc_path = tree / path
            raw = writes.get(path) or (original / path).read_bytes()
            doc = json.loads(raw.decode("utf-8"))
            present, existing = json_pointer_get(doc, pointer)
            if present:
                if existing != value:
                    result["refusals"].append(fail_closed(
                        CONFIG_UNDECIDABLE, "ORG_CONFIG_KEY_IS_ABSENT_OR_ALREADY_EQUAL",
                        f"{path}{pointer} exists with an org value; it is never overwritten", goal,
                        "rerun once the manifest no longer adds it", detail={"path": path, "pointer": pointer}))
                continue
            json_pointer_set(doc, pointer, value)
            writes[path] = (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
            result["config_added"].append({"path": path, "pointer": pointer, "value_sha256": sha(value)})
        for key in target.get("undecidable_config_keys") or []:
            result["refusals"].append(fail_closed(
                CONFIG_UNDECIDABLE, "ORG_CONFIG_KEY_THE_BASELINE_READS_IS_DECLARED_BY_THE_ORGANIZATION",
                f"{key['path']}{key['pointer']}: {key['reason']}", key.get("owning_existing_goal") or goal,
                key.get("next_attempt") or "rerun once the organization declares the key in its own overlay",
                detail={"path": key["path"], "pointer": key["pointer"]}))
        if not (apply and blocked):
            for path, data in writes.items():
                (tree / path).parent.mkdir(parents=True, exist_ok=True)
                (tree / path).write_bytes(data)
            result["applied"] = apply
        converged_dir = out_dir / "converged"
        if converged_dir.exists():
            shutil.rmtree(converged_dir)
        for path, data in writes.items():
            (converged_dir / path).parent.mkdir(parents=True, exist_ok=True)
            (converged_dir / path).write_bytes(data)
        # 4. closure, as the converged tree has it
        check_root = tree if (not apply or result["applied"]) else original
        seeds = [e["path"] for e in manifest["baseline"]["files"].values()]
        for path in dependency_closure(Path(baseline_root), seeds):
            base_sha = sha256_bytes((Path(baseline_root) / path).read_bytes())
            state = "ABSENT"
            if (check_root / path).is_file():
                state = "IDENTICAL" if sha256_bytes((check_root / path).read_bytes()) == base_sha else "DIFFERENT"
            row = {"path": path, "org_owned": is_org_owned(path, manifest),
                   "baseline_sha256": base_sha, "target_state": state,
                   "added_by_convergence": any(a["path"] == path for a in result["closure_added"])}
            if state == "DIFFERENT" and path.endswith(".py") and path not in rendered:
                row.update(api_divergence((Path(baseline_root) / path).read_text(encoding="utf-8"),
                                          (check_root / path).read_text(encoding="utf-8", errors="replace")))
            result["closure"].append(row)
        absent = [c["path"] for c in result["closure"] if c["target_state"] == "ABSENT"]
        if absent:
            result["refusals"].append(fail_closed(
                CLOSURE_ABSENT, "EVERY_FILE_THE_BASELINE_LOADS_EXISTS_IN_THE_TARGET",
                "declare each absent closure file (detail) as a closure addition of baseline bytes, or, where it "
                "is that organization's own configuration, have the organization author it",
                goal, "rerun converge once the closure resolves in the target",
                detail={"absent": absent,
                        "absent_org_owned": [c["path"] for c in result["closure"]
                                             if c["target_state"] == "ABSENT" and c["org_owned"]]}))
        # 5. tests
        if run_test_step and (not apply or result["applied"]):
            tests = run_tests(tree, manifest.get("test_modules") or [], timeout)
            (evidence_dir / "tests.out").write_text(tests["output"], encoding="utf-8")
            failures = parse_test_failures(tests["output"])
            rules = {"pending_close_port_traceback_patterns": manifest.get("pending_close_port_traceback_patterns"),
                     "undecidable_config_keys": [k["pointer"].rsplit("/", 1)[-1]
                                                 for k in target.get("undecidable_config_keys") or []],
                     "divergent_closure": {c["path"]: c for c in result["closure"] if c.get("missing_baseline_symbols")
                                           or c.get("signature_differs")},
                     "org_owned_different": [c["path"] for c in result["closure"]
                                             if c["target_state"] == "DIFFERENT" and c["org_owned"]],
                     "different_closure_files": [c["path"] for c in result["closure"]
                                                 if c["target_state"] == "DIFFERENT" and c["path"].endswith(".py")]}
            buckets: dict[str, list[dict[str, str]]] = {}
            for failure in failures:
                cause = attribute_failure(failure, rules)
                buckets.setdefault(cause, []).append({"test": failure["test"], "kind": failure["kind"],
                                                      "exception": failure["exception"]})
            result["tests"] = {k: v for k, v in tests.items() if k != "output"}
            result["tests"]["failures_by_cause"] = buckets
            import_failed = tests["tests_run"] == 0 and not tests["passed"]
            if import_failed or buckets.get("UNATTRIBUTED"):
                result["refusals"].append(fail_closed(
                    TESTS_FAILED, "BASELINE_EGRESS_TESTS_PASS_ON_THE_CONVERGED_TREE",
                    "repair the unattributed failures named in detail (evidence/tests.out); each is a "
                    "divergence between a carried org extension or org-owned closure file and the baseline contract",
                    goal, "rerun converge; the test step reruns on the converged tree",
                    detail={"tests_run": tests["tests_run"], "import_failed": import_failed,
                            "unattributed": [f["test"] for f in buckets.get("UNATTRIBUTED", [])],
                            "error_kinds": tests["error_kinds"]}))
            divergent = {cause.split(":", 1)[1]: [f["test"] for f in found]
                         for cause, found in buckets.items() if cause.startswith("DIVERGENT_CLOSURE_FILE:")}
            if divergent:
                result["refusals"].append(fail_closed(
                    CLOSURE_DIVERGENT, "THE_TARGETS_CLOSURE_FILES_EXPOSE_THE_API_THE_BASELINE_CALLS",
                    "each closure file in detail is the organization's own revision and lacks baseline symbols or "
                    "signatures the converged files call; converge it as a further manifest unit with its own hunk "
                    "reconciliation, or have the organization add the named symbols",
                    goal, "rerun converge once those closure files expose the baseline API",
                    detail={path: {"tests": tests_,
                                   "missing_baseline_symbols": next(c for c in result["closure"] if c["path"] == path).get("missing_baseline_symbols"),
                                   "signature_differs": next(c for c in result["closure"] if c["path"] == path).get("signature_differs")}
                            for path, tests_ in divergent.items()}))
            # 6. the organization's own tests, before and after, so preservation is observed
            pending_org: list[str] = []
            for org_test in target.get("org_tests") or []:
                before_run = run_command(original, org_test["argv"], timeout)
                after_run = run_command(tree, org_test["argv"], timeout)
                name = re.sub(r"[^\w.-]+", "_", org_test["id"])
                (evidence_dir / f"org-test.{name}.before.out").write_text(before_run["output"], encoding="utf-8")
                (evidence_dir / f"org-test.{name}.after.out").write_text(after_run["output"], encoding="utf-8")
                record = {"id": org_test["id"],
                          "before": {k: v for k, v in before_run.items() if k != "output"},
                          "after": {k: v for k, v in after_run.items() if k != "output"}}
                result["org_tests"].append(record)
                after_failures = parse_test_failures(after_run["output"])
                if not after_failures and not after_run["passed"] and "Traceback (most recent call last):" in after_run["output"]:
                    tail = after_run["output"].rsplit("Traceback (most recent call last):", 1)[1]
                    lines_ = [l for l in tail.strip().splitlines() if l.strip()]
                    after_failures = [{"kind": "ERROR", "test": org_test["id"], "traceback": tail,
                                       "exception": lines_[-1][:300] if lines_ else ""}]  # a script-style test
                causes = sorted({attribute_failure(f, rules) for f in after_failures})
                record["after"]["failures_by_cause"] = {
                    c: [f["test"] for f in after_failures if attribute_failure(f, rules) == c] for c in causes}
                if before_run["passed"] and not after_run["passed"] and causes == ["PENDING_INTR_CLOSE_PORT"]:
                    pending_org.extend(record["after"]["failures_by_cause"]["PENDING_INTR_CLOSE_PORT"])
                elif before_run["passed"] and not after_run["passed"]:
                    result["refusals"].append(fail_closed(
                        ORG_REGRESSED, "THE_ORGANIZATIONS_OWN_TESTS_STILL_PASS_ON_THE_CONVERGED_TREE",
                        f"{org_test['id']} passed before convergence and fails after (evidence/org-test.{name}.after.out); "
                        "carry the behaviour it depends on in the extension",
                        goal, "rerun converge once the organization's own test passes on the converged tree",
                        detail={"org_test": org_test["id"]}))

            pending_baseline = [f["test"] for f in buckets.get("PENDING_INTR_CLOSE_PORT", [])]
            if pending_baseline or pending_org:
                result["refusals"].append(fail_closed(
                    CLOSE_PORT_PENDING, "CONVERGED_CLOSE_IS_THE_INTR_PORT_FOR_THIS_ORGANIZATION",
                    "InTr's per-organization close() port (H52), with the names it needs, lands in this target; "
                    "these tests fail only with a traceback through close()",
                    manifest.get("close_port_owning_goal") or goal,
                    "rerun converge on the target commit that carries the InTr close() port",
                    detail={"baseline_tests": pending_baseline, "org_tests": pending_org}))

    result["disposition"] = ALLOW if not result["refusals"] else FAIL_CLOSED
    evidence_files = sorted(p for p in evidence_dir.rglob("*") if p.is_file())
    evidence_manifest = {str(p.relative_to(evidence_dir)): sha256_bytes(p.read_bytes()) for p in evidence_files}
    result["evidence_manifest"] = evidence_manifest
    result["evidence_manifest_sha256"] = sha(evidence_manifest)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", default=str(ROOT / DEFAULT_MANIFEST))
    parser.add_argument("--organization", required=True)
    parser.add_argument("--target-root", required=True, help="a checkout of the target organization's .github")
    parser.add_argument("--baseline-root", default=str(ROOT))
    parser.add_argument("--out", required=True)
    parser.add_argument("--apply", action="store_true", help="write converged bytes into --target-root")
    parser.add_argument("--no-tests", action="store_true")
    parser.add_argument("--append", action="store_true",
                        help="append the receipt through --target-root's own emitter to STEGVERSE_REPO_LEDGER_ROOT")
    parser.add_argument("--hb-epoch", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args(argv)
    try:
        result = converge(Path(args.manifest), args.organization, Path(args.target_root),
                          Path(args.baseline_root), Path(args.out), apply=args.apply,
                          run_test_step=not args.no_tests, timeout=args.timeout)
        manifest = load_manifest(Path(args.manifest))
    except ConvergenceRefused as exc:
        print(json.dumps(fail_closed(exc.failure_code, exc.failed_predicate, exc.required,
                                     "StegVerse-org/.github#166", exc.next_attempt, exc.detail), indent=2))
        return 1
    if result["disposition"] is not None and args.organization in manifest["targets"]:
        body = receipt_body(manifest, args.organization, result, args.hb_epoch)
        result["receipt_body"] = body
        result["receipt_appended"] = None
        if args.append:
            refusal = epoch_refusal(args.hb_epoch, manifest["owning_existing_goal"])
            if refusal is not None:
                result["receipt_append_refusal"] = refusal
            elif not os.environ.get("STEGVERSE_REPO_LEDGER_ROOT"):
                result["receipt_append_refusal"] = fail_closed(
                    "LEDGER_LOCATION_REQUIRED_FROM_MATERIALIZER", "STEGVERSE_REPO_LEDGER_ROOT_SUPPLIED",
                    "the materializer supplies STEGVERSE_REPO_LEDGER_ROOT; it is never derived here",
                    manifest["owning_existing_goal"], "rerun with the ledger root supplied; nothing was appended")
            else:
                result["receipt_appended"] = append_receipt(body, Path(args.target_root))
    out = Path(args.out) / args.organization / "result.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {k: result.get(k) for k in ("organization", "disposition")}
    summary["refusals"] = [r["failure_code"] for r in result["refusals"]]
    summary["result"] = str(out)
    print(json.dumps(summary, sort_keys=True))
    return 0 if result["disposition"] == ALLOW else 1


if __name__ == "__main__":
    raise SystemExit(main())
