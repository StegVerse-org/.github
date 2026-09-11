from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from stegverse.external_interlock_ingress_binding import build_ingress_bound_interlock_request
from stegverse.manifest_builder import build_manifest
from stegverse.state_transition_evidence import attach_state_transition_evidence

ROOT = Path(__file__).resolve().parents[1]
PROCESSOR = ROOT / "org-boundary/runtime/process_boundary.py"
REGISTRY = ROOT / "org-boundary/registry/services.json"
SERVICE_ID = "stegverse-org.workspace-resource-consumer"


def governance_request():
    return {
        "candidate": {"actor_class": "external_entity", "action": "observe_external_document", "target": "shared-document", "scope": "bounded-ephemeral-projection", "parameters": {"external_side_effect": False}},
        "judgment": {"refusal_available": True, "operator_recoverability": "available", "workload_state": "supported", "time_pressure": "normal", "isolation_state": "supported", "evidence_refs": ["workspace:test:org-binding"]},
        "signal": {"admitted_signal_refs": ["workspace:test:org-binding"], "excluded_signal_refs": [], "transformations": [], "missing_inputs": [], "uncertainty_state": "bounded", "reference_state_hash": "a" * 64, "expected_reference_state_hash": "a" * 64, "reconstruction_available": True, "transformation_provenance_complete": True},
        "execution": {"actor_authority_current": True, "policy_current": True, "delegation_current": True, "evidence_current": True, "affected_entity_conditions_represented": True, "recoverability_profile": "recoverable", "validity_window_open": True, "policy_ref": "workspace:test-policy", "delegation_ref": "workspace:test-delegation", "evidence_refs": ["workspace:test:org-binding"]},
        "capability": {"allowed": True}, "continuity": {"required": False}, "approval": {"required": False}, "permission_present": True,
    }


def interlock_request(*, unresolved: bool = False):
    manifest = build_manifest(
        data={"resource_class": "external.collaborative-document.v1", "resource_ref": "provider-neutral:org-binding", "observation": {"marker": "alpha"}},
        data_class="external.collaborative-document.v1",
        source_framework="provider-neutral-fixture",
        source_output_id="workspace-org-binding-001",
        processor_request=governance_request(),
        created_at="2026-09-10T23:50:00Z",
    )
    manifest = attach_state_transition_evidence(manifest, {
        "profile": "stegverse.state-transition-evidence.v1",
        "transition_id": "workspace-org-binding-transition-001",
        "state_domain": "external_document_projection",
        "prior_state_ref": "sha256:before",
        "new_state_ref": "sha256:after",
        "change_type": "REFRESHED",
        "applicable_predicates": [{"predicate_id": "authorization_current", "applicability": "APPLICABLE", "evidence_status": "UNRESOLVED" if unresolved else "SATISFIED"}],
        "ambiguities": [], "discovered_unknowns": [],
    })
    return build_ingress_bound_interlock_request(
        ingress_manifest=manifest,
        source_organization_id="External-Entity",
        target_organization_id="StegVerse-org",
        operation="OBSERVE_EXTERNAL_RESOURCE",
        authority_ref="TV/TVC:fixture",
        experiment_id="WORKSPACE-ORG-BINDING-001",
    )


def envelope(*, operation: str = "MATERIALIZE", unresolved: bool = False, service: str = SERVICE_ID):
    return {
        "schema_version": "stegverse-org.federation-envelope.v1",
        "packet_id": "workspace-org-packet-001",
        "direction": "INGRESS",
        "origin": {"org": "External-Entity", "service": "external-resource"},
        "destination": {"org": "StegVerse-org", "service": service},
        "carrier": {"class": "TEST", "authority_effect": "NONE"},
        "intr_profile": "test",
        "transition": {"authority_effect": "NONE"},
        "payload": {
            "schema": "stegverse.workspace-resource-request.v1",
            "operation": operation,
            "projection_id": "projection-org-1",
            "interlock_request": interlock_request(unresolved=unresolved),
        },
        "evidence": [],
    }


class WorkspaceInternalEndpointBindingTests(unittest.TestCase):
    def run_boundary(self, packet: dict):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "packet.json"
            out = Path(td) / "result.json"
            src.write_text(json.dumps(packet), encoding="utf-8")
            completed = subprocess.run(
                ["python3", str(PROCESSOR), "--envelope", str(src), "--registry", str(REGISTRY), "--out", str(out)],
                cwd=ROOT,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                check=False,
            )
            result = json.loads(out.read_text()) if out.is_file() else None
            return completed, result

    def test_registry_bound_workspace_endpoint_executes_canonical_sdk_consumer(self):
        completed, result = self.run_boundary(envelope())
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(result["consumed"])
        app = result["application_result"]
        self.assertEqual(app["service_id"], SERVICE_ID)
        self.assertEqual(app["consumer_profile"], "stegverse.workspace-resource-consumer.v1")
        self.assertEqual(app["workspace_state"]["operation"], "MATERIALIZE")
        self.assertEqual(app["workspace_state"]["readiness"], "READY")
        self.assertFalse(app["authority_transfer"])
        self.assertFalse(app["intr_receipt_minted_by_adapter"])

    def test_probe_required_materialize_fails_closed_through_boundary(self):
        completed, result = self.run_boundary(envelope(unresolved=True))
        self.assertNotEqual(completed.returncode, 0)
        self.assertIsNone(result)
        self.assertIn("endpoint-adapter-execution-failed", completed.stderr)

    def test_teardown_remains_available_when_probe_required(self):
        completed, result = self.run_boundary(envelope(operation="REVOKE", unresolved=True))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["application_result"]["workspace_state"]["readiness"], "PROBE_REQUIRED")
        self.assertEqual(result["application_result"]["workspace_state"]["operation"], "REVOKE")

    def test_unknown_workspace_service_fails_closed(self):
        completed, result = self.run_boundary(envelope(service="stegverse-org.workspace-unknown"))
        self.assertNotEqual(completed.returncode, 0)
        self.assertIsNone(result)
        self.assertIn("unknown-service", completed.stderr)


if __name__ == "__main__":
    unittest.main()
