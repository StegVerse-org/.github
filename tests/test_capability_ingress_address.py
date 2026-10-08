"""A bound capability has an address, and the address resolves to the bound operation.

`org-runtime/interlock-intr.json` bound `sdk-manifest-ingress` to
`ORGANIZATION_SDK_MANIFEST_INGRESS` and `capability_endpoint_binding_rule`
called that resolved. `org-kernel/kernel.py::dispatch` resolves
`destination.service` against `org-boundary/registry/services.json` and refuses
`unknown_service` for anything absent from it, and no row resolved to that
operation -- so the binding named a destination transport could not reach. The
receiving operation could only be entered by running its CLI inside a checkout
of this repository, which is to say by already being inside the organization. A
customer's manifest, or a peer organization's, had nowhere to arrive.

These assert the properties that make the address real and keep it from being
read as more than an address: a peer-published submission reaches the bound
operation over the mesh and both ledger levels record it; the overlay stays the
authority on which capability arrives where, so an address cannot grant itself
one; a module that is not the bound operation is refused rather than run; no
processing is selected at the address and the record says where it was; a root
that serves no capability still dispatches, because requiring the resolver
everywhere would be a limit that is not real; and outbound, a peer's capability
address is derived with what that derivation does not prove recorded beside it.
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

PROFILE_ID = "sdk-manifest-ingress"
ADDRESS = "stegverse-org." + PROFILE_ID
OPERATION_ID = "ORGANIZATION_SDK_MANIFEST_INGRESS"
PEER = "StegVerse-Labs"


def _module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kernel = _module("kernel", "org-kernel/kernel.py")
capability = _module("capability_ingress", "org-boundary/runtime/capability_ingress.py")
egress = _module("organization_egress_boundary",
                 "resident-runtime/organization_egress_boundary.py")

REGISTRY = json.loads((ROOT / "org-boundary/registry/services.json").read_text())
BOUNDARY = json.loads((ROOT / "org-runtime/interlock-intr.json").read_text())
SERVICE_IDS = {row["service_id"] for row in REGISTRY["services"]}


def row(service_id):
    return next(r for r in REGISTRY["services"] if r["service_id"] == service_id)


def manifest():
    return json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))


def standing():
    declared = json.loads((ROOT / STANDING).read_text(encoding="utf-8"))
    return {k: v for k, v in declared.items() if not k.startswith("_")}


def submission(body=None, digest=True):
    payload = {"schema": "stegverse.sdk-manifest-crossing-payload/v1",
               "declared_transition_surface": "LLM_ADAPTER"}
    if body is not None:
        payload["manifest"] = body
        if digest:
            payload["manifest_sha256"] = kernel.sha(body)
    return payload


class AddressIsDeclaredTests(unittest.TestCase):
    """The declaration half, which is what was missing."""

    def test_the_bound_receiving_operation_has_a_registered_address(self):
        binding, = BOUNDARY["ingress"]["capability_endpoint_bindings"]
        receiving = binding["receiving_operation"]
        self.assertEqual(receiving["addressed_service"], ADDRESS)
        self.assertIn(ADDRESS, SERVICE_IDS)
        self.assertEqual(row(ADDRESS)["boundary_role"], capability.ROLE)
        self.assertEqual(row(ADDRESS)["capability_profile_id"], binding["profile_id"])

    def test_the_kernel_dispatches_the_role_the_resolver_serves(self):
        """A resolver serving a role no dispatch reaches would be unreachable too."""
        self.assertEqual(kernel.CAPABILITY_INGRESS_ROLE, capability.ROLE)

    def test_the_address_is_not_an_internal_endpoint(self):
        """An INTERNAL_ENDPOINT selects a processor, so it would have to enumerate
        the SDK's capability/route pairs -- the one table `manifest_selection`
        says this boundary must not grow."""
        self.assertNotEqual(row(ADDRESS)["boundary_role"], "INTERNAL_ENDPOINT")
        self.assertNotIn("admits_processing", row(ADDRESS))
        self.assertNotIn("endpoint_adapter", row(ADDRESS))

    def test_the_address_claims_no_authority(self):
        self.assertIs(row(ADDRESS)["address_grants_admission_authority"], False)
        self.assertIs(row(ADDRESS)["selects_processing_at_this_address"], False)


class OverlayIsTheAuthorityTests(unittest.TestCase):
    """An address cannot grant itself a capability by declaring one."""

    def test_a_row_the_overlay_does_not_name_resolves_nothing(self):
        with self.assertRaises(SystemExit) as refused:
            capability.resolve(ROOT, {"service_id": "stegverse-org.not-bound-anywhere"})
        self.assertIn("ADDRESS_SERVES_A_CAPABILITY_THE_OVERLAY_BINDS_HERE",
                      str(refused.exception))

    def test_the_resolution_names_the_overlay_as_its_source(self):
        resolved = capability.resolve(ROOT, row(ADDRESS))
        self.assertEqual(resolved["resolution_source"], "ORGANIZATION_CAPABILITY_OVERLAY")
        self.assertIs(resolved["resolved_from_the_addressed_row_alone"], False)
        self.assertEqual(resolved["receiving_operation_id"], OPERATION_ID)

    def test_a_module_that_is_not_the_bound_operation_is_refused(self):
        """A path edited to point somewhere adjacent must not run under this name."""
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
        receiving = document["ingress"]["capability_endpoint_bindings"][0]["receiving_operation"]
        receiving["operation"] = "../outside.py"
        (root / "org-runtime/interlock-intr.json").write_text(json.dumps(document))
        with self.assertRaises(SystemExit) as refused:
            capability.resolve(root, row(ADDRESS))
        self.assertIn("RECEIVING_OPERATION_IS_OWNED_INSIDE_THIS_ORGANIZATION",
                      str(refused.exception))


class SubmissionShapeTests(unittest.TestCase):
    def test_a_payload_with_no_manifest_is_not_a_submission(self):
        with self.assertRaises(SystemExit) as refused:
            capability.declared_manifest(submission())
        self.assertIn("SUBMISSION_CARRIES_A_MANIFEST", str(refused.exception))

    def test_a_carried_digest_that_disagrees_is_refused(self):
        payload = submission(manifest())
        payload["manifest_sha256"] = "sha256:" + "0" * 64
        with self.assertRaises(SystemExit) as refused:
            capability.declared_manifest(payload)
        self.assertIn("CARRIED_MANIFEST_DIGEST_MATCHES_THE_MANIFEST", str(refused.exception))

    def test_a_submission_without_a_carried_digest_is_still_a_submission(self):
        """The digest is checked when present; its absence is not a refusal."""
        self.assertEqual(capability.declared_manifest(submission(manifest(), digest=False)),
                         manifest())


class PeerSubmissionReachesTheOperationTests(unittest.TestCase):
    """The end this address exists for: a submission from outside arrives."""

    LEDGER_ROOTS = ("STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT")

    def setUp(self):
        self._ledger = tempfile.TemporaryDirectory()
        self.addCleanup(self._ledger.cleanup)
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

    def publish(self, payload, packet_id="peer-manifest-submission"):
        packet = kernel.build_packet(
            origin_org=PEER,
            origin_service=kernel.organization_slug(PEER) + "." + PROFILE_ID,
            destination_org="StegVerse-org",
            destination_service=ADDRESS,
            payload=payload, standing=standing(),
            transition_reference="intr:transition:" + packet_id,
            authority_effect="NONE", packet_id=packet_id)
        kernel.publish_packet(packet, root=self.mesh)
        return packet

    def consume(self):
        results = kernel.consume_addressed_frames(
            ROOT, mesh_root=self.mesh, repo_ledger_root=os.environ["STEGVERSE_REPO_LEDGER_ROOT"],
            org_ledger_root=os.environ["STEGVERSE_ORG_LEDGER_ROOT"])
        self.assertEqual(len(results), 1)
        return results[0]["result"]

    def test_a_peer_published_manifest_reaches_the_bound_operation(self):
        self.publish(submission(manifest()))
        ingested = self.consume()
        self.assertEqual(ingested["status"], "CONSUMED")
        execution = ingested["execution_result"]
        self.assertEqual(execution["service_id"], ADDRESS)
        self.assertIs(execution["consumed"], True)
        application = execution["application_result"]
        self.assertIs(application["capability_received"], True)
        self.assertEqual(application["capability_profile_id"], PROFILE_ID)
        self.assertEqual(application["receiving_operation_id"], OPERATION_ID)
        operation = application["receiving_operation_result"]
        self.assertIs(operation["organization_receipt_observed"], True)
        self.assertEqual(operation["resolved_service_id"], "stegverse-org.llm-adapter")

    def test_both_ledger_levels_record_the_submission(self):
        self.publish(submission(manifest()))
        self.consume()
        for variable, schema in (
                ("STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1"),
                ("STEGVERSE_ORG_LEDGER_ROOT", "stegverse.organization-transition-receipt/v1")):
            found = [json.loads(path.read_text(encoding="utf-8"))
                     for path in Path(os.environ[variable]).rglob("*.json")]
            self.assertTrue([r for r in found if r.get("schema") == schema],
                            variable + " recorded nothing")

    def test_the_address_selects_no_processing_and_says_where_it_was_processed(self):
        """A completed crossing at this address is not this address having
        processed the declared capability."""
        self.publish(submission(manifest()))
        execution = self.consume()["execution_result"]
        self.assertEqual(execution["processing_selection"],
                         "BOUNDARY_LOCAL_NO_PROCESSOR_SELECTED")
        application = execution["application_result"]
        self.assertIs(application["declared_capability_processed_at_this_address"], False)
        self.assertEqual(application["declared_capability_processed_by"], OPERATION_ID)
        self.assertIs(application["addressability_grants_admission_authority"], False)

    def test_a_submission_carrying_no_manifest_refuses_the_dispatch(self):
        """Refused at the boundary, not consumed with a refusal buried inside."""
        self.publish(submission())
        with self.assertRaises(ValueError) as refused:
            kernel.consume_addressed_frames(
            ROOT, mesh_root=self.mesh, repo_ledger_root=os.environ["STEGVERSE_REPO_LEDGER_ROOT"],
            org_ledger_root=os.environ["STEGVERSE_ORG_LEDGER_ROOT"])
        self.assertIn("SUBMISSION_CARRIES_A_MANIFEST", str(refused.exception))


class ResolverIsRequiredOnlyForItsOwnRoleTests(unittest.TestCase):
    """Requiring it of every root would be a limit that is not real."""

    def test_a_root_with_no_resolver_still_dispatches_control(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "org-boundary/registry").mkdir(parents=True)
        (root / "org-boundary/registry/services.json").write_text(json.dumps({
            "schema_version": "stegverse.org-boundary-registry.v1",
            "organization": PEER,
            "services": [{"service_id": kernel.organization_slug(PEER) + ".org-control",
                          "repository": PEER + "/.github",
                          "boundary_role": "BOUNDARY_LOCAL_CONTROL"}],
        }), encoding="utf-8")
        (root / "org-boundary/runtime").mkdir(parents=True)
        for name in ("process_boundary.py", "manifest_selection.py", "node_standing.py"):
            shutil.copy2(ROOT / "org-boundary/runtime" / name, root / "org-boundary/runtime" / name)
        (root / "docs").mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / CONTRACT, root / CONTRACT)
        self.assertFalse((root / "org-boundary/runtime/capability_ingress.py").exists())
        packet = kernel.build_packet(
            origin_org="StegVerse-org", origin_service="stegverse-org.org-control",
            destination_org=PEER,
            destination_service=kernel.organization_slug(PEER) + ".org-control",
            payload={"message_class": "ecosystem.communication",
                     "communication_id": "no-resolver-here", "body": {}},
            standing=standing(), transition_reference="intr:transition:no-resolver",
            authority_effect="NONE", packet_id="no-resolver-here")
        result = kernel.dispatch(root, packet)
        self.assertIs(result["consumed"], True)

    def test_a_capability_address_in_a_root_with_no_resolver_fails_closed(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "org-boundary/registry").mkdir(parents=True)
        (root / "org-boundary/registry/services.json").write_text(json.dumps({
            "schema_version": "stegverse.org-boundary-registry.v1",
            "organization": PEER,
            "services": [{"service_id": kernel.organization_slug(PEER) + "." + PROFILE_ID,
                          "repository": PEER + "/.github",
                          "boundary_role": capability.ROLE,
                          "capability_profile_id": PROFILE_ID}],
        }), encoding="utf-8")
        (root / "org-boundary/runtime").mkdir(parents=True)
        for name in ("process_boundary.py", "manifest_selection.py", "node_standing.py"):
            shutil.copy2(ROOT / "org-boundary/runtime" / name, root / "org-boundary/runtime" / name)
        (root / "docs").mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / CONTRACT, root / CONTRACT)
        packet = kernel.build_packet(
            origin_org="StegVerse-org",
            origin_service="stegverse-org." + PROFILE_ID,
            destination_org=PEER,
            destination_service=kernel.organization_slug(PEER) + "." + PROFILE_ID,
            payload=submission(manifest()), standing=standing(),
            transition_reference="intr:transition:no-resolver-capability",
            authority_effect="NONE", packet_id="no-resolver-capability")
        with self.assertRaises(ValueError) as refused:
            kernel.dispatch(root, packet)
        self.assertIn("org_boundary_capability_ingress_missing", str(refused.exception))


class PeerCapabilityAddressTests(unittest.TestCase):
    """Outbound: the address is derived, and the derivation's limit is recorded."""

    def test_no_capability_addresses_the_peer_control_service(self):
        resolved = egress.resolve_destination(PEER)
        self.assertEqual(resolved["destination_service"],
                         resolved["destination_org_control_service"])
        self.assertIsNone(resolved["destination_capability_profile_id"])

    def test_a_capability_addresses_the_peers_capability_service(self):
        resolved = egress.resolve_destination(PEER, capability=PROFILE_ID)
        self.assertEqual(resolved["destination_service"],
                         kernel.organization_slug(PEER) + "." + PROFILE_ID)
        self.assertNotEqual(resolved["destination_service"],
                            resolved["destination_org_control_service"])

    def test_a_capability_this_organization_does_not_declare_is_refused(self):
        with self.assertRaises(egress.EgressRefused) as refused:
            egress.resolve_destination(PEER, capability="not-a-declared-capability")
        self.assertEqual(refused.exception.failed_predicate,
                         "CAPABILITY_IS_DECLARED_IN_THIS_ORGANIZATIONS_OVERLAY")

    def test_the_derivation_is_the_one_this_organization_answers_at(self):
        """What makes the derivation real rather than invented: it is served here."""
        self.assertEqual(egress.peer_capability_service("StegVerse-org", PROFILE_ID), ADDRESS)
        self.assertIn(ADDRESS, SERVICE_IDS)

    def test_the_resolution_does_not_claim_the_peer_serves_it(self):
        resolved = egress.resolve_destination(PEER, capability=PROFILE_ID)
        self.assertIs(resolved["peer_serves_this_capability_is_proven_here"], False)
        self.assertIs(resolved["destination_capability_declared_by_the_peer_directory"], False)
        self.assertIs(resolved["unserved_capability_is_observable_as_an_unclosed_crossing"], True)

    def test_the_emission_record_binds_the_service_it_addressed(self):
        """A closure reconstructs against this, so recording the control service
        while having addressed a capability would make the crossing unclosable."""
        resolved = egress.resolve_destination(PEER, capability=PROFILE_ID)
        record = egress.emission_record(
            resolved, "StegVerse-org",
            {"packet_id": "p", "transition": {"reference": "r"}},
            {"frame_sha256": "sha256:" + "0" * 64}, {"probe": True})
        self.assertEqual(record["far_side_service_id"], resolved["destination_service"])
        self.assertEqual(record["destination_capability_profile_id"], PROFILE_ID)

    def test_the_declared_capabilities_come_from_the_overlay(self):
        declared = egress.declared_capabilities()
        self.assertIn(PROFILE_ID, declared)
        self.assertEqual(set(declared),
                         {b["profile_id"] for b in
                          BOUNDARY["ingress"]["capability_endpoint_bindings"]})


if __name__ == "__main__":
    unittest.main()
