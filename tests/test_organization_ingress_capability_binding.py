"""The organization declares where a registered capability is received.

`SDK-GENERIC-MANIFEST-ECOSYSTEM-INVARIANT-005` left one predicate unsatisfiable
from the SDK side: `REGISTERED_CAPABILITY_RESOLVES_TO_CANONICAL_ORGANIZATION_
GITHUB_INGRESS_ENDPOINT`. The canonical connector registry declares the
capability `sdk-manifest-ingress` / `SDK:ManifestIngress` and names its owner,
but nothing said where this organization receives a submission on it, so every
manifest handoff failed closed with
`CANONICAL_ORGANIZATION_INGRESS_ENDPOINT_NOT_RESOLVED`.

The missing half is owned here. `repository_endpoint_rule` is
`APPLICATION_REPOSITORIES_EXPOSE_PROFILES_ONLY_ORG_DOT_GITHUB_OWNS_ORG_
COMMUNICATION`, so the binding belongs in this repository's Interlock/InTr
boundary and nowhere else.

These tests assert against the SDK's own resolver rather than against a local
copy of its rules. The SDK is the enforcing authority: a local restatement of
what it accepts could pass here while the real resolution still failed. Feeding
the published document to `resolve_organization_ingress` and to
`execute_manifest` means the thing under test is the thing that enforces.

Non-authorizing. The binding resolves a destination; it admits nothing,
executes nothing and supplies no credential.
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from stegverse.connector_capability_overlay import resolve_organization_ingress
from stegverse.manifest_builder import build_manifest
from stegverse.manifest_state_transition_runtime import execute_manifest

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = ROOT / "org-runtime/interlock-intr.json"
OWNER = "StegVerse-org/.github"

_spec = importlib.util.spec_from_file_location(
    "runtime_boundary", ROOT / "org-runtime/runtime_boundary.py")
runtime_boundary = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runtime_boundary)


def boundary() -> dict:
    return json.loads(BOUNDARY.read_text(encoding="utf-8"))


def manifest() -> dict:
    return build_manifest(
        data={"binding": "organization-ingress-capability"},
        source_framework="organization-boundary-test",
        source_output_id="organization-ingress-capability-binding",
        processor_request={"candidate": {"action": "inspect"}, "judgment": {}, "signal": {},
                          "execution": {}, "capability": {}, "continuity": {}, "approval": {},
                          "permission_present": False},
        created_at="2026-10-03T00:00:00Z")


class OrganizationIngressCapabilityBindingTests(unittest.TestCase):
    def test_the_sdks_own_resolver_resolves_the_published_binding(self):
        """The enforcing function is the test, so this cannot drift from it."""
        resolution = resolve_organization_ingress(
            boundary(), profile_id="sdk-manifest-ingress",
            profile_name="SDK:ManifestIngress", operation="SUBMIT_MANIFEST")
        self.assertEqual(resolution["organization"], "StegVerse-org")
        self.assertEqual(resolution["owner_repository"], OWNER)
        self.assertEqual(resolution["resolution_source"],
                         "ORG_DOT_GITHUB_INTERLOCK_INTR_BOUNDARY")
        self.assertEqual(resolution["receiving_operation"]["owner_repository"], OWNER)

    def test_resolution_grants_nothing(self):
        resolution = resolve_organization_ingress(
            boundary(), profile_id="sdk-manifest-ingress",
            profile_name="SDK:ManifestIngress", operation="SUBMIT_MANIFEST")
        self.assertEqual(resolution["authority_effect"], "NONE_BINDING_ONLY")
        for grant in ("grants_routing_authority", "grants_admission_authority",
                      "grants_execution_authority"):
            self.assertIs(resolution[grant], False)
        self.assertEqual(resolution["environment_inputs"], [])

    def test_the_receiving_operation_is_owned_here_and_is_not_a_host(self):
        """A URL here would put back the host dependency the deployment removed."""
        receiving = boundary()["ingress"]["capability_endpoint_bindings"][0]["receiving_operation"]
        self.assertEqual(receiving["owner_repository"], OWNER)
        self.assertEqual(receiving["address_form"],
                         "REPOSITORY_OWNED_OPERATION_NOT_HOST_OR_URL")
        self.assertIs(receiving["host_required"], False)
        self.assertIs(receiving["environment_url_required"], False)
        self.assertEqual(receiving["credential_authority"], "TV/TVC")
        self.assertEqual(receiving["github_token_runtime_authority"], "NONE")
        # The named operations exist in this repository. A binding pointing at
        # an operation that is not here resolves to nothing real.
        for key in ("admission", "processing", "receipt_append"):
            module = receiving[key].split("::", 1)[0]
            self.assertTrue((ROOT / module).is_file(), module)

    def test_an_unbound_capability_still_fails_closed(self):
        """The binding resolves what it declares, and nothing beyond it."""
        with self.assertRaises(ValueError) as refused:
            resolve_organization_ingress(
                boundary(), profile_id="sdk-manifest-ingress",
                profile_name="SDK:ManifestIngress", operation="EXECUTE_MANIFEST")
        self.assertEqual(
            str(refused.exception),
            "REGISTERED_CAPABILITY_RESOLVES_TO_CANONICAL_ORGANIZATION_GITHUB_INGRESS_ENDPOINT")

    def test_a_document_this_organization_does_not_own_is_refused(self):
        foreign = boundary()
        foreign["owner_repository"] = "StegVerse-org/LLM-adapter"
        with self.assertRaises(ValueError) as refused:
            resolve_organization_ingress(
                foreign, profile_id="sdk-manifest-ingress",
                profile_name="SDK:ManifestIngress", operation="SUBMIT_MANIFEST")
        self.assertEqual(str(refused.exception),
                         "CANONICAL_ORGANIZATION_GITHUB_BOUNDARY_OWNER_REQUIRED")

    def test_the_manifest_handoff_no_longer_fails_closed_on_destination(self):
        """The whole point: the predicate the SDK could not satisfy is satisfied."""
        unresolved = execute_manifest(manifest())
        self.assertEqual(unresolved["state"], "FAIL_CLOSED")
        self.assertEqual(unresolved["failure_code"],
                         "CANONICAL_ORGANIZATION_INGRESS_ENDPOINT_NOT_RESOLVED")

        resolved = execute_manifest(manifest(), boundary())
        self.assertEqual(resolved["disposition"], "ALLOW")
        self.assertEqual(resolved["state"], "MANIFESTED_FOR_INTERLOCK_INTR_HANDOFF")
        self.assertEqual(resolved["destination_resolution_source"],
                         "CANONICAL_CONNECTOR_CAPABILITY_OVERLAY")
        self.assertEqual(resolved["destination_resolution_environment_inputs"], [])

    def test_a_resolved_handoff_is_not_a_completed_transition(self):
        """Resolution names a destination. It does not reach one."""
        resolved = execute_manifest(manifest(), boundary())
        for unobserved in ("intr_admission_observed", "far_side_transition_observed",
                           "organization_receipt_observed",
                           "master_records_reconstruction_observed",
                           "consequence_committed", "receiver_contacted",
                           "transport_performed_by_sdk",
                           "transport_credential_supplied_by_sdk"):
            self.assertIs(resolved[unobserved], False, unobserved)

    def test_the_organization_validator_requires_the_binding(self):
        report = runtime_boundary.validate()
        self.assertIs(report["valid"], True)
        self.assertIs(report["checks"]["capability_bindings_resolve"], True)
        self.assertIs(report["checks"]["sdk_manifest_ingress_bound"], True)
        self.assertEqual(report["authority_effect"], "NONE_VALIDATION_ONLY")

    def test_the_validator_refuses_an_authorizing_binding(self):
        """A binding that grants routing is not a binding; it is a bypass."""
        for flag in runtime_boundary.NON_AUTHORIZING_BINDING_FLAGS:
            with self.subTest(flag=flag):
                document = boundary()
                document["ingress"]["capability_endpoint_bindings"][0][flag] = True
                self.assertIs(runtime_boundary.capability_bindings_resolve(document), False)

    def test_the_validator_refuses_a_second_binding_for_one_capability(self):
        """Two receiving operations for one capability resolves to neither."""
        document = boundary()
        bindings = document["ingress"]["capability_endpoint_bindings"]
        bindings.append(json.loads(json.dumps(bindings[0])))
        self.assertIs(runtime_boundary.capability_bindings_resolve(document), False)
        with self.assertRaises(ValueError):
            resolve_organization_ingress(
                document, profile_id="sdk-manifest-ingress",
                profile_name="SDK:ManifestIngress", operation="SUBMIT_MANIFEST")

    def test_the_validator_refuses_a_located_receiving_operation(self):
        document = boundary()
        document["ingress"]["capability_endpoint_bindings"][0]["receiving_operation"][
            "host_required"] = True
        self.assertIs(runtime_boundary.capability_bindings_resolve(document), False)


if __name__ == "__main__":
    unittest.main()
