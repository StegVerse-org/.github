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
CAPABILITY_REGISTRY = json.loads((ROOT / "org-boundary/registry/services.json").read_text())
FIXTURE = ROOT / "tests/fixtures/sdk-manifests/task-registry-disclosure-to-llm-adapter.json"
GENESIS = ROOT / "tests/fixtures/crossing-standing-genesis.json"
BUILD_SPEC = ROOT / "tests/fixtures/sdk-manifest-build-spec.json"
OWNER = "StegVerse-org/.github"

_spec = importlib.util.spec_from_file_location(
    "organization_manifest_ingress", ROOT / "resident-runtime/organization_manifest_ingress.py")
ingress = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ingress)

# The digest function the organization ledger verifies a repository receipt with.
_ospec = importlib.util.spec_from_file_location(
    "aggregate_repo_transition", ROOT / "resident-runtime/aggregate_repo_transition.py")
organization_ledger = importlib.util.module_from_spec(_ospec)
_ospec.loader.exec_module(organization_ledger)


def manifest() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def standing() -> dict:
    return json.loads(GENESIS.read_text(encoding="utf-8"))


class ReceivingOperationTests(unittest.TestCase):
    LEDGER_ROOTS = ("STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT")

    def setUp(self):
        # Both levels are redirected. A test that appended into either default
        # location would be writing runtime reality from a test run.
        self._ledger = tempfile.TemporaryDirectory()
        self._previous = {name: os.environ.get(name) for name in self.LEDGER_ROOTS}
        for name in self.LEDGER_ROOTS:
            os.environ[name] = str(Path(self._ledger.name) / name.lower())
        self.addCleanup(self._restore)

    def _restore(self):
        for name, previous in self._previous.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
        self._ledger.cleanup()

    def ledger_receipts(self, variable, schema):
        root = Path(os.environ[variable])
        return [json.loads(path.read_text(encoding="utf-8"))
                for path in root.rglob("*.json")
                if json.loads(path.read_text(encoding="utf-8")).get("schema") == schema]

    def receive(self, **overrides):
        payload = {"registry": CAPABILITY_REGISTRY, "standing": standing(), "packet_id": "org-ingress-test", "hb_epoch": 32}
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

    def test_the_organization_consumes_a_repository_receipt_it_did_not_author(self):
        """The organization ledger's job is to consume the level below, not to write it.

        Authoring the source receipt and recording it as the organization's own
        in one call left `preserves_repo_receipt` with nothing to preserve and
        organization replay resting on a receipt that same call had minted.
        """
        result = self.receive()
        self.assertIs(result["repository_receipt_observed"], True)
        self.assertEqual(result["repository"], OWNER)
        self.assertIs(result["organization_receipt_preserves_repository_receipt"], True)

        organization = self.ledger_receipts(
            "STEGVERSE_ORG_LEDGER_ROOT", "stegverse.organization-transition-receipt/v1")
        self.assertEqual(len(organization), 1)
        receipt = organization[0]
        # The three fields that were null when one writer stood in for two levels.
        self.assertEqual(receipt["source_receipt_schema"],
                         "stegverse.repo-transition-receipt/v1")
        self.assertEqual(receipt["source_repository"], OWNER)
        self.assertEqual(receipt["repo_receipt_sha256"], result["repository_receipt_sha256"])
        self.assertEqual(receipt["repo_transition_id"], result["organization_transition_id"])
        self.assertEqual(receipt["org_transition_class"], "REPO_STATE_PROPAGATION")

    def test_the_repository_receipt_is_durable_and_verifies_against_its_own_body(self):
        """Organization replay needs a verified repository receipt underneath it."""
        result = self.receive()
        repository = self.ledger_receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1")
        self.assertEqual(len(repository), 1)
        receipt = repository[0]
        self.assertEqual(receipt["receipt_sha256"], result["repository_receipt_sha256"])
        self.assertEqual(receipt["repository"], OWNER)
        self.assertEqual(receipt["transition_class"], "ORGANIZATION_SDK_MANIFEST_INGRESS")
        # Verified the way the organization ledger verifies it: the claimed
        # digest is the digest of the rest of the receipt.
        body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        self.assertEqual(receipt["receipt_sha256"], organization_ledger.sha(body))
        self.assertIs(result["replay_requires_only_verified_repo_and_organization_receipts"],
                      True)

    def test_the_repository_chain_continues_rather_than_forking(self):
        """A second ingress links to the first; the chain position is the ledger's."""
        first = self.receive()
        second = self.receive(packet_id="org-ingress-test-2")
        self.assertNotEqual(first["repository_receipt_sha256"],
                            second["repository_receipt_sha256"])
        repository = {receipt["receipt_sha256"]: receipt for receipt in self.ledger_receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1")}
        self.assertEqual(len(repository), 2)
        self.assertIsNone(repository[first["repository_receipt_sha256"]]["previous_receipt_sha256"])
        self.assertEqual(repository[second["repository_receipt_sha256"]]["previous_receipt_sha256"],
                         first["repository_receipt_sha256"])

    def test_the_transition_evidence_is_inline_rather_than_a_reference(self):
        self.receive()
        receipt, = self.ledger_receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1")
        evidence = receipt["evidence"]
        self.assertEqual(evidence["receiving_operation"], "ORGANIZATION_SDK_MANIFEST_INGRESS")
        self.assertEqual(evidence["destination_resolution_source"],
                         "CANONICAL_CONNECTOR_CAPABILITY_OVERLAY")
        self.assertEqual([closure["transition_id"] for closure in evidence["transition_closures"]],
                         ["INGRESS_ACCEPTED", "DISPATCHED", "CONSUMED",
                          "RESULT_BOUND", "EGRESS_EMITTED"])
        self.assertEqual(receipt["authority_effect"], "NONE")

    def unadmitted(self, source_output_id="refused-submission"):
        """A manifest the internal endpoint does not admit, so the crossing refuses.

        Its capability is one no organization service admits, so processing
        falls back to the declared surface, whose adapter refuses it. The
        request is the committed fixture's, so the two cannot drift apart.
        """
        spec = json.loads(BUILD_SPEC.read_text(encoding="utf-8"))
        declared = spec["manifests"]["unadmitted-capability-to-llm-adapter"]
        return build_manifest(
            data=declared["data"], source_framework="organization-boundary-test",
            source_output_id=source_output_id, process=declared["process"],
            processor_request=declared["processor_request"],
            created_at="2026-10-03T00:00:00Z")

    def refuse(self, **overrides):
        payload = {"manifest": self.unadmitted(),
                   "standing": {"mode": "ESTABLISH_GENESIS", "node_ref": "test",
                                "predecessor": None}}
        payload.update(overrides)
        return self.receive(**payload)

    def test_a_refused_submission_is_recorded_at_both_levels(self):
        """The submission arrived. Its disposition is the transition."""
        result = self.refuse()
        self.assertEqual(result["disposition"], "FAIL_CLOSED")
        self.assertIs(result["refusal_recorded"], True)
        self.assertEqual(result["refusal_transition_class"],
                         "ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED")
        self.assertEqual(result["refusal_intended_action"],
                         "RECEIVE_A_SUBMITTED_SDK_MANIFEST")
        repository, = self.ledger_receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1")
        organization, = self.ledger_receipts(
            "STEGVERSE_ORG_LEDGER_ROOT", "stegverse.organization-transition-receipt/v1")
        self.assertEqual(repository["transition_class"],
                         "ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED")
        self.assertEqual(repository["receipt_sha256"],
                         result["refusal_repository_receipt_sha256"])
        self.assertEqual(organization["receipt_sha256"],
                         result["refusal_organization_receipt_sha256"])

    def test_the_organization_consumes_the_refusal_receipt_it_did_not_author(self):
        """A refusal is not an exception to the layering the replay rule requires."""
        self.refuse()
        repository, = self.ledger_receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1")
        organization, = self.ledger_receipts(
            "STEGVERSE_ORG_LEDGER_ROOT", "stegverse.organization-transition-receipt/v1")
        self.assertEqual(organization["source_repository"], "StegVerse-org/.github")
        self.assertEqual(organization["repo_receipt_sha256"], repository["receipt_sha256"])
        self.assertEqual(organization["org_transition_class"], "REPO_STATE_PROPAGATION")

    def test_the_refusal_record_carries_the_disposition_and_nothing_it_did_not_produce(self):
        self.refuse()
        repository, = self.ledger_receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1")
        record = repository["evidence"]
        self.assertEqual(record["disposition"], "DENY")
        self.assertEqual(record["intended_action"], "RECEIVE_A_SUBMITTED_SDK_MANIFEST")
        self.assertIs(record["transition_is_the_disposition_of_the_intended_action"], True)
        self.assertIs(record["received"], False)
        self.assertTrue(record["submitted_manifest_sha256"].startswith("sha256:"))
        # Nothing an admitted crossing would have produced.
        for absent in ("resolved_service_id", "boundary_receipts", "sdk_admitted_result",
                       "egress_packet_id", "reconstruction"):
            self.assertNotIn(absent, record, absent)

    def test_a_refusal_is_never_reported_as_an_observed_organization_receipt(self):
        """It means an admitted crossing was observed, and a refusal is not that."""
        result = self.refuse()
        self.assertIs(result["organization_receipt_observed"], False)
        self.assertNotIn("organization_receipt_sha256", result)

    def test_a_manifest_the_crossing_cannot_drive_is_recorded_rather_than_raised(self):
        """No declared standing used to leave the operation by exception."""
        result = self.refuse(standing=None)
        self.assertEqual(result["failed_predicate"],
                         "CROSSING_IS_DRIVABLE_FROM_THE_MANIFEST_AS_DECLARED")
        self.assertIs(result["refusal_recorded"], True)
        self.assertIn("CROSSING_REQUIRES_DECLARED_STANDING", result["detail"])
        repository, = self.ledger_receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1")
        self.assertEqual(repository["transition_class"],
                         "ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED")

    def test_two_refused_submissions_are_two_transitions_on_the_chain(self):
        """A retry is a signal, so the chain shows both attempts."""
        self.refuse(manifest=self.unadmitted("first-attempt"))
        self.refuse(manifest=self.unadmitted("second-attempt"))
        repository = self.ledger_receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1")
        self.assertEqual(len(repository), 2)
        self.assertEqual(len({r["receipt_sha256"] for r in repository}), 2)

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
        """Refused as a disposition, and recorded as one rather than as an admission."""
        result = self.refuse(manifest=self.unadmitted("unadmitted-capability"))
        self.assertEqual(result["disposition"], "FAIL_CLOSED")
        self.assertIs(result["received"], False)
        self.assertEqual(result["failed_predicate"],
                         "ADMITTED_CROSSING_REACHES_ITS_INTERNAL_ENDPOINT")
        self.assertIs(result["organization_receipt_observed"], False)
        self.assertIs(result["refusal_recorded"], True)

    def test_standing_is_still_an_ingress_precondition_when_called_directly(self):
        """The crossing itself refuses; `receive` records that rather than raising."""
        with self.assertRaises(SystemExit) as refused:
            ingress.crossing_module.cross(
                manifest(), registry=CAPABILITY_REGISTRY, standing=None, packet_id="org-ingress-test")
        self.assertIn("CROSSING_REQUIRES_DECLARED_STANDING", str(refused.exception))


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
