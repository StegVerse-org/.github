"""An SDK manifest must actually cross the organization boundary.

Two halves were each correct and nothing joined them. The SDK declares where a
manifest is bound -- `completion.egress`, naming a transition surface reached
over `INTERLOCK_INTR` with `far_side_transition_required` -- and then stops,
because it holds no transport client and a test asserts the transport names
stay gone. This organization's boundary can complete a full InTr crossing, with
the five-receipt chain and a reconstructable terminal receipt, but nothing ever
handed it an SDK manifest. So every SDK manifest run ended at a prepared
handoff and the declared far side was never reached by anything.

`resident-runtime/sdk_manifest_crossing.py` is the join. These cases drive it
over committed SDK-produced manifests, so the crossing is exercised without the
SDK installed: the bridge consumes an artifact, never the SDK itself, and the
two repositories stay decoupled.

Both outcomes are asserted, because both are real. A surface with an installed
endpoint crosses completely. `LLM_ADAPTER` -- what the SDK's own default
manifest declares -- resolves correctly and then stops at a named, reported
disposition, because `stegverse-org.llm-adapter` carries no `endpoint_adapter`.
A bridge that reported that as success would be worse than no bridge.

Source validation only. No authority effect is claimed.
"""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "org-boundary/registry/services.json").read_text())
# A crossing is ingress, so it declares its chain position. These fixtures are
# ingress manifests and carry none of their own, so the caller declares it;
# `predecessor` is present and null, which is explicit genesis.
GENESIS = {"mode": "ESTABLISH_GENESIS", "node_ref": "StegVerse-independent-evaluator",
           "predecessor": None}

FIXTURES = ROOT / "tests/fixtures/sdk-manifests"
REGISTRY = json.loads((ROOT / "org-boundary/registry/services.json").read_text())

spec = importlib.util.spec_from_file_location(
    "sdk_manifest_crossing", ROOT / "resident-runtime/sdk_manifest_crossing.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

RECEIPT_CHAIN = ["INGRESS_ACCEPTED", "DISPATCHED", "CONSUMED", "RESULT_BOUND", "EGRESS_EMITTED"]


def manifest(name):
    return json.loads((FIXTURES / (name + ".json")).read_text())


def service(service_id):
    return next(s for s in REGISTRY["services"] if s["service_id"] == service_id)


class FixtureTests(unittest.TestCase):
    """The fixtures must stay recognizable as SDK output, or they prove nothing."""

    def test_each_fixture_declares_an_intr_bound_far_side(self):
        for path in sorted(FIXTURES.glob("*.json")):
            egress = json.loads(path.read_text())["completion"]["egress"]
            self.assertEqual(egress["transport"], "INTERLOCK_INTR", path.name)
            self.assertIs(egress["far_side_transition_required"], True, path.name)
            self.assertTrue(egress["final_stegverse_transition_surface"], path.name)

    def test_the_llm_adapter_fixture_carries_the_sdk_default_surface(self):
        """If the SDK's default stops being LLM_ADAPTER, the gap case is stale."""
        egress = manifest("governance-to-llm-adapter")["completion"]["egress"]
        self.assertEqual(egress["final_stegverse_transition_surface"], "LLM_ADAPTER")


class DeclaredDestinationTests(unittest.TestCase):
    def test_the_destination_is_read_from_the_manifest(self):
        destination = bridge.declared_destination(manifest("governance-to-boundary-diagnostic"))
        self.assertEqual(destination["surface"], "BOUNDARY_DIAGNOSTIC")
        self.assertEqual(destination["transport"], "INTERLOCK_INTR")
        self.assertIs(destination["far_side_transition_required"], True)

    def test_a_manifest_declaring_no_egress_is_not_carried(self):
        with self.assertRaises(SystemExit) as raised:
            bridge.declared_destination({"completion": {}})
        self.assertEqual(str(raised.exception), "MANIFEST_DECLARES_NO_EGRESS")

    def test_a_manifest_declaring_no_surface_is_not_carried(self):
        with self.assertRaises(SystemExit) as raised:
            bridge.declared_destination(
                {"completion": {"egress": {"transport": "INTERLOCK_INTR"}}})
        self.assertEqual(str(raised.exception), "MANIFEST_DECLARES_NO_TRANSITION_SURFACE")

    def test_an_absent_transport_is_not_assumed_to_be_intr(self):
        """Defaulting an absent transport would carry a manifest over a crossing
        its author never declared."""
        with self.assertRaises(SystemExit) as raised:
            bridge.declared_destination({"completion": {"egress": {
                "final_stegverse_transition_surface": "BOUNDARY_DIAGNOSTIC"}}})
        self.assertEqual(str(raised.exception), "MANIFEST_DECLARES_NON_INTR_TRANSPORT:None")

    def test_a_non_intr_transport_is_refused(self):
        with self.assertRaises(SystemExit) as raised:
            bridge.declared_destination({"completion": {"egress": {
                "final_stegverse_transition_surface": "BOUNDARY_DIAGNOSTIC",
                "transport": "HTTPS"}}})
        self.assertEqual(str(raised.exception), "MANIFEST_DECLARES_NON_INTR_TRANSPORT:HTTPS")

    def test_a_missing_far_side_requirement_is_refused(self):
        with self.assertRaises(SystemExit) as raised:
            bridge.declared_destination({"completion": {"egress": {
                "final_stegverse_transition_surface": "BOUNDARY_DIAGNOSTIC",
                "transport": "INTERLOCK_INTR"}}})
        self.assertEqual(str(raised.exception), "MANIFEST_DECLARES_NO_FAR_SIDE_REQUIREMENT")


class SurfaceResolutionTests(unittest.TestCase):
    def test_a_declared_surface_resolves_to_exactly_one_registered_service(self):
        self.assertEqual(
            bridge.resolve_surface("BOUNDARY_DIAGNOSTIC", REGISTRY)["service_id"],
            "stegverse-org.boundary-diagnostic")
        self.assertEqual(
            bridge.resolve_surface("LLM_ADAPTER", REGISTRY)["service_id"],
            "stegverse-org.llm-adapter")

    def test_an_unexposed_surface_fails_closed(self):
        with self.assertRaises(SystemExit) as raised:
            bridge.resolve_surface("NOT_A_SURFACE", REGISTRY)
        self.assertIn("ORG_EXPOSES_NO_SUCH_TRANSITION_SURFACE", str(raised.exception))

    def test_an_ambiguous_registry_fails_closed_rather_than_guessing(self):
        duplicated = {"organization": "StegVerse-org", "services": [
            {"service_id": "a.llm-adapter"}, {"service_id": "b.llm-adapter"}]}
        with self.assertRaises(SystemExit) as raised:
            bridge.resolve_surface("LLM_ADAPTER", duplicated)
        self.assertIn("TRANSITION_SURFACE_AMBIGUOUS_IN_REGISTRY", str(raised.exception))


class CompleteCrossingTests(unittest.TestCase):
    """The end-to-end case: a declared manifest reaches its far side."""

    @classmethod
    def setUpClass(cls):
        cls.source = manifest("governance-to-boundary-diagnostic")
        cls.result = bridge.cross(cls.source, registry=REGISTRY, standing=GENESIS, packet_id="sdk-manifest-crossing-test")

    def test_the_crossing_completes_and_is_reconstructable(self):
        self.assertIs(self.result["crossing_completed"], True)
        self.assertIs(self.result["consumed"], True)
        self.assertEqual(self.result["reconstruction"], "RECONSTRUCTED")
        self.assertTrue(self.result["terminal_receipt_id"])

    def test_the_crossing_leaves_the_full_receipt_chain(self):
        self.assertEqual(self.result["receipts"], RECEIPT_CHAIN)

    def test_the_egress_validates_as_an_org_crossing(self):
        bridge.intr_transport.validate_org_crossing(self.result["egress"], "EGRESS")

    def test_the_egress_returns_to_the_declaring_origin(self):
        egress = self.result["egress"]
        self.assertEqual(egress["destination"]["service"], "stegverse-org.stegverse-sdk")
        self.assertEqual(egress["origin"]["service"], "stegverse-org.governance")

    def test_the_egress_names_every_receipt_as_evidence(self):
        evidence = self.result["egress"]["evidence"]
        for key in ("ingress_receipt", "dispatch_receipt", "consumption_receipt",
                    "egress_receipt", "reconstruction_reference"):
            self.assertTrue(evidence[key], key)

    def test_the_manifest_that_arrived_is_the_manifest_that_was_declared(self):
        """The far side bound the governance request this manifest carries for its decider."""
        decision = (self.result["egress"]["payload"]["execution_result"]
                    ["application_result"])
        request = self.source["extensions"]["stegverse_governance_request"]
        self.assertEqual(decision["governance_request_sha256"], bridge.sha(request))
        self.assertEqual(decision["decision_state"], "REQUESTED_OF_DECIDING_ORGANIZATION")
        self.assertEqual(decision["deciding_organization"], "StegVerse-Labs")
        self.assertEqual(self.result["manifest_sha256"], "sha256:" + bridge.sha(self.source))

    def test_the_crossing_claims_no_authority_the_manifest_did_not_declare(self):
        declared = self.source.get("transition", {}).get("authority_effect", "NONE")
        self.assertEqual(self.result["authority_effect"], declared)
        self.assertEqual(self.result["authority_effect"], "NONE")

    def test_the_sdk_facing_result_says_how_processing_was_selected(self):
        """A completed crossing is not evidence that the declared capability ran.

        The manifest declares `processing.capability` bound to
        `processing.route_id`; the far side here is a diagnostic, which *is* the
        processor and echoes. An earlier version of this bridge reported that as
        a manifest reaching "its declared surface" with nothing distinguishing a
        transported declaration from a processed one -- the exact overclaim
        `SDK-GENERIC-MANIFEST-ECOSYSTEM-INVARIANT-005` exists to remove. The SDK
        reads this result, so the record has to be in it.
        """
        processing = self.source["processing"]
        self.assertEqual(self.result["declared_capability"], processing["capability"])
        self.assertEqual(self.result["declared_route_id"], processing["route_id"])
        self.assertEqual(self.result["processing_selection"], "MANIFEST_DECLARED")
        self.assertIs(self.result["declared_capability_processed"], True)

    def test_the_result_never_claims_the_boundary_resolved_the_route(self):
        """Route installation belongs to the SDK; the boundary holds no route table."""
        self.assertEqual(self.result["route_admissibility"],
                         "NOT_RESOLVED_AT_BOUNDARY_ROUTE_OWNER_IS_SDK")

    def test_the_same_manifest_crosses_reproducibly(self):
        again = bridge.cross(self.source, registry=REGISTRY, standing=GENESIS, packet_id="sdk-manifest-crossing-test")
        self.assertEqual(again["terminal_receipt_id"], self.result["terminal_receipt_id"])
        self.assertEqual(again["manifest_sha256"], self.result["manifest_sha256"])


class GovernanceReturningOverTheTransportTests(unittest.TestCase):
    """A governance manifest whose result returns over LLM-adapter is processed, not refused.

    `completion.egress` names the return path. LLM-adapter is the transport
    between an LLM and the SDK, so addressing it for processing handed a
    governance manifest to a service that admits only `ecosystem_diagnostic`, and
    every such run was refused. Processing is selected by the declared
    capability and route, so the governance processor decides it and the return
    surface stays what the manifest declared.
    """

    @classmethod
    def setUpClass(cls):
        cls.result = bridge.cross(manifest("governance-to-llm-adapter"), registry=REGISTRY, standing=GENESIS,
                                  packet_id="sdk-manifest-crossing-gap")

    def test_the_return_surface_is_kept_and_the_governance_processor_decides(self):
        self.assertEqual(self.result["declared_transition_surface"], "LLM_ADAPTER")
        self.assertEqual(self.result["resolved_service_id"], "stegverse-org.governance")
        self.assertIs(self.result["crossing_completed"], True)
        self.assertEqual(self.result["processing_selection"], "MANIFEST_DECLARED")

    def test_the_request_is_bound_for_the_organization_that_owns_stegcore(self):
        """StegCore is a StegVerse-Labs repository, so StegVerse-Labs decides; this organization does not."""
        request = self.result["application_result"]
        self.assertEqual(request["decision_authority"], "stegcore.steggate.evaluate_admissibility")
        self.assertEqual(request["decision_authority_repository"], "StegVerse-Labs/StegCore")
        self.assertEqual(request["deciding_organization"], "StegVerse-Labs")
        self.assertEqual(request["deciding_repository"], "StegVerse-Labs/.github")
        self.assertIs(request["evaluator_imported_in_this_organization"], False)
        self.assertNotIn("disposition", request)
        self.assertEqual(request["authority_effect"], "NONE_DECISION_REQUEST_ONLY")

    def test_the_registry_admits_one_pair_and_this_fixture_is_not_it(self):
        llm = service("stegverse-org.llm-adapter")
        self.assertEqual(llm["repository"], "StegVerse-org/LLM-adapter")
        self.assertEqual(llm["admits_processing"],
                         [{"capability": "ecosystem_diagnostic",
                           "route_id": "stegverse.route.ecosystem-diagnostic.v1"}])
        declared = manifest("governance-to-llm-adapter")["processing"]
        self.assertNotIn({"capability": declared["capability"],
                          "route_id": declared["route_id"]},
                         llm["admits_processing"])


if __name__ == "__main__":
    unittest.main()
