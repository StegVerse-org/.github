#!/usr/bin/env python3
"""`ORGANIZATION_GOVERNANCE_DECISION_RETURN` -- return a governance decision to the SDK.

A governance manifest received here is decided by StegVerse-Labs, which owns
StegCore. `organization_manifest_ingress.receive` recorded the ingress and
emitted the request out through this organization's egress; StegVerse-Labs
received it through its own `.github`, decided it, recorded the decision in its
own records, and answered on the federation mesh.

This is the return. It observes the crossing's closure with the egress
boundary's own `close`, which verifies the answer against this organization's
emission record and records the closure at both ledger levels. It then rebuilds
the runtime result from this organization's records -- the ingress transition's
boundary closures are read back from the repository ledger, not carried by the
caller -- and hands it to the SDK's `admit_runtime_result`, which decides
whether it closes the transition.

Nothing waits. No answer yet is `PENDING` and records nothing: an absence is
not an arrival. The decision is recorded in organization records only; Master
Records is not in this path.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from stegverse.manifest_state_transition_runtime import admit_runtime_result, derive_execution_request

ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "ORGANIZATION_GOVERNANCE_DECISION_RETURN"
RESULT_SCHEMA = "stegverse.organization-governance-decision-return-result/v1"
DECISION_SCHEMA = "stegverse.org-governance-decision/v1"
RETRY_ENTRYPOINT = "resident-runtime/governance_decision_return.py::return_decision"


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ingress = _module("organization_manifest_ingress", "resident-runtime/organization_manifest_ingress.py")
egress = _module("organization_egress_boundary", "resident-runtime/organization_egress_boundary.py")


def governance_binding() -> dict[str, Any]:
    bindings = (ingress.boundary().get("egress") or {}).get("capability_destination_bindings") or []
    for entry in bindings:
        if isinstance(entry, dict) and entry.get("profile_id") == "governance":
            return dict(entry)
    raise ValueError("GOVERNANCE_DESTINATION_BINDING_NOT_DECLARED")


def recorded_ingress(transition_id: str) -> dict[str, Any] | None:
    """The ingress transition's evidence, read off this organization's repository ledger."""
    store = egress.ledger_store.PosixLedgerStore(egress.repository_ledger.lr())
    cursor = (store.get(egress.ledger_store.HEAD_KEY) or {}).get("receipt_sha256")
    while cursor:
        receipt = store.get(egress.ledger_store.receipt_key(cursor))
        if receipt is None:
            return None
        if (receipt.get("transition_class") == ingress.OPERATION_ID
                and receipt.get("transition_id") == transition_id):
            evidence = receipt.get("evidence")
            return dict(evidence) if isinstance(evidence, Mapping) else None
        cursor = receipt.get("previous_receipt_sha256")
    return None


def answered_decision(answer: Any, request: Mapping[str, Any], governance_request: Any,
                      deciding_organization: str) -> dict[str, Any]:
    """The decision the deciding organization returned, or FAIL_CLOSED if it answers something else.

    The closure proves a boundary ran this packet. That the answer is a decision
    on *this* request is checked here, against the request this organization
    holds, so a well-formed answer to a different request is never admitted.
    """
    answer = answer if isinstance(answer, Mapping) else {}
    expected = ingress.request_digest(governance_request)
    if answer.get("schema") != DECISION_SCHEMA:
        reason = "GOVERNANCE_ANSWER_IS_NOT_A_DECISION"
    elif answer.get("deciding_organization") != deciding_organization:
        reason = "GOVERNANCE_DECIDED_BY_AN_ORGANIZATION_THE_OVERLAY_DOES_NOT_BIND"
    elif answer.get("governance_request_sha256") != expected:
        reason = "GOVERNANCE_DECISION_ANSWERS_A_DIFFERENT_REQUEST"
    elif answer.get("sdk_request_sha256") != request["request_sha256"]:
        reason = "GOVERNANCE_DECISION_ANSWERS_A_DIFFERENT_SUBMISSION"
    elif answer.get("disposition") not in {"ALLOW", "DENY", "FAIL_CLOSED"}:
        reason = "GOVERNANCE_DECISION_CARRIES_NO_DISPOSITION"
    else:
        return dict(answer)
    return {"disposition": "FAIL_CLOSED", "reason": reason, "answer_received": dict(answer)}


def return_decision(manifest: Mapping[str, Any], *, packet_id: str, communication_id: str,
                    mesh_root: Path | None, hb_epoch: int | None = None) -> dict[str, Any]:
    """Observe the decision's return, record it, and hand it to the SDK."""
    request = derive_execution_request(manifest, ingress.boundary())
    binding = governance_binding()
    base = {"schema": RESULT_SCHEMA, "operation": OPERATION_ID,
            "request_sha256": request["request_sha256"],
            "governance_request_packet_id": packet_id,
            "governance_communication_id": communication_id,
            "deciding_organization": binding["destination_organization"],
            "records_authority": "ORGANIZATION_RECORDS_ONLY",
            "master_records_closure_observed": False}
    if request.get("processing_capability") != "governance":
        return {**base, "disposition": "FAIL_CLOSED", "decision_returned": False,
                "failed_predicate": "MANIFEST_DECLARES_GOVERNANCE_PROCESSING",
                "detail": str(request.get("processing_capability")),
                "authority_effect": "NONE_REFUSAL_ONLY"}

    closed = egress.close(binding["destination_organization"], packet_id, communication_id,
                          mesh_root=mesh_root, hb_epoch=hb_epoch)
    if closed["disposition"] == egress.PENDING:
        return {**base, "disposition": "PENDING", "decision_returned": False,
                "absence_is_not_a_transition": True, "awaits_the_decision": False,
                "retry_entrypoint": RETRY_ENTRYPOINT,
                "authority_effect": "NONE_OBSERVATION_ONLY"}
    closure = {key: closed.get(key) for key in (
        "closure_transition_class", "closure_repository_receipt_sha256",
        "closure_organization_receipt_sha256", "closure_findings", "far_side_terminal_receipt")}
    if closed["disposition"] != egress.ALLOW:
        return {**base, **closure, "disposition": "FAIL_CLOSED", "decision_returned": False,
                "failed_predicate": "DECIDING_ORGANIZATIONS_ANSWER_VERIFIES_AGAINST_THE_EMISSION",
                "detail": ";".join(closed.get("closure_findings") or []),
                "retry_entrypoint": RETRY_ENTRYPOINT,
                "authority_effect": "NONE_REFUSAL_ONLY"}

    transition_id = "ORGANIZATION-SDK-MANIFEST-INGRESS-" + request["request_sha256"][:16]
    recorded = recorded_ingress(transition_id)
    if recorded is None or not recorded.get("transition_closures"):
        return {**base, **closure, "disposition": "FAIL_CLOSED", "decision_returned": False,
                "failed_predicate": "INGRESS_TRANSITION_IS_IN_THIS_ORGANIZATIONS_RECORDS",
                "detail": transition_id,
                "retry_entrypoint": "resident-runtime/organization_manifest_ingress.py::receive",
                "authority_effect": "NONE_REFUSAL_ONLY"}

    governance_request = (manifest.get("extensions") or {}).get("stegverse_governance_request")
    decision = answered_decision(closed.get("far_side_application_result"), request,
                                 governance_request, binding["destination_organization"])
    runtime = ingress.runtime_result(
        request, recorded["transition_closures"],
        {"receipt_sha256": closed["closure_organization_receipt_sha256"]}, decision)
    try:
        admitted = admit_runtime_result(manifest, request, runtime)
    except ValueError as exc:
        return {**base, **closure, "disposition": "FAIL_CLOSED", "decision_returned": True,
                "governance_disposition": decision.get("disposition"),
                "failed_predicate": "SDK_ADMITS_THE_ORGANIZATION_RUNTIME_RESULT",
                "detail": str(exc), "authority_effect": "NONE_REFUSAL_ONLY"}
    return {**base, **closure, "disposition": "ALLOW", "decision_returned": True,
            "governance_disposition": decision.get("disposition"),
            "governance_failed_predicate": admitted.get("failed_predicate"),
            "decision_authority": decision.get("decision_authority"),
            "decided_by": decision.get("deciding_organization"),
            "deciding_organization_receipt_sha256": decision.get("organization_receipt_sha256"),
            "ingress_transition_id": transition_id,
            "sdk_admitted_result": admitted,
            "authority_effect": "NONE_RETURN_ONLY"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--packet-id", required=True)
    parser.add_argument("--communication-id", required=True)
    parser.add_argument("--mesh-root", type=Path, required=True,
                        help="federation mesh this node was materialized with")
    parser.add_argument("--hb-epoch", type=int, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    result = return_decision(json.loads(args.manifest.read_text(encoding="utf-8")),
                             packet_id=args.packet_id, communication_id=args.communication_id,
                             mesh_root=args.mesh_root, hb_epoch=args.hb_epoch)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered)
    print(json.dumps({k: v for k, v in result.items() if k != "sdk_admitted_result"}, sort_keys=True))
    return 0 if result["disposition"] in {"ALLOW", "PENDING"} else 1


if __name__ == "__main__":
    sys.exit(main())
