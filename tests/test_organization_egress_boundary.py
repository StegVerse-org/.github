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

# A peer is materialized as its own organization: its own kernel, emitters and
# ledgers. See tests/peer_organization.py.
_peer_spec = importlib.util.spec_from_file_location("peer_organization", ROOT / "tests/peer_organization.py")
peers = importlib.util.module_from_spec(_peer_spec)
_peer_spec.loader.exec_module(peers)
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


class EgressHarness(unittest.TestCase):
    """Redirected ledgers, a scratch mesh, and the peer's own node. No cases."""

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
        # The peer node's own consumption markers and work intake, supplied
        # by the test as a materializer would, never the peer's checkout.
        self.node_state = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.node_state, True)

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
        return peers.materialize(self, PEER, [{"service_id": PEER_CONTROL, "repository": PEER + "/.github",
                          "boundary_role": "BOUNDARY_LOCAL_CONTROL"}])

    def emit(self, destination=PEER, **overrides):
        body = {"payload": payload(), "standing": GENESIS, "mesh_root": self.mesh,
                "hb_epoch": 32}
        body.update(overrides)
        return egress.emit(destination, body.pop("payload"), **body)


class EgressBoundaryTests(EgressHarness):

    # --- an emission at a supplied epoch is one transition ----------------

    def frames(self):
        return sorted((self.mesh / "frames.d").glob("*.json"))

    def test_a_replayed_emission_at_a_supplied_epoch_publishes_and_records_once(self):
        first = self.emit()
        second = self.emit()
        self.assertEqual(first["disposition"], "ALLOW")
        self.assertEqual(first["packet_id"], second["packet_id"])
        self.assertEqual(first["frame_sha256"], second["frame_sha256"])
        self.assertEqual(first["emission_repository_receipt_sha256"],
                         second["emission_repository_receipt_sha256"])
        self.assertEqual(first["emission_organization_receipt_sha256"],
                         second["emission_organization_receipt_sha256"])
        self.assertEqual(len(self.frames()), 1)
        self.assertEqual(len(self.repo_receipts(egress.EMITTED_CLASS)), 1)

    def test_an_emission_without_a_supplied_epoch_is_recorded_each_time(self):
        """Not reproducible, so not deduplicated: each frame keeps its own record."""
        self.emit(hb_epoch=None)
        self.emit(hb_epoch=None)
        self.assertEqual(len(self.repo_receipts(egress.EMITTED_CLASS)), 2)

    # --- a peer is addressed at the service it declares -------------------

    def test_an_ordinary_peer_resolves_at_its_organization_control_service(self):
        resolved = egress.resolve_destination(PEER)
        self.assertEqual(resolved["destination_service"], PEER_CONTROL)
        self.assertEqual(resolved["destination_addressed_service"], PEER_CONTROL)
        self.assertIs(resolved["destination_serves_an_organization_control_service"], True)

    def test_a_peer_declaring_a_non_control_service_is_addressed_there(self):
        """SV-011 serves a diagnostic and no control service. Naming it in the
        control service field would assert a capability it never declared."""
        resolved = egress.resolve_destination("SV-011")
        self.assertEqual(resolved["destination_service"], "sv-011.boundary-diagnostic")
        self.assertEqual(resolved["destination_addressed_service_role"],
                         "BOUNDARY_LOCAL_DIAGNOSTIC")
        self.assertIsNone(resolved["destination_org_control_service"])
        self.assertIs(resolved["destination_serves_an_organization_control_service"], False)

    def test_a_peer_declaring_no_addressable_service_is_refused(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "org-boundary/registry").mkdir(parents=True)
        shutil.copy2(ROOT / "org-boundary/registry/services.json",
                     root / "org-boundary/registry/services.json")
        (root / "org-boundary/registry/federation.json").write_text(json.dumps({
            "schema_version": "stegverse.org-federation-directory.v1",
            "organizations": [{"organization": "Nowhere", "repository": "Nowhere/.github",
                               "transport_profile": "stegverse.intr.org-boundary.v1"}],
            "denominator": 1}), encoding="utf-8")
        with self.assertRaises(egress.EgressRefused) as refused:
            egress.resolve_destination("Nowhere", root=root)
        self.assertEqual(refused.exception.failed_predicate,
                         "DESTINATION_DECLARES_A_SERVICE_THIS_DIRECTORY_CAN_ADDRESS")

    def test_sv_011_is_a_declared_peer_of_this_organization(self):
        directory = json.loads(
            (ROOT / "org-boundary/registry/federation.json").read_text(encoding="utf-8"))
        rows = {row["organization"]: row for row in directory["organizations"]}
        self.assertIn("SV-011", rows)
        self.assertEqual(directory["denominator"], len(directory["organizations"]))
        row = rows["SV-011"]
        self.assertEqual(row["repository"], "SV-011/entity")
        self.assertEqual(row["transport_profile"], "stegverse.intr.org-boundary.v1")
        # The peer's own registry is where the addressed service is declared.
        self.assertIn("org-boundary/registry/services.json",
                      row["peer_declares_this_in_its_own_registry"])

    def test_no_row_points_the_control_service_field_at_a_non_control_service(self):
        directory = json.loads(
            (ROOT / "org-boundary/registry/federation.json").read_text(encoding="utf-8"))
        for row in directory["organizations"]:
            with self.subTest(organization=row["organization"]):
                control = row.get("org_control_service")
                if control is not None:
                    self.assertTrue(control.endswith(".org-control"), control)

    # --- a carried requirement is not a verified one ----------------------

    def test_the_peers_kernel_generation_is_not_proven_at_resolution(self):
        """`transport_profile` is refused on mismatch; `kernel_required` is only
        carried. A field that reads as verified while nothing verifies it is the
        declaration-without-enforcement defect, so the record says so."""
        resolved = egress.resolve_destination(PEER)
        self.assertIsNotNone(resolved["destination_kernel_required"])
        self.assertIs(resolved["destination_kernel_generation_is_proven_here"], False)
        self.assertIs(resolved["destination_kernel_required_is_checked_at_resolution"], False)
        self.assertIs(
            resolved["declared_kernel_version_does_not_establish_the_enforcement_it_implies"],
            True)

    def test_a_peer_below_the_declared_kernel_requirement_is_not_refused(self):
        """Recorded because it is true, not because it is desirable: this
        boundary cannot read a peer's kernel, so it must not read as though a
        crossing were gated on one."""
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "org-boundary/registry").mkdir(parents=True)
        shutil.copy2(ROOT / "org-boundary/registry/services.json",
                     root / "org-boundary/registry/services.json")
        (root / "org-boundary/registry/federation.json").write_text(json.dumps({
            "schema_version": "stegverse.org-federation-directory.v1",
            "organizations": [{"organization": "Old-Kernel-Peer",
                               "repository": "Old-Kernel-Peer/.github",
                               "org_control_service": "old-kernel-peer.org-control",
                               "kernel_required": "9.9.9",
                               "transport_profile": "stegverse.intr.org-boundary.v1"}],
            "denominator": 1}), encoding="utf-8")
        resolved = egress.resolve_destination("Old-Kernel-Peer", root=root)
        self.assertEqual(resolved["destination_kernel_required"], "9.9.9")
        self.assertEqual(resolved["destination_service"], "old-kernel-peer.org-control")
        self.assertIs(resolved["destination_kernel_generation_is_proven_here"], False)

    def test_the_boundary_declares_the_kernel_requirement_as_unchecked(self):
        resolution = json.loads(
            (ROOT / "org-runtime/interlock-intr.json").read_text(encoding="utf-8")
        )["egress"]["peer_destination_resolution"]
        self.assertIs(resolution["kernel_required_is_declared_per_peer"], True)
        self.assertIs(resolution["kernel_required_is_checked_at_resolution"], False)
        self.assertIs(resolution["peer_kernel_generation_is_proven_here"], False)
        self.assertIs(resolution["peer_kernel_generation_is_the_peers_to_establish"], True)

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
        consumed = self.peer_node().consume(mesh_root=self.mesh,
                                              node_state_root=self.node_state)
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
        self.peer_node().consume(mesh_root=self.mesh,
                                   node_state_root=self.node_state)
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
        self.peer_node().consume(mesh_root=self.mesh,
                                   node_state_root=self.node_state)
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
        self.peer_node().consume(mesh_root=self.mesh,
                                   node_state_root=self.node_state)
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
        self.peer_node().consume(mesh_root=self.mesh,
                                   node_state_root=self.node_state)
        closed = egress.close(PEER, emitted["packet_id"], "egress-test-001",
                              mesh_root=self.mesh, hb_epoch=32)
        self.assertEqual(closed["far_side_terminal_receipt"], recomputed[-1])

    def test_a_terminal_receipt_that_does_not_recompute_refuses_the_closure(self):
        """A response that does not recompute did not run this packet."""
        emitted = self.emit()
        self.peer_node().consume(mesh_root=self.mesh,
                                   node_state_root=self.node_state)
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
        self.peer_node().consume(mesh_root=self.mesh,
                                   node_state_root=self.node_state)
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
        self.peer_node().consume(mesh_root=self.mesh,
                                   node_state_root=self.node_state)
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
        self.peer_node().consume(mesh_root=self.mesh,
                                   node_state_root=self.node_state)
        closed = egress.close(PEER, emitted["packet_id"], "egress-test-001",
                              mesh_root=self.mesh, hb_epoch=32)
        for record in (emitted["emission_record"], closed["closure_record"]):
            self.assertEqual(record["origin_attestation_state"], "NOT_PROVEN")
            self.assertIs(record["origin_is_asserted_by_the_sender"], True)
            self.assertIs(record["origin_is_verified_by_this_boundary"], False)
            self.assertEqual(record["credential_authority"], "TV/TVC")
            self.assertEqual(record["authority_effect"].split("_")[0], "NONE")


class UnclosableCrossingTests(EgressHarness):
    """A crossing whose closure is unreachable is refused, not emitted as ALLOW.

    Found by probing the real StegVerse-Labs tree. A payload with no
    `message_class` emitted ALLOW, published a frame, was consumed by the peer
    and receipted with a full five-stage chain -- and could never close, because
    the responder answers only the request classes in the transport profile and
    `close` correlates a response by `communication_id`. `PENDING` was returned
    forever, which reads as a crossing still in flight rather than one that can
    never complete.

    Every caller already passed both fields, so nothing enforced them: a
    precondition honoured by convention and checked by nothing.
    """

    def emit_payload(self, body):
        return egress.emit(PEER, body, standing=GENESIS, mesh_root=self.mesh,
                           hb_epoch=32)

    def test_a_payload_declaring_no_request_class_is_refused(self):
        result = self.emit_payload({"probe": True})
        self.assertEqual(result["disposition"], "DENY")
        self.assertEqual(result["emission_record"]["failed_predicate"],
                         "PAYLOAD_DECLARES_A_REQUEST_CLASS_THE_BOUNDARY_ANSWERS")

    def test_a_request_class_no_acknowledgement_answers_is_refused(self):
        result = self.emit_payload({"message_class": "ecosystem.not.answered",
                                    "communication_id": "c-1"})
        self.assertEqual(result["disposition"], "DENY")
        self.assertEqual(result["emission_record"]["failed_predicate"],
                         "PAYLOAD_DECLARES_A_REQUEST_CLASS_THE_BOUNDARY_ANSWERS")

    def test_a_payload_carrying_no_communication_id_is_refused(self):
        """Closure correlates on it and reads it from nowhere else."""
        for identifier in (None, "", "   "):
            with self.subTest(communication_id=identifier):
                body = {"message_class": "ecosystem.communication"}
                if identifier is not None:
                    body["communication_id"] = identifier
                result = self.emit_payload(body)
                self.assertEqual(result["disposition"], "DENY")
                self.assertEqual(result["emission_record"]["failed_predicate"],
                                 "PAYLOAD_CARRIES_THE_COMMUNICATION_ID_CLOSURE_CORRELATES_ON")

    def test_an_unclosable_crossing_publishes_no_frame(self):
        """It is refused before the packet is built, so nothing crosses."""
        self.emit_payload({"probe": True})
        self.assertEqual(list(Path(self.mesh).rglob("*.json")), [])

    def test_an_unclosable_crossing_is_recorded_as_a_refusal(self):
        before = len(self.repo_receipts())
        self.emit_payload({"probe": True})
        self.assertEqual(len(self.repo_receipts()), before + 1)
        record, = self.repo_receipts(egress.EMIT_REFUSED_CLASS)
        self.assertTrue(record["receipt_sha256"])

    def test_every_request_class_the_profile_answers_closes(self):
        """The refusal is the complement of what works, not a narrowing of it."""
        for index, request_class in enumerate(sorted(kernel.RESPONDED_REQUEST_CLASSES)):
            with self.subTest(message_class=request_class):
                identifier = "closable-%d" % index
                emitted = self.emit_payload(
                    {"message_class": request_class, "communication_id": identifier,
                     "subject": "s", "body": {}})
                self.assertEqual(emitted["disposition"], "ALLOW")
                self.peer_node().consume(mesh_root=self.mesh,
                                           node_state_root=self.node_state)
                closed = egress.close(PEER, emitted["packet_id"], identifier,
                                      mesh_root=self.mesh, hb_epoch=32)
                self.assertEqual(closed["disposition"], "ALLOW")
                self.assertIs(closed["closed"], True)

    def test_the_refusal_reads_the_profiles_own_set_rather_than_a_second_copy(self):
        """The set was a literal in the responder and keys in the response map.

        Two copies of the same set drift, and a drift here would refuse a
        crossing the peer would have answered, or admit one it would not.
        """
        self.assertEqual(set(kernel.RESPONDED_REQUEST_CLASSES),
                         {"ecosystem.monitor.request", "ecosystem.work.request",
                          "ecosystem.communication"})
        for request_class, acknowledgement in kernel.RESPONDED_REQUEST_CLASSES.items():
            with self.subTest(request_class=request_class):
                self.assertEqual(kernel.response_message_class(request_class),
                                 acknowledgement)
                self.assertIn(acknowledgement, egress.ACK_CLASSES)

    def test_what_the_check_does_not_establish_is_stated(self):
        """The set is this organization's responder's; a peer's is not readable here."""
        self.assertIn("peer", egress.closability_refusal.__doc__)
        self.assertIsNone(egress.closability_refusal(
            {"message_class": "ecosystem.communication", "communication_id": "c"}))


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

    def test_the_validator_requires_the_unclosable_crossing_refusal(self):
        report = self.boundary.validate()
        self.assertIs(report["checks"]["egress_refuses_an_unclosable_crossing"], True)

    def test_the_declared_answering_set_is_the_kernels_own(self):
        """Restating the set here would let the declaration drift from the code."""
        declared = self.document["egress"]["closable_crossing_precondition"]
        self.assertEqual(declared["responded_request_classes_source"],
                         "org-kernel/kernel.py::RESPONDED_REQUEST_CLASSES")
        self.assertEqual(sorted(declared["responded_request_classes"]),
                         sorted(kernel.RESPONDED_REQUEST_CLASSES))

    def test_the_validator_refuses_a_declaration_that_drifts_from_the_kernel(self):
        drifted = dict(self.document)
        egress_block = dict(drifted["egress"])
        precondition = dict(egress_block["closable_crossing_precondition"])
        precondition["responded_request_classes"] = ["ecosystem.communication"]
        egress_block["closable_crossing_precondition"] = precondition
        drifted["egress"] = egress_block
        self.assertIs(self.boundary.egress_refuses_an_unclosable_crossing(drifted), False)

    def test_the_validator_refuses_a_declaration_claiming_it_reads_a_peers_set(self):
        """The refusal rests on the shared profile, not on knowing the peer."""
        overclaimed = dict(self.document)
        egress_block = dict(overclaimed["egress"])
        precondition = dict(egress_block["closable_crossing_precondition"])
        precondition["peer_responded_request_classes_are_readable_here"] = True
        egress_block["closable_crossing_precondition"] = precondition
        overclaimed["egress"] = egress_block
        self.assertIs(self.boundary.egress_refuses_an_unclosable_crossing(overclaimed), False)

    def test_an_absent_precondition_declaration_fails_closed(self):
        without = dict(self.document)
        egress_block = {k: v for k, v in without["egress"].items()
                        if k != "closable_crossing_precondition"}
        without["egress"] = egress_block
        self.assertIs(self.boundary.egress_refuses_an_unclosable_crossing(without), False)

    def test_the_validator_refuses_a_destination_directory_it_does_not_own(self):
        document = json.loads(json.dumps(self.document))
        document["egress"]["peer_destination_resolution"]["source"] = "CALLER_SUPPLIED"
        self.assertIs(
            self.boundary.egress_destinations_resolve_from_the_directory(document), False)


if __name__ == "__main__":
    unittest.main()
