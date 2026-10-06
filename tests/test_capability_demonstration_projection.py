"""A capability is mapped by having been demonstrated, not by having been listed.

The capability map was going to be enumerated -- a service per peer, written
down here -- and `peer_capability_resolution` already records why that is weak:
this organization writing down what its peers serve is a declaration none of
them made.

ST-022 settles the other half. Capability profiles use the service-registry
mechanism raised from service to participant, and "a profile enables
capability. It does not decide admissibility -- admissibility resolves at the
binding moment, per transition." So the owner surface already separates
intention from occurrence. This projection derives the second from evidence
every crossing already writes, and declares nothing.

These assert the properties that make the map evidence rather than a claim: a
demonstration must cite a verified receipt; a refusal is counted as exercise and
not as capability, so a refusing declaration is distinguishable from an untried
one; a peer address appears only once a closure showed it served something, with
no declared column invented for it; a closure whose far-side chain did not
recompute is an unserved attempt; and absence from the map is never refutation.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json"
MANIFEST = "tests/fixtures/sdk-manifests/task-registry-disclosure-to-llm-adapter.json"
STANDING = "tests/fixtures/crossing-standing-genesis.json"

PEER = "StegVerse-Labs"
PEER_CONTROL = "stegverse-labs.org-control"
PEER_CAPABILITY = "stegverse-labs.sdk-manifest-ingress"
PROFILE_ID = "sdk-manifest-ingress"
GENESIS = {"mode": "ESTABLISH_GENESIS", "node_ref": "capability-map", "predecessor": None}


def _module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capmap = _module("capability_demonstration_projection",
                 "resident-runtime/capability_demonstration_projection.py")
egress = _module("organization_egress_boundary",
                 "resident-runtime/organization_egress_boundary.py")
repository_ledger = _module("repo_transition_emit", ".stegverse/transition-ledger/emit.py")
ledger_store = _module("ledger_store", "resident-runtime/ledger_store.py")
kernel = egress.kernel


class CapabilityMapTests(unittest.TestCase):
    LEDGER_ROOTS = ("STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT")

    def setUp(self):
        self._ledger = tempfile.TemporaryDirectory()
        self._previous = {name: os.environ.get(name)
                          for name in self.LEDGER_ROOTS + ("STEGVERSE_ORG_FEDERATION_ROOT",)}
        self.addCleanup(self._restore)
        for name in self.LEDGER_ROOTS:
            os.environ[name] = str(Path(self._ledger.name) / name.lower())
        self.mesh = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.mesh, True)
        os.environ["STEGVERSE_ORG_FEDERATION_ROOT"] = str(self.mesh)

    def _restore(self):
        for name, previous in self._previous.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
        self._ledger.cleanup()

    # --- fixtures ----------------------------------------------------------

    def peer_node(self, serves_the_capability=True):
        """The peer's own node. Whether it serves the capability is the variable."""
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        services = [{"service_id": PEER_CONTROL, "repository": PEER + "/.github",
                     "boundary_role": "BOUNDARY_LOCAL_CONTROL"}]
        if serves_the_capability:
            services.append({"service_id": PEER_CAPABILITY, "repository": PEER + "/.github",
                             "boundary_role": "BOUNDARY_LOCAL_CONTROL"})
        (root / "org-boundary/registry").mkdir(parents=True)
        (root / "org-boundary/registry/services.json").write_text(json.dumps({
            "schema_version": "stegverse.org-boundary-registry.v1", "organization": PEER,
            "boundary_rule": "ALL_ORGANIZATION_INGRESS_EGRESS_GENERATED_AT_ORG_DOT_GITHUB_BOUNDARY",
            "services": services}), encoding="utf-8")
        (root / "org-boundary/runtime").mkdir(parents=True)
        for name in ("process_boundary.py", "manifest_selection.py", "node_standing.py"):
            shutil.copy2(ROOT / "org-boundary/runtime" / name,
                         root / "org-boundary/runtime" / name)
        (root / "docs").mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / CONTRACT, root / CONTRACT)
        return root

    def outbound_capability_crossing(self, communication_id="cap-1", serves=True):
        emitted = egress.emit(
            PEER, {"message_class": "ecosystem.communication",
                   "communication_id": communication_id, "body": {}},
            standing=GENESIS, capability=PROFILE_ID, mesh_root=self.mesh, hb_epoch=32)
        kernel.consume_and_respond(self.peer_node(serves), mesh_root=self.mesh)
        return egress.close(PEER, emitted["packet_id"], communication_id,
                            mesh_root=self.mesh, hb_epoch=32)

    def outbound_control_crossing(self, communication_id="ctl-1"):
        emitted = egress.emit(
            PEER, {"message_class": "ecosystem.communication",
                   "communication_id": communication_id, "body": {}},
            standing=GENESIS, mesh_root=self.mesh, hb_epoch=32)
        kernel.consume_and_respond(self.peer_node(), mesh_root=self.mesh)
        return egress.close(PEER, emitted["packet_id"], communication_id,
                            mesh_root=self.mesh, hb_epoch=32)

    def inbound_submission(self, packet_id="capmap-inbound"):
        manifest = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
        standing = {k: v for k, v in
                    json.loads((ROOT / STANDING).read_text(encoding="utf-8")).items()
                    if not k.startswith("_")}
        packet = kernel.build_packet(
            origin_org=PEER, origin_service=PEER_CAPABILITY,
            destination_org="StegVerse-org",
            destination_service="stegverse-org." + PROFILE_ID,
            payload={"schema": "stegverse.sdk-manifest-crossing-payload/v1",
                     "declared_transition_surface": "LLM_ADAPTER",
                     "manifest_sha256": kernel.sha(manifest), "manifest": manifest},
            standing=standing, transition_reference="intr:transition:" + packet_id,
            authority_effect="NONE", packet_id=packet_id)
        kernel.publish_packet(packet, root=self.mesh)
        return kernel.consume_addressed_frames(ROOT, mesh_root=self.mesh)

    def append(self, transition_class, evidence, transition_id="SYNTHETIC"):
        return repository_ledger.append(
            transition_id, transition_class, "sha256:" + "a" * 64, "sha256:" + "b" * 64,
            evidence, "NONE", hb_epoch=32)

    def own(self, projection=None):
        projection = projection or capmap.projection()
        return {row["capability_profile_id"]: row
                for row in projection["this_organization"]["capabilities"]}

    # --- the declared side -------------------------------------------------

    def test_a_declared_capability_nothing_exercised_is_named_as_such(self):
        """The defect class, made countable: a declaration nothing has enforced."""
        self.outbound_control_crossing()
        row = self.own()[PROFILE_ID]
        self.assertIs(row["declared"], True)
        self.assertIs(row["demonstrated"], False)
        self.assertIs(row["exercised"], False)
        self.assertEqual(row["state"], capmap.DECLARED_NOT_YET_DEMONSTRATED)
        self.assertEqual(row["admitted_demonstration_count"], 0)
        self.assertEqual(row["refused_demonstration_count"], 0)

    def test_the_declared_side_comes_from_the_overlay(self):
        self.assertEqual(set(capmap.declared_profiles()),
                         {entry["profile_id"] for entry in
                          json.loads((ROOT / "org-runtime/interlock-intr.json").read_text())
                          ["ingress"]["capability_endpoint_bindings"]})

    # --- the demonstrated side ---------------------------------------------

    def test_an_admitted_submission_demonstrates_the_capability(self):
        self.inbound_submission()
        row = self.own()[PROFILE_ID]
        self.assertIs(row["demonstrated"], True)
        self.assertIs(row["exercised"], True)
        self.assertEqual(row["state"], capmap.DECLARED_AND_DEMONSTRATED)
        self.assertEqual(row["admitted_demonstration_count"], 1)
        self.assertEqual(len(row["evidence_receipts"]), 1)

    def test_every_demonstration_cites_a_receipt(self):
        """Nothing is counted that cannot be pointed at."""
        self.inbound_submission()
        projection = capmap.projection()
        for row in projection["this_organization"]["capabilities"]:
            for citation in row["evidence_receipts"]:
                self.assertTrue(str(citation).startswith("sha256:"), citation)
        for entry in projection["peer_addresses"]["addresses"]:
            self.assertTrue(entry["evidence_receipts"])

    def test_a_refusal_is_exercise_and_not_capability(self):
        """A capability that only refuses is not demonstrated, and is being tested.

        Keying on the resolution source would have found admissions only, and a
        refusing declaration would have been indistinguishable from an untried
        one -- which is exactly what this map exists to tell apart.
        """
        self.append("ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED", {
            "receiving_operation": "ORGANIZATION_SDK_MANIFEST_INGRESS",
            "profile_id": PROFILE_ID, "operation": "SUBMIT_MANIFEST",
            "disposition": "DENY", "received": False,
            "submitted_processing_capability": "ecosystem_diagnostic",
            "submitted_route_id": "stegverse.route.ecosystem-diagnostic.v1"})
        row = self.own()[PROFILE_ID]
        self.assertIs(row["demonstrated"], False)
        self.assertIs(row["exercised"], True)
        self.assertEqual(row["refused_demonstration_count"], 1)
        self.assertEqual(row["admitted_demonstration_count"], 0)
        self.assertEqual(row["state"], capmap.DECLARED_NOT_YET_DEMONSTRATED)

    def test_the_refusal_record_carries_what_the_map_needs(self):
        """The upstream evidence, asserted here because the map depends on it."""
        ingress = _module("organization_manifest_ingress",
                          "resident-runtime/organization_manifest_ingress.py")
        record = ingress.refusal_record("SOME_PREDICATE", "detail", {
            "processing": {"capability": "ecosystem_diagnostic", "route_id": "r"}})
        self.assertEqual(record["profile_id"], PROFILE_ID)
        self.assertEqual(record["receiving_operation"], "ORGANIZATION_SDK_MANIFEST_INGRESS")
        self.assertEqual(record["submitted_processing_capability"], "ecosystem_diagnostic")
        # A refusal resolved no destination and must not claim to have.
        self.assertNotIn("destination_resolution_source", record)

    def test_a_submission_declaring_nothing_records_nulls_not_omission(self):
        ingress = _module("organization_manifest_ingress",
                          "resident-runtime/organization_manifest_ingress.py")
        record = ingress.refusal_record("SOME_PREDICATE", "detail", {"no": "processing"})
        self.assertIn("submitted_processing_capability", record)
        self.assertIsNone(record["submitted_processing_capability"])

    # --- the peer side -----------------------------------------------------

    def test_a_closed_capability_crossing_demonstrates_the_peer_address(self):
        """What `peer_serves_this_capability_is_proven_here: false` cannot say at
        resolution time, a closure can say afterwards."""
        closure = self.outbound_capability_crossing()
        self.assertIs(closure["closed"], True)
        entry, = capmap.projection()["peer_addresses"]["addresses"]
        self.assertEqual(entry["address"], PEER_CAPABILITY)
        self.assertEqual(entry["capability_profile_id"], PROFILE_ID)
        self.assertEqual(entry["served_demonstration_count"], 1)
        self.assertEqual(entry["unserved_attempt_count"], 0)

    def test_no_declared_column_is_invented_for_a_peer(self):
        """A peer's profile is the peer's to declare and is unreadable here."""
        self.outbound_capability_crossing()
        entry, = capmap.projection()["peer_addresses"]["addresses"]
        self.assertIs(entry["declared_profile_readable_here"], False)
        self.assertNotIn("declared", entry)

    def test_a_peer_entry_is_an_address_not_an_identified_organization(self):
        self.outbound_capability_crossing()
        projection = capmap.projection()
        self.assertIs(projection["a_peer_address_is_not_an_identified_organization"], True)
        self.assertEqual(projection["origin_attestation_state"], "NOT_PROVEN")
        rows = capmap.served_by_a_peer_address(capmap.lineage.repository_chain())
        for row in rows:
            self.assertIs(row["proves_which_organization_the_address_belongs_to"], False)

    def test_a_control_crossing_invents_no_capability_for_the_control_service(self):
        self.outbound_control_crossing()
        self.assertEqual(capmap.projection()["peer_addresses"]["addresses"], [])

    def test_a_closure_with_no_emission_is_not_a_demonstration(self):
        """Without the emission a closure cannot say which capability was served."""
        self.append("ORGANIZATION_EGRESS_CLOSED", {
            "request_packet_id": "a-packet-no-emission-names",
            "verified_the_far_side_terminal_receipt_recomputes": True})
        self.assertEqual(capmap.projection()["peer_addresses"]["addresses"], [])

    def test_a_chain_that_did_not_recompute_is_an_unserved_attempt(self):
        """Evidence the address did not mint this packet's chain is the opposite
        of a demonstration, and is carried rather than dropped."""
        chain = capmap.lineage.repository_chain
        self.outbound_capability_crossing()
        emission = next(c for c in capmap.emissions(chain()).values())
        self.append("ORGANIZATION_EGRESS_CLOSURE_REFUSED", {
            "request_packet_id": emission["packet_id"],
            "verified_the_far_side_terminal_receipt_recomputes": False,
            "closure_findings": ["FAR_SIDE_TERMINAL_RECEIPT_DOES_NOT_RECOMPUTE:x"]})
        entry, = capmap.projection()["peer_addresses"]["addresses"]
        self.assertEqual(entry["served_demonstration_count"], 1)
        self.assertEqual(entry["unserved_attempt_count"], 1)

    # --- what the map must never be read as --------------------------------

    def test_the_projection_states_that_absence_is_not_refutation(self):
        self.inbound_submission()
        projection = capmap.projection()
        self.assertIs(
            projection["absence_of_a_demonstration_is_not_evidence_of_absent_capability"], True)
        self.assertIs(projection["map_is_a_ratchet_of_positive_evidence"], True)

    def test_the_projection_grants_nothing_and_cites_st_022(self):
        self.inbound_submission()
        projection = capmap.projection()
        self.assertIs(projection["demonstration_is_evidence_not_a_grant"], True)
        self.assertIs(projection[
            "a_profile_enables_capability_it_does_not_decide_admissibility"], True)
        self.assertIs(projection[
            "admissibility_resolves_per_transition_not_from_this_projection"], True)
        self.assertIs(projection[
            "effective_capability_is_an_intersection_with_every_ancestor_ceiling"], True)
        self.assertIn("ST-022", projection["profile_declaration_authority"])
        self.assertEqual(projection["authority_effect"], "NONE_PROJECTION_ONLY")

    def test_the_projection_declares_and_stores_nothing(self):
        self.inbound_submission()
        before = len(capmap.lineage.repository_chain())
        projection = capmap.projection()
        self.assertIs(projection["nothing_is_declared_or_stored_by_this_projection"], True)
        self.assertEqual(len(capmap.lineage.repository_chain()), before)

    def test_a_chain_that_does_not_verify_refuses_the_projection(self):
        self.inbound_submission()
        root = Path(os.environ["STEGVERSE_REPO_LEDGER_ROOT"])
        store = ledger_store.PosixLedgerStore(root)
        head = store.get(ledger_store.HEAD_KEY)["receipt_sha256"]
        key = ledger_store.receipt_key(head)
        store.put(key, {**store.get(key), "transition_class": "TAMPERED"})
        with self.assertRaises(SystemExit) as refused:
            capmap.projection()
        self.assertIn("PROJECTION_STANDS_ON_A_VERIFIED_CHAIN", str(refused.exception))

    def test_the_declared_and_the_ledger_roots_are_not_the_same_root(self):
        """Reading the overlay out of a ledger directory produced an empty
        declared side and made every demonstrated capability read as undeclared."""
        self.inbound_submission()
        ledger = Path(os.environ["STEGVERSE_REPO_LEDGER_ROOT"])
        projection = capmap.projection(ledger_root=ledger, root=ROOT)
        self.assertIs(self.own(projection)[PROFILE_ID]["declared"], True)


if __name__ == "__main__":
    unittest.main()
