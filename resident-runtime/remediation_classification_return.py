#!/usr/bin/env python3
"""`ORGANIZATION_REMEDIATION_CLASSIFICATION_RETURN` -- take StegHealer's classification into governance.

A non-ALLOW's remediation lane left this organization over InTr for StegHealer
(`organization_manifest_ingress.request_remediation_classification`), and
StegVerse-Labs answered on the federation mesh with a non-authorizing
classification recorded there as `REMEDIATION_CLASSIFIED`. This is its return,
step 4 of the owner contract (StegVerse-org/.github#98, comment 6134521366):

1. The crossing's closure is observed with the egress boundary's own `close`,
   which verifies the answer against this organization's emission record and
   records the closure at both ledger levels.
2. The answer must be StegHealer's classification of exactly the lane this
   organization emitted.
3. The existing non-authorizing preflight
   (`governed_remediation_return_preflight.py`) runs as a precondition.
4. The SDK's Manifest Builder builds the governance manifest that decides the
   mapped remediation (`stegverse.governed_remediation.remediation_governance_manifest`),
   and this organization's own ingress receives it. That governance request goes
   out on the existing governance route to the organization that owns StegCore,
   and its decision returns through `governance_decision_return.py`. No second
   authorization mechanism.

A classification, a preflight, CI or a receipt-shaped document never grants
authority here. The SDK acts only on a read-back ALLOW. Nothing waits: an absent
answer is an observation and records nothing.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "ORGANIZATION_REMEDIATION_CLASSIFICATION_RETURN"
RESULT_SCHEMA = "stegverse.organization-remediation-classification-return/v1"
CLASSIFICATION_SCHEMA = "stegverse.org-remediation-classification/v1"
COMMUNICATION_PREFIX = "remediation:"
RETRY_ENTRYPOINT = "resident-runtime/remediation_classification_return.py::return_on_consumption"
OWNING_EXISTING_GOAL = "STEGHEALTH-ECOSYSTEM-FAILURE-REMEDIATION-001"
# The governance request built from a returned classification declares its chain
# position the way every committed request here does: explicitly, as genesis,
# and not as authenticated standing.
GOVERNANCE_STANDING = {
    "mode": "ESTABLISH_GENESIS",
    "node_ref": "StegVerse-Labs/StegVerse-Healer",
    "predecessor": None,
    "_declared_not_authenticated": "A declared standing is not authenticated standing; the ingress decides "
                                   "the disposition and the organization ledger records it either way.",
}


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


returning = _module("governance_decision_return_for_remediation", "resident-runtime/governance_decision_return.py")
preflight_module = _module("governed_remediation_return_preflight",
                           "resident-runtime/governed_remediation_return_preflight.py")
ingress = returning.ingress
egress = returning.egress


def _refused(base: Mapping[str, Any], failed_predicate: str, required: str, *, next_attempt: str,
             failure_code: str = "REMEDIATION_CLASSIFICATION_NOT_RETURNED", **detail: Any) -> dict[str, Any]:
    return {**base, "disposition": "FAIL_CLOSED", "failure_code": failure_code,
            "failed_predicate": failed_predicate, "required_evidence_or_repair": required,
            "retry_entrypoint": RETRY_ENTRYPOINT, "owning_existing_goal": OWNING_EXISTING_GOAL,
            "next_attempt": next_attempt, "authority_effect": "NONE_REFUSAL_ONLY", **detail}


def answered_classification(answer: Any, fork_request: Mapping[str, Any], route: Mapping[str, Any]) -> str | None:
    """None when the answer is StegHealer's classification of exactly this lane, else why not."""
    answer = answer if isinstance(answer, Mapping) else {}
    steghealer = route.get("steghealer") or {}
    if answer.get("schema") != CLASSIFICATION_SCHEMA:
        return "REMEDIATION_ANSWER_IS_NOT_A_CLASSIFICATION"
    if answer.get("classifying_organization") != steghealer.get("organization"):
        return "REMEDIATION_CLASSIFIED_BY_AN_ORGANIZATION_THE_ROUTE_DOES_NOT_NAME"
    if answer.get("service_id") != steghealer.get("service_id"):
        return "REMEDIATION_CLASSIFIED_AT_A_SERVICE_THE_ROUTE_DOES_NOT_NAME"
    if answer.get("remediation_request_sha256") != ingress.request_digest(dict(fork_request)):
        return "REMEDIATION_CLASSIFICATION_ANSWERS_A_DIFFERENT_LANE"
    if answer.get("classification_grants_authority") is not False:
        return "REMEDIATION_CLASSIFICATION_AUTHORITY_ESCALATION"
    if answer.get("disposition") != "ALLOW" or not isinstance(answer.get("classification"), Mapping):
        return "REMEDIATION_NOT_CLASSIFIED:" + str(answer.get("reason"))
    return None


def return_classification(manifest: Mapping[str, Any], *, packet_id: str, communication_id: str,
                          registry: Mapping[str, Any], mesh_root: Path | None,
                          hb_epoch: int | None = None) -> dict[str, Any]:
    """Observe StegHealer's answer, record its closure, and take the classification into governance."""
    request = ingress.derive_execution_request(manifest, ingress.boundary())
    base = {"schema": RESULT_SCHEMA, "operation": OPERATION_ID,
            "remediation_request_sha256": request["request_sha256"],
            "remediation_packet_id": packet_id, "remediation_communication_id": communication_id,
            "records_authority": "ORGANIZATION_RECORDS_ONLY"}
    if request.get("processing_capability") != "remediation":
        return _refused(base, "MANIFEST_DECLARES_REMEDIATION_PROCESSING", "a remediation lane manifest",
                        next_attempt="return the classification of a remediation lane only")
    fork_request = (request.get("state_graph") or {}).get("request") or {}
    route = fork_request.get("remediation_route") or {}
    closed = egress.close(route.get("steghealer", {}).get("organization"), packet_id, communication_id,
                          mesh_root=mesh_root, hb_epoch=hb_epoch)
    if closed["disposition"] == egress.PENDING:
        return {**base, "disposition": "PENDING", "classification_returned": False,
                "absence_is_not_a_transition": True, "observation_only": True,
                "retry_entrypoint": RETRY_ENTRYPOINT, "authority_effect": "NONE_OBSERVATION_ONLY"}
    closure = {key: closed.get(key) for key in (
        "closure_transition_class", "closure_repository_receipt_sha256",
        "closure_organization_receipt_sha256", "closure_findings")}
    if closed["disposition"] != egress.ALLOW:
        return _refused({**base, **closure}, "STEGHEALERS_ANSWER_VERIFIES_AGAINST_THE_EMISSION",
                        "an answer that verifies against this organization's emission record",
                        next_attempt="the lane stays on the mesh; the answer is observed again",
                        detail=";".join(closed.get("closure_findings") or []))
    answer = closed.get("far_side_application_result")
    refusal = answered_classification(answer, fork_request, route)
    if refusal is not None:
        return _refused({**base, **closure}, refusal, "StegHealer's classification of exactly this lane",
                        next_attempt="nothing is taken into governance for this lane")
    classification = answer["classification"]
    original_request, non_allow = fork_request["original_request"], fork_request["non_allow"]
    try:
        preflight = preflight_module.inspect_governed_remediation_return(
            classification, original_request, str(classification.get("suggested_action")))
    except ValueError as exc:
        # An unmapped condition (governance review) or a mismatch: the non-ALLOW
        # stands, and nothing is proposed to governance as a remediation.
        return _refused({**base, **closure, "classification": classification},
                        "REMEDIATION_PREFLIGHT_PASSES:" + str(exc),
                        "a classification that maps to RESUBMIT or RE_MANIFEST and binds the original request",
                        next_attempt="the original non-ALLOW stands; an unmapped condition is the owner's review")
    evidence_refs = [ref for ref in (closed.get("closure_organization_receipt_sha256"),
                                     answer.get("organization_receipt_sha256")) if ref]
    try:
        from stegverse.governed_remediation import remediation_governance_manifest
        governance = remediation_governance_manifest(
            classification, original_request, non_allow, preflight=preflight,
            evidence_refs=evidence_refs, organization_boundary=ingress.boundary())
    except (ImportError, ValueError) as exc:
        return _refused({**base, **closure, "classification": classification, "preflight": preflight},
                        "SDK_BUILDS_THE_REMEDIATION_GOVERNANCE_MANIFEST",
                        "the pinned SDK's stegverse.governed_remediation.remediation_governance_manifest",
                        next_attempt="return the classification again under an SDK that builds it",
                        detail=type(exc).__name__ + ":" + str(exc))
    submitted = ingress.receive(governance, registry=dict(registry), standing=dict(GOVERNANCE_STANDING),
                                packet_id=packet_id + ":governance", hb_epoch=hb_epoch, mesh_root=mesh_root)
    return {**base, **closure,
            "disposition": submitted.get("disposition"),
            "classification_returned": True,
            "suggested_action": classification.get("suggested_action"),
            "classification": classification,
            "preflight": preflight,
            "steghealer_organization_receipt_sha256": answer.get("organization_receipt_sha256"),
            "governance_request_sha256": submitted.get("request_sha256"),
            "governance_request_packet_id": submitted.get("governance_request_packet_id"),
            "governance_submission": {key: submitted.get(key) for key in (
                "disposition", "governance_decision_state", "deciding_organization", "failure_code",
                "failed_predicate", "organization_receipt_sha256", "governance_communication_id")},
            "decision_return_entrypoint": "resident-runtime/governance_decision_return.py::return_decision",
            "authority_effect": "NONE_RETURN_ONLY"}


def return_on_consumption(response_packet: Mapping[str, Any], *, registry: Mapping[str, Any],
                          mesh_root: Path | None, hb_epoch: int | None = None) -> dict[str, Any] | None:
    """Materialize the return when StegHealer's answer to a remediation lane is consumed."""
    payload = response_packet.get("payload") or {}
    communication_id = payload.get("communication_id")
    if not (isinstance(communication_id, str) and communication_id.startswith(COMMUNICATION_PREFIX)):
        return None
    request_sha256 = communication_id[len(COMMUNICATION_PREFIX):]
    request_packet_id = (payload.get("body") or {}).get("request_packet_id")
    base = {"schema": RESULT_SCHEMA, "operation": OPERATION_ID, "trigger": "CLASSIFICATION_FRAME_CONSUMED",
            "response_packet_id": response_packet.get("packet_id"),
            "remediation_packet_id": request_packet_id, "remediation_communication_id": communication_id,
            "remediation_request_sha256": request_sha256}
    if not isinstance(request_packet_id, str) or not request_packet_id:
        return _refused(base, "ANSWER_NAMES_THE_LANE_IT_ANSWERS", "an answer naming the lane packet",
                        next_attempt="nothing is returned for an answer that names no lane")
    manifest, failed, detail = returning.retained_manifest(request_sha256)
    if manifest is None:
        return _refused(base, failed, "the lane's ingress transition, recorded with its canonical manifest",
                        next_attempt="return the classification once the lane's ingress is in this organization's records",
                        detail=detail)
    returned = return_classification(manifest, packet_id=request_packet_id, communication_id=communication_id,
                                     registry=registry, mesh_root=mesh_root, hb_epoch=hb_epoch)
    return {**returned, "trigger": "CLASSIFICATION_FRAME_CONSUMED",
            "response_packet_id": response_packet.get("packet_id")}


__all__ = ["OPERATION_ID", "RESULT_SCHEMA", "answered_classification", "return_classification",
           "return_on_consumption"]


if __name__ == "__main__":
    print(json.dumps({"operation": OPERATION_ID, "entrypoint": "return_on_consumption"}))
