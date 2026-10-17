"""A NON-ALLOW is a receipt, and a route-related one is delivered.

StegVerse-org records each NON-ALLOW on both ledgers. When the manifest
derives an execution request, that receipt is a disposition delivered to
StegHealer on the route `remediation_route` calculates. The organization does
not decide remediation and does not consume a classification or a return.

A NON-ALLOW whose manifest derives no request has no manifested route. It
stays the six-field receipt on both ledgers and is not emitted. No mesh frame
is published.

Ledger roots and the mesh are temporary per test.
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "org-boundary/registry/services.json").read_text())
UNADMITTED = ROOT / "tests/fixtures/sdk-manifests/unadmitted-capability-to-llm-adapter.json"
GENESIS = json.loads((ROOT / "tests/fixtures/crossing-standing-genesis.json").read_text())
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
CLASSIFICATION_SCHEMA = "stegverse.org-remediation-classification-request/v1"


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ingress = _load("organization_manifest_ingress_non_allow", "resident-runtime/organization_manifest_ingress.py")
kernel = _load("organization_kernel_non_allow", "org-kernel/kernel.py")
federation = _load("federation_cycle_non_allow", "resident-runtime/federation_cycle.py")


class NonAllowReceiptTests(unittest.TestCase):
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

    def receipts(self, variable, schema):
        root = Path(os.environ[variable])
        if not root.exists():
            return []
        return [json.loads(path.read_text(encoding="utf-8"))
                for path in root.rglob("*.json")
                if json.loads(path.read_text(encoding="utf-8")).get("schema") == schema]

    def receive(self, manifest):
        return ingress.receive(manifest, registry=REGISTRY, standing=GENESIS,
                               packet_id="non-allow-receipt-test", hb_epoch=41, mesh_root=self.mesh)

    def frames(self):
        directory = self.mesh / "frames.d"
        if not directory.exists():
            return []
        return [json.loads(path.read_text(encoding="utf-8")) for path in directory.glob("*.json")]

    def refusal_pair(self, out):
        repository = [receipt for receipt in self.receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1")
            if receipt["transition_class"] == "ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED"]
        organization = [receipt for receipt in self.receipts(
            "STEGVERSE_ORG_LEDGER_ROOT", "stegverse.organization-transition-receipt/v1")
            if (receipt.get("boundary_evidence") or {}).get("receiving_operation") == ingress.OPERATION_ID]
        self.assertEqual(len(repository), 1)
        self.assertEqual(len(organization), 1)
        return repository[0], organization[0]

    def assert_receipt_on_both_ledgers(self, out, *, stored, failure_code,
                                       owning_goal="ORGANIZATION-ROLE-RUNTIME-REALITY-DEPLOYMENT-001",
                                       retry="resident-runtime/organization_manifest_ingress.py::receive"):
        # The returned disposition is the stored one (REFUSAL_DISPOSITIONS).
        self.assertEqual(out["disposition"], stored)
        self.assertIs(out["received"], False)
        self.assertIs(out["refusal_recorded"], True)
        self.assertIs(out["organization_receipt_observed"], False)
        self.assertEqual(out["authority_effect"], "NONE_REFUSAL_ONLY")
        self.assertEqual(out["failure_code"], failure_code)
        self.assertEqual(out["owning_existing_goal"], owning_goal)
        self.assertIn(retry, out["retry_entrypoint"])
        for field in SIX_FIELDS:
            self.assertTrue(out.get(field), field)
        self.assertNotIn("remediation_fork", out)
        self.assertNotIn("remediation_lane", out)
        self.assertNotIn("classification_state", out)
        self.assertNotIn("decision_return_entrypoint", out)
        self.assertNotIn("organization_receipt_sha256", out)
        self.assertIs(out.get("classification_consumed", False), False)
        self.assertIs(out.get("expects_a_classification", False), False)
        self.assertIs(out.get("remediation_decision_made_here", False), False)

        repository, organization = self.refusal_pair(out)
        self.assertEqual(repository["receipt_sha256"], out["refusal_repository_receipt_sha256"])
        self.assertEqual(repository["evidence"]["disposition"], stored)
        self.assertEqual(out["refusal_stored_disposition"], stored)
        self.assertEqual(repository["evidence"]["failed_predicate"], out["failed_predicate"])
        self.assertEqual(organization["receipt_sha256"], out["refusal_organization_receipt_sha256"])
        self.assertEqual(organization["repo_receipt_sha256"], repository["receipt_sha256"])
        self.assertEqual(organization["source_repository"], "StegVerse-org/.github")
        self.assertEqual(organization["org_transition_class"], "REPO_STATE_PROPAGATION")
        self.assertEqual(organization["boundary_evidence"]["disposition"], stored)
        self.assertEqual(organization["boundary_evidence"]["failed_predicate"], out["failed_predicate"])

    def calculated_route(self, manifest):
        from stegverse.remediation_fork import remediation_route
        request = ingress.derive_execution_request(manifest, ingress.boundary())
        return remediation_route(
            {"disposition": "FAIL_CLOSED", "organization": "StegVerse-org",
             "evaluation_boundary": ingress.OPERATION_ID,
             "request_sha256": request["request_sha256"],
             "failure_code": "PROCESSING_SERVICE_NOT_DECLARED_FOR_CONSUMER_ROUTE",
             "failed_predicate": "CONSUMER_ROUTE_RESOLVES_TO_A_DECLARED_PROCESSING_SERVICE"},
            original_route_id=request["route_id"],
            original_processing_capability=request["processing_capability"],
            original_destination=request["manifest_declared_destination"])

    def test_a_route_related_non_allow_is_recorded_and_delivered(self):
        """Receipt on both ledgers, emitted on the calculated route, nothing consumed back."""
        manifest = json.loads(UNADMITTED.read_text(encoding="utf-8"))
        out = self.receive(manifest)
        # D7: the unadmitted pair fails closed at the ingress, stored as FAIL_CLOSED,
        # with its own six fields passed through to the delivered disposition.
        self.assertEqual(out["failed_predicate"], "CONSUMER_ROUTE_RESOLVES_TO_A_DECLARED_PROCESSING_SERVICE")
        self.assert_receipt_on_both_ledgers(
            out, stored="FAIL_CLOSED",
            failure_code="PROCESSING_SERVICE_NOT_DECLARED_FOR_CONSUMER_ROUTE",
            owning_goal="INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001")
        self.assertIs(out["disposition_delivered"], True)
        self.assertIs(out["classification_consumed"], False)

        route = self.calculated_route(manifest)
        egress_hop = next(hop for hop in route["direct_route_to_steghealer"]
                          if hop["crossing"] == "INTERLOCK_INTR_EGRESS"
                          and hop["from"] == "StegVerse-org")
        internal = next(hop for hop in route["direct_route_to_steghealer"]
                        if hop["crossing"] == "INTERNAL_ENDPOINT")
        self.assertEqual(out["disposition_route_sha256"], route["route_sha256"])
        self.assertEqual(out["disposition_destination_organization"], egress_hop["to"])
        self.assertEqual(egress_hop["to"], route["steghealer"]["organization"])
        self.assertEqual(out["disposition_destination_service"], internal["to"])
        self.assertEqual(internal["to"], route["steghealer"]["service_id"])

        frame, = self.frames()
        self.assertEqual(frame["destination_org"], egress_hop["to"])
        packet = kernel.recover_packet(frame)
        self.assertEqual(packet["destination"]["org"], egress_hop["to"])
        self.assertEqual(packet["destination"]["service"], internal["to"])
        self.assertEqual(packet["intr_profile"], "stegverse.intr.org-boundary.v1")
        body = packet["payload"]["body"]
        self.assertEqual(body["schema"], ingress.DISPOSITION_SCHEMA)
        self.assertNotEqual(body["schema"], CLASSIFICATION_SCHEMA)
        self.assertEqual(body["delivery"], "NON_ALLOW_DISPOSITION")
        self.assertEqual(packet["payload"]["requested_action"], "DELIVER_NON_ALLOW_DISPOSITION")
        self.assertIs(body["classification_requested"], False)
        self.assertNotIn("remediation_request", body)
        for field in SIX_FIELDS:
            self.assertEqual(body[field], out[field])
        self.assertEqual(body["receipt"]["repository_receipt_sha256"],
                         out["refusal_repository_receipt_sha256"])
        self.assertEqual(body["receipt"]["organization_receipt_sha256"],
                         out["refusal_organization_receipt_sha256"])
        reference = body["manifest_reference"]
        self.assertTrue(reference["submitted_manifest_sha256"].startswith("sha256:"))
        self.assertEqual(reference["request_sha256"], out["request_sha256"])
        self.assertEqual(reference["data_packet_id"], "non-allow-receipt-test")
        self.assertEqual(body["route"], route)
        self.assertEqual(body["route_sha256"], route["route_sha256"])

        emitted = [receipt for receipt in self.receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1")
            if receipt["transition_class"] == "ORGANIZATION_EGRESS_EMITTED"]
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["evidence"]["destination_organization"], egress_hop["to"])
        self.assertEqual(emitted[0]["evidence"]["destination_service"], internal["to"])
        classes = {receipt["transition_class"] for receipt in self.receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1")}
        self.assertNotIn("ORGANIZATION_EGRESS_CLOSED", classes)
        self.assertNotIn("REMEDIATION_CLASSIFIED", classes)
        self.assertEqual(federation.returns_for_consumed(
            [{"result": {"status": "CONSUMED", "packet": {"payload": {
                "communication_id": out["disposition_communication_id"]}}}}],
            mesh_root=self.mesh), [])

    def test_one_non_allow_is_one_receipt_pair_and_one_delivery(self):
        manifest = json.loads(UNADMITTED.read_text(encoding="utf-8"))
        first, again = self.receive(manifest), self.receive(manifest)
        self.assertEqual(first["refusal_repository_receipt_sha256"],
                         again["refusal_repository_receipt_sha256"])
        self.assertEqual(first["refusal_organization_receipt_sha256"],
                         again["refusal_organization_receipt_sha256"])
        self.assertEqual(first["disposition_packet_id"], again["disposition_packet_id"])
        self.assertEqual(first["emission_repository_receipt_sha256"],
                         again["emission_repository_receipt_sha256"])
        self.assertIs(again["classification_consumed"], False)
        repository = self.receipts("STEGVERSE_REPO_LEDGER_ROOT",
                                   "stegverse.repo-transition-receipt/v1")
        self.assertEqual(len([r for r in repository
                              if r["transition_class"] == "ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED"]), 1)
        self.assertEqual(len([r for r in repository
                              if r["transition_class"] == "ORGANIZATION_EGRESS_EMITTED"]), 1)
        self.assertEqual(len(self.frames()), 1)
        self.assertNotIn("remediation_fork", again)
        self.assertNotIn("remediation_lane", again)

    def test_a_submission_with_no_derivable_request_is_recorded_and_not_emitted(self):
        """No manifested route: the receipt is the whole record, and nothing leaves.

        A submission that does not derive an execution request has no route and
        no destination. It is recorded as the six-field receipt on both ledgers.
        No frame is published, and no classification is consumed.
        """
        out = self.receive({"not": "a manifest"})
        self.assertEqual(out["failed_predicate"], "ORGANIZATION_RESOLVES_ITS_OWN_INGRESS_DESTINATION")
        self.assert_receipt_on_both_ledgers(
            out, stored="FAIL_CLOSED", failure_code="ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED")
        self.assertNotIn("disposition_delivered", out)
        self.assertNotIn("disposition_packet_id", out)
        self.assertEqual(self.frames(), [])
        classes = {receipt["transition_class"] for receipt in self.receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1")}
        self.assertEqual(classes, {"ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED"})

    def test_the_outbound_binding_is_a_disposition_and_not_a_classification_request(self):
        bindings = {entry["profile_id"]: entry
                    for entry in ingress.boundary()["egress"]["capability_destination_bindings"]}
        self.assertIn("governance", bindings)
        disposition = bindings["remediation"]
        self.assertEqual(disposition["binding_role"], "NON_ALLOW_DISPOSITION_DELIVERY")
        self.assertTrue(str(disposition["route_source"]).startswith("MANIFEST_CALCULATED"))
        self.assertIs(disposition["route_must_agree_with_this_binding"], True)
        self.assertEqual(disposition["request_schema"], ingress.DISPOSITION_SCHEMA)
        self.assertNotEqual(disposition["request_schema"], CLASSIFICATION_SCHEMA)
        self.assertIs(disposition["expects_a_classification"], False)
        self.assertIs(disposition["consumes_a_return"], False)
        self.assertIs(disposition["remediation_decision_made_here"], False)
        self.assertNotIn("classification_authority", disposition)
        self.assertNotIn("decision_return_operation", disposition)
        self.assertNotIn("awaits_the_classification", disposition)
        served = [row["service_id"] for row in REGISTRY["services"]
                  if row.get("service_id") == "stegverse-org.remediation"
                  or any((pair.get("capability") == "remediation")
                         for pair in (row.get("admits_processing") or []))]
        self.assertEqual(served, [])
        self.assertFalse((ROOT / "resident-runtime/remediation_endpoint.py").exists())
        self.assertFalse((ROOT / "resident-runtime/remediation_classification_return.py").exists())
        self.assertFalse((ROOT / "resident-runtime/governed_remediation_return_preflight.py").exists())
        self.assertNotIn("remediation_returns_for_consumed",
                         (ROOT / "resident-runtime/federation_cycle.py").read_text(encoding="utf-8"))
        self.assertNotIn("remediation_returns",
                         (ROOT / "resident-runtime/governance_return_cycle.py").read_text(encoding="utf-8"))
        self.assertNotIn("REMEDIATION_OWNING_GOAL",
                         (ROOT / "resident-runtime/organization_manifest_ingress.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
