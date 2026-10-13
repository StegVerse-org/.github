"""Non-authorizing organization remediation-return preflight.

This checks consistency of a proposed Healer classification and SDK request.
It cannot authenticate organization custody, grant a return, or mint receipts.
"""
from __future__ import annotations
import hashlib
import json
from typing import Any, Mapping


def _wire_manifest_sha256(request: Mapping[str, Any]) -> str | None:
    """The request's wire identity. Requests derived before StegVerse-SDK#323
    (the original Experiment 3 request among them) carry no
    wire_manifest_sha256; their wire identity is the digest of the
    canonical_manifest they hold, as the SDK (53a6749) and Healer use it."""
    declared = request.get("wire_manifest_sha256")
    if isinstance(declared, str) and declared:
        return declared
    original = request.get("canonical_manifest")
    if isinstance(original, Mapping):
        return hashlib.sha256(json.dumps(
            dict(original), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")).hexdigest()
    return None


def inspect_governed_remediation_return(
    classification: Mapping[str, Any],
    request: Mapping[str, Any],
    proposed_action: str,
) -> dict[str, Any]:
    """Produce a fail-closed evidence-only preflight for separate governance."""
    if classification.get("schema") != "stegverse.healer.sdk-deny-classification/v1":
        raise ValueError("HEALER_CLASSIFICATION_SCHEMA_REQUIRED")
    if classification.get("state") != "DETECTED":
        raise ValueError("HEALER_CLASSIFICATION_STATE_REQUIRED")
    if classification.get("authority_effect") != "NONE_CLASSIFICATION_ONLY":
        raise ValueError("HEALER_CLASSIFICATION_AUTHORITY_ESCALATION")
    if classification.get("governance_disposition") != "NOT_EVALUATED":
        raise ValueError("PREAPPROVED_HEALER_CLASSIFICATION_REJECTED")
    if classification.get("execution_authority_granted") is not False:
        raise ValueError("HEALER_EXECUTION_AUTHORITY_ESCALATION")
    if classification.get("original_request_sha256") != request.get("request_sha256"):
        raise ValueError("REMEDIATION_ORIGINAL_REQUEST_BINDING_MISMATCH")
    if not isinstance(request.get("request_sha256"), str) or not request["request_sha256"]:
        raise ValueError("REMEDIATION_REQUEST_FIELD_REQUIRED:request_sha256")
    wire = _wire_manifest_sha256(request)
    if not wire:
        raise ValueError("REMEDIATION_REQUEST_FIELD_REQUIRED:wire_manifest_sha256")
    complete_digest = hashlib.sha256(json.dumps(
        dict(request), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()
    if classification.get("original_request_document_sha256") != complete_digest:
        raise ValueError("REMEDIATION_REQUEST_DOCUMENT_DIGEST_MISMATCH")
    if classification.get("original_wire_manifest_sha256") != wire:
        raise ValueError("REMEDIATION_WIRE_MANIFEST_DIGEST_MISMATCH")
    if not isinstance(classification.get("source_disposition_ref"), str) or not classification["source_disposition_ref"]:
        raise ValueError("REMEDIATION_SOURCE_EVIDENCE_REQUIRED")
    if proposed_action not in ("RESUBMIT", "RE_MANIFEST"):
        raise ValueError("REMEDIATION_ACTION_NOT_RECOGNIZED")
    # The classification is evidence, never permission to switch action lanes.
    # A correctable envelope DENY cannot be silently re-labelled RESUBMIT.
    if classification.get("suggested_action") != proposed_action:
        raise ValueError("REMEDIATION_ACTION_CLASSIFICATION_MISMATCH")
    return {
        "schema": "stegverse.organization.remediation-return-preflight/v1",
        "state": "AWAIT_AUTHENTIC_ORGANIZATION_GOVERNANCE",
        "disposition": "FAIL_CLOSED",
        "proposed_action": proposed_action,
        "original_request_sha256": request["request_sha256"],
        "source_disposition_ref": classification["source_disposition_ref"],
        "required_evidence_or_repair": "AUTHENTIC_GOVERNED_RETURN_AND_SOVEREIGN_LEDGER_READBACK",
        "authority_effect": "NONE_PREFLIGHT_ONLY",
        "execution_authority_granted": False,
    }
