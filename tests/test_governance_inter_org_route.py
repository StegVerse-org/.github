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

import importlib.util
import json
import os
import tempfile
import unittest
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

    def test_nothing_waits_and_the_sdk_is_handed_nothing_before_the_decision(self):
        emitted = self.receive()
        self.assertIs(emitted["awaits_the_decision"], False)
        self.assertNotIn("sdk_admitted_result", emitted)
        self.assertEqual(emitted["sdk_admission"], "AT_DECISION_RETURN")
        pending = self.return_decision(emitted)
        self.assertEqual(pending["disposition"], "PENDING")
        self.assertIs(pending["decision_returned"], False)
        self.assertIs(pending["absence_is_not_a_transition"], True)

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
