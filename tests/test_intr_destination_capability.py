"""``intr-destination`` is a universal ingress capability, not a purpose route.

Governance stays bound to the organization that owns the decider. A
route-related NON-ALLOW disposition is a separate outbound binding, delivered
on the manifest-calculated route, and it is not a classification request.
This capability is the mesh
primitive underneath purpose routes: every organization can advertise it, a
peer address is derived as
``organization_slug + "." + "intr-destination"``, and a purpose-neutral
diagnostic can be emitted and closed. Peer installation is not proven at
resolution. A closure can show that something at the addressed service ran
the packet; an absent answer stays ``PENDING`` and is not recorded as a close.

Both ledger roots and the mesh are redirected. Nothing here is an authentic
production receipt or a live peer installation.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STANDING = "tests/fixtures/crossing-standing-genesis.json"

PROFILE_ID = "intr-destination"
PROFILE_NAME = "InTr:Destination"
OPERATION = "DIAGNOSTIC_CROSSING"
OPERATION_ID = "ORGANIZATION_INTR_DESTINATION_INGRESS"
ADDRESS = "stegverse-org." + PROFILE_ID
PAYLOAD_SCHEMA = "stegverse.org-intr-destination-diagnostic/v1"
PEER = "StegVerse-Labs"
MANIFEST_PROFILE = "sdk-manifest-ingress"
THIS = "StegVerse-org"
CONSTRAINT = "CONSTRAINT_VARIABLE"
DISPOSITION_ROLE = "TRANSITION_EVIDENCE_ONLY"
CONSTRAINT_FIELDS = (
    "routing_authority_constraint",
    "admission_authority_constraint",
    "execution_authority_constraint",
    "time_constraint",
)


def assert_constraints(test, record):
    for name in CONSTRAINT_FIELDS:
        test.assertEqual(record[name], CONSTRAINT, name)
    test.assertEqual(record["disposition_role"], DISPOSITION_ROLE)


def _module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kernel = _module("kernel", "org-kernel/kernel.py")
capability = _module("capability_ingress", "org-boundary/runtime/capability_ingress.py")
egress = _module("organization_egress_boundary",
                 "resident-runtime/organization_egress_boundary.py")
ingress = _module("intr_destination_ingress", "resident-runtime/intr_destination_ingress.py")
runtime_boundary = _module("runtime_boundary", "org-runtime/runtime_boundary.py")

REGISTRY = json.loads((ROOT / "org-boundary/registry/services.json").read_text(encoding="utf-8"))
BOUNDARY = json.loads((ROOT / "org-runtime/interlock-intr.json").read_text(encoding="utf-8"))
FEDERATION = json.loads((ROOT / "org-boundary/registry/federation.json").read_text(encoding="utf-8"))
GENESIS = {"mode": "ESTABLISH_GENESIS", "node_ref": "intr-destination-test", "predecessor": None}


def binding(profile_id, document=None):
    matches = [entry for entry in (document or BOUNDARY)["ingress"]["capability_endpoint_bindings"]
               if entry.get("profile_id") == profile_id]
    if len(matches) != 1:
        raise AssertionError(profile_id)
    return matches[0]


def row(service_id):
    return next(item for item in REGISTRY["services"] if item["service_id"] == service_id)


def standing():
    declared = json.loads((ROOT / STANDING).read_text(encoding="utf-8"))
    return {key: value for key, value in declared.items() if not key.startswith("_")}


def diagnostic(communication_id="intr-destination-diagnostic-001", schema=PAYLOAD_SCHEMA):
    return {
        "message_class": "ecosystem.communication",
        "communication_id": communication_id,
        "subject": "purpose-neutral mesh diagnostic",
        "body": {"schema": schema, "probe": "diagnostic-crossing"},
    }


class DeclarationTests(unittest.TestCase):
    def test_the_overlay_advertises_the_capability_and_grants_nothing(self):
        declared = binding(PROFILE_ID)
        self.assertEqual(declared["profile_name"], PROFILE_NAME)
        self.assertEqual(declared["operation"], OPERATION)
        self.assertEqual(declared["payload_schema"], PAYLOAD_SCHEMA)
        self.assertEqual(declared["submission_reader"], capability.COMMUNICATION_READER)
        self.assertEqual(declared["authority_effect"], "NONE_BINDING_ONLY")
        for flag in ("grants_routing_authority", "grants_admission_authority",
                     "grants_execution_authority", "environment_selected_ingress"):
            self.assertIs(declared[flag], False, flag)
        receiving = declared["receiving_operation"]
        self.assertEqual(receiving["operation_id"], OPERATION_ID)
        self.assertEqual(receiving["addressed_service"], ADDRESS)
        self.assertEqual(receiving["addressed_service_boundary_role"], capability.ROLE)
        self.assertIs(receiving["selects_processing_at_the_capability_address"], False)
        self.assertIs(receiving["host_required"], False)
        self.assertIs(receiving["environment_url_required"], False)
        self.assertTrue((ROOT / receiving["operation"]).is_file())

    def test_the_registry_row_is_an_address_and_not_an_admission(self):
        served = row(ADDRESS)
        self.assertEqual(served["boundary_role"], "BOUNDARY_LOCAL_CAPABILITY_INGRESS")
        self.assertEqual(served["capability_profile_id"], PROFILE_ID)
        self.assertIs(served["address_grants_admission_authority"], False)
        self.assertIs(served["selects_processing_at_this_address"], False)
        self.assertNotIn("endpoint_adapter", served)
        self.assertNotIn("admits_processing", served)
        self.assertIn("ecosystem.communication", served["accepts"])
        self.assertIn(PAYLOAD_SCHEMA, served["accepts"])

    def test_both_served_addresses_are_named_and_no_peer_address_is(self):
        """The derivation is proven on every capability this organization serves.

        A string could name only one. Naming one of two would understate what
        is served here. The field is still not a map of what peers serve.
        """
        proven = BOUNDARY["egress"]["peer_capability_resolution"]["proven_on_this_organization"]
        served = {entry["receiving_operation"]["addressed_service"]
                  for entry in BOUNDARY["ingress"]["capability_endpoint_bindings"]}
        self.assertEqual(set(proven), served)
        self.assertEqual(served, {"stegverse-org.sdk-manifest-ingress", ADDRESS})
        self.assertNotIn("stegverse-labs.intr-destination", proven)
        report = runtime_boundary.validate()
        self.assertIs(report["valid"], True, report["checks"])
        self.assertIs(report["checks"]["capability_addresses_resolve"], True)
        self.assertIs(report["checks"]["peer_capability_addresses_derive"], True)

    def test_naming_only_one_served_address_is_refused(self):
        document = json.loads(json.dumps(BOUNDARY))
        document["egress"]["peer_capability_resolution"]["proven_on_this_organization"] = (
            "stegverse-org.sdk-manifest-ingress")
        self.assertIs(runtime_boundary.peer_capability_addresses_derive(document), False)

    def test_a_peer_address_in_the_proven_field_is_refused(self):
        document = json.loads(json.dumps(BOUNDARY))
        document["egress"]["peer_capability_resolution"]["proven_on_this_organization"] = [
            "stegverse-org.sdk-manifest-ingress", ADDRESS, "stegverse-labs.intr-destination"]
        self.assertIs(runtime_boundary.peer_capability_addresses_derive(document), False)

    def test_a_single_served_address_may_still_be_named_as_a_string(self):
        document = json.loads(json.dumps(BOUNDARY))
        document["ingress"]["capability_endpoint_bindings"] = [
            entry for entry in document["ingress"]["capability_endpoint_bindings"]
            if entry["profile_id"] == MANIFEST_PROFILE]
        document["egress"]["peer_capability_resolution"]["proven_on_this_organization"] = (
            "stegverse-org.sdk-manifest-ingress")
        self.assertIs(runtime_boundary.peer_capability_addresses_derive(document), True)

    def test_peer_services_are_not_written_into_the_federation_directory(self):
        for entry in FEDERATION["organizations"]:
            for key in ("org_control_service", "addressed_service"):
                self.assertNotIn(PROFILE_ID, str(entry.get(key) or ""))

    def test_governance_remains_and_the_disposition_binding_is_not_this_capability(self):
        destinations = {entry["profile_id"]: entry
                        for entry in BOUNDARY["egress"]["capability_destination_bindings"]}
        self.assertIn("governance", destinations)
        disposition = destinations["remediation"]
        self.assertEqual(disposition["binding_role"], "NON_ALLOW_DISPOSITION_DELIVERY")
        self.assertTrue(str(disposition["route_source"]).startswith("MANIFEST_CALCULATED"))
        self.assertNotEqual(disposition["request_schema"],
                            "stegverse.org-remediation-classification-request/v1")
        self.assertIs(disposition["expects_a_classification"], False)
        self.assertIs(disposition["consumes_a_return"], False)
        self.assertNotIn(PROFILE_ID, destinations)


class OverlayAuthorityTests(unittest.TestCase):
    def test_resolution_names_the_overlay_and_the_bound_operation(self):
        resolved = capability.resolve(ROOT, row(ADDRESS))
        self.assertEqual(resolved["resolution_source"], "ORGANIZATION_CAPABILITY_OVERLAY")
        self.assertIs(resolved["resolved_from_the_addressed_row_alone"], False)
        self.assertEqual(resolved["receiving_operation_id"], OPERATION_ID)
        self.assertEqual(resolved["capability_operation"], OPERATION)
        self.assertEqual(ingress.OPERATION_ID, OPERATION_ID)

    def test_a_row_the_overlay_does_not_name_resolves_nothing(self):
        with self.assertRaises(SystemExit) as refused:
            capability.resolve(ROOT, {"service_id": "stegverse-org.not-bound-anywhere"})
        self.assertIn("ADDRESS_SERVES_A_CAPABILITY_THE_OVERLAY_BINDS_HERE",
                      str(refused.exception))

    def test_a_module_that_is_not_the_bound_operation_is_refused(self):
        resolved = dict(capability.resolve(ROOT, row(ADDRESS)))
        resolved["receiving_operation_path"] = ROOT / "resident-runtime/organization_egress_boundary.py"
        with self.assertRaises(SystemExit) as refused:
            capability.load_operation(resolved)
        self.assertIn("MODULE_IDENTIFIES_ITSELF_AS_THE_BOUND_OPERATION",
                      str(refused.exception))

    def test_an_operation_outside_this_organization_is_refused(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "org-runtime").mkdir(parents=True)
        document = json.loads(json.dumps(BOUNDARY))
        receiving = binding(PROFILE_ID, document)["receiving_operation"]
        receiving["operation"] = "../outside.py"
        (root / "org-runtime/interlock-intr.json").write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(SystemExit) as refused:
            capability.resolve(root, row(ADDRESS))
        self.assertIn("RECEIVING_OPERATION_IS_OWNED_INSIDE_THIS_ORGANIZATION",
                      str(refused.exception))

    def test_the_readers_do_not_cross(self):
        with self.assertRaises(SystemExit) as manifest_refused:
            capability.submission_for(binding(MANIFEST_PROFILE), diagnostic())
        self.assertIn("SUBMISSION_CARRIES_A_MANIFEST", str(manifest_refused.exception))
        with self.assertRaises(SystemExit) as diagnostic_refused:
            capability.submission_for(binding(PROFILE_ID), {"manifest": {"probe": True}})
        self.assertIn("SUBMISSION_DECLARES_A_RESPONDED_REQUEST_CLASS",
                      str(diagnostic_refused.exception))

    def test_a_diagnostic_body_under_another_schema_is_refused(self):
        with self.assertRaises(SystemExit) as refused:
            capability.submission_for(binding(PROFILE_ID), diagnostic(schema="stegverse.org-governance-decision/v1"))
        self.assertIn("SUBMISSION_BODY_DECLARES_THE_BOUND_PAYLOAD_SCHEMA", str(refused.exception))


class RedirectedLedgers(unittest.TestCase):
    LEDGER_ROOTS = ("STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT")

    def setUp(self):
        self._work = tempfile.TemporaryDirectory()
        self.addCleanup(self._work.cleanup)
        previous = {name: os.environ.get(name) for name in self.LEDGER_ROOTS}
        for name in self.LEDGER_ROOTS:
            os.environ[name] = str(Path(self._work.name) / name.lower())
        self.mesh = Path(self._work.name) / "mesh"

        def restore():
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        self.addCleanup(restore)

    def receipts(self, variable, schema, transition_class=None):
        found = []
        root = Path(os.environ[variable])
        if not root.exists():
            return found
        for path in root.rglob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("schema") != schema:
                continue
            if transition_class is not None and record.get("transition_class") != transition_class:
                continue
            found.append(record)
        return found


class OperationReceiptTests(RedirectedLedgers):
    def test_a_diagnostic_is_acknowledged_at_both_ledger_levels_as_evidence_only(self):
        result = ingress.receive(diagnostic(), registry=REGISTRY, packet_id="direct-diagnostic",
                                 hb_epoch=32)
        self.assertEqual(result["disposition"], "ALLOW", result.get("detail"))
        self.assertIs(result["received"], True)
        self.assertIs(result["communication_acknowledged"], True)
        self.assertIs(result["repository_receipt_observed"], True)
        self.assertIs(result["organization_receipt_observed"], True)
        self.assertIs(result["organization_receipt_preserves_repository_receipt"], True)
        self.assertEqual(result["authority_effect"], "NONE_DIAGNOSTIC_ACK_ONLY")
        for flag in ("selects_processing", "purpose_specific_route", "standing_rechecked_here"):
            self.assertIs(result[flag], False, flag)
        assert_constraints(self, result)
        repository, = self.receipts("STEGVERSE_REPO_LEDGER_ROOT",
                                    "stegverse.repo-transition-receipt/v1", OPERATION_ID)
        self.assertEqual(repository["evidence"]["profile_id"], PROFILE_ID)
        self.assertEqual(repository["evidence"]["receiving_operation"], OPERATION_ID)
        organization, = self.receipts("STEGVERSE_ORG_LEDGER_ROOT",
                                      "stegverse.organization-transition-receipt/v1")
        self.assertEqual(organization["repo_receipt_sha256"], repository["receipt_sha256"])

    def test_a_replay_of_the_same_diagnostic_does_not_mint_a_second_pair(self):
        first = ingress.receive(diagnostic(), registry=REGISTRY, packet_id="replayed-diagnostic",
                                hb_epoch=32)
        second = ingress.receive(diagnostic(), registry=REGISTRY, packet_id="replayed-diagnostic",
                                 hb_epoch=32)
        self.assertIs(second["transition_replayed"], True)
        self.assertEqual(first["repository_receipt_sha256"], second["repository_receipt_sha256"])
        self.assertEqual(len(self.receipts("STEGVERSE_REPO_LEDGER_ROOT",
                                           "stegverse.repo-transition-receipt/v1", OPERATION_ID)), 1)

    def test_a_payload_that_is_not_the_diagnostic_is_refused_and_recorded(self):
        result = ingress.receive(
            {"message_class": "ecosystem.work.request", "communication_id": "not-a-diagnostic",
             "body": {"schema": "stegverse.org-governance-decision-request/v1"}},
            registry=REGISTRY, packet_id="refused-diagnostic", hb_epoch=32)
        self.assertEqual(result["disposition"], "DENY")
        self.assertIs(result["communication_acknowledged"], False)
        self.assertIs(result["refusal_recorded"], True)
        self.assertEqual(result["failed_predicate"], "SUBMISSION_DECLARES_A_RESPONDED_REQUEST_CLASS")
        self.assertEqual(result["authority_effect"], "NONE_REFUSAL_ONLY")
        self.assertEqual(len(self.receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1",
            ingress.REFUSED_CLASS)), 1)
        self.assertEqual(self.receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1", OPERATION_ID), [])


class AddressedAndClosedTests(RedirectedLedgers):
    def publish(self, payload, service, packet_id, origin=PEER):
        packet = kernel.build_packet(
            origin_org=origin,
            origin_service=kernel.organization_slug(origin) + "." + PROFILE_ID,
            destination_org="StegVerse-org", destination_service=service,
            payload=payload, standing=standing(),
            transition_reference="intr:transition:" + packet_id,
            authority_effect="NONE", packet_id=packet_id)
        kernel.publish_packet(packet, root=self.mesh, epoch=4096)
        return packet

    def consume(self):
        return kernel.consume_addressed_frames(
            ROOT, mesh_root=self.mesh,
            repo_ledger_root=os.environ["STEGVERSE_REPO_LEDGER_ROOT"],
            org_ledger_root=os.environ["STEGVERSE_ORG_LEDGER_ROOT"])

    def frames_to(self, organization):
        directory = self.mesh / "frames.d"
        if not directory.is_dir():
            return []
        frames = []
        for path in directory.glob("*.json"):
            frame = json.loads(path.read_text(encoding="utf-8"))
            if frame.get("destination_org") == organization:
                frames.append(frame)
        return frames

    def test_a_peer_frame_at_the_address_is_received_and_grants_nothing(self):
        self.publish(diagnostic("addressed-diagnostic"), ADDRESS, "addressed-diagnostic")
        results = self.consume()
        self.assertEqual(len(results), 1)
        execution = results[0]["result"]["execution_result"]
        self.assertEqual(results[0]["result"]["status"], "CONSUMED")
        self.assertEqual(execution["service_id"], ADDRESS)
        self.assertEqual(execution["processing_selection"], "BOUNDARY_LOCAL_NO_PROCESSOR_SELECTED")
        application = execution["application_result"]
        self.assertIs(application["capability_received"], True)
        self.assertEqual(application["capability_profile_id"], PROFILE_ID)
        self.assertEqual(application["receiving_operation_id"], OPERATION_ID)
        self.assertIs(application["declared_capability_processed_at_this_address"], False)
        self.assertIs(application["addressability_grants_admission_authority"], False)
        operation = application["receiving_operation_result"]
        self.assertEqual(operation["disposition"], "ALLOW", operation.get("detail"))
        self.assertIs(operation["communication_acknowledged"], True)
        self.assertEqual(operation["authority_effect"], "NONE_DIAGNOSTIC_ACK_ONLY")
        self.assertIs(operation["organization_receipt_preserves_repository_receipt"], True)
        repository, = self.receipts("STEGVERSE_REPO_LEDGER_ROOT",
                                    "stegverse.repo-transition-receipt/v1", OPERATION_ID)
        matched = [record for record in self.receipts(
            "STEGVERSE_ORG_LEDGER_ROOT", "stegverse.organization-transition-receipt/v1")
            if record.get("repo_receipt_sha256") == repository["receipt_sha256"]]
        self.assertEqual(len(matched), 1)

    def test_a_communication_addressed_to_the_manifest_capability_is_not_a_manifest(self):
        self.publish(diagnostic("wrong-reader"), "stegverse-org.sdk-manifest-ingress", "wrong-reader")
        with self.assertRaises(ValueError) as refused:
            self.consume()
        self.assertIn("SUBMISSION_CARRIES_A_MANIFEST", str(refused.exception))

    def test_outbound_resolution_derives_the_peer_address_and_does_not_prove_it_serves(self):
        resolved = egress.resolve_destination(PEER, capability=PROFILE_ID)
        self.assertEqual(resolved["destination_service"],
                         kernel.organization_slug(PEER) + "." + PROFILE_ID)
        self.assertNotEqual(resolved["destination_service"],
                            resolved["destination_org_control_service"])
        self.assertIs(resolved["peer_serves_this_capability_is_proven_here"], False)
        self.assertIs(resolved["destination_capability_declared_by_the_peer_directory"], False)
        self.assertEqual(egress.peer_capability_service("StegVerse-org", PROFILE_ID), ADDRESS)

    def test_an_undeclared_capability_is_still_refused(self):
        with self.assertRaises(egress.EgressRefused) as refused:
            egress.resolve_destination(PEER, capability="not-a-declared-capability")
        self.assertEqual(refused.exception.failed_predicate,
                         "CAPABILITY_IS_DECLARED_IN_THIS_ORGANIZATIONS_OVERLAY")

    def test_an_undeclared_peer_is_still_refused(self):
        with self.assertRaises(egress.EgressRefused) as refused:
            egress.resolve_destination("Not-A-Declared-Peer", capability=PROFILE_ID)
        self.assertEqual(refused.exception.failed_predicate,
                         "DESTINATION_IS_A_DECLARED_PEER_OF_THIS_ORGANIZATION")

    def answer(self, packet):
        """Answer as a boundary does: the kernel's own receipt chain and control response."""
        chain, previous = [], None
        for kind in egress.FAR_SIDE_RECEIPT_KINDS:
            receipt = kernel.receipt(kind, packet["packet_id"], packet["destination"]["service"],
                                     previous, {"payload_hash": kernel.sha(packet["payload"])})
            chain.append(receipt["receipt_id"])
            previous = receipt["receipt_id"]
        response = kernel.build_control_response(
            packet, {"application_result": {
                "schema": ingress.RESULT_SCHEMA, "disposition": "ALLOW",
                "authority_effect": "NONE_DIAGNOSTIC_ACK_ONLY"},
                "reconstruction": {"terminal_receipt_id": chain[-1]}})
        kernel.publish_packet(response, root=self.mesh)
        return chain[-1]

    def test_a_diagnostic_crossing_closes_only_when_the_far_side_answers(self):
        emitted = egress.emit(PEER, diagnostic("closable-diagnostic"), standing=GENESIS,
                              capability=PROFILE_ID, mesh_root=self.mesh, hb_epoch=32)
        self.assertEqual(emitted["disposition"], "ALLOW", emitted.get("detail"))
        self.assertIs(emitted["emitted"], True)
        self.assertEqual(emitted["destination_service"], "stegverse-labs.intr-destination")
        self.assertIs(emitted["peer_serves_this_capability_is_proven_here"], False)
        self.assertEqual(emitted["emission_record"]["far_side_service_id"],
                         emitted["destination_service"])
        pending = egress.close(PEER, emitted["packet_id"], "closable-diagnostic",
                               mesh_root=self.mesh, hb_epoch=33)
        self.assertEqual(pending["disposition"], "PENDING")
        self.assertIs(pending["closed"], False)
        self.assertIs(pending["closure_recorded"], False)
        self.assertIs(pending["absence_is_not_a_transition"], True)
        self.assertEqual(self.receipts("STEGVERSE_REPO_LEDGER_ROOT",
                                       "stegverse.repo-transition-receipt/v1",
                                       egress.CLOSED_CLASS), [])

        frame, = self.frames_to(PEER)
        packet = kernel.recover_packet(frame)
        self.assertEqual(packet["destination"]["service"], "stegverse-labs.intr-destination")
        self.assertEqual(packet["payload"]["message_class"], "ecosystem.communication")
        terminal = self.answer(packet)
        closed = egress.close(PEER, emitted["packet_id"], "closable-diagnostic",
                              mesh_root=self.mesh, hb_epoch=34)
        self.assertEqual(closed["disposition"], "ALLOW", closed.get("closure_findings"))
        self.assertIs(closed["closed"], True)
        self.assertEqual(closed["far_side_terminal_receipt"], terminal)
        # Closure shows a boundary ran this packet. It does not show which
        # organization that boundary belongs to, and resolution did not claim
        # the peer serves the capability.
        self.assertIs(closed["closure_record"]["reconstruction_proves_the_boundary_ran_this_packet"], True)
        self.assertIs(closed["closure_record"]["reconstruction_proves_who_the_far_side_is"], False)
        self.assertIs(emitted["peer_serves_this_capability_is_proven_here"], False)
        self.assertEqual(len(self.receipts("STEGVERSE_REPO_LEDGER_ROOT",
                                           "stegverse.repo-transition-receipt/v1",
                                           egress.CLOSED_CLASS)), 1)
        self.assertTrue(self.receipts("STEGVERSE_ORG_LEDGER_ROOT",
                                      "stegverse.organization-transition-receipt/v1"))


class DiagnosticSelfClosureTests(RedirectedLedgers):
    """A self-closure records both receipts on supplied temporary ledgers.

    Nothing in this class is an authentic production receipt, and nothing here
    is a live peer. The temporary chain only shows that the closure appends
    and that a readback can see ``communication_id``.
    """

    def test_a_self_closure_records_communication_id_on_both_receipts(self):
        before = (ROOT / "org-boundary/registry/federation.json").read_bytes()
        result = ingress.closure(
            "self-close-comm-001", registry=REGISTRY, packet_id="self-close-packet-001",
            hb_epoch=32)
        self.assertEqual((ROOT / "org-boundary/registry/federation.json").read_bytes(), before)
        self.assertEqual(result["schema"], ingress.CLOSURE_SCHEMA)
        self.assertEqual(result["disposition"], "ALLOW", result.get("detail"))
        self.assertIs(result["self_closure"], True)
        self.assertIs(result["peer_enumerated"], False)
        self.assertEqual(result["addressed_service"], ADDRESS)
        self.assertEqual(result["communication_id"], "self-close-comm-001")
        self.assertIs(result["communication_acknowledged"], True)
        assert_constraints(self, result)
        repository, = self.receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1", OPERATION_ID)
        self.assertEqual(repository["evidence"]["communication_id"], "self-close-comm-001")
        matched = [record for record in self.receipts(
            "STEGVERSE_ORG_LEDGER_ROOT", "stegverse.organization-transition-receipt/v1")
            if record.get("repo_receipt_sha256") == repository["receipt_sha256"]]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["boundary_evidence"]["communication_id"], "self-close-comm-001")

    def test_a_replay_of_the_same_self_closure_does_not_mint_a_second_pair(self):
        first = ingress.closure(
            "self-close-replay", registry=REGISTRY, packet_id="self-close-replay-packet",
            hb_epoch=32)
        second = ingress.closure(
            "self-close-replay", registry=REGISTRY, packet_id="self-close-replay-packet",
            hb_epoch=99)
        self.assertIs(second["transition_replayed"], True)
        self.assertEqual(first["organization_receipt_sha256"], second["organization_receipt_sha256"])
        self.assertEqual(len(self.receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1", OPERATION_ID)), 1)

    def test_a_blank_communication_id_writes_nothing(self):
        with self.assertRaises(ingress.SelfClosureRefused) as refused:
            ingress.closure(" ", registry=REGISTRY, packet_id="self-close-blank", hb_epoch=32)
        self.assertEqual(refused.exception.failed_predicate, "COMMUNICATION_ID_REQUIRED")
        self.assertEqual(self.receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1"), [])
        self.assertEqual(self.receipts(
            "STEGVERSE_ORG_LEDGER_ROOT", "stegverse.organization-transition-receipt/v1"), [])

    def test_a_registry_that_does_not_serve_the_address_writes_nothing(self):
        with self.assertRaises(ingress.SelfClosureRefused) as refused:
            ingress.closure(
                "self-close-unserved",
                registry={"organization": THIS, "services": []},
                packet_id="self-close-unserved", hb_epoch=32)
        self.assertEqual(refused.exception.failed_predicate,
                         "THIS_ORGANIZATION_SERVES_INTR_DESTINATION")
        self.assertEqual(self.receipts(
            "STEGVERSE_ORG_LEDGER_ROOT", "stegverse.organization-transition-receipt/v1"), [])

    def test_self_closure_fast_forwards_an_existing_git_ledger_and_reads_back(self):
        # Supplied temporary git ref. Not the published organization ledger,
        # and not an authentic production receipt.
        repo = Path(self._work.name) / "ledger"
        subprocess.check_call(["git", "init", "-q", str(repo)])
        ref = "refs/stegverse/organization-ledger"
        namespace = "repository-ledger/" + THIS + "/.github"
        org_root = "git+" + str(repo) + "#" + ref
        os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = org_root
        os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = org_root + ":" + namespace
        first = ingress.closure(
            "git-close-001", registry=REGISTRY, packet_id="git-close-packet-001", hb_epoch=40)
        tip_before = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", ref], text=True).strip()
        count_before = int(subprocess.check_output(
            ["git", "-C", str(repo), "rev-list", "--count", ref], text=True))
        second = ingress.closure(
            "git-close-002", registry=REGISTRY, packet_id="git-close-packet-002", hb_epoch=41)
        tip_after = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", ref], text=True).strip()
        count_after = int(subprocess.check_output(
            ["git", "-C", str(repo), "rev-list", "--count", ref], text=True))
        subprocess.check_call(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", tip_before, tip_after])
        self.assertGreater(count_after, count_before)
        self.assertNotEqual(first["organization_receipt_sha256"],
                            second["organization_receipt_sha256"])
        replay = ingress.closure(
            "git-close-002", registry=REGISTRY, packet_id="git-close-packet-002", hb_epoch=77)
        self.assertIs(replay["transition_replayed"], True)
        self.assertEqual(subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", ref], text=True).strip(), tip_after)
        fresh = Path(self._work.name) / "readback.git"
        subprocess.check_call(["git", "init", "-q", "--bare", str(fresh)])
        subprocess.check_call(
            ["git", "--git-dir", str(fresh), "fetch", "-q", str(repo), "+" + ref + ":" + ref])
        verified = ingress.verify_closure(
            "git+" + str(fresh) + "#" + ref, second, repository_namespace=namespace)
        digests = [item["receipt_sha256"] for item in verified["chain"]]
        self.assertIn(first["organization_receipt_sha256"], digests)
        self.assertIn(second["organization_receipt_sha256"], digests)
        self.assertEqual(verified["self_closure_communication_id"], "git-close-002")
        self.assertIs(verified["communication_id_on_organization_receipt"], True)
        self.assertIs(verified["communication_id_on_repository_receipt"], True)
        self.assertIs(verified["self_closure_extends_published_chain"], True)
        self.assertEqual(verified["head_receipt_sha256"], second["organization_receipt_sha256"])
        fresh_tip = subprocess.check_output(
            ["git", "--git-dir", str(fresh), "rev-parse", ref], text=True).strip()
        self.assertEqual(fresh_tip, tip_after)
        subprocess.check_call(
            ["git", "--git-dir", str(fresh), "merge-base", "--is-ancestor", tip_before, fresh_tip])


class LedgerWriterSelfClosureModeTests(unittest.TestCase):
    """The writer's self-closure mode appends, pushes fast-forward only, and reads back.

    This inspects the workflow text. It does not dispatch the workflow and it
    does not write the published ledger ref.
    """

    def text(self):
        # G17: the transition writer is job ledger-transition of the organization ledger writer.
        from tests.workflow_surface import writer_job
        return writer_job("ledger-transition")

    def step(self, name):
        return self.text().split("      - name: " + name + "\n")[1].split("      - name:")[0]

    def test_the_self_closure_mode_matches_the_other_writers(self):
        # Re-purposed (base id kept) under Rigel's rule (2026-10-25): InTr paths exist only between
        # distinct organizations, so the self-closure (an InTr hop inside this organization) is retired.
        # Its two steps are removed, as in SV-LLM/.github#62; the registry row records it retired,
        # never to be selected. The request mode keeps the writer's lock, permissions and one publish.
        text = self.text()
        from tests.workflow_surface import registry
        self.assertNotIn("workflow_dispatch:", text.split("\njobs:\n", 1)[0])
        pending = [r for r in registry()["fail_closed_pending"] if "self-closure" in r["surface"]]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["disposition"], "FAIL_CLOSED")
        self.assertEqual(pending[0]["failed_predicate"], "INTR_HOP_IS_BETWEEN_DISTINCT_ORGANIZATIONS")
        self.assertIn("retired_by_owner_rule", pending[0])
        for field in ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
                      "owning_existing_goal", "next_attempt"):
            self.assertTrue(pending[0][field], field)
        self.assertNotIn("Close an intr-destination diagnostic against this organization", text)
        self.assertNotIn("Read the intr-destination self-closure back from a fresh fetch", text)
        self.assertNotIn("--self-close", text)
        self.assertNotIn("--verify-self-closure", text)
        self.assertNotIn("if: env.MODE == 'self-closure'", text)
        self.assertIn("MODE: ${{ github.event.inputs.mode || 'request' }}", text)
        self.assertIn("group: organization-ledger", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("contents: write", text)
        for name in ("Select committed transition requests",
                     "Receive each request and append to the repository and organization ledgers",
                     "Publish the designated mesh ref (fast-forward only)",
                     "Read the organization and repository ledgers back from a fresh fetch"):
            self.assertIn("if: env.MODE != 'self-closure'", self.step(name), name)
        # One fast-forward push publishes the ledger ref.
        self.assertEqual(text.count('git push origin "$LEDGER_REF:$LEDGER_REF"'), 1)
        self.assertNotIn("if:", self.step("Publish the ledger ref (fast-forward only)").split("run:")[0])
        self.assertNotIn("--force", text)
        prohibited = "gr" + "ant"
        self.assertNotIn(prohibited, text.lower())
        self.assertNotIn(prohibited, (
            ROOT / "resident-runtime/intr_destination_ingress.py").read_text(encoding="utf-8").lower())

    def test_a_request_dispatch_still_names_a_committed_request(self):
        # #166 P4: workflow_dispatch is removed, so the request input branch was dead; a
        # committed request is selected only by the push that carries it.
        text = self.step("Select committed transition requests")
        self.assertNotIn("INPUT_REQUEST", text)
        self.assertNotIn("DISPATCH_REQUEST_", text)
        self.assertIn(".stegverse/transition-requests/*.json", text)


class LedgerWriterNonAllowMessageTests(unittest.TestCase):
    """Every FAIL_CLOSED/DENY message of the ledger writer carries the six fields.

    This reads the workflow text and runs individual step scripts in a scratch
    directory. It does not dispatch the workflow and writes no ledger ref.
    """

    SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair",
           "retry_entrypoint", "owning_existing_goal", "next_attempt")
    GOAL = "StegVerse-org/.github#162 P0-runtime-and-custody"
    RETRY = ".github/workflows/organization-ledger-writer.yml"
    # Messages that already carried all six fields keep their own owning goal.
    EARLIER_GOALS = {
        "MESH_REF_PUBLISH_RACE": "SVORG-MESH-LOCATION-BINDING-001",
        "ORGANIZATION_LEDGER_PUBLISH_RACE": "LLMA-DECLARED-PATH-CONFORMANCE-368",
        "AUTHENTICATED_LEDGER_READBACK_UNAVAILABLE": "LLMA-DECLARED-PATH-CONFORMANCE-368",
        # B-P31 (StegVerse-org/.github#207): the dispatch epoch is gated by the
        # organization writer's shared rule, whose refusal names its own goal.
        "HB_EPOCH_NOT_SUPPLIED": "INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001",
        "HB_EPOCH_INVALID": "INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001",
    }

    def text(self):
        from tests.workflow_surface import writer_job
        return writer_job("ledger-transition")

    def script(self, name):
        import textwrap
        step = self.text().split("      - name: " + name + "\n")[1].split("      - name:")[0]
        # Only the run block's own lines: a comment introducing the next step is
        # indented less and would otherwise shift the dedent (and a heredoc's
        # terminator) off the block's margin.
        block = []
        for line in step.split("        run: |\n", 1)[1].splitlines(keepends=True):
            if line.strip() and not line.startswith("          "):
                break
            block.append(line)
        return textwrap.dedent("".join(block))

    def assert_six(self, message):
        self.assertIn(message["disposition"], ("FAIL_CLOSED", "DENY"), message)
        for field in self.SIX:
            self.assertIsInstance(message.get(field), str, (field, message))
            self.assertTrue(message[field].strip(), (field, message))
        self.assertTrue(message["retry_entrypoint"].startswith(self.RETRY), message)
        self.assertEqual(message["owning_existing_goal"],
                         self.EARLIER_GOALS.get(message["failure_code"], self.GOAL), message)

    def test_every_fail_closed_or_deny_message_in_the_workflow_carries_the_six_fields(self):
        import re
        text = self.text()
        literals = re.findall(r"""echo '(\{"disposition":"(?:FAIL_CLOSED|DENY)".*?\})'""", text)
        # The ERR-trap form quotes the same one-line message inside the trap string.
        literals += re.findall(r"""trap 'echo '"'"'(\{"disposition":"(?:FAIL_CLOSED|DENY)".*?\})'"'"' >&2' ERR""", text)
        codes = set()
        for literal in literals:
            message = json.loads(literal)
            self.assert_six(message)
            codes.add(message["failure_code"])
        self.assertEqual(codes, {
            "ORGANIZATION_LEDGER_CONTRACT_OR_REQUEST_INVALID", "ORGANIZATION_LEDGER_REF_BINDING_FAILED",
            "MESH_REF_PUBLISH_RACE", "ORGANIZATION_LEDGER_PUBLISH_RACE",
            "AUTHENTICATED_LEDGER_READBACK_UNAVAILABLE"})
        # No refusal is a bare "FAIL_CLOSED: CODE" line any more.
        self.assertNotRegex(text, r"FAIL_CLOSED: [A-Z_]+")
        for line in text.splitlines():
            if re.search(r'"disposition":"(FAIL_CLOSED|DENY)"', line):
                for field in self.SIX:
                    self.assertIn('"%s"' % field, line)
        # The mesh readback's failing exit prints a six-field message first.
        mesh = self.script("Read the designated mesh ref back from a fresh fetch")
        block = mesh[mesh.index("if emitted and not frames:"):]
        import ast
        message = ast.literal_eval(block.split("print(json.dumps(", 1)[1].split(", sort_keys=True)", 1)[0])
        self.assertEqual(message["failure_code"], "EMISSION_RECORDED_WITHOUT_A_MESH_FRAME")
        self.assert_six(message)
        # Every explicit failing exit follows a six-field message, either this
        # workflow's own or the one the called runtime prints (resolved, binding).
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if re.search(r"\bexit 1\b|sys\.exit\(1\)|raise SystemExit\(", line):
                window = "\n".join(lines[max(0, index - 12):index + 1])
                self.assertTrue(
                    "owning_existing_goal" in window or 'echo "$resolved"; exit 1' in line
                    or 'echo "$binding"; exit 1' in line or "print(json.dumps(resolved" in window
                    # The shared-rule epoch gate prints the writer's own six-field refusal.
                    or "print(json.dumps({**refusal" in window
                    # The request-epoch refusals, each a six-field record, printed as written.
                    or 'cat "$RUNNER_TEMP"/epoch-refusals/*.json' in window,
                    "line %d: %s" % (index + 1, line.strip()))
        for name in ("Validate committed request and readback implementation before any append",
                     "Bind the designated organization ledger ref and the repository ledger subtree within it"):
            self.assertTrue(self.script(name).startswith("trap '"), name)

    def run_step(self, name, cwd, env, script=None):
        bin_dir = Path(cwd) / ".bin"
        bin_dir.mkdir(exist_ok=True)
        if not (bin_dir / "python").exists():
            (bin_dir / "python").symlink_to(sys.executable)
        environment = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                           RUNNER_TEMP=str(Path(cwd) / ".runner"), **env)
        Path(environment["RUNNER_TEMP"]).mkdir(exist_ok=True)
        return subprocess.run(["bash", "-e", "-c", script or self.script(name)], cwd=cwd, env=environment,
                              capture_output=True, text=True)

    def last_message(self, run):
        # A literal echo puts disposition first; the shared-rule gate prints
        # its refusal with sorted keys, so any JSON object line naming one counts.
        lines = [line[line.index("{"):] for line in (run.stdout + "\n" + run.stderr).splitlines()
                 if '{"disposition"' in line or ("{" in line and '"disposition": ' in line)]
        self.assertTrue(lines, run.stdout + run.stderr)
        return json.loads(lines[-1])

    def test_request_mode_and_self_closure_refusals_resolve_with_the_six_fields(self):
        select = "Select committed transition requests"
        with tempfile.TemporaryDirectory() as tmp:
            git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a],
                                            cwd=tmp, check=True, capture_output=True, text=True).stdout.strip()
            git("init", "-q")
            requests = Path(tmp, ".stegverse", "transition-requests")
            requests.mkdir(parents=True)
            (requests / "earlier.json").write_text("{}", encoding="utf-8")
            git("add", "-A"); git("commit", "-q", "-m", "before")
            before = git("rev-parse", "HEAD")
            (requests / "committed.json").write_text("{}", encoding="utf-8")
            Path(tmp, "elsewhere.json").write_text("{}", encoding="utf-8")
            git("add", "-A"); git("commit", "-q", "-m", "push")
            # A push selects exactly the transition requests it adds or modifies; nothing is
            # named by an input (there is none since workflow_dispatch was removed).
            run = self.run_step(select, tmp, {"GITHUB_EVENT_NAME": "push", "BEFORE": before,
                                              "GITHUB_SHA": git("rev-parse", "HEAD"),
                                              "INPUT_REQUEST": "elsewhere.json"})
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(Path(tmp, ".runner", "requests.txt").read_text().split(),
                             [".stegverse/transition-requests/committed.json"])
            self.assertNotIn("failure_code", run.stdout + run.stderr)

        # The self-closure step is removed (Rigel's rule, 2026-10-25: no InTr hop inside one organization);
        # it has no refusals left to resolve.
        self.assertNotIn("      - name: Close an intr-destination diagnostic against this organization\n", self.text())

        with tempfile.TemporaryDirectory() as tmp:
            for name, code in (("Validate committed request and readback implementation before any append",
                                "ORGANIZATION_LEDGER_CONTRACT_OR_REQUEST_INVALID"),
                               ("Bind the designated organization ledger ref and the repository ledger subtree within it",
                                "ORGANIZATION_LEDGER_REF_BINDING_FAILED")):
                run = self.run_step(name, tmp, {"LEDGER_REF": "refs/stegverse/organization-ledger",
                                                "GITHUB_ENV": str(Path(tmp, "github-env"))})
                self.assertNotEqual(run.returncode, 0, name)
                message = self.last_message(run)
                self.assertEqual(message["failure_code"], code)
                self.assert_six(message)


if __name__ == "__main__":
    unittest.main()
