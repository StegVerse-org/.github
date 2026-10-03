"""An outbound organization crossing is recorded, at both levels, under its disposition.

Inter-organization transport already worked. A packet addressed to another
organization publishes into the federation mesh, that organization's resident
cycle consumes frames addressed to it, and its response comes back addressed to
the origin. What it left behind was nothing: `publish_packet` appends to no
ledger and `collect_ecosystem_responses` only reads the mesh, so leaving the
organization -- the most consequential transition in the ecosystem -- emitted no
receipt at all, while `organization_scope_rule` requires one for every state
transition occurring within the organization.

These assert the properties that make the crossing a transition rather than a
side effect: the emission and the closure are each recorded with their
disposition, a refusal is recorded and never as a crossing that left, the
destination comes from this organization's own peer directory, an absence is not
recorded as anything, and the record claims nothing it did not verify.
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

_spec = importlib.util.spec_from_file_location(
    "organization_egress_boundary", ROOT / "resident-runtime/organization_egress_boundary.py")
egress = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(egress)
kernel = egress.kernel

#: A peer this organization's own federation directory declares.
PEER = "StegVerse-Labs"
PEER_CONTROL = "stegverse-labs.org-control"
GENESIS = {"mode": "ESTABLISH_GENESIS", "node_ref": "egress-test", "predecessor": None}


def payload(communication_id="egress-test-001"):
    return {"message_class": "ecosystem.communication",
            "communication_id": communication_id,
            "subject": "outbound crossing test",
            "body": {"probe": True}}


class EgressBoundaryTests(unittest.TestCase):
    LEDGER_ROOTS = ("STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT")

    def setUp(self):
        # Both levels are redirected. A test that appended into either default
        # location would be writing runtime reality from a test run.
        self._ledger = tempfile.TemporaryDirectory()
        self._previous = {name: os.environ.get(name) for name in self.LEDGER_ROOTS}
        for name in self.LEDGER_ROOTS:
            os.environ[name] = str(Path(self._ledger.name) / name.lower())
        self.addCleanup(self._restore)
        self.mesh = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.mesh, True)

    def _restore(self):
        for name, previous in self._previous.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
        self._ledger.cleanup()

    def receipts(self, variable, schema, transition_class=None):
        found = [json.loads(path.read_text(encoding="utf-8"))
                 for path in Path(os.environ[variable]).rglob("*.json")
                 if json.loads(path.read_text(encoding="utf-8")).get("schema") == schema]
        if transition_class is not None:
            found = [r for r in found if r.get("transition_class") == transition_class]
        return found

    def repo_receipts(self, transition_class=None):
        return self.receipts("STEGVERSE_REPO_LEDGER_ROOT",
                             "stegverse.repo-transition-receipt/v1", transition_class)

    def org_receipts(self):
        return self.receipts("STEGVERSE_ORG_LEDGER_ROOT",
                             "stegverse.organization-transition-receipt/v1")

    def peer_node(self):
        """Stand up the peer organization's own node: its registry and boundary runtime."""
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "org-boundary/registry").mkdir(parents=True)
        (root / "org-boundary/registry/services.json").write_text(json.dumps({
            "schema_version": "stegverse.org-boundary-registry.v1",
            "organization": PEER,
            "boundary_rule": "ALL_ORGANIZATION_INGRESS_EGRESS_GENERATED_AT_ORG_DOT_GITHUB_BOUNDARY",
            "services": [{"service_id": PEER_CONTROL, "repository": PEER + "/.github",
                          "boundary_role": "BOUNDARY_LOCAL_CONTROL"}],
        }), encoding="utf-8")
        (root / "org-boundary/runtime").mkdir(parents=True)
        for name in ("process_boundary.py", "manifest_selection.py", "node_standing.py"):
            shutil.copy2(ROOT / "org-boundary/runtime" / name,
                         root / "org-boundary/runtime" / name)
        (root / "docs").mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / CONTRACT, root / CONTRACT)
        return root

    def emit(self, destination=PEER, **overrides):
        body = {"payload": payload(), "standing": GENESIS, "mesh_root": self.mesh,
                "hb_epoch": 32}
        body.update(overrides)
        return egress.emit(destination, body.pop("payload"), **body)

    # --- the crossing as a transition -------------------------------------

    def test_an_emitted_crossing_is_recorded_at_both_levels(self):
        result = self.emit()
        self.assertEqual(result["disposition"], "ALLOW")
        self.assertIs(result["emitted"], True)
        repository, = self.repo_receipts(egress.EMITTED_CLASS)
        organization = self.org_receipts()
        self.assertEqual(len(organization), 1)
        self.assertEqual(repository["receipt_sha256"],
                         result["emission_repository_receipt_sha256"])
        self.assertEqual(organization[0]["receipt_sha256"],
                         result["emission_organization_receipt_sha256"])

    def test_the_organization_consumes_the_repository_receipt_it_did_not_author(self):
        """A crossing is not an exception to the layering the replay rule requires."""
        self.emit()
        repository, = self.repo_receipts(egress.EMITTED_CLASS)
        organization, = self.org_receipts()
        self.assertEqual(organization["source_repository"], "StegVerse-org/.github")
        self.assertEqual(organization["repo_receipt_sha256"], repository["receipt_sha256"])
        self.assertEqual(organization["org_transition_class"], "REPO_STATE_PROPAGATION")

    def test_the_record_says_a_boundary_was_crossed(self):
        """Unlike repository propagation, which records that it crossed none."""
        record = self.emit()["emission_record"]
        self.assertIs(record["crossed_an_organization_boundary"], True)
        self.assertIs(record["interlock_intr_involved"], True)
        self.assertEqual(record["intended_action"],
                         "CROSS_AN_ORGANIZATION_BOUNDARY_OUTBOUND")
        self.assertIs(record["transition_is_the_disposition_of_the_intended_action"], True)

    def test_the_destination_comes_from_this_organizations_own_peer_directory(self):
        record = self.emit()["emission_record"]
        self.assertEqual(record["destination_resolution_source"],
                         "ORGANIZATION_FEDERATION_DIRECTORY")
        self.assertIs(record["destination_resolved_from_caller_argument"], False)
        self.assertEqual(record["destination_repository"], PEER + "/.github")
        self.assertEqual(record["destination_org_control_service"], PEER_CONTROL)
        self.assertEqual(record["transport_profile"], egress.TRANSPORT_PROFILE)

    def test_the_record_carries_digests_rather_than_the_payload(self):
        record = self.emit()["emission_record"]
        self.assertTrue(record["payload_sha256"].startswith("sha256:"))
        self.assertTrue(record["frame_sha256"].startswith("sha256:"))
        self.assertNotIn("probe", json.dumps(record))

    # --- refusals ----------------------------------------------------------

    def test_an_organization_that_is_not_a_declared_peer_is_refused_and_recorded(self):
        result = self.emit(destination="Not-A-Declared-Peer")
        self.assertEqual(result["disposition"], "DENY")
        self.assertIs(result["emitted"], False)
        self.assertIs(result["refusal_recorded"], True)
        self.assertEqual(result["failed_predicate"],
                         "DESTINATION_IS_A_DECLARED_PEER_OF_THIS_ORGANIZATION")
        repository, = self.repo_receipts(egress.EMIT_REFUSED_CLASS)
        self.assertEqual(repository["receipt_sha256"],
                         result["emission_repository_receipt_sha256"])

    def test_a_refusal_is_never_recorded_as_a_crossing_that_left(self):
        result = self.emit(destination="Not-A-Declared-Peer")
        self.assertEqual(self.repo_receipts(egress.EMITTED_CLASS), [])
        record = result["emission_record"]
        self.assertIs(record["packet_emitted"], False)
        self.assertIs(record["crossed_an_organization_boundary"], False)
        self.assertEqual(record["disposition"], "DENY")
        # Nothing this boundary never resolved or emitted appears in the record.
        for absent in ("packet_id", "frame_sha256", "destination_repository",
                       "destination_org_control_service", "transport_profile"):
            self.assertNotIn(absent, record, absent)

    def test_a_refused_crossing_publishes_no_frame(self):
        self.emit(destination="Not-A-Declared-Peer")
        self.assertEqual(kernel.scan_addressed_frames("Not-A-Declared-Peer", root=self.mesh), [])

    def test_a_peer_speaking_another_transport_profile_is_refused(self):
        with self.assertRaises(egress.EgressRefused) as refused:
            egress.resolve_destination(PEER, root=self.peer_profile_mismatch_root())
        self.assertEqual(refused.exception.failed_predicate,
                         "DESTINATION_SPEAKS_THIS_BOUNDARY_TRANSPORT_PROFILE")

    def peer_profile_mismatch_root(self):
        """A copy of this organization's root whose directory declares another profile."""
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "org-boundary/registry").mkdir(parents=True)
        shutil.copy2(ROOT / "org-boundary/registry/services.json",
                     root / "org-boundary/registry/services.json")
        directory = json.loads(
            (ROOT / "org-boundary/registry/federation.json").read_text(encoding="utf-8"))
        for row in directory["organizations"]:
            if row["organization"] == PEER:
                row["transport_profile"] = "some.other.transport/v9"
        (root / "org-boundary/registry/federation.json").write_text(
            json.dumps(directory), encoding="utf-8")
        return root

    # --- closure -----------------------------------------------------------

    def test_an_absence_is_not_recorded_as_anything(self):
        """Nothing crossed, so there is no disposition -- polling is not a transition."""
        emitted = self.emit()
        before = len(self.repo_receipts())
        pending = egress.close(PEER, emitted["packet_id"], "egress-test-001",
                               mesh_root=self.mesh, hb_epoch=32)
        self.assertEqual(pending["disposition"], "PENDING")
        self.assertIs(pending["closure_recorded"], False)
        self.assertIs(pending["absence_is_not_a_transition"], True)
        self.assertEqual(len(self.repo_receipts()), before)

    def test_the_full_round_trip_closes_and_is_recorded(self):
        """Emit, the peer consumes and responds, the closure is observed and bound."""
        emitted = self.emit()
        consumed = kernel.consume_and_respond(self.peer_node(), mesh_root=self.mesh)
        self.assertEqual([(row["result"] or {}).get("status") for row in consumed],
                         ["CONSUMED"])
        closed = egress.close(PEER, emitted["packet_id"], "egress-test-001",
                              mesh_root=self.mesh, hb_epoch=32)
        self.assertEqual(closed["disposition"], "ALLOW")
        self.assertIs(closed["closed"], True)
        self.assertEqual(closed["closure_findings"], [])
        self.assertEqual(closed["responding_organization"], PEER)
        self.assertTrue(closed["far_side_terminal_receipt"])
        repository, = self.repo_receipts(egress.CLOSED_CLASS)
        self.assertEqual(repository["receipt_sha256"],
                         closed["closure_repository_receipt_sha256"])

    def test_the_emission_and_the_closure_are_two_transitions_on_one_chain(self):
        emitted = self.emit()
        kernel.consume_and_respond(self.peer_node(), mesh_root=self.mesh)
        egress.close(PEER, emitted["packet_id"], "egress-test-001",
                     mesh_root=self.mesh, hb_epoch=32)
        by = {r["receipt_sha256"]: r for r in self.repo_receipts()}
        head = json.loads((Path(os.environ["STEGVERSE_REPO_LEDGER_ROOT"]) / "HEAD.json")
                          .read_text(encoding="utf-8"))["receipt_sha256"]
        order, cursor = [], head
        while cursor in by:
            order.append(by[cursor]["transition_class"])
            cursor = by[cursor]["previous_receipt_sha256"]
        order.reverse()
        self.assertEqual(order, [egress.EMITTED_CLASS, egress.CLOSED_CLASS])

    def test_a_response_answering_another_packet_refuses_the_closure(self):
        """Recorded as a crossing whose disposition is DENY, not as a closed one."""
        self.emit()
        kernel.consume_and_respond(self.peer_node(), mesh_root=self.mesh)
        closed = egress.close(PEER, "pkt-not-the-one-emitted", "egress-test-001",
                              mesh_root=self.mesh, hb_epoch=32)
        self.assertEqual(closed["disposition"], "DENY")
        self.assertIs(closed["closed"], False)
        self.assertTrue(any(f.startswith("RESPONSE_ANSWERS_A_DIFFERENT_PACKET")
                            for f in closed["closure_findings"]), closed["closure_findings"])
        self.assertEqual(self.repo_receipts(egress.CLOSED_CLASS), [])
        self.assertEqual(len(self.repo_receipts(egress.CLOSURE_REFUSED_CLASS)), 1)

    def test_the_closure_reconstructs_the_far_side_chain_rather_than_trusting_it(self):
        """The terminal id that came back is recomputed here and compared.

        An earlier version of this record said the far side's receipt could not
        be verified here. It can: a boundary receipt id derives from the packet
        id, the service id and the payload digest, all of which this
        organization holds.
        """
        emitted = self.emit()
        kernel.consume_and_respond(self.peer_node(), mesh_root=self.mesh)
        closed = egress.close(PEER, emitted["packet_id"], "egress-test-001",
                              mesh_root=self.mesh, hb_epoch=32)
        record = closed["closure_record"]
        self.assertIs(record["far_side_receipt_reconstructed_here"], True)
        self.assertIs(record["verified_the_far_side_terminal_receipt_recomputes"], True)
        self.assertEqual(record["far_side_terminal_receipt"],
                         record["far_side_terminal_receipt_recomputed"])
        self.assertEqual(len(record["far_side_receipt_chain_recomputed"]),
                         len(egress.FAR_SIDE_RECEIPT_KINDS))
        self.assertNotIn("far_side_receipt_carried_not_verified", record)

    def test_the_recomputation_uses_only_inputs_this_organization_holds(self):
        """Not a claim about the far side's honesty -- a recomputation."""
        emitted = self.emit()
        emission = emitted["emission_record"]
        recomputed = egress.reconstruct_far_side_chain(
            emitted["packet_id"], emission["far_side_service_id"],
            emission["far_side_payload_hash"])
        kernel.consume_and_respond(self.peer_node(), mesh_root=self.mesh)
        closed = egress.close(PEER, emitted["packet_id"], "egress-test-001",
                              mesh_root=self.mesh, hb_epoch=32)
        self.assertEqual(closed["far_side_terminal_receipt"], recomputed[-1])

    def test_a_terminal_receipt_that_does_not_recompute_refuses_the_closure(self):
        """A response that does not recompute did not run this packet."""
        emitted = self.emit()
        kernel.consume_and_respond(self.peer_node(), mesh_root=self.mesh)
        real = egress.reconstruct_far_side_chain
        egress.reconstruct_far_side_chain = lambda *a, **k: ["forged-terminal-receipt"]
        self.addCleanup(setattr, egress, "reconstruct_far_side_chain", real)
        closed = egress.close(PEER, emitted["packet_id"], "egress-test-001",
                              mesh_root=self.mesh, hb_epoch=32)
        self.assertEqual(closed["disposition"], "DENY")
        self.assertTrue(any(f.startswith("FAR_SIDE_TERMINAL_RECEIPT_DOES_NOT_RECOMPUTE")
                            for f in closed["closure_findings"]), closed["closure_findings"])
        self.assertEqual(len(self.repo_receipts(egress.CLOSURE_REFUSED_CLASS)), 1)

    def test_a_crossing_with_no_emission_record_here_cannot_be_closed(self):
        """The local half of the bilateral match: no record of emitting it."""
        self.emit()
        kernel.consume_and_respond(self.peer_node(), mesh_root=self.mesh)
        # A response exists, but this organization's chain holds no emission
        # receipt for the packet id being closed.
        closed = egress.close(PEER, "pkt-never-emitted-here", "egress-test-001",
                              mesh_root=self.mesh, hb_epoch=32)
        self.assertEqual(closed["disposition"], "DENY")
        self.assertIn("THIS_ORGANIZATION_HAS_NO_EMISSION_RECORD_FOR_THIS_PACKET",
                      closed["closure_findings"])

    def test_the_closure_record_states_what_reconstruction_does_not_establish(self):
        """It proves a boundary ran the packet, not whose boundary it was."""
        emitted = self.emit()
        kernel.consume_and_respond(self.peer_node(), mesh_root=self.mesh)
        record = egress.close(PEER, emitted["packet_id"], "egress-test-001",
                              mesh_root=self.mesh, hb_epoch=32)["closure_record"]
        self.assertIs(record["reconstruction_proves_the_boundary_ran_this_packet"], True)
        self.assertIs(record["reconstruction_proves_who_the_far_side_is"], False)
        self.assertIs(record["reconstruction_proves_the_far_side_persisted_its_chain"], False)
        self.assertIs(record["bilateral_match_requires_the_far_side_chain_to_be_readable"], True)

    def test_the_emission_records_the_digest_the_far_side_will_bind(self):
        """Closure reconstructs against this organization's own record of what it sent."""
        record = self.emit()["emission_record"]
        self.assertEqual(record["far_side_service_id"], PEER_CONTROL)
        self.assertTrue(record["far_side_payload_hash"].startswith("sha256:"))
        self.assertEqual(record["far_side_payload_hash"], kernel.sha(payload()))

    # --- what the crossing does not prove ----------------------------------

    def test_every_record_states_that_the_origin_is_asserted_and_not_attested(self):
        """A frame in a shared mesh carries whatever origin its writer put in it."""
        emitted = self.emit()
        kernel.consume_and_respond(self.peer_node(), mesh_root=self.mesh)
        closed = egress.close(PEER, emitted["packet_id"], "egress-test-001",
                              mesh_root=self.mesh, hb_epoch=32)
        for record in (emitted["emission_record"], closed["closure_record"]):
            self.assertEqual(record["origin_attestation_state"], "NOT_PROVEN")
            self.assertIs(record["origin_is_asserted_by_the_sender"], True)
            self.assertIs(record["origin_is_verified_by_this_boundary"], False)
            self.assertEqual(record["credential_authority"], "TV/TVC")
            self.assertEqual(record["authority_effect"].split("_")[0], "NONE")


class BoundaryDocumentDeclaresEgressTests(unittest.TestCase):
    """The organization's own boundary document binds the outbound half.

    Before this, `egress` carried only `interlock_required` and `intr_required`:
    the outbound half was declared to exist and bound to nothing, so a reader of
    the boundary document could not say which operation leaves the organization.
    A declaration the validator does not check is the defect this ecosystem
    exists to catch, so each check below is asserted to refuse.
    """

    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "runtime_boundary", ROOT / "org-runtime/runtime_boundary.py")
        self.boundary = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.boundary)
        self.document = json.loads(
            (ROOT / "org-runtime/interlock-intr.json").read_text(encoding="utf-8"))

    def test_the_organization_validator_requires_the_emitting_operation(self):
        report = self.boundary.validate()
        self.assertIs(report["checks"]["egress_emitting_operation_bound"], True)
        self.assertIs(report["checks"]["egress_destinations_resolve_from_the_directory"], True)
        self.assertIs(report["valid"], True)

    def test_the_declared_operation_is_the_one_this_change_installs(self):
        operation = self.boundary.egress_emitting_operation(self.document)
        self.assertEqual(operation["operation_id"], egress.OPERATION_ID)
        self.assertEqual(operation["emission"],
                         "resident-runtime/organization_egress_boundary.py::emit")
        self.assertEqual(operation["closure"],
                         "resident-runtime/organization_egress_boundary.py::close")
        self.assertEqual(sorted(operation["emission_transition_classes"]),
                         sorted([egress.EMITTED_CLASS, egress.EMIT_REFUSED_CLASS]))
        self.assertEqual(sorted(operation["closure_transition_classes"]),
                         sorted([egress.CLOSED_CLASS, egress.CLOSURE_REFUSED_CLASS]))

    def test_an_unbound_egress_still_fails_closed(self):
        """What the document said before: the half existed and bound nothing."""
        document = json.loads(json.dumps(self.document))
        document["egress"].pop("emitting_operation")
        self.assertIs(self.boundary.egress_emitting_operation_bound(document), False)

    def test_the_validator_refuses_an_authorizing_emitting_operation(self):
        for flag in self.boundary.EGRESS_NON_AUTHORIZING_FLAGS:
            with self.subTest(flag=flag):
                document = json.loads(json.dumps(self.document))
                document["egress"]["emitting_operation"][flag] = True
                self.assertIs(self.boundary.egress_emitting_operation_bound(document), False)

    def test_the_validator_refuses_a_located_emitting_operation(self):
        """A host dependency here would put back what the deployment removes."""
        for field in ("host_required", "environment_url_required"):
            with self.subTest(field=field):
                document = json.loads(json.dumps(self.document))
                document["egress"]["emitting_operation"][field] = True
                self.assertIs(self.boundary.egress_emitting_operation_bound(document), False)

    def test_the_validator_refuses_an_operation_claiming_it_attested_the_origin(self):
        """The overclaim the records exist to avoid, refused in the declaration too."""
        for field, value in (("origin_attestation_state", "PROVEN"),
                             ("origin_is_verified_by_this_boundary", True),
                             ("reconstruction_proves_who_the_far_side_is", True),
                             ("reconstruction_proves_the_far_side_persisted_its_chain", True)):
            with self.subTest(field=field):
                document = json.loads(json.dumps(self.document))
                document["egress"]["emitting_operation"][field] = value
                self.assertIs(self.boundary.egress_emitting_operation_bound(document), False)

    def test_the_validator_requires_the_declaration_to_claim_reconstruction(self):
        """The retracted limit: declaring it unreconstructable is now refused."""
        for field in ("far_side_receipt_reconstructed_here",
                      "far_side_chain_recomputed_from_emitter_held_inputs",
                      "closure_requires_this_organizations_own_emission_record"):
            with self.subTest(field=field):
                document = json.loads(json.dumps(self.document))
                document["egress"]["emitting_operation"][field] = False
                self.assertIs(self.boundary.egress_emitting_operation_bound(document), False)

    def test_the_validator_refuses_a_destination_resolved_from_the_caller(self):
        document = json.loads(json.dumps(self.document))
        document["egress"]["peer_destination_resolution"]["resolved_from_caller_argument"] = True
        self.assertIs(
            self.boundary.egress_destinations_resolve_from_the_directory(document), False)

    def test_the_validator_refuses_a_destination_directory_it_does_not_own(self):
        document = json.loads(json.dumps(self.document))
        document["egress"]["peer_destination_resolution"]["source"] = "CALLER_SUPPLIED"
        self.assertIs(
            self.boundary.egress_destinations_resolve_from_the_directory(document), False)


if __name__ == "__main__":
    unittest.main()
