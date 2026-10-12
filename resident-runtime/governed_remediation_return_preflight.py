"""Non-authorizing organization remediation-return preflight.

This checks consistency of a proposed Healer classification and SDK request.
It cannot authenticate organization custody, grant a return, or mint receipts.
"""
from __future__ import annotations
from typing import Any, Mapping


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
    if not isinstance(classification.get("source_disposition_ref"), str) or not classification["source_disposition_ref"]:
        raise ValueError("REMEDIATION_SOURCE_EVIDENCE_REQUIRED")
    if proposed_action not in ("RESUBMIT", "RE_MANIFEST"):
        raise ValueError("REMEDIATION_ACTION_NOT_RECOGNIZED")
    if proposed_action == "RE_MANIFEST" and classification.get("suggested_action") != "RE_MANIFEST":
        raise ValueError("REMANIFEST_NOT_CLASSIFIED")
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
