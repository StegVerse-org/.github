"""REQUIRED_VERIFICATION: no required test is skipped, unrun or missing, and no required job is left unrun
(StegVerse-org/.github#166 ENTERPRISE-HOST-PROVIDER-ERADICATION-001; Rigel's standing rule relayed by
Coordination, Oct 23, refined the same day: the skip rule must never stop work, so the suite is split into
callable test sets and a pull request must run the sets its change requires, with 0 skipped).

Lowest supported operating mode: E0. Stdlib only; no clock, no network, no secret, nothing written outside
--out. Three commands:

  run         runs unittest modules (discovered or listed) with a result class that records every outcome.
              A skipped test, an expected failure, an unexpected success, a module or fixture that did not
              load (loader _FailedTest, setUpClass / setUpModule error or skip), a run of 0 tests, and (with
              --base) a test present at the base commit and absent at the head are each FAIL_CLOSED
              REQUIRED_VERIFICATION_SKIPPED with six fields. A failing test is FAIL_CLOSED REQUIRED_TEST_FAILED:
              `run` holds no baseline. (The required-verification.yml full-suite job instead runs the selected
              test sets and adjudicates them against the receipted main baseline with the pinned
              StegVerse-Labs tool; see .stegverse/test-set-spec.json.)
  path-scope  for every path-filtered pull_request workflow at the head, a change that edits a file the
              workflow runs but that its filter does not match leaves a required job unrun ->
              REQUIRED_JOB_PATH_FILTERED_OUT; a pull_request job present at the base and absent at the head
              -> REQUIRED_JOB_MISSING. Both are REQUIRED_VERIFICATION_SKIPPED. (Transitive imports are not
              followed; the unfiltered required-verification.yml full-suite job covers them.)
  gate        every required job completed and succeeded, and the full-suite job showed a sealed test-set
              selection whose seal verified and which selected the always-run core set. Otherwise FAIL_CLOSED
              REQUIRED_VERIFICATION_SKIPPED (REQUIRED_JOB_NOT_SUCCESSFUL, REQUIRED_JOB_MISSING or
              SELECTION_NOT_SHOWN). Sets the selection did not select are listed by count only: they are not
              run and are not reported as skipped.

Exit 0 only when nothing is FAIL_CLOSED.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterable

SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
RVS = "REQUIRED_VERIFICATION_SKIPPED"
GOAL = "StegVerse-org/.github#166 ENTERPRISE-HOST-PROVIDER-ERADICATION-001"
PREDICATES = {
    "SKIPPED": "REQUIRED_TEST_IS_NOT_SKIPPED",
    "EXPECTED_FAILURE": "REQUIRED_TEST_IS_NOT_SKIPPED",
    "UNEXPECTED_SUCCESS": "REQUIRED_TEST_IS_NOT_SKIPPED",
    "COLLECTION_ERROR": "REQUIRED_MODULE_IS_COLLECTED_AND_RUN",
    "MODULE_NOT_RUN": "REQUIRED_MODULE_IS_COLLECTED_AND_RUN",
    "TEST_MISSING_AT_HEAD": "TEST_PRESENT_AT_BASE_RUNS_AT_HEAD",
    "SUITE_ACCOUNTING_UNOBSERVED": "EVERY_TEST_OUTCOME_IS_ACCOUNTED",
    "REQUIRED_JOB_PATH_FILTERED_OUT": "REQUIRED_JOB_RUNS_ON_A_CHANGE_IN_ITS_SCOPE",
    "REQUIRED_JOB_MISSING": "EVERY_REQUIRED_JOB_AT_THE_BASE_EXISTS_AT_THE_HEAD",
    "REQUIRED_JOB_NOT_SUCCESSFUL": "EVERY_REQUIRED_JOB_COMPLETED_AND_SUCCEEDED",
    "SELECTION_NOT_SHOWN": "THE_FULL_SUITE_SHOWS_A_SEALED_SELECTION_THAT_RAN_THE_CORE_SET",
}
FIXTURE_IDS = re.compile(r"^(setUpClass|tearDownClass|setUpModule|tearDownModule) \((.+)\)$")


def row(code: str, predicate: str, subject: str | None, repair: str, retry: str, nxt: str, goal: str = GOAL,
        **detail: Any) -> dict[str, Any]:
    return {"test": subject, "disposition": "FAIL_CLOSED", "blocking": True, "failure_code": code,
            "failed_predicate": predicate, "required_evidence_or_repair": repair, "retry_entrypoint": retry,
            "owning_existing_goal": goal, "next_attempt": nxt, **detail}


def rvs(kind: str, subject: str | None, repair: str, retry: str, nxt: str = "the next run of this job at the exact head",
        **detail: Any) -> dict[str, Any]:
    return row(RVS, PREDICATES[kind], subject, repair, retry, nxt, kind=kind, **detail)


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *a: Any, **k: Any) -> None:
        super().__init__(*a, **k)
        self.outcomes: list[tuple[str, str, str]] = []

    def addSuccess(self, test):  # noqa: N802
        super().addSuccess(test)
        self.outcomes.append((test.id(), "PASS", ""))

    def addFailure(self, test, err):  # noqa: N802
        super().addFailure(test, err)
        self.outcomes.append((test.id(), "FAIL", self._exc_info_to_string(err, test)[-300:]))

    def addError(self, test, err):  # noqa: N802
        super().addError(test, err)
        self.outcomes.append((test.id() if hasattr(test, "id") else str(test), "ERROR",
                              self._exc_info_to_string(err, test)[-300:] if hasattr(test, "_testMethodName") else str(err[1])[-300:]))

    def addSkip(self, test, reason):  # noqa: N802
        super().addSkip(test, reason)
        self.outcomes.append((test.id() if hasattr(test, "id") else str(test), "SKIPPED", str(reason)))

    def addExpectedFailure(self, test, err):  # noqa: N802
        super().addExpectedFailure(test, err)
        self.outcomes.append((test.id(), "EXPECTED_FAILURE", ""))

    def addUnexpectedSuccess(self, test):  # noqa: N802
        super().addUnexpectedSuccess(test)
        self.outcomes.append((test.id(), "UNEXPECTED_SUCCESS", ""))

    def addSubTest(self, test, subtest, err):  # noqa: N802
        super().addSubTest(test, subtest, err)
        if err is not None:
            kind = "FAIL" if issubclass(err[0], test.failureException) else "ERROR"
            self.outcomes.append((test.id(), kind, subtest.id() + ": " + self._exc_info_to_string(err, test)[-300:]))


def _walk(suite: unittest.TestSuite) -> Iterable[unittest.TestCase]:
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from _walk(t)
        else:
            yield t


def load(start: str, pattern: str, modules: list[str]) -> unittest.TestSuite:
    loader = unittest.TestLoader()
    if modules:
        return loader.loadTestsFromNames(modules)
    return loader.discover(start, pattern=pattern, top_level_dir=start)


def list_ids(tree: Path, start: str, pattern: str, modules: list[str]) -> list[str] | None:
    code = ("import json, sys, unittest\nsys.path.insert(0, sys.argv[1])\n"
            "from pathlib import Path\nimport importlib.util\n"
            "spec = importlib.util.spec_from_file_location('rv', sys.argv[2]); rv = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(rv)\n"
            "s = rv.load(sys.argv[1], sys.argv[3], [m for m in sys.argv[4:]])\n"
            "print(json.dumps(sorted(t.id() for t in rv._walk(s))))\n")
    done = subprocess.run([sys.executable, "-c", code, str(tree / start), __file__, pattern, *modules],
                          cwd=tree / start, capture_output=True, text=True)
    try:
        return json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def git(root: Path | str, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def run(root: Path, start: str, pattern: str, modules: list[str], base: str | None, retry: str) -> dict[str, Any]:
    sys.path.insert(0, str(root / start))
    suite = load(str(root / start), pattern, modules)
    planned = [t.id() for t in _walk(suite)]
    runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=2, resultclass=RecordingResult)
    result = runner.run(suite)
    rows: list[dict[str, Any]] = []
    counts = {"ran": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "skipped": len(result.skipped), "expected_failures": len(result.expectedFailures),
              "unexpected_successes": len(result.unexpectedSuccesses)}
    reported = set()
    for test_id, outcome, detail in result.outcomes:
        reported.add(test_id)
        fixture = FIXTURE_IDS.match(test_id)
        if test_id.startswith("unittest.loader._FailedTest") or ".loader._FailedTest." in test_id:
            rows.append(rvs("COLLECTION_ERROR", test_id.rsplit(".", 1)[-1], f"the module did not import, so none "
                            f"of its tests ran: {detail[-200:]}", retry))
        elif fixture and outcome in ("ERROR", "SKIPPED"):
            rows.append(rvs("COLLECTION_ERROR" if outcome == "ERROR" else "SKIPPED", test_id,
                            f"{fixture.group(1)} of {fixture.group(2)} {'failed' if outcome == 'ERROR' else 'skipped'}, "
                            f"so the tests behind it did not run: {detail[-200:]}", retry))
        elif outcome in ("SKIPPED", "EXPECTED_FAILURE", "UNEXPECTED_SUCCESS"):
            rows.append(rvs(outcome, test_id, f"run this test at the exact head; it was {outcome.lower().replace('_', ' ')}"
                            f"{' (' + detail[:200] + ')' if detail else ''}. A skipped run is unproven, not passed", retry))
        elif outcome in ("FAIL", "ERROR"):
            rows.append(row("REQUIRED_TEST_FAILED", "EVERY_REQUIRED_TEST_PASSES_AT_THE_EXACT_HEAD", test_id,
                            "fix the failure; this repository holds no receipted test baseline, so no failure is "
                            f"marked pre-existing: {detail[-200:]}", retry, "the next push to this pull request"))
    for test_id in planned:
        if test_id not in reported and not test_id.startswith("unittest.loader."):
            rows.append(rvs("SUITE_ACCOUNTING_UNOBSERVED", test_id, "a loaded test reported no outcome", retry))
    if result.testsRun == 0:
        rows.append(rvs("MODULE_NOT_RUN", " ".join(modules) or f"{start}/{pattern}", "the run executed 0 tests",
                        retry))
    base_count = None
    if base:
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "base"
            git(root, "worktree", "add", "--detach", "-q", str(tree), base)
            try:
                base_ids = list_ids(tree, start, pattern, modules)
            finally:
                git(root, "worktree", "remove", "--force", str(tree))
        if base_ids is None:
            rows.append(rvs("SUITE_ACCOUNTING_UNOBSERVED", None, "the base's tests could not be listed, so a test "
                            "removed by this change cannot be ruled out", retry))
        else:
            base_count = len(base_ids)
            have = set(planned)
            for test_id in base_ids:
                if test_id not in have and not test_id.startswith("unittest.loader."):
                    rows.append(rvs("TEST_MISSING_AT_HEAD", test_id, "the test exists at the base and is not run at "
                                    "the head (removed, renamed or no longer loaded); restore it, or land its removal "
                                    "as its own reviewed change naming the replacement", retry,
                                    "the next push to this pull request"))
    rows.sort(key=lambda r: r["failure_code"] != RVS)        # verification first: it sets the headline
    record: dict[str, Any] = {"schema": "stegverse.required-verification/v1", "lowest_supported_mode": "E0",
                              "counts": counts, "planned": len(planned), "base_tests": base_count, "tests": rows,
                              "required_verification_skipped": sum(1 for r in rows if r["failure_code"] == RVS),
                              "authority_effect": "NONE"}
    if rows:
        record.update({"disposition": "FAIL_CLOSED", **{k: rows[0][k] for k in SIX_FIELDS}})
    else:
        record["disposition"] = "ALLOW"
    return record


# -- path scope -------------------------------------------------------------------------------------------------

REFERENCED_PATH = re.compile(r"(?<![\w./-])((?:tests|scripts|resident-runtime|org-runtime|org-kernel|workers)/[\w./*-]+\.py)\b")


def glob_regex(pattern: str) -> re.Pattern:
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + "$")


def workflow_pr_filter(text: str) -> tuple[bool, list[str] | None, list[str]]:
    """(triggers on pull_request, its `paths` list or None when unfiltered, its `paths-ignore` list)."""
    lines = text.splitlines()
    on_idx = next((i for i, l in enumerate(lines) if re.match(r"^(on|'on'|\"on\"|true):", l)), None)
    if on_idx is None:
        return False, None, []
    if "pull_request" in lines[on_idx]:
        return bool(re.search(r"\bpull_request\b(?!_)", lines[on_idx])), None, []
    block, i = [], on_idx + 1
    while i < len(lines) and (not lines[i].strip() or lines[i].startswith((" ", "\t", "#"))):
        block.append(lines[i])
        i += 1
    at = next((j for j, l in enumerate(block) if re.match(r"^\s+pull_request\s*:", l)), None)
    if at is None:
        return any(re.match(r"^\s+-\s*pull_request\s*$", l) for l in block), None, []
    indent = len(block[at]) - len(block[at].lstrip())
    sub, j = [], at + 1
    while j < len(block) and (not block[j].strip() or block[j].lstrip().startswith("#")
                              or len(block[j]) - len(block[j].lstrip()) > indent):
        sub.append(block[j])
        j += 1
    lists: dict[str, list[str]] = {}
    key = None
    for l in sub:
        m = re.match(r"^\s+(paths|paths-ignore|branches|types|branches-ignore)\s*:\s*(\[.*\])?\s*$", l)
        if m:
            key = m.group(1)
            lists[key] = [p.strip().strip("'\"") for p in m.group(2)[1:-1].split(",")] if m.group(2) else []
            continue
        m = re.match(r"^\s+-\s*['\"]?([^'\"#]+?)['\"]?\s*(?:#.*)?$", l)
        if m and key:
            lists[key].append(m.group(1))
        elif l.strip() and not l.lstrip().startswith("#"):
            key = None
    return True, lists.get("paths"), lists.get("paths-ignore", [])


def workflow_jobs(text: str) -> list[str]:
    lines = text.splitlines()
    at = next((i for i, l in enumerate(lines) if re.match(r"^jobs\s*:", l)), None)
    jobs: list[str] = []
    for l in lines[at + 1:] if at is not None else []:
        if l and not l.startswith((" ", "\t", "#")):
            break
        m = re.match(r"^  ([A-Za-z_][\w-]*)\s*:", l)
        if m:
            jobs.append(m.group(1))
    return jobs


def _workflows(root: Path, commit: str) -> dict[str, str]:
    names = git(root, "ls-tree", "--name-only", commit, ".github/workflows/").split()
    return {wf: git(root, "show", f"{commit}:{wf}") for wf in names if wf.endswith((".yml", ".yaml"))}


def path_scope(root: Path, base: str, head: str, retry: str) -> dict[str, Any]:
    diff = sorted(git(root, "diff", "--name-only", f"{base}...{head}").split())
    rows, table = [], []
    at_head = _workflows(root, head)
    for wf, text in sorted(at_head.items()):
        on_pr, paths, ignore = workflow_pr_filter(text)
        if not on_pr:
            continue
        pats = [p for p in REFERENCED_PATH.findall(text)]
        referenced = {wf} | {p for p in pats if "*" not in p}
        globs = [glob_regex(p) for p in pats if "*" in p]
        if paths is None:
            triggered = bool(diff) and not (ignore and all(any(glob_regex(p).match(f) for p in ignore) for f in diff))
        else:
            inc = [glob_regex(p) for p in paths if not p.startswith("!")]
            neg = [glob_regex(p[1:]) for p in paths if p.startswith("!")]
            triggered = any(any(r.match(f) for r in inc) and not any(n.match(f) for n in neg) for f in diff)
        in_scope = sorted(f for f in diff if f in referenced or any(g.match(f) for g in globs))
        table.append({"workflow": wf, "path_filtered": paths is not None, "triggered": triggered,
                      "changed_files_it_runs": in_scope})
        if in_scope and not triggered:
            rows.append(rvs("REQUIRED_JOB_PATH_FILTERED_OUT", wf, f"this change edits {', '.join(in_scope)}, which "
                            f"{wf} runs, but its pull_request path filter does not match the change, so the job never "
                            "runs: add those paths to its filter", retry, "the next push to this pull request",
                            changed_files=in_scope))
    for wf, text in sorted(_workflows(root, base).items()):
        if not workflow_pr_filter(text)[0]:
            continue
        head_jobs = workflow_jobs(at_head[wf]) if wf in at_head and workflow_pr_filter(at_head[wf])[0] else []
        for job in workflow_jobs(text):
            if job not in head_jobs:
                rows.append(rvs("REQUIRED_JOB_MISSING", f"{wf}#{job}", "this pull_request job runs at the base and is "
                                "absent at the head; restore it, or land its retirement as its own reviewed change "
                                "naming where its checks now run", retry, "the next push to this pull request"))
    record: dict[str, Any] = {"schema": "stegverse.required-verification-path-scope/v1", "base": base, "head": head,
                              "changed_paths": diff, "workflows": table, "tests": rows, "authority_effect": "NONE",
                              "required_verification_skipped": len(rows)}
    record.update({"disposition": "FAIL_CLOSED", **{k: rows[0][k] for k in SIX_FIELDS}} if rows else
                  {"disposition": "ALLOW"})
    return record


def gate(needs: dict[str, Any], selection: dict[str, Any] | None, required: list[str], retry: str) -> dict[str, Any]:
    nxt = "the next push to this pull request"
    rows = []
    for job in sorted(set(required) - set(needs)):
        rows.append(rvs("REQUIRED_JOB_MISSING", job, f"the gate needs {job}; restore it in the gate's needs", retry, nxt))
    for job, v in sorted(needs.items()):
        result = (v or {}).get("result")
        if result != "success":
            rows.append(rvs("REQUIRED_JOB_NOT_SUCCESSFUL", job, f"{job} ended {result!r}; its own record names the "
                            "six fields to repair", retry, nxt, result=result))
    sel = selection if isinstance(selection, dict) else {}
    if not (sel.get("seal_verifies") is True and sel.get("core_selected") is True and sel.get("receipt_sha256")):
        rows.append(rvs("SELECTION_NOT_SHOWN", "full-suite", "the full-suite job must output a test-set selection "
                        "whose seal verifies and which selected the core set (seal_verifies, core_selected, "
                        f"receipt_sha256); got {json.dumps(sel, sort_keys=True)[:400]}", retry, nxt))
    record: dict[str, Any] = {"schema": "stegverse.required-verification-gate/v1", "jobs": {k: (v or {}).get("result")
                              for k, v in sorted(needs.items())}, "required_jobs": sorted(required),
                              "selection": sel, "tests": rows, "authority_effect": "NONE",
                              "required_verification_skipped": len(rows)}
    record.update({"disposition": "FAIL_CLOSED", **{k: rows[0][k] for k in SIX_FIELDS}} if rows else
                  {"disposition": "ALLOW"})
    return record


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="REQUIRED_VERIFICATION (E0)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--root", default=".")
    r.add_argument("--start", default="tests")
    r.add_argument("--pattern", default="test_*.py")
    r.add_argument("--module", action="append", default=[], help="dotted module (relative to --start) to run")
    r.add_argument("--base", help="base commit: every test it holds must run at the head")
    r.add_argument("--retry-entrypoint", required=True)
    r.add_argument("--out", required=True)
    s = sub.add_parser("path-scope")
    s.add_argument("--root", default=".")
    s.add_argument("--base", required=True)
    s.add_argument("--head", required=True)
    s.add_argument("--retry-entrypoint", required=True)
    s.add_argument("--out", required=True)
    g = sub.add_parser("gate")
    g.add_argument("--needs", required=True, help="the gate job's toJSON(needs)")
    g.add_argument("--selection", default="", help="the full-suite job's selection summary (JSON)")
    g.add_argument("--require", action="append", required=True, help="a job the gate needs (repeat)")
    g.add_argument("--retry-entrypoint", required=True)
    g.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "gate":
        try:
            selection = json.loads(a.selection) if a.selection.strip() else None
        except json.JSONDecodeError:
            selection = None
        record = gate(json.loads(a.needs), selection, a.require, a.retry_entrypoint)
    else:
        root = Path(a.root).resolve()
        record = (run(root, a.start, a.pattern, a.module, a.base, a.retry_entrypoint) if a.cmd == "run"
                  else path_scope(root, a.base, a.head, a.retry_entrypoint))
    Path(a.out).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: record.get(k) for k in ("disposition", "counts", "required_verification_skipped", "jobs",
                                                 *SIX_FIELDS) if k in record}, sort_keys=True))
    for t in record["tests"]:
        print(f"FAIL_CLOSED {t['failure_code']}{'/' + t['kind'] if t.get('kind') else ''} {t['test']}")
    return 0 if record["disposition"] == "ALLOW" else 1


if __name__ == "__main__":
    sys.exit(main())
