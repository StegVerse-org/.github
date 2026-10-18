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
        "symbols": {}, "closure": [], "refusals": [], "tests": None, "applied": False,
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
    reconciled = set(target.get("reconciled_hunk_sha256") or [])
    rendered: dict[str, bytes] = {}

    # 1. pins
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
        after = render(base_bytes, path, manifest, values)
        rendered[path] = after
        after_sha = sha256_bytes(after)
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
            "after_sha256": after_sha, "after_lines": after.count(b"\n"),
            "after_normalized_sha256": sha256_bytes(normalize(after, path, manifest, values)),
            "baseline_sha256": entry["sha256"],
            "byte_identical_to_baseline": after == base_bytes,
            "already_converged": before == after,
            "diff_file": diff_name, "diff_lines": diff.count("\n"),
            "diff_sha256": sha256_bytes(diff.encode("utf-8")),
        })
        if normalized_before is not None:
            result["hunks"].extend(classify_hunks(base_bytes, normalized_before, path, organization, reconciled))
            if path.endswith(".py"):
                b_syms = top_level_symbols(base_bytes.decode("utf-8"))
                t_syms = top_level_symbols(normalized_before.decode("utf-8", errors="replace"))
                result["symbols"][path] = {
                    "only_in_target": sorted(set(t_syms) - set(b_syms)),
                    "only_in_baseline": sorted(set(b_syms) - set(t_syms)),
                    "changed": sorted(n for n in set(t_syms) & set(b_syms) if t_syms[n] != b_syms[n]),
                    "identical": sorted(n for n in set(t_syms) & set(b_syms) if t_syms[n] == b_syms[n]),
                }

    # 2. no silent deletion
    unreconciled = [h for h in result["hunks"]
                    if h["class"] in (ORG_SPECIFIC_HUNK, DIVERGENT) and not h["reconciled"]]
    if unreconciled:
        org_specific = [h for h in unreconciled if h["class"] == ORG_SPECIFIC_HUNK]
        result["refusals"].append(fail_closed(
            ORG_SPECIFIC, "EVERY_NON_PARAMETER_NON_COSMETIC_TARGET_HUNK_IS_RECONCILED",
            "for each hunk named in detail: port it into the baseline under the owning goal, or record its "
            "hunk_sha256 under targets." + organization + ".reconciled_hunk_sha256 with the reason it is superseded; "
            "convergence never deletes it silently",
            goal, "rerun converge once every listed hunk_sha256 is reconciled in the manifest",
            detail={"org_specific_hunks": len(org_specific),
                    "divergent_code_hunks": len(unreconciled) - len(org_specific),
                    "new_top_level_definitions": sorted({d for h in unreconciled for d in h["new_top_level_definitions"]}),
                    "hunk_sha256": [h["hunk_sha256"] for h in unreconciled]}))

    # 3. closure
    seeds = [e["path"] for e in manifest["baseline"]["files"].values()]
    for path in dependency_closure(Path(baseline_root), seeds):
        target_file = Path(target_root) / path
        base_sha = sha256_bytes((Path(baseline_root) / path).read_bytes())
        state = "ABSENT"
        if target_file.is_file():
            state = "IDENTICAL" if sha256_bytes(target_file.read_bytes()) == base_sha else "DIFFERENT"
        result["closure"].append({"path": path, "org_owned": is_org_owned(path, manifest),
                                  "baseline_sha256": base_sha, "target_state": state})
    absent = [c["path"] for c in result["closure"] if c["target_state"] == "ABSENT"]
    if absent:
        result["refusals"].append(fail_closed(
            CLOSURE_ABSENT, "EVERY_FILE_THE_BASELINE_LOADS_EXISTS_IN_THE_TARGET",
            "converge or declare each absent closure file (detail) in the target organization first; "
            "org-owned ones are that organization's own configuration and are not overwritten from the baseline",
            goal, "rerun converge once the closure resolves in the target",
            detail={"absent": absent,
                    "absent_org_owned": [c["path"] for c in result["closure"]
                                         if c["target_state"] == "ABSENT" and c["org_owned"]]}))

    # 4. converge, in a sandbox unless applying
    with tempfile.TemporaryDirectory(prefix=f"convergence-{organization}-") as sandbox:
        tree = Path(target_root) if apply else Path(sandbox) / "tree"
        if not apply:
            shutil.copytree(target_root, tree, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        blocked = any(r["failure_code"] in (BASELINE_MISMATCH, TARGET_DRIFTED, ORG_SPECIFIC)
                      for r in result["refusals"])
        if apply and blocked:
            pass  # never overwrite the real checkout across an unreconciled refusal
        else:
            for path, data in rendered.items():
                (tree / path).parent.mkdir(parents=True, exist_ok=True)
                (tree / path).write_bytes(data)
            result["applied"] = apply
        converged_dir = out_dir / "converged"
        for path, data in rendered.items():
            (converged_dir / path).parent.mkdir(parents=True, exist_ok=True)
            (converged_dir / path).write_bytes(data)
        # 5. tests
        if run_test_step and (not apply or result["applied"]):
            tests = run_tests(tree, manifest.get("test_modules") or [], timeout)
            (evidence_dir / "tests.out").write_text(tests["output"], encoding="utf-8")
            result["tests"] = {k: v for k, v in tests.items() if k != "output"}
            if not tests["passed"]:
                result["refusals"].append(fail_closed(
                    TESTS_FAILED, "BASELINE_EGRESS_TESTS_PASS_ON_THE_CONVERGED_TREE",
                    "repair the failing tests' preconditions in the target (see evidence/tests.out); "
                    "a refusal from an earlier predicate usually explains them",
                    goal, "rerun converge; the test step reruns on the converged tree",
                    detail={k: tests[k] for k in ("tests_run", "failures", "errors", "error_kinds", "timed_out")}))

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
