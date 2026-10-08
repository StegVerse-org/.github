"""A governance manifest is decided by the organization that owns StegCore, over InTr.

StegCore is a StegVerse-Labs repository. A governance manifest submitted to this
organization is therefore not decided here: the ingress records it, emits the
request out through this organization's `.github` egress onto the federation
mesh, and the decision returns from StegVerse-Labs/.github on the crossing's
closure. These tests drive that round trip against the SDK's own request
derivation and result admission.

The far side is played here by the kernel functions every organization's
boundary runs -- `receipt` to mint the chain and `build_control_response` to
answer -- because StegVerse-Labs' own adapter lives in StegVerse-Labs/.github.
What this organization verifies about the answer is the same either way: it is
recomputed against this organization's own emission record.

Both ledger roots and the mesh are redirected per test, so nothing is written
into an operator's runtime reality.
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
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "org-boundary/registry/services.json").read_text())
FIXTURE = ROOT / "tests/fixtures/sdk-manifests/governance-to-llm-adapter.json"
GENESIS = json.loads((ROOT / "tests/fixtures/crossing-standing-genesis.json").read_text())
DECIDER = "StegVerse-Labs"
DECIDING_SERVICE = "stegverse-labs.governance"


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ingress = _load("organization_manifest_ingress", "resident-runtime/organization_manifest_ingress.py")
returning = _load("governance_decision_return", "resident-runtime/governance_decision_return.py")
kernel = returning.egress.kernel


def manifest() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class GovernanceInterOrgRouteTests(unittest.TestCase):
    LEDGER_ROOTS = ("STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT")

    def setUp(self):
        self._work = tempfile.TemporaryDirectory()
        self.addCleanup(self._work.cleanup)
        self.mesh = Path(self._work.name) / "mesh"
        previous = {name: os.environ.get(name) for name in self.LEDGER_ROOTS}
        for name in self.LEDGER_ROOTS:
            os.environ[name] = str(Path(self._work.name) / name.lower())

        def restore():
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        self.addCleanup(restore)

    def receive(self, **overrides):
        options = {"registry": REGISTRY, "standing": GENESIS, "packet_id": "governance-route-test",
                   "hb_epoch": 32, "mesh_root": self.mesh}
        options.update(overrides)
        return ingress.receive(manifest(), **options)

    def frames_to(self, organization):
        return [frame for frame in (json.loads(path.read_text())
                                    for path in (self.mesh / "frames.d").glob("*.json"))
                if frame["destination_org"] == organization]

    def answer(self, emitted, decision_overrides=None, terminal=None):
        """Answer the emitted request as a deciding boundary does, onto the mesh."""
        frame = self.frames_to(DECIDER)[0]
        packet = kernel.recover_packet(frame)
        body = packet["payload"]["body"]
        chain, previous = [], None
        for kind in returning.egress.FAR_SIDE_RECEIPT_KINDS:
            receipt = kernel.receipt(kind, packet["packet_id"], packet["destination"]["service"],
                                     previous, {"payload_hash": kernel.sha(packet["payload"])})
            chain.append(receipt["receipt_id"])
            previous = receipt["receipt_id"]
        decision = {"schema": "stegverse.org-governance-decision/v1",
                    "service_id": DECIDING_SERVICE, "deciding_organization": DECIDER,
                    "decision_authority": "stegcore.steggate.evaluate_admissibility",
                    "sdk_request_sha256": body["sdk_request_sha256"],
                    "governance_request_sha256": body["governance_request_sha256"],
                    "disposition": "DENY", "reason": "signal.inputs_incomplete",
                    "organization_receipt_sha256": "sha256:" + "d" * 64,
                    "authority_effect": "NONE_DECISION_ONLY"}
        decision.update(decision_overrides or {})
        response = kernel.build_control_response(
            packet, {"application_result": decision,
                     "reconstruction": {"terminal_receipt_id": terminal or chain[-1]}})
        kernel.publish_packet(response, root=self.mesh)
        return packet

    def return_decision(self, emitted, **overrides):
        options = {"packet_id": emitted["governance_request_packet_id"],
                   "communication_id": emitted["governance_communication_id"],
                   "mesh_root": self.mesh, "hb_epoch": 33}
        options.update(overrides)
        return returning.return_decision(manifest(), **options)

    def test_the_request_leaves_through_egress_for_the_organization_that_owns_stegcore(self):
        emitted = self.receive()
        self.assertEqual(emitted["disposition"], "ALLOW", emitted.get("detail"))
        self.assertEqual(emitted["governance_decision_state"], "REQUESTED_OF_DECIDING_ORGANIZATION")
        self.assertEqual(emitted["deciding_organization"], DECIDER)
        self.assertEqual(emitted["deciding_service"], DECIDING_SERVICE)
        self.assertIs(emitted["evaluator_imported_in_this_organization"], False)
        self.assertEqual(emitted["emission_transition_class"], "ORGANIZATION_EGRESS_EMITTED")
        frames = self.frames_to(DECIDER)
        self.assertEqual(len(frames), 1)
        packet = kernel.recover_packet(frames[0])
        self.assertEqual(packet["origin"]["org"], "StegVerse-org")
        self.assertEqual(packet["destination"], {"org": DECIDER, "service": DECIDING_SERVICE})
        self.assertEqual(packet["payload"]["message_class"], "ecosystem.work.request")

    def test_a_manifest_arriving_at_the_capability_address_leaves_on_the_mesh_it_arrived_on(self):
        """Through transport, not only by calling the operation: a peer's frame at
        `stegverse-org.sdk-manifest-ingress` is consumed by the kernel with the mesh
        the node was materialized with, and that mesh reaches the receiving
        operation, so the governance request leaves instead of failing closed
        on mesh_location_required_from_materializer."""
        body = manifest()
        packet = kernel.build_packet(
            origin_org="SV-LLM", origin_service="sv-llm.org-control",
            destination_org="StegVerse-org", destination_service="stegverse-org.sdk-manifest-ingress",
            payload={"schema": "stegverse.sdk-manifest-crossing-payload/v1",
                     "declared_transition_surface": "LLM_ADAPTER",
                     "manifest": body, "manifest_sha256": kernel.sha(body)},
            standing=GENESIS, transition_reference="intr:transition:capability-address-mesh",
            authority_effect="NONE", packet_id="capability-address-mesh")
        kernel.publish_packet(packet, root=self.mesh)
        results = kernel.consume_addressed_frames(ROOT, mesh_root=self.mesh)
        self.assertEqual(len(results), 1)
        application = results[0]["result"]["execution_result"]["application_result"]
        self.assertIs(application["capability_received"], True)
        operation = application["receiving_operation_result"]
        self.assertEqual(operation["disposition"], "ALLOW", operation.get("detail"))
        self.assertEqual(operation["governance_decision_state"], "REQUESTED_OF_DECIDING_ORGANIZATION")
        self.assertEqual(len(self.frames_to(DECIDER)), 1)

    def test_nothing_waits_and_the_sdk_is_handed_nothing_before_the_decision(self):
        emitted = self.receive()
        self.assertIs(emitted["awaits_the_decision"], False)
        self.assertNotIn("sdk_admitted_result", emitted)
        self.assertEqual(emitted["sdk_admission"], "AT_DECISION_RETURN")
        pending = self.return_decision(emitted)
        self.assertEqual(pending["disposition"], "PENDING")
        self.assertIs(pending["decision_returned"], False)
        self.assertIs(pending["absence_is_not_a_transition"], True)

    def consumed_answers(self):
        """This organization's federation cycle consuming its mesh, and the returns it materializes."""
        cycle = _load("federation_cycle_under_test", "resident-runtime/federation_cycle.py")
        # Consumption markers go to the node state the materializer supplies,
        # never the checkout.
        results = cycle.K.consume_and_respond(ROOT, mesh_root=self.mesh,
                                              node_state_root=Path(self._work.name) / "node")
        return results, cycle.returns_for_consumed(results, mesh_root=self.mesh)

    def test_ingress_retains_the_canonical_manifest_and_it_reproduces_the_recorded_request(self):
        emitted = self.receive()
        evidence = returning.recorded_ingress("ORGANIZATION-SDK-MANIFEST-INGRESS-" + emitted["request_sha256"][:16])
        self.assertEqual(evidence["canonical_manifest_json"], ingress.canonical_manifest_json(manifest()))
        retained, failed, _ = returning.retained_manifest(emitted["request_sha256"])
        self.assertIsNone(failed)
        self.assertEqual(retained, manifest())

    def test_consuming_the_decision_materializes_the_return_without_a_separate_call(self):
        emitted = self.receive()
        self.answer(emitted)
        results, returns = self.consumed_answers()
        self.assertTrue(any((r.get("result") or {}).get("status") == "CONSUMED" for r in results))
        self.assertEqual(len(returns), 1)
        returned = returns[0]
        self.assertEqual(returned["trigger"], "DECISION_FRAME_CONSUMED")
        self.assertEqual(returned["disposition"], "ALLOW")
        self.assertIs(returned["decision_returned"], True)
        self.assertEqual(returned["governance_disposition"], "DENY")
        self.assertEqual(returned["governance_request_packet_id"], emitted["governance_request_packet_id"])
        self.assertEqual(returned["closure_transition_class"], "ORGANIZATION_EGRESS_CLOSED")

    def test_a_cycle_that_consumes_no_decision_materializes_no_return(self):
        self.receive()
        _, returns = self.consumed_answers()
        self.assertEqual(returns, [])

    def test_an_answer_for_a_request_this_organization_never_received_fails_closed(self):
        packet = {"packet_id": "stray", "payload": {"communication_id": "governance:" + "e" * 64,
                                                    "body": {"request_packet_id": "never-emitted"}}}
        returned = returning.return_on_consumption(packet, mesh_root=self.mesh)
        self.assertEqual(returned["disposition"], "FAIL_CLOSED")
        self.assertEqual(returned["failed_predicate"], "INGRESS_TRANSITION_IS_IN_THIS_ORGANIZATIONS_RECORDS")
        self.assertTrue(returned["retry_entrypoint"])

    def test_an_ingress_record_without_the_manifest_fails_closed_by_name(self):
        emitted = self.receive()
        recorded = returning.recorded_ingress
        def without_manifest(transition_id):
            evidence = recorded(transition_id)
            evidence.pop("canonical_manifest_json", None)
            return evidence
        with mock.patch.object(returning, "recorded_ingress", without_manifest):
            failed = returning.retained_manifest(emitted["request_sha256"])[1]
        self.assertEqual(failed, "CANONICAL_MANIFEST_RETAINED_AT_INGRESS")

    def test_a_retained_manifest_that_no_longer_reproduces_the_request_fails_closed(self):
        emitted = self.receive()
        recorded = returning.recorded_ingress
        def altered(transition_id):
            evidence = recorded(transition_id)
            changed = json.loads(evidence["canonical_manifest_json"])
            changed["declared_intent"] = "altered after ingress"
            evidence["canonical_manifest_json"] = json.dumps(changed)
            return evidence
        with mock.patch.object(returning, "recorded_ingress", altered):
            failed = returning.retained_manifest(emitted["request_sha256"])[1]
        self.assertEqual(failed, "RETAINED_MANIFEST_REPRODUCES_THE_RECORDED_REQUEST")

    def test_an_answer_that_is_not_a_governance_decision_is_not_this_operations(self):
        packet = {"packet_id": "other", "payload": {"communication_id": "ecosystem-abc", "body": {}}}
        self.assertIsNone(returning.return_on_consumption(packet, mesh_root=self.mesh))

    def test_the_returned_decision_is_admitted_by_the_sdk_in_organization_records_only(self):
        emitted = self.receive()
        self.answer(emitted)
        returned = self.return_decision(emitted)
        self.assertEqual(returned["disposition"], "ALLOW", returned.get("detail"))
        self.assertEqual(returned["governance_disposition"], "DENY")
        self.assertEqual(returned["decided_by"], DECIDER)
        self.assertEqual(returned["closure_transition_class"], "ORGANIZATION_EGRESS_CLOSED")
        admitted = returned["sdk_admitted_result"]
        self.assertEqual(admitted["disposition"], "DENY")
        self.assertEqual(admitted["failed_predicate"], "signal.inputs_incomplete")
        self.assertEqual(admitted["records_authority"], "ORGANIZATION_RECORDS_ONLY")
        self.assertIs(returned["master_records_organization_record_observed"], False)
        self.assertNotIn("master_records_closure_observed", returned)

    def test_every_transition_here_is_in_this_organizations_records(self):
        emitted = self.receive()
        self.answer(emitted)
        self.return_decision(emitted)
        root = Path(os.environ["STEGVERSE_REPO_LEDGER_ROOT"]) / "receipts"
        classes = sorted(json.loads(path.read_text())["transition_class"] for path in root.glob("*.json"))
        self.assertEqual(classes, ["ORGANIZATION_EGRESS_CLOSED", "ORGANIZATION_EGRESS_EMITTED",
                                   "ORGANIZATION_SDK_MANIFEST_INGRESS"])

    def test_an_answer_to_a_different_request_is_decided_fail_closed(self):
        emitted = self.receive()
        self.answer(emitted, {"governance_request_sha256": "0" * 64})
        returned = self.return_decision(emitted)
        self.assertEqual(returned["governance_disposition"], "FAIL_CLOSED")
        self.assertEqual(returned["sdk_admitted_result"]["failed_predicate"],
                         "GOVERNANCE_DECISION_ANSWERS_A_DIFFERENT_REQUEST")

    def test_an_answer_from_an_organization_the_overlay_does_not_bind_is_decided_fail_closed(self):
        emitted = self.receive()
        self.answer(emitted, {"deciding_organization": "StegVerse-org"})
        returned = self.return_decision(emitted)
        self.assertEqual(returned["sdk_admitted_result"]["failed_predicate"],
                         "GOVERNANCE_DECIDED_BY_AN_ORGANIZATION_THE_OVERLAY_DOES_NOT_BIND")

    def test_an_answer_whose_chain_does_not_recompute_is_refused_and_recorded(self):
        emitted = self.receive()
        self.answer(emitted, terminal="egress_emitted-" + "0" * 24)
        returned = self.return_decision(emitted)
        self.assertEqual(returned["disposition"], "FAIL_CLOSED")
        self.assertIs(returned["decision_returned"], False)
        self.assertEqual(returned["closure_transition_class"], "ORGANIZATION_EGRESS_CLOSURE_REFUSED")

    def run_cli(self, emitted):
        path = Path(self._work.name) / "manifest.json"
        path.write_text(json.dumps(manifest()), encoding="utf-8")
        argv = ["governance_decision_return.py", "--manifest", str(path),
                "--packet-id", emitted["governance_request_packet_id"],
                "--communication-id", emitted["governance_communication_id"],
                "--mesh-root", str(self.mesh), "--hb-epoch", "33"]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            return returning.main()

    def test_a_pending_observation_does_not_exit_as_a_returned_decision(self):
        emitted = self.receive()
        self.assertEqual(self.run_cli(emitted), returning.EXIT_PENDING_OBSERVATION)
        self.assertNotEqual(returning.EXIT_PENDING_OBSERVATION, returning.EXIT_RETURNED)
        self.assertNotEqual(returning.EXIT_PENDING_OBSERVATION, returning.EXIT_NOT_ALLOWED)
        self.assertIs(self.return_decision(emitted)["observation_only"], True)

    def test_a_returned_decision_exits_as_returned_whatever_the_governance_disposition(self):
        emitted = self.receive()
        self.answer(emitted)
        self.assertEqual(self.run_cli(emitted), returning.EXIT_RETURNED)

    def test_a_refused_return_exits_as_not_allowed(self):
        emitted = self.receive()
        self.answer(emitted, terminal="egress_emitted-" + "0" * 24)
        self.assertEqual(self.run_cli(emitted), returning.EXIT_NOT_ALLOWED)

    def test_a_node_materialized_without_a_mesh_records_why_the_request_did_not_leave(self):
        refused = self.receive(mesh_root=None)
        self.assertEqual(refused["disposition"], "FAIL_CLOSED")
        self.assertEqual(refused["governance_decision_state"], "REQUEST_NOT_EMITTED")
        self.assertEqual(refused["emission_transition_class"], "ORGANIZATION_EGRESS_REFUSED")
        self.assertIn("mesh_location_required_from_materializer", refused["detail"])
        self.assertIs(refused["organization_receipt_observed"], True)

    def test_governance_is_bound_to_stegverse_labs_and_nowhere_else(self):
        resolved = returning.egress.resolve_destination(DECIDER, capability="governance")
        self.assertEqual(resolved["destination_service"], DECIDING_SERVICE)
        with self.assertRaises(returning.egress.EgressRefused) as raised:
            returning.egress.resolve_destination("StegGhost", capability="governance")
        self.assertEqual(raised.exception.failed_predicate,
                         "CAPABILITY_IS_SENT_TO_THE_ORGANIZATION_THAT_OWNS_IT")

    def test_this_organization_does_not_import_stegcore(self):
        for relative in ("resident-runtime/governance_endpoint.py",
                         "resident-runtime/organization_manifest_ingress.py",
                         "resident-runtime/governance_decision_return.py"):
            source = (ROOT / relative).read_text()
            self.assertNotIn("import stegcore", source, relative)
            self.assertNotIn("from stegcore", source, relative)


if __name__ == "__main__":
    unittest.main()
