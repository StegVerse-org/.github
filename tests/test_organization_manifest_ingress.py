"""The organization drives a submitted manifest into its own receiving operation.

The capability binding resolved a destination and stopped. `ORGANIZATION_SDK_
MANIFEST_INGRESS` is the operation that destination names, and these tests
exercise it against the SDK's own request derivation and result admission
rather than against a local restatement of either: the SDK decides whether a
runtime result closes a transition, so a local copy of its rules could pass
here while real admission still failed.

The ledger root is redirected per test. The organization ledger is durable
sovereign state, and a test that appended into the operator's real ledger would
be writing runtime reality from a test run.
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

from stegverse.manifest_builder import build_manifest
from stegverse.manifest_state_transition_runtime import derive_execution_request

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/sdk-manifests/task-registry-disclosure-to-llm-adapter.json"
GENESIS = ROOT / "tests/fixtures/crossing-standing-genesis.json"
OWNER = "StegVerse-org/.github"

_spec = importlib.util.spec_from_file_location(
    "organization_manifest_ingress", ROOT / "resident-runtime/organization_manifest_ingress.py")
ingress = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ingress)


def manifest() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def standing() -> dict:
    return json.loads(GENESIS.read_text(encoding="utf-8"))


class ReceivingOperationTests(unittest.TestCase):
    def setUp(self):
        self._ledger = tempfile.TemporaryDirectory()
        self._previous = os.environ.get("STEGVERSE_ORG_LEDGER_ROOT")
        os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = self._ledger.name
        self.addCleanup(self._restore)

    def _restore(self):
        if self._previous is None:
            os.environ.pop("STEGVERSE_ORG_LEDGER_ROOT", None)
        else:
            os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = self._previous
        self._ledger.cleanup()

    def receive(self, **overrides):
        payload = {"standing": standing(), "packet_id": "org-ingress-test", "hb_epoch": 32}
        payload.update(overrides)
        value = payload.pop("manifest", manifest())
        return ingress.receive(value, **payload)

    def test_a_submitted_manifest_is_received_and_emits_an_organization_receipt(self):
        """The whole point: organization_receipt_observed stops being false."""
        result = self.receive()
        self.assertEqual(result["disposition"], "ALLOW", result.get("detail"))
        self.assertIs(result["received"], True)
        self.assertIs(result["intr_admission_observed"], True)
        self.assertIs(result["far_side_transition_observed"], True)
        self.assertIs(result["organization_receipt_observed"], True)
        self.assertTrue(result["organization_receipt_sha256"].startswith("sha256:"))

    def test_the_organization_resolves_its_own_destination_from_its_own_document(self):
        """Not handed one, not fetched: a supplied document names its own organization."""
        result = self.receive()
        self.assertEqual(result["destination_resolution_source"],
                         "CANONICAL_CONNECTOR_CAPABILITY_OVERLAY")
        self.assertEqual(result["destination_resolution_environment_inputs"], [])
        self.assertEqual(result["owner_repository"], OWNER)
        self.assertEqual(result["receiving_operation"], "ORGANIZATION_SDK_MANIFEST_INGRESS")
        self.assertEqual(result["receiving_operation_declared"]["owner_repository"], OWNER)
        self.assertIs(result["receiving_operation_declared"]["host_required"], False)

    def test_the_sdk_admits_the_result_rather_than_the_organization_grading_itself(self):
        admitted = self.receive()["sdk_admitted_result"]
        self.assertEqual(admitted["state"], "COMPLETE")
        self.assertEqual(admitted["reconstruction_status"], "PASS")
        self.assertIs(admitted["terminal_state"]["records_only"], True)
        self.assertIs(admitted["terminal_state"]["continued_authority"], False)

    def test_the_result_is_bound_to_the_receipt_that_exists(self):
        """`manifest_receipt_id` is the appended receipt, not an id minted for the occasion."""
        result = self.receive()
        self.assertEqual(result["sdk_admitted_result"]["manifest_receipt_id"],
                         result["organization_receipt_sha256"])

    def test_custody_is_published_separately_and_never_awaited(self):
        """`may_be_awaited_by_a_transition` is false, so this claims no closure."""
        result = self.receive()
        self.assertIs(result["master_records_closure_observed"], False)
        self.assertEqual(result["master_records_propagation_entrypoint"],
                         "resident-runtime/submit_org_transition_to_master_records.py")
        self.assertEqual(result["authority_effect"], "NONE_RECEIVING_OPERATION_ONLY")

    def test_the_boundary_receipt_chain_is_reconstructed_here_not_taken_on_trust(self):
        result = self.receive()
        self.assertIs(result["boundary_receipt_chain_reconstructed_independently"], True)
        closures = result["transition_closures"]
        self.assertEqual([closure["transition_id"] for closure in closures],
                         ["INGRESS_ACCEPTED", "DISPATCHED", "CONSUMED",
                          "RESULT_BOUND", "EGRESS_EMITTED"])
        previous = None
        for index, closure in enumerate(closures):
            self.assertEqual(closure["state"], "RECORDED")
            self.assertEqual(closure["reconstruction_status"], "PASS")
            self.assertEqual(closure["receipt_sha256"], closure["reconstructed_receipt_sha256"])
            self.assertEqual(len(closure["receipt_sha256"]), 64)
            if index:
                self.assertEqual(closure["predecessor_receipt_sha256"], previous)
            else:
                self.assertNotIn("predecessor_receipt_sha256", closure)
            previous = closure["receipt_sha256"]

    def test_a_tampered_receipt_chain_fails_the_reconstruction_closed(self):
        """A chain that does not recompute is refused, not recorded."""
        crossing = {
            "ingress_packet_id": "p", "resolved_service_id": "s", "payload_hash": "0" * 64,
            "terminal_receipt_id": "x",
            "boundary_receipts": [{"kind": "INGRESS_ACCEPTED", "previous_receipt_id": None,
                                   "evidence_hash": "f" * 64,
                                   "receipt_id": "ingress_accepted-" + "f" * 24}],
        }
        with self.assertRaises(ValueError) as refused:
            ingress.reconstruct_closures(crossing)
        self.assertIn("BOUNDARY_RECEIPT_RECONSTRUCTION_MISMATCH", str(refused.exception))

    def test_an_absent_chain_fails_closed(self):
        with self.assertRaises(ValueError) as refused:
            ingress.reconstruct_closures({"boundary_receipts": []})
        self.assertEqual(str(refused.exception), "BOUNDARY_RECEIPT_CHAIN_ABSENT")

    def test_a_capability_bound_elsewhere_is_not_received_here(self):
        """Reading the resolution, rather than assuming it, is what refuses this."""
        request = dict(derive_execution_request(manifest(), ingress.boundary()))
        resolution = json.loads(json.dumps(request["manifest_declared_destination"]))
        resolution["receiving_operation"]["owner_repository"] = "StegVerse-org/LLM-adapter"
        request["manifest_declared_destination"] = resolution
        with self.assertRaises(ValueError) as refused:
            ingress.bound_here(request)
        self.assertEqual(str(refused.exception),
                         "ORGANIZATION_RECEIVING_OPERATION_OWNED_ELSEWHERE")

    def test_a_different_capability_resolution_is_refused(self):
        request = dict(derive_execution_request(manifest(), ingress.boundary()))
        resolution = json.loads(json.dumps(request["manifest_declared_destination"]))
        resolution["operation"] = "EXECUTE_MANIFEST"
        request["manifest_declared_destination"] = resolution
        with self.assertRaises(ValueError) as refused:
            ingress.bound_here(request)
        self.assertEqual(str(refused.exception),
                         "ORGANIZATION_INGRESS_RESOLVED_A_DIFFERENT_CAPABILITY")

    def test_a_capability_the_internal_endpoint_does_not_admit_is_refused(self):
        """A refused crossing stays refused and mints no organization receipt."""
        governed = build_manifest(
            data={"probe": True}, source_framework="organization-boundary-test",
            source_output_id="unadmitted-capability",
            processor_request={"candidate": {"action": "inspect"}, "judgment": {}, "signal": {},
                              "execution": {}, "capability": {}, "continuity": {},
                              "approval": {}, "permission_present": False},
            created_at="2026-10-03T00:00:00Z")
        result = self.receive(manifest=governed,
                              standing={"mode": "ESTABLISH_GENESIS", "node_ref": "test",
                                        "predecessor": None})
        self.assertEqual(result["disposition"], "FAIL_CLOSED")
        self.assertIs(result["received"], False)
        self.assertEqual(result["failed_predicate"],
                         "ADMITTED_CROSSING_REACHES_ITS_INTERNAL_ENDPOINT")
        self.assertIs(result["organization_receipt_observed"], False)

    def test_a_crossing_without_declared_standing_never_reaches_the_ledger(self):
        """Standing is an ingress precondition, so it fails before anything is minted."""
        with self.assertRaises(SystemExit):
            self.receive(standing=None)


class CrossingReconstructabilityTests(unittest.TestCase):
    """The crossing returns what reconstruction needs, so `RECONSTRUCTED` is checkable."""

    def test_the_crossing_returns_the_chain_and_the_payload_digest(self):
        _spec_cross = importlib.util.spec_from_file_location(
            "sdk_manifest_crossing", ROOT / "resident-runtime/sdk_manifest_crossing.py")
        crossing_module = importlib.util.module_from_spec(_spec_cross)
        _spec_cross.loader.exec_module(crossing_module)
        crossing = crossing_module.cross(manifest(), standing=standing(),
                                         packet_id="reconstructability-test")
        self.assertIs(crossing["crossing_completed"], True)
        self.assertEqual(len(crossing["payload_hash"]), 64)
        self.assertEqual([receipt["kind"] for receipt in crossing["boundary_receipts"]],
                         crossing["receipts"])
        for receipt in crossing["boundary_receipts"]:
            for field in ("kind", "receipt_id", "evidence_hash", "previous_receipt_id"):
                self.assertIn(field, receipt)


if __name__ == "__main__":
    unittest.main()
