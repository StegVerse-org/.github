"""The push range includes an unreceipted base (resident-runtime/merge_transfer_range.py).

Lane B's case: the 41035e9e push (StegVerse-org/.github#202) had before =
f40ad7dd (#203), which an earlier push carried before the merge-transfer writer
existed, so it has no receipt; merge_transfer.pushed_commits excludes it
(before..after). Temp ledgers are the pinned real ledger tips (git archive),
never the published ref. The ledger ref and full history must be in this clone.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base_tests = load("test_merge_transfer_for_range", "tests/test_merge_transfer.py")
rng = load("merge_transfer_range_under_test", "resident-runtime/merge_transfer_range.py")
mt = rng.mt
Ledger, reseal = base_tests.Ledger, base_tests.reseal

F160 = "f160ac7d61891ee8b187368fbf05372eacc8064c"   # #200, receipted by the 41035e9e push
F40A = "f40ad7dd47160add7f1f18559b2dda6c73f57f29"   # #203, no receipt
M202 = "41035e9e4bca6d4114f2f6a181b03dda2de85481"   # #202's merge: the push whose base was f40ad7dd
SIDE = "b590fb0adf9a2212501b2807a43e4aea24631f03"   # #202's head: an ancestor of M202, not on main's first-parent line
FIX = json.loads((ROOT / "tests/fixtures/merge-transfer/f40ad7dd.json").read_text())
OLD = json.loads((ROOT / "tests/fixtures/merge-transfer/f160ac7d.json").read_text())
PENDING = ROOT / ".stegverse/merge-transfer/pending.json"


class UnreceiptedBase(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger(FIX)  # real tip 824e0b76: f160ac7d and 41035e9e ledgered, f40ad7dd not

    def tearDown(self):
        self.ledger.close()

    def test_lane_b_case_the_base_is_included(self):
        self.assertEqual(mt.pushed_commits(F40A, M202, None), [M202])  # the gap Lane B found
        self.assertEqual(rng.commits_for_push(F40A, M202, None), [F40A, M202])
        base, result = rng.unreceipted_base(F40A, M202)
        self.assertEqual(base, F40A)
        self.assertEqual((result["disposition"], result["failure_code"]), ("FAIL_CLOSED", mt.NOT_LEDGERED))

    def test_pending_first_then_base_then_range_without_duplicates(self):
        self.assertEqual(rng.commits_for_push(F40A, M202, PENDING), [F160, F40A, M202])

    def test_a_receipted_base_is_not_included(self):
        self.assertEqual(mt.verify_merge_transfer(mt.repository(), F160)["disposition"], "ALLOW")
        self.assertEqual(rng.commits_for_push(F160, F40A, None), [F40A])

    def test_a_base_off_the_first_parent_line_or_zero_is_not_included(self):
        self.assertIsNone(rng.unreceipted_base(SIDE, M202)[0])
        self.assertNotIn(SIDE, rng.commits_for_push(SIDE, M202, None))
        self.assertIsNone(rng.unreceipted_base("0" * 40, M202)[0])
        self.assertIsNone(rng.unreceipted_base("", M202)[0])
        self.assertIsNone(rng.unreceipted_base(M202, F40A)[0])  # not an ancestor

    def test_a_contradicted_base_is_deny_and_not_appended_over(self):
        appended = mt.append_merge_transfer(FIX["commit"])
        rep_key = mt.store_module().receipt_key(appended["repository_receipt_sha256"])
        rep = self.ledger.read(rep_key, repo=True)
        rep["evidence"]["ref"] = "refs/heads/other"
        self.ledger.write(rep_key, reseal(rep), repo=True)
        base, result = rng.unreceipted_base(F40A, M202)
        self.assertIsNone(base)
        self.assertEqual((result["disposition"], result["failure_code"]), ("DENY", mt.LINK_UNVERIFIED))
        self.assertEqual(rng.commits_for_push(F40A, M202, None), [M202])

    def test_the_writer_appends_the_selected_commits_and_each_verifies(self):
        before = mt.verify_merge_transfer(mt.repository(), F40A)
        self.assertEqual(before, FIX["real_state_at_ledger_tip"])
        for commit in rng.commits_for_push(F40A, M202, PENDING):
            result = mt.append_merge_transfer(mt.commit_facts(commit))
            self.assertEqual(result["disposition"], "ALLOW", result)
            self.assertEqual(result["replayed"], commit != F40A, commit)  # only f40ad7dd is new
        verified = mt.verify_merge_transfer(mt.repository(), F40A)
        self.assertEqual(verified, FIX["verified"])
        self.assertEqual((verified["transfer"], verified["pull_request"]), ("VERIFIED", 203))
        for commit in (F160, M202):
            self.assertEqual(mt.verify_merge_transfer(mt.repository(), commit)["transfer"], "VERIFIED")


class OlderTip(unittest.TestCase):
    def test_at_the_tip_before_any_merge_receipt_the_base_is_included(self):
        ledger = Ledger(OLD)  # 2acec0e1: no merge-transfer receipts
        try:
            self.assertEqual(rng.commits_for_push(F160, F40A, None), [F160, F40A])
        finally:
            ledger.close()


class WriterUsesTheRange(unittest.TestCase):
    def test_the_writer_and_the_dry_run_select_through_the_range_script(self):
        from tests.workflow_surface import catalog_groups, step_bodies, writer_job
        texts = {"writer job merge-transfer": writer_job("merge-transfer"),
                 "organization-ledger-merge-transfer-validation.yml": "\n".join(
                     step_bodies(g) for g in catalog_groups("organization-ledger-merge-transfer-validation.yml"))}
        for name, text in texts.items():
            self.assertIn("python3 resident-runtime/merge_transfer_range.py --before", text, name)
            self.assertNotIn("merge_transfer.py commits", text, name)


if __name__ == "__main__":
    unittest.main()
