"""A NON-ALLOW is a receipt on both organization ledgers.

StegVerse-org records each NON-ALLOW and does not request remediation, fork a
lane, or take a classification return into governance. StegHealer observes the
receipts. Ledger roots are temporary per test.
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


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ingress = _load("organization_manifest_ingress_non_allow", "resident-runtime/organization_manifest_ingress.py")


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

    def assert_receipt_on_both_ledgers(self, out):
        self.assertEqual(out["disposition"], "FAIL_CLOSED")
        self.assertIs(out["received"], False)
        self.assertIs(out["refusal_recorded"], True)
        self.assertIs(out["organization_receipt_observed"], False)
        self.assertEqual(out["authority_effect"], "NONE_REFUSAL_ONLY")
        self.assertEqual(out["failure_code"], "ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED")
        self.assertEqual(out["owning_existing_goal"], "ORGANIZATION-ROLE-RUNTIME-REALITY-DEPLOYMENT-001")
        self.assertEqual(out["retry_entrypoint"],
                         "resident-runtime/organization_manifest_ingress.py::receive")
        for field in SIX_FIELDS:
            self.assertTrue(out.get(field), field)
        self.assertNotIn("remediation_fork", out)
        self.assertNotIn("remediation_lane", out)
        self.assertNotIn("organization_receipt_sha256", out)
        frames = self.mesh / "frames.d"
        self.assertFalse(frames.exists() and any(frames.glob("*.json")))

        repository, = self.receipts("STEGVERSE_REPO_LEDGER_ROOT",
                                    "stegverse.repo-transition-receipt/v1")
        organization, = self.receipts("STEGVERSE_ORG_LEDGER_ROOT",
                                      "stegverse.organization-transition-receipt/v1")
        self.assertEqual(repository["transition_class"], "ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED")
        self.assertEqual(repository["receipt_sha256"], out["refusal_repository_receipt_sha256"])
        self.assertEqual(repository["evidence"]["disposition"], "DENY")
        self.assertEqual(repository["evidence"]["failed_predicate"], out["failed_predicate"])
        self.assertEqual(organization["receipt_sha256"], out["refusal_organization_receipt_sha256"])
        self.assertEqual(organization["repo_receipt_sha256"], repository["receipt_sha256"])
        self.assertEqual(organization["source_repository"], "StegVerse-org/.github")
        self.assertEqual(organization["org_transition_class"], "REPO_STATE_PROPAGATION")
        self.assertEqual(organization["boundary_evidence"]["disposition"], "DENY")
        self.assertEqual(organization["boundary_evidence"]["failed_predicate"], out["failed_predicate"])

    def test_an_unadmitted_request_is_a_receipt_on_both_ledgers(self):
        out = self.receive(json.loads(UNADMITTED.read_text(encoding="utf-8")))
        self.assertEqual(out["failed_predicate"], "ADMITTED_CROSSING_REACHES_ITS_INTERNAL_ENDPOINT")
        self.assert_receipt_on_both_ledgers(out)

    def test_one_non_allow_is_one_receipt_pair(self):
        manifest = json.loads(UNADMITTED.read_text(encoding="utf-8"))
        first, again = self.receive(manifest), self.receive(manifest)
        self.assertEqual(first["refusal_repository_receipt_sha256"],
                         again["refusal_repository_receipt_sha256"])
        self.assertEqual(first["refusal_organization_receipt_sha256"],
                         again["refusal_organization_receipt_sha256"])
        self.assertEqual(len(self.receipts("STEGVERSE_REPO_LEDGER_ROOT",
                                           "stegverse.repo-transition-receipt/v1")), 1)
        self.assertEqual(len(self.receipts("STEGVERSE_ORG_LEDGER_ROOT",
                                           "stegverse.organization-transition-receipt/v1")), 1)
        self.assertNotIn("remediation_fork", again)
        self.assertNotIn("remediation_lane", again)

    def test_a_submission_with_no_derivable_request_is_still_a_receipt(self):
        out = self.receive({"not": "a manifest"})
        self.assertEqual(out["failed_predicate"], "ORGANIZATION_RESOLVES_ITS_OWN_INGRESS_DESTINATION")
        self.assert_receipt_on_both_ledgers(out)

    def test_this_organization_does_not_bind_or_serve_remediation(self):
        bindings = [entry["profile_id"]
                    for entry in ingress.boundary()["egress"]["capability_destination_bindings"]]
        self.assertEqual(bindings, ["governance"])
        self.assertNotIn("remediation", bindings)
        served = [row["service_id"] for row in REGISTRY["services"]
                  if row.get("service_id") == "stegverse-org.remediation"
                  or any((pair.get("capability") == "remediation")
                         for pair in (row.get("admits_processing") or []))]
        self.assertEqual(served, [])
        self.assertFalse((ROOT / "resident-runtime/remediation_endpoint.py").exists())
        self.assertFalse((ROOT / "resident-runtime/remediation_classification_return.py").exists())


if __name__ == "__main__":
    unittest.main()
