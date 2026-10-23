"""REQUIRED_VERIFICATION (resident-runtime/required_verification.py) over toy repositories: every skipped,
expected-failure, unexpected-success, unloaded, fixture-skipped, missing-at-head or zero-test run, and every
path-filtered-out or missing required job, is FAIL_CLOSED REQUIRED_VERIFICATION_SKIPPED with six fields; a
failing test is REQUIRED_TEST_FAILED and never pre-existing."""
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

    def test_the_workflows_of_this_pull_request_use_the_strict_runner(self) -> None:
        for name in ("drift-receipt-appender-validation.yml", "main-change-receipt-validation.yml",
                     "required-verification.yml"):
            text = (ROOT / ".github" / "workflows" / name).read_text()
            self.assertIn("resident-runtime/required_verification.py", text, name)
            self.assertNotIn("unittest discover", text, name)
            for word in ("workflow_dispatch", "schedule:", "cron", "contents: write"):
                self.assertNotIn(word, text, name)
        on_pr, paths, _ = rv.workflow_pr_filter((ROOT / ".github/workflows/required-verification.yml").read_text())
        self.assertTrue(on_pr)
        self.assertIsNone(paths)          # the full suite and the path-scope check run on every pull request


if __name__ == "__main__":
    unittest.main()
