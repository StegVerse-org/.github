"""`close` with no response in the mesh fails closed with the six fields.

Regression for the bare `PENDING` that `organization_egress_boundary.close`
returned when no response from the destination was materialized in the mesh.
An absent response is the protocol's receiver-unavailable disposition,
`DURABLE_QUEUE_OR_EVENT_EPHEMERAL_MATERIALIZATION` (org-contract
`propagation_receiver_unavailable_disposition`), returned FAIL_CLOSED with
failure_code, failed_predicate, required_evidence_or_repair, retry_entrypoint,
owning_existing_goal and next_attempt. The path still writes nothing at either
ledger level: an absence is not an arrival.

Precedence (`CLOSE_REFUSAL_PRECEDENCE`): input refusals precede state
refusals, and within inputs the supplied epoch is first. A call missing both an
epoch and a response is HB_EPOCH_NOT_SUPPLIED; an invalid epoch with no
response is HB_EPOCH_INVALID; only a supplied epoch reaches the response check.

The module is byte-identical in StegVerse-org/.github and
StegVerse-Labs/.github. The destination is the other of those two
organizations, read from this organization's own registry. Both ledger roots
and the mesh are temporary; a passing test is not an authentic receipt.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LEDGER_ENV = ("STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT")
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
ENTRYPOINT = "resident-runtime/organization_egress_boundary.py::close"


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


egress = _load("organization_egress_boundary_response_absent",
               "resident-runtime/organization_egress_boundary.py")


def _files(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


class CloseResponseAbsentFailsClosed(unittest.TestCase):
    def setUp(self):
        self._work = tempfile.TemporaryDirectory()
        self.addCleanup(self._work.cleanup)
        work = Path(self._work.name)
        self.mesh = work / "mesh"
        self.mesh.mkdir()
        self.repo_ledger = work / "repo-ledger"
        self.org_ledger = work / "org-ledger"
        previous = {name: os.environ.get(name) for name in LEDGER_ENV}
        os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = str(self.repo_ledger)
        os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = str(self.org_ledger)

        def restore():
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        self.addCleanup(restore)
        origin = egress.this_organization()
        self.peer = "StegVerse-org" if origin == "StegVerse-Labs" else "StegVerse-Labs"

    def close(self, hb_epoch="40"):
        return egress.close(self.peer, "packet-response-absent", "comm-response-absent",
                            mesh_root=self.mesh, hb_epoch=hb_epoch)

    def assert_response_absent_refusal(self, result):
        self.assertEqual(result["disposition"], "FAIL_CLOSED")
        self.assertNotEqual(result["disposition"], "PENDING")
        for field in SIX_FIELDS:
            self.assertIsInstance(result.get(field), str, field)
            self.assertTrue(result[field].strip(), field)
        self.assertEqual(result["failure_code"],
                         "DURABLE_QUEUE_OR_EVENT_EPHEMERAL_MATERIALIZATION")
        self.assertEqual(result["failed_predicate"],
                         "EGRESS_RESPONSE_DURABLY_MATERIALIZED_BEFORE_CLOSE")
        self.assertEqual(result["retry_entrypoint"], ENTRYPOINT)
        self.assertEqual(result["owning_existing_goal"],
                         "INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001")
        self.assertEqual(result["owning_existing_goal"], egress.INTR_PROTOCOL_GOAL)
        self.assertIn("comm-response-absent", result["required_evidence_or_repair"])
        self.assertIn(ENTRYPOINT, result["next_attempt"])
        self.assertIs(result["closed"], False)
        self.assertIs(result["closure_recorded"], False)
        self.assertIs(result["refusal_recorded"], False)
        self.assertIs(result["absence_is_not_a_transition"], True)
        self.assertEqual(result["authority_effect"], "NONE_REFUSAL_ONLY")
        self.assertEqual(result["destination_organization"], self.peer)
        self.assertEqual(result["request_packet_id"], "packet-response-absent")
        self.assertEqual(result["communication_id"], "comm-response-absent")
        self.assertNotIn("closure_repository_receipt_sha256", result)
        self.assertNotIn("closure_organization_receipt_sha256", result)

    def assert_nothing_appended(self):
        self.assertEqual(_files(self.repo_ledger), [])
        self.assertEqual(_files(self.org_ledger), [])

    def test_no_response_fails_closed_with_the_six_fields(self):
        self.assert_response_absent_refusal(self.close())
        self.assert_nothing_appended()

    def test_the_refusal_is_the_same_on_every_attempt_and_records_nothing(self):
        first, second = self.close("40"), self.close("41")
        self.assertEqual(first, second)
        self.assert_response_absent_refusal(second)
        self.assert_nothing_appended()

    def assert_epoch_refusal(self, result, failure_code):
        self.assertEqual(result["disposition"], "FAIL_CLOSED")
        for field in SIX_FIELDS:
            self.assertIsInstance(result.get(field), str, field)
            self.assertTrue(result[field].strip(), field)
        self.assertEqual(result["failure_code"], failure_code)
        self.assertEqual(result["failed_predicate"], "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH")
        self.assertEqual(result["retry_entrypoint"], ENTRYPOINT)
        self.assertEqual(result["owning_existing_goal"],
                         "INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001")
        self.assertIs(result["closed"], False)
        self.assertIs(result["closure_recorded"], False)
        self.assertIs(result["refusal_recorded"], False)
        self.assertEqual(result["authority_effect"], "NONE_REFUSAL_ONLY")
        self.assertEqual(result["request_packet_id"], "packet-response-absent")
        self.assertEqual(result["communication_id"], "comm-response-absent")

    def test_no_epoch_and_no_response_is_hb_epoch_not_supplied(self):
        self.assert_epoch_refusal(self.close(None), "HB_EPOCH_NOT_SUPPLIED")
        self.assert_nothing_appended()

    def test_an_invalid_epoch_and_no_response_is_hb_epoch_invalid(self):
        for invalid in ("31", "+33", " 33", "3_3", "33.0", True, 31):
            with self.subTest(hb_epoch=invalid):
                self.assert_epoch_refusal(self.close(invalid), "HB_EPOCH_INVALID")
        self.assert_nothing_appended()

    def test_a_supplied_epoch_and_no_response_is_the_response_absence(self):
        for supplied in ("32", "0033", 40):
            with self.subTest(hb_epoch=supplied):
                self.assert_response_absent_refusal(self.close(supplied))
        self.assert_nothing_appended()

    def test_the_epoch_is_checked_before_the_destination_or_the_mesh_is_read(self):
        with mock.patch.object(egress, "resolve_destination",
                               side_effect=AssertionError("destination read")), \
                mock.patch.object(egress.kernel, "collect_ecosystem_responses",
                                  side_effect=AssertionError("mesh read")):
            self.assert_epoch_refusal(self.close(None), "HB_EPOCH_NOT_SUPPLIED")
        self.assert_nothing_appended()

    def test_the_declared_precedence_puts_inputs_before_state_and_the_epoch_first(self):
        order = egress.CLOSE_REFUSAL_PRECEDENCE
        self.assertEqual(order[0], ("SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH", "INPUT"))
        kinds = [kind for _, kind in order]
        self.assertEqual(kinds, sorted(kinds, key=lambda kind: kind != "INPUT"))
        self.assertIn(("EGRESS_RESPONSE_DURABLY_MATERIALIZED_BEFORE_CLOSE", "STATE"), order)

    def test_no_constant_names_a_bare_pending_disposition(self):
        self.assertFalse(hasattr(egress, "PENDING"))

    def test_the_cli_exits_nonzero_on_the_refusal(self):
        work = Path(self._work.name)
        payload, standing = work / "payload.json", work / "standing.json"
        payload.write_text("{}", encoding="utf-8")
        standing.write_text(json.dumps({"predecessor": None}), encoding="utf-8")
        real_close = egress.close

        def on_this_mesh(*args, **kwargs):
            return real_close(*args, mesh_root=self.mesh, **kwargs)
        argv = ["organization_egress_boundary.py", "--destination-organization", self.peer,
                "--payload", str(payload), "--standing", str(standing), "--close",
                "--packet-id", "packet-response-absent",
                "--communication-id", "comm-response-absent", "--hb-epoch", "40"]
        out = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(egress, "close", on_this_mesh), \
                contextlib.redirect_stdout(out):
            code = egress.main()
        self.assertEqual(code, 1)
        self.assert_response_absent_refusal(json.loads(out.getvalue()))
        self.assert_nothing_appended()


if __name__ == "__main__":
    unittest.main()
