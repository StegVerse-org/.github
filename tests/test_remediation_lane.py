"""A non-ALLOW's remediation lane leaves this organization over InTr for its calculated route.

The SDK builds the fork (StegVerse-SDK `stegverse/remediation_fork.py`) with a
route calculated from where the need for remediation was recognized, the
manifested path and the direct route to StegHealer. This organization is the
route's entry: it receives the remediation manifest through its InTr ingress,
binds the next hop the route names (`resident-runtime/remediation_endpoint.py`)
and emits it through its InTr egress to StegVerse-Labs. Nothing here
classifies or decides. Ledger roots and the mesh are temporary per test.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

from stegverse.manifest_state_transition_runtime import derive_execution_request
from stegverse.remediation_fork import build_remediation_fork

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "org-boundary/registry/services.json").read_text())
FIXTURE = ROOT / "tests/fixtures/sdk-manifests/governance-to-llm-adapter.json"
GENESIS = json.loads((ROOT / "tests/fixtures/crossing-standing-genesis.json").read_text())


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ingress = _load("organization_manifest_ingress_lane", "resident-runtime/organization_manifest_ingress.py")
endpoint = _load("remediation_endpoint_under_test", "resident-runtime/remediation_endpoint.py")


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _non_allow(request, **overrides):
    deny = {"schema": "stegverse.sdk.manifest-profile-disposition/v1", "state": "DENY", "disposition": "DENY",
            "terminal": False, "evaluation_boundary": "SDK_MANIFEST_PROFILE_SOURCE_ONLY",
            "request_sha256": request["request_sha256"], "failed_predicate": "EXAMPLE_PREDICATE"}
    deny.update(overrides)
    return deny


class _LaneFixture(unittest.TestCase):
    LEDGER_ROOTS = ("STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT")

    def setUp(self):
        self._work = tempfile.TemporaryDirectory()
        self.addCleanup(self._work.cleanup)
        self.mesh = Path(self._work.name) / "mesh"
        previous = {name: os.environ.get(name) for name in self.LEDGER_ROOTS}
        for name in self.LEDGER_ROOTS:
            os.environ[name] = str(Path(self._work.name) / name.lower())
        self.addCleanup(lambda: [os.environ.pop(n, None) if v is None else os.environ.__setitem__(n, v)
                                 for n, v in previous.items()])
        self.original = derive_execution_request(json.loads(FIXTURE.read_text()), ingress.boundary())
        self.fork = build_remediation_fork(self.original, _non_allow(self.original), ingress.boundary())

    def frames_to(self, organization):
        return [frame for frame in (json.loads(p.read_text()) for p in (self.mesh / "frames.d").glob("*.json"))
                if frame["destination_org"] == organization]

    def receive(self, manifest):
        return ingress.receive(manifest, registry=REGISTRY, standing=GENESIS, packet_id="remediation-lane-test",
                               hb_epoch=41, mesh_root=self.mesh)



class RemediationLaneTests(_LaneFixture):
    def test_the_route_enters_here_and_leaves_over_intr_for_steghealers_organization(self):
        route = self.fork["remediation_route"]
        self.assertEqual(route["entry_organization"], "StegVerse-org")
        self.assertEqual([h["crossing"] for h in route["direct_route_to_steghealer"]],
                         ["INTERLOCK_INTR_INGRESS", "INTERLOCK_INTR_EGRESS", "INTERLOCK_INTR_INGRESS",
                          "INTERNAL_ENDPOINT"])
        out = self.receive(self.fork["remediation_manifest"])
        self.assertEqual(out["disposition"], "ALLOW", out)
        self.assertEqual(out["processing_capability"], "remediation")
        self.assertTrue(out["intr_admission_observed"])
        self.assertEqual(out["next_organization"], "StegVerse-Labs")
        self.assertEqual(out["next_service"], "stegverse-labs.remediation")
        self.assertEqual(out["remediation_route_sha256"], route["route_sha256"])
        self.assertFalse(out["classification_grants_authority"])
        self.assertTrue(out["emission_organization_receipt_sha256"])
        frames = self.frames_to("StegVerse-Labs")
        self.assertEqual(len(frames), 1)

    def test_one_lane_is_one_transition(self):
        first = self.receive(self.fork["remediation_manifest"])
        again = self.receive(copy.deepcopy(self.fork["remediation_manifest"]))
        self.assertEqual(first["organization_transition_id"], again["organization_transition_id"])
        self.assertTrue(again["transition_replayed"])

    def test_the_endpoint_follows_the_calculated_route_and_refuses_anything_else(self):
        manifest = copy.deepcopy(self.fork["remediation_manifest"])
        bound = endpoint.bind(manifest)
        self.assertEqual(bound["next_organization"], "StegVerse-Labs")
        self.assertFalse(bound["classifier_imported_in_this_organization"])
        elsewhere = copy.deepcopy(manifest)
        elsewhere["extensions"][endpoint.REQUEST_EXTENSION]["remediation_route"]["entry_organization"] = "Other"
        with self.assertRaises(SystemExit):
            endpoint.bind(elsewhere)
        bypass = copy.deepcopy(manifest)
        hops = bypass["extensions"][endpoint.REQUEST_EXTENSION]["remediation_route"]["direct_route_to_steghealer"]
        bypass["extensions"][endpoint.REQUEST_EXTENSION]["remediation_route"]["direct_route_to_steghealer"] = [
            h for h in hops if h["crossing"] != "INTERLOCK_INTR_INGRESS" or h["from"] == "SDK"]
        with self.assertRaises(SystemExit):
            endpoint.bind(bypass)
        other = copy.deepcopy(manifest)
        other["extensions"][endpoint.REQUEST_EXTENSION]["remediation_route"]["steghealer"]["service_id"] = "x.y"
        with self.assertRaises(SystemExit):
            endpoint.bind(other)

    def test_a_redirected_route_is_refused_at_ingress_and_nothing_is_emitted(self):
        manifest = copy.deepcopy(self.fork["remediation_manifest"])
        manifest["extensions"]["stegverse_remediation_fork_request"]["remediation_route"][
            "direct_route_to_steghealer"][-1]["to"] = "somewhere-else"
        out = self.receive(manifest)
        self.assertNotEqual(out["disposition"], "ALLOW")
        self.assertFalse((self.mesh / "frames.d").exists() and self.frames_to("StegVerse-Labs"))

    def test_the_overlay_declares_remediation_once_and_the_registry_serves_it(self):
        bindings = [b for b in ingress.boundary()["egress"]["capability_destination_bindings"]
                    if b["profile_id"] == "remediation"]
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0]["destination_service"], "stegverse-labs.remediation")
        self.assertFalse(bindings[0]["classification_grants_authority"])
        served = [s for s in REGISTRY["services"]
                  if {"capability": "remediation", "route_id": "stegverse.route.governed-remediation.v1"}
                  in (s.get("admits_processing") or [])]
        self.assertEqual([s["service_id"] for s in served], ["stegverse-org.remediation"])



class RemediationClassificationReturnTests(_LaneFixture):
    """StegHealer's answer returns, its closure is recorded, and the classification goes to governance."""

    def setUp(self):
        super().setUp()
        self.returning = _load("remediation_classification_return_under_test",
                               "resident-runtime/remediation_classification_return.py")
        self.emitted = self.receive(self.fork["remediation_manifest"])
        self.lane_request = self.fork["remediation_manifest"]["extensions"]["stegverse_remediation_fork_request"]

    def classification(self, action="RESUBMIT", **overrides):
        original = self.lane_request["original_request"]
        document = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"),
                                             ensure_ascii=False).encode()).hexdigest()
        row = {"schema": "stegverse.healer.sdk-deny-classification/v1", "state": "DETECTED",
               "source_disposition_ref": "runtime-state/sdk-manifest-state-transition/dispositions/x.json",
               "original_request_sha256": original["request_sha256"],
               "original_request_document_sha256": document,
               "original_wire_manifest_sha256": original["wire_manifest_sha256"],
               "suggested_action": action, "governance_disposition": "NOT_EVALUATED",
               "execution_authority_granted": False, "authority_effect": "NONE_CLASSIFICATION_ONLY"}
        row.update(overrides)
        return row

    def answer(self, classification, **overrides):
        kernel = self.returning.returning.egress.kernel
        frame = self.frames_to("StegVerse-Labs")[0]
        packet = kernel.recover_packet(frame)
        body = packet["payload"]["body"]
        chain, previous = [], None
        for kind in self.returning.egress.FAR_SIDE_RECEIPT_KINDS:
            receipt = kernel.receipt(kind, packet["packet_id"], packet["destination"]["service"],
                                     previous, {"payload_hash": kernel.sha(packet["payload"])})
            chain.append(receipt["receipt_id"])
            previous = receipt["receipt_id"]
        result = {"schema": "stegverse.org-remediation-classification/v1",
                  "service_id": "stegverse-labs.remediation", "classifying_organization": "StegVerse-Labs",
                  "remediation_request_sha256": body["remediation_request_sha256"],
                  "classification_grants_authority": False, "disposition": "ALLOW",
                  "state": "REMEDIATION_CLASSIFIED", "classification": classification,
                  "organization_receipt_sha256": "sha256:" + "e" * 64}
        result.update(overrides)
        response = kernel.build_control_response(
            packet, {"application_result": result, "reconstruction": {"terminal_receipt_id": chain[-1]}})
        kernel.publish_packet(response, root=self.mesh)

    def return_it(self):
        return self.returning.return_classification(
            self.fork["remediation_manifest"], packet_id=self.emitted["remediation_packet_id"],
            communication_id=self.emitted["remediation_communication_id"], registry=REGISTRY,
            mesh_root=self.mesh, hb_epoch=42)

    def test_no_answer_is_an_observation_and_records_nothing(self):
        out = self.return_it()
        self.assertEqual(out["disposition"], "PENDING")
        self.assertFalse(out["classification_returned"])

    def test_a_classification_closes_the_crossing_and_goes_to_the_existing_governance_route(self):
        self.answer(self.classification())
        out = self.return_it()
        self.assertTrue(out["classification_returned"], out)
        self.assertEqual(out["suggested_action"], "RESUBMIT")
        self.assertEqual(out["closure_transition_class"], "ORGANIZATION_EGRESS_CLOSED")
        self.assertEqual(out["preflight"]["authority_effect"], "NONE_PREFLIGHT_ONLY")
        submission = out["governance_submission"]
        self.assertEqual(submission["disposition"], "ALLOW", out)
        self.assertEqual(submission["governance_decision_state"], "REQUESTED_OF_DECIDING_ORGANIZATION")
        self.assertEqual(submission["deciding_organization"], "StegVerse-Labs")
        # The lane frame, then the governance request frame, both to StegVerse-Labs.
        self.assertEqual(len(self.frames_to("StegVerse-Labs")), 2)

    def test_an_answer_for_another_lane_or_claiming_authority_goes_nowhere(self):
        for overrides, predicate in (({"remediation_request_sha256": "0" * 64},
                                      "REMEDIATION_CLASSIFICATION_ANSWERS_A_DIFFERENT_LANE"),
                                     ({"classification_grants_authority": True},
                                      "REMEDIATION_CLASSIFICATION_AUTHORITY_ESCALATION")):
            with self.subTest(predicate=predicate):
                self.setUp()
                self.answer(self.classification(), **overrides)
                out = self.return_it()
                self.assertEqual((out["disposition"], out["failed_predicate"]), ("FAIL_CLOSED", predicate))
                self.assertEqual(len(self.frames_to("StegVerse-Labs")), 1)

    def test_an_unmapped_classification_is_refused_by_the_preflight_and_the_non_allow_stands(self):
        self.answer(self.classification(action="GOVERNANCE_REVIEW_REQUIRED"))
        out = self.return_it()
        self.assertEqual(out["disposition"], "FAIL_CLOSED")
        self.assertTrue(out["failed_predicate"].startswith("REMEDIATION_PREFLIGHT_PASSES:"))
        self.assertEqual(len(self.frames_to("StegVerse-Labs")), 1)


class Pre323RequestGovernanceTests(_LaneFixture):
    """A request derived before StegVerse-SDK#323 carries no wire_manifest_sha256 (the original
    Experiment 3 request among them). This organization's preflight and the SDK's remediation
    governance manifest must take the same wire identity for it: the canonical_manifest digest."""

    def setUp(self):
        super().setUp()
        from stegverse.route_resolution import canonical_sha256
        self.preflight = _load("governed_remediation_return_preflight_pre323",
                               "resident-runtime/governed_remediation_return_preflight.py")
        historical = copy.deepcopy(self.original)
        for key in ("wire_manifest_sha256", "canonical_manifest_projection", "request_sha256"):
            historical.pop(key, None)
        historical["request_sha256"] = canonical_sha256(historical)
        self.historical = historical
        self.deny = _non_allow(historical, evaluation_boundary="SDK_MANIFEST_PROFILE",
                               failed_predicate="canonical_manifest_sha256_binding_mismatch",
                               source_disposition_ref="runtime-state/sdk-manifest-state-transition/dispositions/x.json")
        self.classification = {
            "schema": "stegverse.healer.sdk-deny-classification/v1", "state": "DETECTED",
            "source_disposition_ref": self.deny["source_disposition_ref"],
            "original_request_sha256": historical["request_sha256"],
            "original_request_document_sha256": _sha(historical),
            "original_wire_manifest_sha256": canonical_sha256(historical["canonical_manifest"]),
            "suggested_action": "RE_MANIFEST", "governance_disposition": "NOT_EVALUATED",
            "execution_authority_granted": False, "authority_effect": "NONE_CLASSIFICATION_ONLY"}

    def test_preflight_and_sdk_governance_manifest_agree_on_the_wire_identity(self):
        from stegverse.governed_remediation import remediation_candidate, remediation_governance_manifest
        preflight = self.preflight.inspect_governed_remediation_return(
            self.classification, self.historical, "RE_MANIFEST")
        self.assertEqual(preflight["proposed_action"], "RE_MANIFEST")
        candidate = remediation_candidate(self.classification, self.historical, self.deny)
        self.assertEqual(candidate["parameters"]["original_wire_manifest_sha256"],
                         self.classification["original_wire_manifest_sha256"])
        governance = remediation_governance_manifest(
            self.classification, self.historical, self.deny, preflight=preflight,
            evidence_refs=["sha256:" + "e" * 64], organization_boundary=ingress.boundary())
        request = derive_execution_request(governance, ingress.boundary())
        self.assertEqual(request["processing_capability"], "governance")
        self.assertEqual(governance["candidate"], candidate)

    def test_a_pre323_request_with_another_wire_identity_is_refused_by_both(self):
        from stegverse.governed_remediation import remediation_candidate
        self.classification["original_wire_manifest_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "REMEDIATION_WIRE_MANIFEST_DIGEST_MISMATCH"):
            self.preflight.inspect_governed_remediation_return(self.classification, self.historical, "RE_MANIFEST")
        with self.assertRaisesRegex(ValueError, "original_wire_manifest_sha256"):
            remediation_candidate(self.classification, self.historical, self.deny)


class IngressRefusalForkTests(_LaneFixture):
    """A refusal at this ingress is a non-ALLOW recognized here, so it carries its remediation fork too."""

    UNADMITTED = ROOT / "tests/fixtures/sdk-manifests/unadmitted-capability-to-llm-adapter.json"

    def refuse(self):
        return self.receive(json.loads(self.UNADMITTED.read_text()))

    def test_the_refusal_forks_a_lane_recognized_here_that_leaves_over_intr(self):
        out = self.refuse()
        self.assertEqual(out["disposition"], "FAIL_CLOSED")
        self.assertEqual(out["failure_code"], "ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED")
        self.assertIs(out["received"], False)
        fork = out["remediation_fork"]
        route = fork["remediation_route"]
        self.assertEqual(route["recognized_at"]["node"], "ORGANIZATION")
        self.assertEqual(route["recognized_at"]["organization"], "StegVerse-org")
        self.assertEqual(route["entry_organization"], "StegVerse-org")
        self.assertEqual([h["crossing"] for h in route["direct_route_to_steghealer"]],
                         ["INTERLOCK_INTR_EGRESS", "INTERLOCK_INTR_INGRESS", "INTERNAL_ENDPOINT"])
        non_allow = fork["remediation_manifest"]["extensions"]["stegverse_remediation_fork_request"]["non_allow"]
        self.assertEqual(non_allow["failed_predicate"], out["failed_predicate"])
        self.assertEqual(non_allow["refusal_organization_receipt_sha256"],
                         out["refusal_organization_receipt_sha256"])
        lane = out["remediation_lane"]
        self.assertEqual(lane["disposition"], "ALLOW", lane)
        self.assertEqual(lane["next_service"], "stegverse-labs.remediation")
        self.assertEqual(len(self.frames_to("StegVerse-Labs")), 1)

    def test_the_refusal_itself_is_unchanged_by_its_fork(self):
        out = self.refuse()
        for field in ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
                      "owning_existing_goal", "next_attempt"):
            self.assertTrue(out[field], field)
        self.assertIs(out["organization_receipt_observed"], False)
        self.assertEqual(out["authority_effect"], "NONE_REFUSAL_ONLY")

    def test_one_refusal_is_one_lane(self):
        first, again = self.refuse(), self.refuse()
        self.assertEqual(first["remediation_fork"]["remediation_request_sha256"],
                         again["remediation_fork"]["remediation_request_sha256"])
        self.assertTrue(again["remediation_lane"]["transition_replayed"])

    def test_a_refusal_with_no_derivable_request_carries_the_six_field_fork_refusal(self):
        out = self.receive({"not": "a manifest"})
        self.assertEqual(out["failed_predicate"], "ORGANIZATION_RESOLVES_ITS_OWN_INGRESS_DESTINATION")
        refusal = out["remediation_fork"]
        self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
        for field in ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
                      "owning_existing_goal", "next_attempt"):
            self.assertTrue(refusal[field], field)
        self.assertNotIn("remediation_lane", out)

    def test_a_remediation_lanes_own_refusal_forks_nothing(self):
        manifest = copy.deepcopy(self.fork["remediation_manifest"])
        manifest["extensions"]["stegverse_remediation_fork_request"]["remediation_route"][
            "direct_route_to_steghealer"][-1]["to"] = "somewhere-else"
        out = self.receive(manifest)
        self.assertNotEqual(out["disposition"], "ALLOW")
        self.assertNotIn("remediation_fork", out)
        self.assertNotIn("remediation_lane", out)


if __name__ == "__main__":
    unittest.main()
