"""test_suite_skip_receipt.py: every skip on a head is listed and fails closed.

Synthetic JUnit XML in a temporary directory only. Nothing here is skipped.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "test_suite_skip_receipt", ROOT / "scripts" / "test_suite_skip_receipt.py")
receipt_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(receipt_module)

SIX = receipt_module.SIX


def junit(cases: str) -> str:
    return f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{cases}</testsuite></testsuites>'


PASS = '<testcase classname="tests.test_a" name="test_ok" time="0.1"/>'
SKIP = ('<testcase classname="tests.test_b.K" name="test_needs_x" time="0">'
        '<skipped type="pytest.skip" message="X is not installed">tests/test_b.py:12: X is not installed</skipped></testcase>')
FAIL = '<testcase classname="tests.test_c" name="test_bad"><failure message="boom"/></testcase>'
ERR = '<testcase classname="" name="tests.test_d"><error message="collection failure"/></testcase>'
XFAIL = '<testcase classname="tests.test_e" name="test_x"><skipped type="pytest.xfail" message="known"/></testcase>'


class SkipReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def build(self, cases: str, items=(), base_cases: str | None = None) -> dict:
        base = self.write("base.xml", junit(base_cases)) if base_cases is not None else None
        return receipt_module.build(self.write("head.xml", junit(cases)), "h" * 40, "retry",
                                    "goal", list(items), base, "b" * 40 if base else None)

    def test_zero_skipped_and_no_failure_is_allow(self):
        r = self.build(PASS)
        self.assertEqual(r["disposition"], "ALLOW")
        self.assertEqual(r["counts"]["skipped"], 0)
        self.assertEqual(r["refusals"], [])

    def test_a_skip_fails_closed_with_the_six_fields_and_is_listed_with_its_reason(self):
        r = self.build(PASS + SKIP)
        self.assertEqual(r["disposition"], "FAIL_CLOSED")
        self.assertEqual(r["counts"]["skipped"], 1)
        (ref,) = r["refusals"]
        self.assertEqual(ref["failure_code"], "TEST_SUITE_SKIPPED_ON_HEAD")
        self.assertEqual(set(ref), set(SIX))
        self.assertTrue(all(ref[k] for k in SIX))
        (row,) = r["skipped"]
        self.assertEqual(row["test"], "tests.test_b.K::test_needs_x")
        self.assertEqual(row["reason"], "X is not installed")
        self.assertEqual(row["location"], "tests/test_b.py:12")

    def test_an_unrecorded_skip_still_fails_closed_and_says_it_has_no_owner(self):
        row = self.build(SKIP)["skipped"][0]
        self.assertEqual(row["item"]["failure_code"], "TEST_SUITE_SKIP_UNCLASSIFIED")
        self.assertEqual(row["item"]["owning_existing_goal"], "UNRECORDED")

    def test_a_recorded_owner_item_never_converts_the_skip(self):
        item = dict(zip(SIX, ("C", "P", "R", "E", "G", "N")), test_prefix="tests.test_b.",
                    classification="K")
        r = self.build(SKIP, items=[item])
        self.assertEqual(r["disposition"], "FAIL_CLOSED")
        self.assertEqual(r["counts"]["skipped"], 1)
        self.assertEqual(r["skipped"][0]["item"]["owning_existing_goal"], "G")

    def test_xfail_is_listed_apart_from_skips(self):
        r = self.build(PASS + XFAIL)
        self.assertEqual((r["counts"]["skipped"], r["counts"]["xfailed"]), (0, 1))

    def test_failures_are_listed_but_not_judged_without_a_base(self):
        r = self.build(PASS + FAIL + ERR)
        self.assertEqual(r["disposition"], "ALLOW")
        self.assertEqual(r["failing_on_head"], ["tests.test_c::test_bad", "tests.test_d"])

    def test_a_failure_the_base_already_had_is_receipted_and_does_not_block(self):
        r = self.build(PASS + FAIL, base_cases=PASS + FAIL)
        self.assertEqual(r["disposition"], "ALLOW")
        self.assertEqual(r["pre_existing_on_base_not_blocking"], ["tests.test_c::test_bad"])
        self.assertEqual(r["new_failures_on_head"], [])

    def test_a_failure_the_base_did_not_have_fails_closed(self):
        r = self.build(PASS + FAIL, base_cases=PASS)
        self.assertEqual([x["failure_code"] for x in r["refusals"]], ["TEST_SUITE_NEW_FAILURE_ON_HEAD"])

    def test_an_unreadable_run_is_never_allow(self):
        bad = self.write("bad.xml", "<not-xml")
        r = receipt_module.build(bad, "h", "retry", "goal", [])
        self.assertEqual(r["disposition"], "FAIL_CLOSED")
        self.assertEqual(r["refusals"][0]["failure_code"], "TEST_SUITE_NOT_OBSERVED_ON_HEAD")
        missing = receipt_module.build(self.dir / "absent.xml", "h", "retry", "goal", [])
        self.assertEqual(missing["disposition"], "FAIL_CLOSED")

    def test_an_empty_run_is_never_allow(self):
        r = self.build("")
        self.assertEqual(r["refusals"][0]["failure_code"], "TEST_SUITE_NOT_OBSERVED_ON_HEAD")

    def test_main_writes_the_receipt_and_exits_nonzero_on_a_skip(self):
        out = self.dir / "r.json"
        rc = receipt_module.main(["--junit", str(self.write("j.xml", junit(SKIP))), "--head", "h",
                                  "--out", str(out), "--retry-entrypoint", "e", "--owning-goal", "g"])
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out.read_text())["counts"]["skipped"], 1)

    def test_the_receipt_is_deterministic(self):
        self.assertEqual(self.build(PASS + SKIP + FAIL), self.build(PASS + SKIP + FAIL))

    def selection(self, selected, not_selected=()):
        return {"selected_tests": list(selected), "not_selected_for_this_change": list(not_selected),
                "selected_because": {}, "changed_paths": [], "unmapped_changed_paths": []}

    def test_only_skips_in_the_selected_tests_fail_closed(self):
        head = self.write("head.xml", junit(PASS + SKIP))
        r = receipt_module.build(head, "h", "retry", "goal", [],
                                 selection=self.selection(["tests/test_a.py"], ["tests/test_b.py"]))
        self.assertEqual(r["disposition"], "ALLOW")
        self.assertEqual(r["counts"]["skipped"], 0)
        self.assertEqual(r["not_selected_for_this_change"], ["tests/test_b.py"])
        r = receipt_module.build(head, "h", "retry", "goal", [],
                                 selection=self.selection(["tests/test_a.py", "tests/test_b.py"]))
        self.assertEqual(r["refusals"][0]["failure_code"], "TEST_SUITE_SKIPPED_ON_HEAD")
        self.assertEqual(r["refusals"][0]["failed_predicate"], "SELECTED_TESTS_ON_EXACT_HEAD_ZERO_SKIPPED")

    def test_a_change_that_selects_nothing_runs_nothing_and_reports_no_pass(self):
        r = receipt_module.build(self.dir / "absent.xml", "h", "retry", "goal", [],
                                 selection=self.selection([], ["tests/test_a.py"]))
        self.assertEqual(r["disposition"], "ALLOW")
        self.assertEqual(r["counts"], {"tests": 0, "skipped": 0})
        self.assertNotIn("passed", r["counts"])

    def test_a_selected_module_that_fails_to_import_is_counted(self):
        r = receipt_module.build(self.write("h.xml", junit(ERR)), "h", "retry", "goal", [],
                                 selection=self.selection(["tests/test_d.py"]))
        self.assertEqual(r["failing_on_head"], ["tests.test_d"])


if __name__ == "__main__":
    unittest.main()
