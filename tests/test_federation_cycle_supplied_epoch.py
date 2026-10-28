"""The federation cycle and the resident executor read no clock.

The cycle record was stamped with `kernel.hb_reference()` called with no epoch,
which derives the reference from the host clock, and the executor stamped
`datetime.now()` as `observed_at`. Both now take the epoch the materializer
supplies (`--hb-epoch`), checked by the one shared supplied-epoch rule. Without
a valid epoch the cycle refuses with six fields before anything is read or
written (B-P31, StegVerse-org/.github#207: the cycle's own epoch stamps every
receipt it writes, so no frame is consumed without one -- §Q, F7).

Source validation only. No authority effect is claimed.
"""
import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FC = _load("federation_cycle_supplied_epoch", "resident-runtime/federation_cycle.py")


def refused_cycle(**kwargs):
    """Run a cycle that must refuse; return (refusal, consume mock, record mock)."""
    with tempfile.TemporaryDirectory() as work, \
            mock.patch.object(FC.K, "consume_and_respond", return_value=[]) as consume, \
            mock.patch.object(FC.K, "record_federation_cycle", return_value=Path(work) / "cycle.json") as record, \
            contextlib.redirect_stdout(io.StringIO()):
        try:
            FC.main(mesh_root=Path(work) / "mesh", node_state_root=Path(work) / "state",
                    repo_ledger_root=Path(work) / "repo", org_ledger_root=Path(work) / "org", **kwargs)
        except FC.PR.organization_ledger.OrgLedgerEpochRefused as exc:
            return exc.refusal, consume, record
        raise AssertionError("the cycle ran without a supplied epoch")


def run_cycle(**kwargs):
    with tempfile.TemporaryDirectory() as work, \
            mock.patch.object(FC.K, "consume_and_respond", return_value=[]), \
            mock.patch.object(FC, "returns_for_consumed", return_value=[]), \
            mock.patch.object(FC.PR, "propagate_all", return_value={
                "repositories_declared": 0, "repositories_present": 0,
                "receipts_propagated": 0, "receipts_already_carried": 0}), \
            mock.patch.object(FC.K, "record_federation_cycle", return_value=Path(work) / "cycle.json"), \
            mock.patch.object(FC.K, "datetime", wraps=FC.K.datetime) as clock, \
            contextlib.redirect_stdout(io.StringIO()):
        receipt = FC.main(mesh_root=Path(work) / "mesh", node_state_root=Path(work) / "state",
                          repo_ledger_root=Path(work) / "repo", org_ledger_root=Path(work) / "org",
                          **kwargs)
        clock.now.assert_not_called()
        return receipt


class FederationCycleSuppliedEpochTests(unittest.TestCase):
    def test_a_supplied_epoch_stamps_the_record_and_reads_no_clock(self):
        receipt = run_cycle(hb_epoch="446655631")
        reference = receipt["heartbeat_reference"]
        self.assertEqual(reference["epoch"], 446655631)
        self.assertIs(reference["derived_from_clock"], False)
        self.assertNotIn("heartbeat_reference_refusal", receipt)

    def test_no_epoch_is_refused_with_six_fields_and_nothing_consumed(self):
        refusal, consume, record = refused_cycle()
        self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
        self.assertEqual(refusal["failure_code"], "HB_EPOCH_NOT_SUPPLIED")
        self.assertEqual(refusal["failed_predicate"], "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH")
        for field in SIX_FIELDS:
            with self.subTest(field=field):
                self.assertTrue(refusal[field])
        # Refused before anything is read or written: no frame, no cycle record.
        consume.assert_not_called()
        record.assert_not_called()

    def test_no_epoch_records_no_reference_and_six_fields(self):
        """Base name kept (required-verification TEST_PRESENT_AT_BASE_RUNS_AT_HEAD); it asserts the rule that
        replaced the old one, never the old rule. The old rule recorded the cycle with no reference
        and still consumed the frames. #207 refuses an epoch-less cycle with six fields before
        anything is consumed or recorded.
        """
        self.test_no_epoch_is_refused_with_six_fields_and_nothing_consumed()

    def test_coerced_or_low_epochs_are_invalid(self):
        for value in ("+33", " 33", "3_3", "31", "33.0", ""):
            with self.subTest(value=value):
                refusal, consume, record = refused_cycle(hb_epoch=value)
                self.assertEqual(refusal["failure_code"], "HB_EPOCH_INVALID")
                consume.assert_not_called()
                record.assert_not_called()

    def test_the_supplied_epoch_reaches_propagation_as_admitted(self):
        # Admitted by the shared rule as ASCII digits, the cycle's epoch reaches the
        # writer as that value; an absent or invalid one never reaches it.
        for supplied, expected in (("446655631", 446655631), ("0033", 33)):
            with self.subTest(supplied=supplied), tempfile.TemporaryDirectory() as work, \
                    mock.patch.object(FC.K, "consume_and_respond", return_value=[]), \
                    mock.patch.object(FC, "returns_for_consumed", return_value=[]), \
                    mock.patch.object(FC.PR, "propagate_all", return_value={
                        "repositories_declared": 0, "repositories_present": 0,
                        "receipts_propagated": 0, "receipts_already_carried": 0}) as propagate, \
                    mock.patch.object(FC.K, "record_federation_cycle", return_value=Path(work) / "cycle.json"), \
                    contextlib.redirect_stdout(io.StringIO()):
                FC.main(mesh_root=Path(work) / "mesh", node_state_root=Path(work) / "state",
                        repo_ledger_root=Path(work) / "repo", org_ledger_root=Path(work) / "org",
                        hb_epoch=supplied)
                propagate.assert_called_once_with(hb_epoch=expected)

    def test_the_supplied_epoch_reaches_propagation_unchanged(self):
        """Base name kept (required-verification TEST_PRESENT_AT_BASE_RUNS_AT_HEAD); it asserts the rule that
        replaced the old one, never the old rule. The old rule passed the raw text (absent or
        invalid included) through to the writer. #207 admits the epoch by the shared rule first, so
        propagation receives the admitted integer and an absent or invalid one never reaches it.
        """
        self.test_the_supplied_epoch_reaches_propagation_as_admitted()

    def test_the_cycle_and_executor_sources_hold_no_clock_read(self):
        for rel in ("resident-runtime/federation_cycle.py", "resident-runtime/resident_executor.py"):
            source = (ROOT / rel).read_text(encoding="utf-8")
            with self.subTest(rel=rel):
                self.assertNotIn("datetime.now", source)
                self.assertNotIn("observed_at", source)
                self.assertNotIn("hb_reference()", source)


if __name__ == "__main__":
    unittest.main()
