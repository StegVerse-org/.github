"""A federation cycle does not report consumption ALLOW over a frame it failed to consume.

The kernel records a non-DENY refusal and leaves the frame unmarked for the next
pass. The cycle's consumption disposition is then FAIL_CLOSED with the frame and
its retry entrypoint; a DENY frame is a recorded governed outcome and is counted.

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


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FC = _load("federation_cycle_under_test", "resident-runtime/federation_cycle.py")
RE = _load("resident_executor_under_test", "resident-runtime/resident_executor.py")

CONSUMED = {"path": "mesh/a.json", "result": {"status": "CONSUMED", "packet_id": "pkt-a"}}
DENIED = {"path": "mesh/b.json", "result": {"status": "REFUSED", "disposition": "DENY",
                                            "failed_predicate": "POLICY_DENIED", "packet_id": "pkt-b"}}
FAILED = {"path": "mesh/c.json", "result": {"status": "REFUSED", "disposition": "FAIL_CLOSED",
                                            "failed_predicate": "RECEIPT_CUSTODY_UNAVAILABLE", "packet_id": "pkt-c"}}


def run_cycle(results):
    with tempfile.TemporaryDirectory() as work, \
            mock.patch.object(FC.K, "consume_and_respond", return_value=results), \
            mock.patch.object(FC, "returns_for_consumed", return_value=[]), \
            mock.patch.object(FC.PR, "propagate_all", return_value={
                "repositories_declared": 0, "repositories_present": 0,
                "receipts_propagated": 0, "receipts_already_carried": 0}), \
            mock.patch.object(FC.K, "record_federation_cycle", return_value=Path(work) / "cycle.json"), \
            contextlib.redirect_stdout(io.StringIO()):
        return FC.main(mesh_root=Path(work) / "mesh", node_state_root=Path(work) / "state",
                       repo_ledger_root=Path(work) / "repo", org_ledger_root=Path(work) / "org",
                       hb_epoch=4096)


class FrameConsumptionDispositionTests(unittest.TestCase):
    def test_all_frames_consumed_or_denied_is_allow(self):
        receipt = run_cycle([CONSUMED, DENIED])
        self.assertEqual(receipt["consumption"], {"disposition": "ALLOW"})
        self.assertEqual(receipt["frames_consumed"], 1)
        self.assertEqual(receipt["frames_denied"], 1)

    def test_a_fail_closed_frame_makes_consumption_fail_closed(self):
        receipt = run_cycle([CONSUMED, DENIED, FAILED])
        consumption = receipt["consumption"]
        self.assertEqual(consumption["disposition"], "FAIL_CLOSED")
        self.assertEqual(consumption["failed_predicate"], "FEDERATION_FRAME_CONSUMPTION_NOT_COMPLETED")
        self.assertEqual(consumption["failed_frames"], [{
            "path": "mesh/c.json", "packet_id": "pkt-c", "disposition": "FAIL_CLOSED",
            "failed_predicate": "RECEIPT_CUSTODY_UNAVAILABLE"}])
        self.assertTrue(consumption["retry_entrypoint"])
        self.assertIs(consumption["consequence_committed"], False)

    def test_resident_executor_no_longer_reads_the_cycle_as_allow(self):
        receipt = run_cycle([CONSUMED, FAILED])
        failed = RE.failed_transitions(receipt)
        self.assertIn("consumption", [row.get("transition") for row in failed])


if __name__ == "__main__":
    unittest.main()
