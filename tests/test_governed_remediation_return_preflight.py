"""Non-authorizing governed-remediation preflight tests."""
import importlib.util
import hashlib
import json
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "resident-runtime" / "governed_remediation_return_preflight.py"
spec = importlib.util.spec_from_file_location("governed_remediation_return_preflight", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    request = {"request_sha256": "a" * 64, "wire_manifest_sha256": "b" * 64}
    classification = {
        "schema": "stegverse.healer.sdk-deny-classification/v1",
        "state": "DETECTED", "authority_effect": "NONE_CLASSIFICATION_ONLY",
        "governance_disposition": "NOT_EVALUATED", "execution_authority_granted": False,
        "original_request_sha256": request["request_sha256"],
        "original_request_document_sha256": hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest(),
        "original_wire_manifest_sha256": request["wire_manifest_sha256"],
        "source_disposition_ref": "sdk-profile-deny-001",
        "suggested_action": "RE_MANIFEST",
    }
    return classification, request


class ReturnPreflightTests(unittest.TestCase):
    def test_classified_remanifest_still_fails_closed(self):
        classification, request = fixture()
        out = module.inspect_governed_remediation_return(classification, request, "RE_MANIFEST")
        self.assertEqual(out["disposition"], "FAIL_CLOSED")
        self.assertEqual(out["authority_effect"], "NONE_PREFLIGHT_ONLY")
        self.assertFalse(out["execution_authority_granted"])
        for field in ("failure_code", "failed_predicate", "required_evidence_or_repair",
                      "retry_entrypoint", "owning_existing_goal", "next_attempt"):
            self.assertTrue(out.get(field), field)
        self.assertEqual(out["failure_code"], "REMEDIATION_GOVERNANCE_AUTHORITY_NOT_YET_EVALUATED")

    def test_request_substitution_rejected(self):
        classification, request = fixture()
        request["request_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "REMEDIATION_ORIGINAL_REQUEST_BINDING_MISMATCH"):
            module.inspect_governed_remediation_return(classification, request, "RE_MANIFEST")

    def test_request_document_digest_substitution_rejected(self):
        classification, request = fixture()
        classification["original_request_document_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "REMEDIATION_REQUEST_DOCUMENT_DIGEST_MISMATCH"):
            module.inspect_governed_remediation_return(classification, request, "RE_MANIFEST")

    def test_wire_manifest_digest_substitution_rejected(self):
        classification, request = fixture()
        classification["original_wire_manifest_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "REMEDIATION_WIRE_MANIFEST_DIGEST_MISMATCH"):
            module.inspect_governed_remediation_return(classification, request, "RE_MANIFEST")

    def test_resubmit_cannot_bypass_remanifest_classification(self):
        classification, request = fixture()
        with self.assertRaisesRegex(ValueError, "REMEDIATION_ACTION_CLASSIFICATION_MISMATCH"):
            module.inspect_governed_remediation_return(classification, request, "RESUBMIT")

    def test_review_required_is_not_resubmit_authority(self):
        classification, request = fixture()
        classification["suggested_action"] = "GOVERNANCE_REVIEW_REQUIRED"
        with self.assertRaisesRegex(ValueError, "REMEDIATION_ACTION_CLASSIFICATION_MISMATCH"):
            module.inspect_governed_remediation_return(classification, request, "RESUBMIT")

    def test_preapproved_healer_rejected(self):
        classification, request = fixture()
        classification["governance_disposition"] = "ALLOW"
        with self.assertRaisesRegex(ValueError, "PREAPPROVED_HEALER_CLASSIFICATION_REJECTED"):
            module.inspect_governed_remediation_return(classification, request, "RE_MANIFEST")

    def test_unclassified_remanifest_rejected(self):
        classification, request = fixture()
        classification["suggested_action"] = "GOVERNANCE_REVIEW_REQUIRED"
        with self.assertRaisesRegex(ValueError, "REMEDIATION_ACTION_CLASSIFICATION_MISMATCH"):
            module.inspect_governed_remediation_return(classification, request, "RE_MANIFEST")

    def test_pre_323_request_uses_canonical_manifest_wire_identity(self):
        # The original Experiment 3 request predates StegVerse-SDK#323 and has
        # no wire_manifest_sha256 field.
        canonical = {"payload": {"goal_task_id": "MIR-SV-CAPABILITY-BOUNDARY-EXPERIMENT-003"}}
        request = {"request_sha256": "a" * 64, "canonical_manifest": canonical}
        wire = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False).encode("utf-8")).hexdigest()
        classification, _ = fixture()
        classification["original_request_document_sha256"] = hashlib.sha256(json.dumps(
            request, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
        classification["original_wire_manifest_sha256"] = wire
        out = module.inspect_governed_remediation_return(classification, request, "RE_MANIFEST")
        self.assertEqual(out["disposition"], "FAIL_CLOSED")
        classification["original_wire_manifest_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "REMEDIATION_WIRE_MANIFEST_DIGEST_MISMATCH"):
            module.inspect_governed_remediation_return(classification, request, "RE_MANIFEST")

    def test_request_without_any_wire_identity_fails_closed(self):
        classification, _ = fixture()
        with self.assertRaisesRegex(ValueError, "REMEDIATION_REQUEST_FIELD_REQUIRED:wire_manifest_sha256"):
            module.inspect_governed_remediation_return(classification, {"request_sha256": "a" * 64}, "RE_MANIFEST")


if __name__ == "__main__":
    unittest.main()
