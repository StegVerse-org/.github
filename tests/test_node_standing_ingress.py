"""The boundary carries and validates the canonical predecessor, from the contract.

`CANONICAL-NODE-INGRESS-CONTRACT-001` records the gap these cases close as its
own finding, and states the obligation:

    organization_boundary_must_carry_predecessor: true
    receiving_boundary_must_validate_predecessor: true
    current_organization_boundary_support: NOT_PROVEN

The kernel minted a five-receipt chain per crossing and nothing more. Those
receipts chain within one dispatch, which the contract's
`BOUNDARY_CANNOT_CARRY_CANONICAL_PREDECESSOR` finding explicitly refuses to
accept as predecessor standing: "do not equate lane-local receipt chaining with
cross-lane predecessor standing."

These cases hold the named regressions the contract requires, by name, and they
read the expectations out of the contract rather than restating them. A case
that hardcoded a rule would pass against a boundary that had drifted from the
document it claims to implement -- which is the defect class this whole effort
exists to close, one level up.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json"

SPEC = importlib.util.spec_from_file_location("org_kernel", ROOT / "org-kernel/kernel.py")
K = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(K)

STANDING_SPEC = importlib.util.spec_from_file_location(
    "node_standing", ROOT / "org-boundary/runtime/node_standing.py")
NS = importlib.util.module_from_spec(STANDING_SPEC)
STANDING_SPEC.loader.exec_module(NS)

CONTRACT_DOC = json.loads((ROOT / CONTRACT).read_text())

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64


def genesis(**overrides):
    return {"mode": "ESTABLISH_GENESIS", "node_ref": "evaluator-node", "predecessor": None, **overrides}


def binding(generation=1, epoch=32):
    return {"generation": generation, "manifest_sha256": DIGEST,
            "result_sha256": OTHER_DIGEST, "heartbeat_epoch": epoch}


def verify(**overrides):
    declared = {"mode": "VERIFY_EXISTING", "node_ref": "evaluator-node",
                "generation": 2, "predecessor": binding()}
    declared.update(overrides)
    return declared


def packet(standing, payload=None):
    return K.build_packet(origin_org="Source-Org", origin_service="source.sdk",
                          destination_org="Target-Org", destination_service="target.diag",
                          payload=payload if payload is not None else {"probe": "ping"},
                          standing=standing)


class ContractIsTheAuthorityTests(unittest.TestCase):
    """The rules are read, not restated. A second copy would be a second authority."""

    def test_the_standing_modes_come_from_the_contract(self):
        declared = CONTRACT_DOC["standing_modes"]
        expected = tuple(n for n in declared if n != "INVALID_OR_UNRESOLVED")
        self.assertEqual(NS.standing_modes(CONTRACT_DOC), expected)

    def test_the_predecessor_field_set_comes_from_the_contract(self):
        self.assertEqual(list(NS.predecessor_fields(CONTRACT_DOC)),
                         CONTRACT_DOC["lineage_contract"]["predecessor_fields"])

    def test_the_disposition_vocabulary_comes_from_the_contract(self):
        declared = CONTRACT_DOC["required_dispositions"]
        resolved = NS.dispositions(CONTRACT_DOC)
        self.assertEqual(resolved["success"], declared["success"])
        self.assertEqual(resolved["missing_or_unverifiable_required_evidence"],
                         declared["missing_or_unverifiable_required_evidence"])

    def test_a_contract_missing_its_lineage_fields_fails_closed(self):
        """A drifted contract must not silently admit whatever shape it still names."""
        broken = {**CONTRACT_DOC, "lineage_contract": {"owner": "x"}}
        with self.assertRaisesRegex(SystemExit, "missing-predecessor-fields"):
            NS.require(broken, packet(genesis()))

    def test_the_contract_still_declares_the_requirement_these_cases_satisfy(self):
        """If the obligation is ever withdrawn, this suite should say so loudly."""
        requirement = CONTRACT_DOC["boundary_lineage_requirement"]
        self.assertIs(requirement["organization_boundary_must_carry_predecessor"], True)
        self.assertIs(requirement["receiving_boundary_must_validate_predecessor"], True)


class RequiredRegressionTests(unittest.TestCase):
    """The contract's `required_regressions`, by their declared names."""

    def test_GENESIS_REQUIRES_PRESENT_NULL_PREDECESSOR(self):
        resolved = NS.require(CONTRACT_DOC, packet(genesis()))
        self.assertEqual(resolved["node_standing_disposition"], "ALLOW")
        self.assertEqual(resolved["standing_mode"], "ESTABLISH_GENESIS")
        self.assertEqual(resolved["standing_generation"], 1)
        self.assertIsNone(resolved["standing_predecessor"])

    def test_MISSING_PREDECESSOR_KEY_FAILS_CLOSED(self):
        declared = genesis()
        del declared["predecessor"]
        with self.assertRaisesRegex(SystemExit, "fail_closed:predecessor-key-absent"):
            NS.require(CONTRACT_DOC, packet(declared))

    def test_a_genesis_that_names_a_predecessor_is_denied_not_quietly_accepted(self):
        with self.assertRaisesRegex(SystemExit, "deny:explicit-genesis-declares-no-predecessor"):
            NS.require(CONTRACT_DOC, packet(genesis(predecessor=binding())))

    def test_ESTABLISHED_NODE_REQUIRES_VALIDATED_PREDECESSOR(self):
        resolved = NS.require(CONTRACT_DOC, packet(verify()))
        self.assertEqual(resolved["node_standing_disposition"], "ALLOW")
        self.assertEqual(resolved["standing_generation"], 2)
        self.assertEqual(resolved["standing_predecessor"], binding())
        self.assertIs(resolved["boundary_validated_predecessor"], True)

    def test_FAILED_EXISTING_NODE_VERIFICATION_DOES_NOT_REENROLL(self):
        """A failure stays a failure. It does not become a genesis."""
        with self.assertRaisesRegex(SystemExit, "generation-not-successor"):
            NS.require(CONTRACT_DOC, packet(verify(generation=5)))
        for broken in ({}, {"generation": 1}, {**binding(), "extra": 1}, "not-an-object"):
            with self.assertRaises(SystemExit):
                NS.require(CONTRACT_DOC, packet(verify(predecessor=broken)))

    def test_a_verified_standing_cannot_claim_the_first_generation(self):
        with self.assertRaisesRegex(SystemExit, "generation-below-2"):
            NS.require(CONTRACT_DOC, packet(verify(generation=1)))

    def test_HEARTBEAT_ONLY_ORDERING(self):
        """Order comes from the oscillator count, and the contract forbids a clock."""
        lineage = CONTRACT_DOC["lineage_contract"]
        self.assertEqual(lineage["ordering"], "OSCILLATOR_HEARTBEAT_EPOCH_ONLY")
        self.assertIs(lineage["wall_clock_ordering_permitted"], False)
        resolved = NS.require(CONTRACT_DOC, packet(verify()))
        self.assertEqual(resolved["ordering"], "OSCILLATOR_HEARTBEAT_EPOCH_ONLY")
        for epoch in (0, -1, 1.5, True, "32", None):
            with self.assertRaises(SystemExit):
                NS.require(CONTRACT_DOC, packet(verify(predecessor=binding(epoch=epoch))))

    def test_CALLER_EDITABLE_CLASSIFICATION_DOES_NOT_ESTABLISH_IDENTITY(self):
        """Naming this organization as your own origin is not a way out of standing.

        That bypass is the one the contract records as
        `LIVE_GATEWAY_ACCEPTS_CALLER_FABRICATED_IDENTITY`, so there is no
        origin-based exemption to find here.
        """
        self.assertEqual(
            CONTRACT_DOC["source_classification"]["caller_editable_ingress_source_field"],
            "FORBIDDEN_AS_AUTHORITATIVE_EVIDENCE")
        claimed = K.build_packet(origin_org="Target-Org", origin_service="target.org-control",
                                 destination_org="Target-Org", destination_service="target.diag",
                                 payload={"probe": "ping"}, standing=genesis())
        del claimed["standing"]
        with self.assertRaisesRegex(SystemExit, "no-standing-declared"):
            NS.require(CONTRACT_DOC, claimed)
        resolved = NS.require(CONTRACT_DOC, packet(genesis()))
        self.assertIs(resolved["caller_editable_origin_established_identity"], False)

    def test_an_unsupported_mode_is_denied_and_an_absent_one_fails_closed(self):
        with self.assertRaisesRegex(SystemExit, "deny:unsupported-standing-mode:SOMETHING_ELSE"):
            NS.require(CONTRACT_DOC, packet(genesis(mode="SOMETHING_ELSE")))
        declared = genesis()
        del declared["mode"]
        with self.assertRaisesRegex(SystemExit, "no-mode-declared"):
            NS.require(CONTRACT_DOC, packet(declared))


class StandingClaimsNoMoreThanItProvesTests(unittest.TestCase):
    """An ALLOW is structural. The contract keeps attestation NOT_PROVEN."""

    def test_an_allow_does_not_claim_authentication_or_an_attestation_owner(self):
        resolved = NS.require(CONTRACT_DOC, packet(genesis()))
        self.assertIs(resolved["structural_standing_only"], True)
        self.assertIs(resolved["structural_standing_is_authenticated_standing"], False)
        self.assertEqual(resolved["attestation_owner_state"], "NOT_PROVEN")
        self.assertEqual(resolved["authoritative_source_classification"], "NOT_PROVEN")
        self.assertEqual(resolved["standing_authority_effect"], "NONE_STANDING_ONLY")
        self.assertIs(resolved["silent_reenrollment_occurred"], False)

    def test_a_declared_predecessor_is_checked_for_shape_not_recomputed(self):
        """The owner's binding takes the manifest and result; a crossing carries digests."""
        resolved = NS.require(CONTRACT_DOC, packet(verify()))
        self.assertIs(resolved["declared_predecessor_lineage_recomputed"], False)
        self.assertIs(
            CONTRACT_DOC["lineage_contract"]["local_second_predecessor_semantics_permitted"], False)

    def test_readiness_publishes_the_requirement_and_grants_nothing(self):
        ready = NS.readiness(CONTRACT_DOC)
        self.assertEqual(ready["standing_modes"], list(NS.standing_modes(CONTRACT_DOC)))
        self.assertIs(ready["predecessor_key_required"], True)
        self.assertEqual(ready["refusal_disposition"], "FAIL_CLOSED")
        self.assertIn("predecessor key absent", ready["refusal_conditions"])
        self.assertIs(ready["readiness_is_not_standing"], True)
        self.assertEqual(ready["authority_effect"], "NONE_READINESS_ONLY")


class EnvelopeAndManifestMustAgreeTests(unittest.TestCase):
    """Carrying standing beside a manifest is a bypass unless the two agree."""

    def manifest_payload(self, generation, predecessor):
        return {"request": {"payload": {"manifest": {
            "schema": "stegverse.external_organization.interaction_manifest.v2",
            "generation": generation, "predecessor": predecessor}}}}

    def test_a_payload_with_no_manifest_is_not_an_error(self):
        resolved = NS.require(CONTRACT_DOC, packet(genesis()))
        self.assertIs(resolved["carried_generation_manifest"], False)
        self.assertIsNone(resolved["standing_agrees_with_carried_manifest"])

    def test_an_agreeing_manifest_is_recorded_as_agreeing(self):
        resolved = NS.require(CONTRACT_DOC,
                              packet(genesis(), self.manifest_payload(1, None)))
        self.assertIs(resolved["carried_generation_manifest"], True)
        self.assertIs(resolved["standing_agrees_with_carried_manifest"], True)

    def test_an_envelope_claiming_genesis_over_a_later_manifest_fails_closed(self):
        """Otherwise the envelope is how you skip the chain you actually declared."""
        with self.assertRaisesRegex(SystemExit, "carried-manifest-generation-disagrees"):
            NS.require(CONTRACT_DOC,
                       packet(genesis(), self.manifest_payload(5, binding(generation=4))))

    def test_a_disagreeing_predecessor_fails_closed(self):
        with self.assertRaisesRegex(SystemExit, "carried-manifest-predecessor-disagrees"):
            NS.require(CONTRACT_DOC,
                       packet(verify(), self.manifest_payload(2, binding(generation=1, epoch=99))))


class BothDispatchPathsAreGatedTests(unittest.TestCase):
    """Standing resolves above the role branch, so neither arm is the unguarded one."""

    ADAPTER = ('import argparse, json\n'
               'from pathlib import Path\n'
               'ap=argparse.ArgumentParser(); ap.add_argument("--envelope"); ap.add_argument("--out")\n'
               'a=ap.parse_args()\n'
               'packet=json.loads(Path(a.envelope).read_text())\n'
               'Path(a.out).write_text(json.dumps({"ok":True,'
               '"adapter_saw_standing":"standing" in packet}))\n')

    def root(self, row):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        (root / "org-boundary/registry").mkdir(parents=True)
        (root / "org-boundary/runtime").mkdir(parents=True)
        (root / "org-boundary/registry/services.json").write_text(
            json.dumps({"organization": "Target-Org", "services": [row]}))
        for name in ("process_boundary.py", "manifest_selection.py", "node_standing.py"):
            shutil.copy2(ROOT / "org-boundary/runtime" / name, root / "org-boundary/runtime" / name)
        (root / "docs").mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / CONTRACT, root / CONTRACT)
        return root

    def test_the_boundary_local_path_carries_the_resolved_standing(self):
        root = self.root({"service_id": "target.diag", "boundary_role": "BOUNDARY_LOCAL_DIAGNOSTIC"})
        result = K.dispatch(root, packet(genesis()))
        self.assertEqual(result["node_standing_disposition"], "ALLOW")
        self.assertIs(result["boundary_carried_predecessor"], True)

    def test_the_internal_endpoint_path_carries_it_too(self):
        root = self.root({"service_id": "target.diag", "boundary_role": "INTERNAL_ENDPOINT",
                          "endpoint_adapter": "adapter.py",
                          "admits_processing": [{"capability": "ecosystem_diagnostic",
                                                 "route_id": "stegverse.route.ecosystem-diagnostic.v1"}]})
        (root / "adapter.py").write_text(self.ADAPTER)
        result = K.dispatch(root, packet(genesis()))
        self.assertEqual(result["node_standing_disposition"], "ALLOW")
        # The adapter receives the envelope, so the standing it carries is
        # visible to the far side rather than being consumed by the kernel.
        self.assertIs(result["application_result"]["adapter_saw_standing"], True)
        self.assertIs(result["boundary_validated_predecessor"], True)

    def test_a_refused_crossing_leaves_no_receipt_chain_on_either_path(self):
        """A refusal must not leave receipts implying the crossing was consumed."""
        declared = genesis()
        del declared["predecessor"]
        for row in ({"service_id": "target.diag", "boundary_role": "BOUNDARY_LOCAL_DIAGNOSTIC"},
                    {"service_id": "target.diag", "boundary_role": "INTERNAL_ENDPOINT",
                     "endpoint_adapter": "adapter.py"}):
            root = self.root(row)
            (root / "adapter.py").write_text(self.ADAPTER)
            with self.assertRaisesRegex(ValueError, "node_standing_refused:.*predecessor-key-absent"):
                K.dispatch(root, packet(declared))


class ResponsesDoNotFabricateASuccessorTests(unittest.TestCase):
    """Deriving a successor binding locally would be a second owner of lineage."""

    def test_a_response_carries_the_request_standing_and_says_that_is_what_it_did(self):
        request = packet(verify())
        carried = K.carried_standing(request)
        self.assertEqual(carried["generation"], 2)
        self.assertEqual(carried["predecessor"], binding())
        self.assertIs(carried["standing_carried_forward_from_request"], True)

    def test_a_request_with_no_standing_cannot_produce_a_response(self):
        with self.assertRaisesRegex(ValueError, "response_requires_request_standing"):
            K.carried_standing({"packet_id": "x"})


class EverySeparatelyInvocableIngressSurfaceIsGatedTests(unittest.TestCase):
    """A gate in one entry point is not a gate on the boundary.

    `process_boundary.py` is a complete ingress surface in its own right: it
    resolves the registry, checks the destination, selects processing and mints
    receipts, and `resident-runtime/sdk_manifest_crossing.py` runs it directly
    as a subprocess without ever entering `kernel.dispatch`. So standing
    resolved only in the kernel left the SDK manifest crossing -- the external
    lane, the one an evaluator actually uses -- ungated, which is the inverse of
    what the contract requires. These cases hold both surfaces.
    """

    def test_the_crossing_lane_refuses_an_envelope_with_no_standing(self):
        """The lane that bypasses the kernel must still fail closed."""
        import subprocess, sys
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        envelope = root / "ingress.json"
        envelope.write_text(json.dumps({
            "schema_version": "x", "packet_id": "p1", "direction": "INGRESS",
            "origin": {"org": "Source-Org", "service": "source.sdk"},
            "destination": {"org": "StegVerse-org", "service": "stegverse-org.boundary-diagnostic"},
            "carrier": {"kind": "HB_DERIVED", "reference": "canonical"},
            "intr_profile": "stegverse.intr.org-boundary.v1",
            "transition": {"reference": "diagnostic", "authority_effect": "NONE"},
            "payload": {"probe": "ping"}, "evidence": {}}))
        completed = subprocess.run(
            [sys.executable, str(ROOT / "org-boundary/runtime/process_boundary.py"),
             "--envelope", str(envelope), "--registry", str(ROOT / "org-boundary/registry/services.json"), "--out", str(root / "out.json")],
            cwd=str(ROOT), capture_output=True, text=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("no-standing-declared", completed.stdout + completed.stderr)
        self.assertFalse((root / "out.json").exists(),
                         "a refused crossing must not write an execution result")

    def test_process_boundary_resolves_standing_before_it_selects_processing(self):
        """Selection is processing; a crossing without standing never reaches it."""
        source = (ROOT / "org-boundary/runtime/process_boundary.py").read_text()
        standing_at = source.index("node_standing.require(")
        selection_at = source.index("selection.select_processing(")
        self.assertLess(standing_at, selection_at)

    def test_the_crossing_refuses_to_run_without_a_declared_chain_position(self):
        """An ingress manifest declares none, so `cross` will not invent one."""
        crossing = load_module("sdk_manifest_crossing",
                               ROOT / "resident-runtime/sdk_manifest_crossing.py")
        with self.assertRaisesRegex(SystemExit, "CROSSING_REQUIRES_DECLARED_STANDING"):
            crossing.manifest_standing({"manifest_profile": "stegverse.ingress-manifest.v1"}, None)
        with self.assertRaisesRegex(SystemExit, "MUST_DECLARE_THE_PREDECESSOR_KEY"):
            crossing.manifest_standing({}, {"mode": "ESTABLISH_GENESIS", "node_ref": "n"})

    def test_a_generation_manifest_supplies_its_own_chain_position(self):
        """Derived, so the envelope and the manifest cannot disagree."""
        crossing = load_module("sdk_manifest_crossing",
                               ROOT / "resident-runtime/sdk_manifest_crossing.py")
        derived = crossing.manifest_standing({
            "generation": 1, "predecessor": None,
            "source_organization": {"organization_id": "Evaluator-Org"}})
        self.assertEqual(derived, {"mode": "ESTABLISH_GENESIS", "node_ref": "Evaluator-Org",
                                   "generation": 1, "predecessor": None})
        successor = crossing.manifest_standing({
            "generation": 2, "predecessor": binding(),
            "source_organization": {"organization_id": "Evaluator-Org"}})
        self.assertEqual(successor["mode"], "VERIFY_EXISTING")
        self.assertEqual(successor["predecessor"], binding())


class ContinuationIsPublishedTests(unittest.TestCase):
    """The contract requires discovery to publish both profiles. It now does.

    `machine_readable_instructions.requirement` is a requirement on the running
    surface, and until these cases it was held by nothing: standing resolved
    and the admitted node was told nothing about what to do next. That made the
    continuation something we had to send someone out of band, which is the
    resolution path this contract exists to replace.
    """

    def profiles(self):
        return CONTRACT_DOC["machine_readable_instructions"]

    def test_both_declared_profiles_are_published(self):
        declared = {name for name, value in self.profiles().items()
                    if isinstance(value, dict) and "consumer" in value and "steps" in value}
        self.assertEqual(set(NS.instruction_profiles(CONTRACT_DOC)), declared)
        # Two, by the contract's own declaration -- not a number kept here.
        self.assertEqual(len(declared), 2)

    def test_node_classes_come_from_the_declared_consumers(self):
        expected = {value["consumer"]: name
                    for name, value in NS.instruction_profiles(CONTRACT_DOC).items()}
        self.assertEqual(NS.node_classes(CONTRACT_DOC), expected)

    def test_allow_carries_the_profile_the_declared_class_selects(self):
        for consumer, profile in NS.node_classes(CONTRACT_DOC).items():
            with self.subTest(consumer=consumer):
                resolved = NS.require(CONTRACT_DOC, packet(genesis(node_class=consumer)))
                self.assertTrue(resolved["node_class_resolved"])
                self.assertEqual(resolved["selected_continuation_profile"], profile)
                self.assertEqual(resolved["machine_readable_instructions"][profile],
                                 self.profiles()[profile])

    def test_both_profiles_are_disclosed_whatever_the_class_selects(self):
        # The class says which one is yours. It does not narrow what is shown,
        # because the requirement is to publish both.
        resolved = NS.require(CONTRACT_DOC, packet(genesis(
            node_class="LLM_OR_MACHINE_ALREADY_CAPABLE_OF_EMITTING_A_CANONICAL_MANIFEST")))
        self.assertEqual(set(resolved["machine_readable_instructions"]),
                         set(NS.instruction_profiles(CONTRACT_DOC)))

    def test_readiness_publishes_both_before_standing_is_held(self):
        ready = NS.readiness(CONTRACT_DOC)
        self.assertEqual(set(ready["machine_readable_instructions"]),
                         set(NS.instruction_profiles(CONTRACT_DOC)))
        # Readiness is discovery, not selection: it names no class as yours.
        self.assertNotIn("selected_continuation_profile", ready)
        self.assertTrue(ready["readiness_is_not_standing"])

    def test_the_contract_requires_no_host_and_no_endpoint(self):
        # Carried from the contract rather than asserted here, because this is
        # the claim the external reviewer prompt's HTTP framing contradicts.
        section = self.profiles()
        resolved = NS.require(CONTRACT_DOC, packet(genesis()))
        self.assertIs(resolved["no_new_host_required"], section["no_new_host_required"])
        self.assertIs(resolved["no_new_endpoint_required"], section["no_new_endpoint_required"])
        self.assertTrue(resolved["no_new_host_required"])

    def test_instructions_grant_nothing(self):
        resolved = NS.require(CONTRACT_DOC, packet(genesis()))
        self.assertEqual(resolved["instructions_authority_effect"],
                         self.profiles()["authority_effect"])
        self.assertEqual(resolved["instructions_authority_effect"], "NONE_INSTRUCTIONS_ONLY")
        self.assertTrue(resolved["instructions_are_contract_data_not_authority"])
        # Publishing the steps is not performing them, and naming an owner is
        # not reaching it. Both said rather than left to be read as more.
        self.assertFalse(resolved["continuation_executed_here"])
        self.assertFalse(resolved["named_owner_surfaces_reached_here"])
        # Standing's own effect is untouched by carrying instructions.
        self.assertEqual(resolved["standing_authority_effect"], "NONE_STANDING_ONLY")

    def test_a_node_class_does_not_open_the_standing_gate(self):
        # The class is instructions-only, so it cannot substitute for any part
        # of the standing declaration the contract requires.
        declared = genesis(
            node_class="LLM_OR_MACHINE_ALREADY_CAPABLE_OF_EMITTING_A_CANONICAL_MANIFEST")
        declared.pop("predecessor")
        with self.assertRaises(SystemExit):
            NS.require(CONTRACT_DOC, packet(declared))

    def test_an_unresolved_class_is_recorded_not_refused(self):
        # Instructions carry no authority, so a class naming no declared
        # consumer is a selection that did not happen -- not a standing
        # failure. Refusing here would gate ingress on a field the contract
        # gives no authority, which is the inverse of the defect under review.
        resolved = NS.require(CONTRACT_DOC, packet(genesis(node_class="NOT_A_DECLARED_CLASS")))
        self.assertEqual(resolved["node_standing_disposition"], "ALLOW")
        self.assertTrue(resolved["node_class_declared"])
        self.assertFalse(resolved["node_class_resolved"])
        self.assertIsNone(resolved["selected_continuation_profile"])
        self.assertEqual(set(resolved["machine_readable_instructions"]),
                         set(NS.instruction_profiles(CONTRACT_DOC)))

    def test_an_absent_class_still_publishes_both(self):
        resolved = NS.require(CONTRACT_DOC, packet(genesis()))
        self.assertFalse(resolved["node_class_declared"])
        self.assertFalse(resolved["node_class_resolved"])
        self.assertEqual(set(resolved["machine_readable_instructions"]),
                         set(NS.instruction_profiles(CONTRACT_DOC)))

    def test_a_profile_added_to_the_contract_is_published_without_code_change(self):
        extended = json.loads(json.dumps(CONTRACT_DOC))
        extended["machine_readable_instructions"]["INVENTED_CONTINUATION"] = {
            "consumer": "INVENTED_CONSUMER_CLASS", "steps": ["DO_NOTHING"]}
        self.assertIn("INVENTED_CONTINUATION", NS.instruction_profiles(extended))
        resolved = NS.require(extended, packet(genesis(node_class="INVENTED_CONSUMER_CLASS")))
        self.assertEqual(resolved["selected_continuation_profile"], "INVENTED_CONTINUATION")

    def test_external_interlock_intr_is_deferred_in_both_profiles(self):
        # The question of whether external InTr must be wired before a node can
        # observe this invariant is answered by the contract, not by us: the
        # crossing is internal and post-submission in both profiles.
        for name, profile in NS.instruction_profiles(CONTRACT_DOC).items():
            with self.subTest(profile=name):
                self.assertEqual(profile["interlock_intr"], "INTERNAL_POST_SUBMISSION")
                self.assertEqual(profile["external_interlock_intr"],
                                 "DEFERRED_TO_SUCCESSOR_AFTER_TESTS_5_AND_6")


if __name__ == "__main__":
    unittest.main()
