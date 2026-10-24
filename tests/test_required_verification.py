"""REQUIRED_VERIFICATION (resident-runtime/required_verification.py) over toy repositories: every skipped,
expected-failure, unexpected-success, unloaded, fixture-skipped, missing-at-head or zero-test run, and every
path-filtered-out or missing required job, is FAIL_CLOSED REQUIRED_VERIFICATION_SKIPPED with six fields; a
failing test is REQUIRED_TEST_FAILED and never pre-existing under `run`. The gate needs every job to succeed
and the full suite to show a sealed selection that ran the core set."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "resident-runtime" / "required_verification.py"
sys.path.insert(0, str(TOOL.parent))
if str(ROOT) not in sys.path:  # tests.workflow_surface (G17 #238) when run with --start tests
    sys.path.append(str(ROOT))
import required_verification as rv  # noqa: E402

SIX = rv.SIX_FIELDS
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@stegverse.invalid", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@stegverse.invalid", "GIT_CONFIG_NOSYSTEM": "1"}
OK_TEST = "import unittest\nclass A(unittest.TestCase):\n    def test_a(self):\n        pass\n    def test_b(self):\n        pass\n"


class RequiredVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        (self.repo / "tests").mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.write("tests/test_a.py", OK_TEST)
        self.base = self.commit("base")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True,
                              env=ENV).stdout.strip()

    def write(self, rel: str, text: str) -> None:
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self, msg: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def run_tool(self, *args: str) -> tuple[int, dict]:
        out = Path(self.tmp.name) / "out.json"
        done = subprocess.run([sys.executable, str(TOOL), *args, "--root", str(self.repo), "--retry-entrypoint",
                               "toy.yml", "--out", str(out)], capture_output=True, text=True, env=ENV)
        return done.returncode, json.loads(out.read_text())

    def assert_rvs(self, code: int, record: dict, kind: str) -> dict:
        self.assertEqual(code, 1)
        self.assertEqual(record["disposition"], "FAIL_CLOSED")
        self.assertEqual(record["failure_code"], "REQUIRED_VERIFICATION_SKIPPED")
        for k in SIX:
            self.assertTrue(record.get(k), k)
        hits = [t for t in record["tests"] if t.get("kind") == kind]
        self.assertTrue(hits, [t.get("kind") for t in record["tests"]])
        for t in hits:
            self.assertEqual((t["failure_code"], t["disposition"], t["blocking"]),
                             ("REQUIRED_VERIFICATION_SKIPPED", "FAIL_CLOSED", True))
            for k in SIX:
                self.assertTrue(t.get(k), k)
        self.assertNotIn("PRE_EXISTING_BASELINE_FAILURE", json.dumps(record))
        return hits[0]

    def test_clean_run_is_allow(self) -> None:
        code, record = self.run_tool("run", "--base", self.base)
        self.assertEqual((code, record["disposition"]), (0, "ALLOW"))
        self.assertEqual(record["counts"]["ran"], 2)
        self.assertEqual(record["counts"]["skipped"], 0)

    def test_skip_expected_failure_and_unexpected_success(self) -> None:
        self.write("tests/test_k.py", "import unittest\nclass K(unittest.TestCase):\n"
                   "    @unittest.skip('tool absent')\n    def test_s(self):\n        pass\n"
                   "    @unittest.expectedFailure\n    def test_xf(self):\n        self.fail()\n"
                   "    @unittest.expectedFailure\n    def test_xp(self):\n        pass\n")
        self.commit("k")
        code, record = self.run_tool("run")
        self.assertEqual(self.assert_rvs(code, record, "SKIPPED")["test"], "test_k.K.test_s")
        self.assert_rvs(code, record, "EXPECTED_FAILURE")
        self.assert_rvs(code, record, "UNEXPECTED_SUCCESS")

    def test_setupclass_skip_like_an_unreachable_private_repository(self) -> None:
        self.write("tests/test_o.py", "import unittest\nclass O(unittest.TestCase):\n    @classmethod\n"
                   "    def setUpClass(cls):\n        raise unittest.SkipTest('repo-standards unreachable')\n"
                   "    def test_o(self):\n        pass\n")
        self.commit("o")
        code, record = self.run_tool("run")
        self.assertTrue(self.assert_rvs(code, record, "SKIPPED")["test"].startswith("setUpClass"))

    def test_module_that_does_not_import(self) -> None:
        self.write("tests/test_bad.py", "import not_a_module_anywhere\n")
        self.commit("bad")
        code, record = self.run_tool("run")
        self.assertEqual(self.assert_rvs(code, record, "COLLECTION_ERROR")["test"], "test_bad")

    def test_zero_tests_is_module_not_run(self) -> None:
        code, record = self.run_tool("run", "--pattern", "test_nothing_matches_*.py")
        self.assert_rvs(code, record, "MODULE_NOT_RUN")

    def test_test_present_at_base_and_missing_at_head(self) -> None:
        self.write("tests/test_a.py", OK_TEST.split("    def test_b")[0])
        self.commit("drop test_b")
        code, record = self.run_tool("run", "--base", self.base)
        self.assertEqual(self.assert_rvs(code, record, "TEST_MISSING_AT_HEAD")["test"], "test_a.A.test_b")

    def test_failure_is_fail_closed_and_never_pre_existing(self) -> None:
        self.write("tests/test_f.py", "import unittest\nclass F(unittest.TestCase):\n    def test_f(self):\n"
                   "        self.fail('x')\n")
        self.commit("f")
        code, record = self.run_tool("run")
        self.assertEqual(code, 1)
        self.assertEqual(record["failure_code"], "REQUIRED_TEST_FAILED")
        self.assertNotIn("PRE_EXISTING_BASELINE_FAILURE", json.dumps(record))

    def test_skip_sorts_ahead_of_a_failure(self) -> None:
        self.write("tests/test_f.py", "import unittest\nclass F(unittest.TestCase):\n    def test_f(self):\n"
                   "        self.fail('x')\n    @unittest.skip('r')\n    def test_s(self):\n        pass\n")
        self.commit("f")
        code, record = self.run_tool("run")
        self.assert_rvs(code, record, "SKIPPED")

    def test_path_filter_leaving_a_required_job_unrun(self) -> None:
        wf = ("name: unit\non:\n  pull_request:\n    branches: [main]\n    paths:\n      - 'tests/test_a.py'\n"
              "{more}permissions:\n  contents: read\njobs:\n  unit:\n    runs-on: ubuntu-latest\n    steps:\n"
              "      - run: python3 resident-runtime/tool.py && python3 -m unittest discover -s tests -p 'test_a.py'\n")
        self.write(".github/workflows/unit.yml", wf.format(more=""))
        self.write("resident-runtime/tool.py", "print(1)\n")
        base = self.commit("wf")
        self.write("resident-runtime/tool.py", "print(2)\n")
        head = self.commit("edit tool")
        code, record = self.run_tool("path-scope", "--base", base, "--head", head)
        row = self.assert_rvs(code, record, "REQUIRED_JOB_PATH_FILTERED_OUT")
        self.assertEqual(row["changed_files"], ["resident-runtime/tool.py"])
        self.write(".github/workflows/unit.yml", wf.format(more="").replace(
            "      - 'tests/test_a.py'\n", "      - 'tests/test_a.py'\n      - 'resident-runtime/tool.py'\n"))
        head = self.commit("widen")
        code, record = self.run_tool("path-scope", "--base", base, "--head", head)
        self.assertEqual((code, record["disposition"]), (0, "ALLOW"), record)

    def test_missing_required_job(self) -> None:
        self.write(".github/workflows/unit.yml", "name: u\non: pull_request\njobs:\n  unit:\n    runs-on: x\n"
                   "    steps: []\n  dry-run:\n    runs-on: x\n    steps: []\n")
        base = self.commit("two jobs")
        self.write(".github/workflows/unit.yml", "name: u\non: pull_request\njobs:\n  unit:\n    runs-on: x\n"
                   "    steps: []\n")
        head = self.commit("drop dry-run")
        code, record = self.run_tool("path-scope", "--base", base, "--head", head)
        self.assertEqual(self.assert_rvs(code, record, "REQUIRED_JOB_MISSING")["test"], ".github/workflows/unit.yml#dry-run")
        (self.repo / ".github/workflows/unit.yml").unlink()
        head = self.commit("drop the workflow")
        code, record = self.run_tool("path-scope", "--base", base, "--head", head)
        self.assertEqual(len([t for t in record["tests"] if t["kind"] == "REQUIRED_JOB_MISSING"]), 2)

    def test_workflow_filter_forms(self) -> None:
        f = rv.workflow_pr_filter
        self.assertEqual(f("on:\n  pull_request:\n  push:\n"), (True, None, []))
        self.assertEqual(f("on: [push, pull_request]\n"), (True, None, []))
        self.assertEqual(f("on:\n  pull_request:\n    paths: ['a/**', 'b.py']\n"), (True, ["a/**", "b.py"], []))
        self.assertEqual(f("on:\n  push:\n    paths:\n      - 'x'\n"), (False, None, []))
        self.assertTrue(rv.glob_regex("tests/test_main_change_receipt*.py").match("tests/test_main_change_receipt_census.py"))
        self.assertTrue(rv.glob_regex("**/*.json").match("x.json"))

    def gate(self, needs: dict, selection: str) -> tuple[int, dict]:
        out = Path(self.tmp.name) / "gate.json"
        done = subprocess.run([sys.executable, str(TOOL), "gate", "--needs", json.dumps(needs), "--selection",
                               selection, "--require", "full-suite", "--require", "path-scope",
                               "--retry-entrypoint", "toy.yml", "--out", str(out)],
                              capture_output=True, text=True, env=ENV)
        return done.returncode, json.loads(out.read_text())

    def test_gate_allows_successful_jobs_with_a_shown_selection(self) -> None:
        ok = {"full-suite": {"result": "success"}, "path-scope": {"result": "success"}}
        shown = json.dumps({"receipt_sha256": "sha256:ab", "seal_verifies": True, "core_selected": True,
                            "mode": "DIFF", "sets_total": 98, "selected_count": 2, "input_unavailable": []})
        code, record = self.gate(ok, shown)
        self.assertEqual((code, record["disposition"]), (0, "ALLOW"))
        self.assertEqual(record["selection"]["selected_count"], 2)
        self.assertNotIn("SKIPPED", json.dumps(record["selection"]))   # unselected sets are counted, not "skipped"

    def test_gate_fails_closed_on_an_unsuccessful_or_missing_job_or_an_unshown_selection(self) -> None:
        shown = json.dumps({"receipt_sha256": "sha256:ab", "seal_verifies": True, "core_selected": True})
        code, record = self.gate({"full-suite": {"result": "failure"}, "path-scope": {"result": "success"}}, shown)
        self.assertEqual(self.assert_rvs(code, record, "REQUIRED_JOB_NOT_SUCCESSFUL")["test"], "full-suite")
        code, record = self.gate({"full-suite": {"result": "success"}}, shown)
        self.assertEqual(self.assert_rvs(code, record, "REQUIRED_JOB_MISSING")["test"], "path-scope")
        ok = {"full-suite": {"result": "success"}, "path-scope": {"result": "success"}}
        for sel in ("", "not json", json.dumps({"receipt_sha256": "sha256:ab", "seal_verifies": False,
                                                "core_selected": True}),
                    json.dumps({"receipt_sha256": "sha256:ab", "seal_verifies": True, "core_selected": False})):
            code, record = self.gate(ok, sel)
            self.assert_rvs(code, record, "SELECTION_NOT_SHOWN")

    def test_gate_holds_the_selection_to_this_pull_requests_exact_head_and_base(self) -> None:
        ok = {"full-suite": {"result": "success"}, "path-scope": {"result": "success"}}
        head, base, merge = "a" * 40, "b" * 40, "c" * 40
        sel = {"receipt_sha256": "sha256:ab", "seal_verifies": True, "core_selected": True, "mode": "DIFF",
               "head_sha": merge, "base_sha": base, "pr_head_sha": head}

        def run(selection: dict, *extra: str) -> tuple[int, dict]:
            out = Path(self.tmp.name) / "gate-bound.json"
            done = subprocess.run([sys.executable, str(TOOL), "gate", "--needs", json.dumps(ok), "--selection",
                                   json.dumps(selection), "--require", "full-suite", "--require", "path-scope",
                                   *extra, "--retry-entrypoint", "toy.yml", "--out", str(out)],
                                  capture_output=True, text=True, env=ENV)
            return done.returncode, json.loads(out.read_text())

        code, record = run(sel, "--pr-head", head, "--base-sha", base)
        self.assertEqual((code, record["disposition"]), (0, "ALLOW"), record)
        for bad in (dict(sel, pr_head_sha="d" * 40), dict(sel, base_sha="d" * 40), dict(sel, head_sha=None),
                    {k: v for k, v in sel.items() if k != "pr_head_sha"}):
            code, record = run(bad, "--pr-head", head, "--base-sha", base)
            self.assertEqual(self.assert_rvs(code, record, "SELECTION_NOT_FOR_THIS_HEAD")["test"], "full-suite")

    def test_the_full_suite_runs_only_the_selected_sets_with_the_pinned_labs_tool(self) -> None:
        from tests.workflow_surface import catalog_group, catalog_groups, step_bodies
        # G17 (#238): the workflow's jobs are catalog groups run by validation-dispatcher.yml; the aggregator's gate
        # is the last step of required-verification.full-suite and path-scope is its own group (its own check)
        self.assertEqual([g["id"] for g in catalog_groups("required-verification.yml")],
                         ["required-verification.full-suite", "required-verification.path-scope"])
        full = catalog_group("required-verification.full-suite")
        wf = step_bodies(full) + json.dumps(full["env"])
        self.assertEqual(full["steps"][-1]["run_file"].rsplit("/", 1)[1], "08-the-sealed-selection-ran-the-core-set-gate.sh")
        self.assertNotIn("if", full["steps"][-1])        # the gate runs only when every earlier step succeeded
        for needle in ('test_set_selection.py" select', "--selection", "--baseline-receipt", "labs-tool-pin.json",
                       "required_verification.py gate", "--require full-suite",
                       '--pr-head "$HEAD_SHA"', '--base-sha "$BASE_SHA"', "STEGVERSE_LABS_ROOT", '"head_sha"'):
            self.assertIn(needle, wf)
        self.assertNotIn("run --pattern", wf)            # no whole-suite run beside the selected sets
        pin = json.loads((ROOT / ".stegverse/test-suite-baseline/labs-tool-pin.json").read_text())
        self.assertRegex(pin["commit"], r"^[0-9a-f]{40}$")
        self.assertIn("scripts/test_set_selection.py", pin["files"])
        self.assertIn("scripts/test_suite_baseline_drift.py", pin["files"])
        for digest in pin["files"].values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
        spec = json.loads((ROOT / ".stegverse/test-set-spec.json").read_text())
        self.assertEqual(spec["core"]["tests"], ["tests/test_required_verification.py"])
        for path in ("tools/tasks/steps/required-verification.full-suite/*", "tools/tasks/task_catalog.json",
                     ".stegverse/test-suite-baseline/labs-tool-pin.json"):
            self.assertIn(path, spec["selects_all"])
        for name, decl in spec["inputs"].items():
            for key in ("owner", "repair", "finish_point", "check"):
                self.assertTrue(decl.get(key), (name, key))
        manifest = json.loads((ROOT / ".stegverse/test-sets.json").read_text())
        ids = {s["id"] for s in manifest["sets"]}
        self.assertIn("core", ids)
        for path in sorted((ROOT / "tests").glob("test_*.py")):
            rel = path.relative_to(ROOT).as_posix()
            self.assertTrue(any(i == rel or i.startswith(rel + "[") for i in ids) or
                            rel in spec["core"]["tests"], rel)

    def test_the_workflows_of_this_pull_request_use_the_strict_runner(self) -> None:
        from tests.workflow_surface import DISPATCHER, catalog_groups, step_bodies
        for name in ("drift-receipt-appender-validation.yml", "main-change-receipt-validation.yml",
                     "required-verification.yml"):
            self.assertFalse((ROOT / ".github" / "workflows" / name).exists(), name)   # G17: catalog groups only
            groups = catalog_groups(name)
            self.assertTrue(groups, name)
            text = "\n".join(step_bodies(g) + json.dumps(g["env"]) for g in groups)
            self.assertIn("resident-runtime/required_verification.py", text, name)
            self.assertNotIn("unittest discover", text, name)
            for word in ("workflow_dispatch", "schedule:", "cron", "contents: write", "git push"):
                self.assertNotIn(word, text, name)
            for g in groups:
                self.assertEqual(g["events"], ["pull_request"], g["id"])
        on_pr, paths, _ = rv.workflow_pr_filter(DISPATCHER.read_text())
        self.assertTrue(on_pr)
        self.assertIsNone(paths)          # the full suite and the path-scope check run on every pull request


if __name__ == "__main__":
    unittest.main()
