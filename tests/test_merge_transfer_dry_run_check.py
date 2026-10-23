import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "resident-runtime"))

import merge_transfer_dry_run_check as gate  # noqa: E402
from merge_transfer import NOT_LEDGERED, SIX_FIELDS  # noqa: E402

VERIFIED = {"merge_commit": "a" * 40, "disposition": "ALLOW", "transfer": "VERIFIED"}
NOT_LEDGERED_RECORD = {"merge_commit": "b" * 40, "disposition": "FAIL_CLOSED", "transfer": "UNVERIFIED",
                       "failure_code": NOT_LEDGERED, "failed_predicate": "MAIN_MERGE_HAS_AN_ORGANIZATION_LEDGER_RECEIPT",
                       "required_evidence_or_repair": "run the writer", "retry_entrypoint": "merge_transfer.py append",
                       "owning_existing_goal": "StegVerse-org/.github#162", "next_attempt": "next push to main"}


def variant(base, **changes):
    out = copy.deepcopy(base)
    for key, value in changes.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


class DryRunGateTests(unittest.TestCase):
    def test_the_two_stated_shapes_pass(self):
        self.assertEqual(gate.check([VERIFIED, NOT_LEDGERED_RECORD]), [])

    def test_allow_requires_verified(self):
        for record in (variant(VERIFIED, transfer="UNVERIFIED"), variant(VERIFIED, transfer=None),
                       variant(VERIFIED, transfer="UNVERIFIED", failure_code=NOT_LEDGERED)):
            self.assertFalse(gate.record_ok(record), record)

    def test_fail_closed_requires_not_ledgered(self):
        for code in ("MERGE_TRANSFER_RECEIPT_LINK_UNVERIFIED", "X", " " + NOT_LEDGERED, None):
            self.assertFalse(gate.record_ok(variant(NOT_LEDGERED_RECORD, failure_code=code)), code)

    def test_partial_or_malformed_six_fields_fail(self):
        for field in SIX_FIELDS:
            for bad in (None, "", " ", 1, ["x"], " padded", "padded "):
                with self.subTest(field=field, value=bad):
                    if field == "failure_code" and isinstance(bad, str) and bad.strip() == NOT_LEDGERED:
                        continue
                    self.assertFalse(gate.record_ok(variant(NOT_LEDGERED_RECORD, **{field: bad})))

    def test_deny_and_other_dispositions_fail(self):
        for disposition in ("DENY", "allow", "FAIL_CLOSED ", "", None):
            self.assertFalse(gate.record_ok(variant(VERIFIED, disposition=disposition)), disposition)
            self.assertFalse(gate.record_ok(variant(NOT_LEDGERED_RECORD, disposition=disposition)), disposition)

    def test_one_bad_record_fails_the_whole_result(self):
        failures = gate.check([VERIFIED, variant(NOT_LEDGERED_RECORD, next_attempt=" ")])
        self.assertEqual(len(failures), 1)

    def test_non_list_and_non_object_shapes_fail(self):
        for results in ({}, "x", None, 1, []):
            self.assertTrue(gate.check(results), results)
        self.assertTrue(gate.check([["x"]]))
        self.assertTrue(gate.check(["x"]))

    def test_cli_exit_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "real-state.json"
            script = ROOT / "resident-runtime" / "merge_transfer_dry_run_check.py"
            path.write_text(json.dumps([VERIFIED, NOT_LEDGERED_RECORD]), encoding="utf-8")
            self.assertEqual(subprocess.run([sys.executable, str(script), str(path)], capture_output=True).returncode, 0)
            path.write_text(json.dumps([variant(NOT_LEDGERED_RECORD, failure_code="X")]), encoding="utf-8")
            result = subprocess.run([sys.executable, str(script), str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("DRY_RUN_GATE_FAIL", result.stdout)


if __name__ == "__main__":
    unittest.main()
