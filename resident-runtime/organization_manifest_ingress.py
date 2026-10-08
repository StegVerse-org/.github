#!/usr/bin/env python3
"""`ORGANIZATION_SDK_MANIFEST_INGRESS` -- receive a submitted SDK manifest here.

The capability overlay says where a registered capability is received:
`org-runtime/interlock-intr.json` binds `sdk-manifest-ingress` /
`SDK:ManifestIngress` / `SUBMIT_MANIFEST` to a receiving operation this
repository owns. That binding resolved a destination and stopped there. Nothing
drove a submission into it, so `organization_receipt_observed` stayed false on
every handoff and the crossing never happened.

This is the receiving operation. The organization resolves its own destination
from its own boundary document -- it is not handed one, and it does not fetch
one, because `repository_endpoint_rule` makes this repository the owner of
organization communication and a document supplied by a caller would let the
caller name its own organization.

The sequence is the one the binding declares, in that order:

    derive_execution_request(manifest, this organization's boundary)
    resident-runtime/sdk_manifest_crossing.py::cross       admission
    org-boundary/runtime/process_boundary.py               processing
    .stegverse/transition-ledger/emit.py::append           repository receipt
    resident-runtime/aggregate_repo_transition.py::append  organization receipt
    stegverse.manifest_state_transition_runtime.admit_runtime_result

The two ledger levels are both written, in that order, because the transition
occurs in this repository and the organization ledger's job is to consume a
receipt from the level below. One writer standing in for both levels is what
`preserves_repo_receipt: true` has nothing to preserve from, and it leaves
organization replay resting on a receipt the same call minted, where
`ORGANIZATION_REPLAY_MUST_REQUIRE_ONLY_VERIFIED_REPO_RECEIPTS_AND_ORG_RECEIPTS`
asks for a verified repository receipt underneath.

Two resolutions happen at two boundaries and must not be confused. The overlay
resolves *organization* ingress: which organization receives this capability,
and on what operation. `completion.egress` then resolves which *internal*
endpoint of that organization serves the declared surface. The SDK's
`completion_egress_controls_outbound_organization_routing: false` is about the
first; it does not make a manifest's declared internal surface unreadable once
the manifest has arrived.

The organization never grades its own result. It reports what it observed and
hands that to the SDK's own `admit_runtime_result`, which is the authority on
whether a runtime result closes the transition. A refusal is returned verbatim,
naming its own predicate, rather than being retried into a success.

A refusal is also recorded. A state transition is the disposition of an intended
action, not only a successful one: a submission that arrived and was refused is
a transition whose disposition is DENY, and `organization_scope_rule` makes no
exception for it. Every refusal path through `receive` -- an unresolvable
destination, a capability bound elsewhere, a crossing this manifest cannot
drive, a far side that refused, a boundary chain that does not reconstruct --
appends a repository receipt and the organization receipt that consumes it,
under `ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED`. Before this they returned a
refusal and wrote nothing, which made a held or retried submission
indistinguishable from one that never arrived.

`organization_receipt_observed` stays false on a refusal regardless. It means an
admitted crossing was observed, and a refusal receipt is not that; a caller
reading one as the other would treat a refused submission as a completed
transition. The refusal's own digests are returned under their own names.

Nothing here grants authority. The organization appends its own receipt, which
is its own runtime reality; it publishes its organization records to Master
Records separately and does not claim a Master Records organization record it
has not seen.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from stegverse.manifest_state_transition_runtime import (
    RESULT_SCHEMA,
    admit_runtime_result,
    derive_execution_request,
)

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = ROOT / "org-runtime/interlock-intr.json"

OPERATION_ID = "ORGANIZATION_SDK_MANIFEST_INGRESS"
OWNER_REPOSITORY = "StegVerse-org/.github"
PROFILE_ID = "sdk-manifest-ingress"
PROFILE_NAME = "SDK:ManifestIngress"
OPERATION = "SUBMIT_MANIFEST"
RESULT_SCHEMA_ORG = "stegverse.organization-manifest-ingress-result/v1"
REFUSAL_SCHEMA = "stegverse.organization-manifest-ingress-refusal-record/v1"
GOVERNANCE_REQUEST_SCHEMA = "stegverse.org-governance-decision-request/v1"

#: The intended action every submission carries, whatever its disposition.
#:
#: A state transition is the disposition of an intended action, not only a
#: successful one. `organization_scope_rule` is that every state transition
#: occurring within the organization emits an organization receipt, and a
#: refused submission is one: it arrived, it was dispositioned, and nothing
#: recorded it. Refusing and keeping no record makes a held or retried
#: submission indistinguishable from one that never arrived.
INTENDED_ACTION = "RECEIVE_A_SUBMITTED_SDK_MANIFEST"
REFUSED_CLASS = "ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED"
# The organization ledger is its own runtime reality locus, so replay of this
# transition terminates on this chain. That is the contract's own replay_rule,
# not a claim about any higher level.
ORGANIZATION_REPLAY = "PASS"


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


crossing_module = _module("sdk_manifest_crossing", "resident-runtime/sdk_manifest_crossing.py")
repository_ledger = _module("repo_transition_emit", ".stegverse/transition-ledger/emit.py")
organization_ledger = _module("aggregate_repo_transition",
                              "resident-runtime/aggregate_repo_transition.py")


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(value: Any) -> str:
    return hashlib.sha256(canon(value)).hexdigest()


def boundary() -> dict[str, Any]:
    """This organization's own Interlock/InTr boundary document."""
    return json.loads(BOUNDARY.read_text(encoding="utf-8"))


def submitted_capability(manifest: Any) -> dict[str, Any]:
    """What the submission itself declared it wanted processed, or nulls.

    Read defensively, because some refusals happen before the manifest is known
    to be well formed. A submission that declared nothing records nulls rather
    than being omitted: the distinction between "declared nothing" and "we did
    not record it" is the whole value of having the field.
    """
    processing = (manifest or {}).get("processing") if isinstance(manifest, Mapping) else None
    processing = processing if isinstance(processing, Mapping) else {}
    return {
        "submitted_processing_capability": processing.get("capability"),
        "submitted_route_id": processing.get("route_id"),
        "submitted_capability_is_as_declared_by_the_submission": True,
    }


def refusal_record(failed_predicate: str, detail: str,
                   manifest: Any) -> dict[str, Any]:
    """What a refused submission records.

    The manifest reaches the chain by digest only. Nothing an admitted crossing
    would have produced appears here -- no resolved service, no boundary receipt
    chain, no runtime result -- because the organization produced none, and a
    record naming them would read as a submission that was received.

    What a refusal *does* carry is which capability's receiving operation
    refused, and what the submission declared it wanted. Those are not things an
    admitted crossing produced -- the first is a constant of this operation and
    the second is the submitter's own declaration -- and without them a
    capability that only ever refuses is indistinguishable from one nothing has
    ever exercised. `destination_resolution_source` is deliberately *not* here:
    a refusal resolved no destination, and marking it as a record that did would
    put it in a population measured for target and scope fields it correctly
    lacks.
    """
    return {
        "schema": REFUSAL_SCHEMA,
        "receiving_operation": OPERATION_ID,
        "profile_id": PROFILE_ID,
        "operation": OPERATION,
        **submitted_capability(manifest),
        "intended_action": INTENDED_ACTION,
        "disposition": "DENY",
        "transition_is_the_disposition_of_the_intended_action": True,
        "failed_predicate": failed_predicate,
        "detail": detail,
        "refusal_is_verbatim": True,
        "submitted_manifest_sha256": "sha256:" + sha(
            dict(manifest) if isinstance(manifest, Mapping) else manifest),
        "received": False,
        "retry_is_a_transition_not_a_lost_signal": True,
        "authority_effect": "NONE_REFUSAL_RECORD_ONLY",
    }


def _record_refusal(record: Mapping[str, Any], hb_epoch: int | None) -> dict[str, Any]:
    """Append a refusal at both levels, in the order the replay rule requires.

    The repository ledger records it first and the organization ledger consumes
    that receipt, exactly as an admitted submission is recorded. One writer
    standing in for both levels would leave `preserves_repo_receipt` with
    nothing to preserve -- a refusal is not an exception to that.
    """
    predecessor = record["submitted_manifest_sha256"]
    successor = "sha256:" + sha(dict(record))
    repository_receipt = repository_ledger.append(
        "ORGANIZATION-SDK-MANIFEST-INGRESS-REFUSED-" + sha(dict(record))[:16],
        REFUSED_CLASS, predecessor, successor, dict(record), "NONE", hb_epoch=hb_epoch)
    organization_receipt = organization_ledger.append(
        repository_receipt, "REPO_STATE_PROPAGATION", predecessor, successor,
        {"receiving_operation": OPERATION_ID,
         "intended_action": INTENDED_ACTION,
         "disposition": "DENY",
         "failed_predicate": record["failed_predicate"]},
        "NONE", hb_epoch=hb_epoch)
    return {"repository_receipt": repository_receipt,
            "organization_receipt": organization_receipt}


def _refused(failed_predicate: str, detail: str, *, manifest: Any,
             hb_epoch: int | None = None, **extra: Any) -> dict[str, Any]:
    record = refusal_record(failed_predicate, detail, manifest)
    appended = _record_refusal(record, hb_epoch)
    return {
        "schema": RESULT_SCHEMA_ORG,
        "organization": "StegVerse-org",
        "receiving_operation": OPERATION_ID,
        "disposition": "FAIL_CLOSED",
        "received": False,
        "failed_predicate": failed_predicate,
        "detail": detail,
        # The refusal is recorded at both levels. `organization_receipt_observed`
        # stays false regardless: it means an admitted crossing was observed, and
        # a refusal receipt is not that. A caller reading it as one would treat a
        # refused submission as a completed transition.
        "organization_receipt_observed": False,
        "refusal_recorded": True,
        "refusal_transition_class": REFUSED_CLASS,
        "refusal_intended_action": INTENDED_ACTION,
        "refusal_repository_receipt_sha256":
            appended["repository_receipt"]["receipt_sha256"],
        "refusal_organization_receipt_sha256":
            appended["organization_receipt"]["receipt_sha256"],
        "authority_effect": "NONE_REFUSAL_ONLY",
        **extra,
    }


def bound_here(request: Mapping[str, Any]) -> dict[str, Any]:
    """Confirm the SDK resolved this capability to this operation, in this repository.

    The resolution comes back on the request. Reading it rather than assuming it
    means a manifest bound to another organization is refused here instead of
    being received by the wrong receiver.
    """
    resolution = request.get("manifest_declared_destination")
    if not isinstance(resolution, Mapping):
        raise ValueError("ORGANIZATION_INGRESS_RESOLUTION_ABSENT_FROM_REQUEST")
    if (resolution.get("profile_id"), resolution.get("profile_name"),
            resolution.get("operation")) != (PROFILE_ID, PROFILE_NAME, OPERATION):
        raise ValueError("ORGANIZATION_INGRESS_RESOLVED_A_DIFFERENT_CAPABILITY")
    receiving = resolution.get("receiving_operation")
    if not isinstance(receiving, Mapping):
        raise ValueError("ORGANIZATION_RECEIVING_OPERATION_ABSENT")
    if receiving.get("owner_repository") != OWNER_REPOSITORY:
        raise ValueError("ORGANIZATION_RECEIVING_OPERATION_OWNED_ELSEWHERE")
    if receiving.get("operation_id") != OPERATION_ID:
        raise ValueError("ORGANIZATION_RECEIVING_OPERATION_IS_NOT_THIS_ONE")
    return dict(receiving)


def reconstruct_closures(crossing: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Recompute every boundary receipt from its own subject, and chain them.

    The boundary reports `RECONSTRUCTED`. Repeating its computation here is what
    makes that reportable rather than merely asserted: each receipt's digest is
    recomputed from the packet, the service, the payload digest, its kind and
    its declared predecessor, and a receipt whose declared digest or id does not
    match what the subject produces fails the whole chain closed.
    """
    receipts = crossing.get("boundary_receipts")
    if not isinstance(receipts, list) or not receipts:
        raise ValueError("BOUNDARY_RECEIPT_CHAIN_ABSENT")
    base = {"packet_id": crossing["ingress_packet_id"],
            "service_id": crossing["resolved_service_id"],
            "payload_hash": crossing["payload_hash"]}
    closures: list[dict[str, Any]] = []
    previous_id: str | None = None
    previous_digest: str | None = None
    for receipt in receipts:
        kind = receipt.get("kind")
        if not isinstance(kind, str) or not kind:
            raise ValueError("BOUNDARY_RECEIPT_KIND_INVALID")
        if receipt.get("previous_receipt_id") != previous_id:
            raise ValueError("BOUNDARY_RECEIPT_CHAIN_PREDECESSOR_MISMATCH:" + kind)
        digest = sha({**base, "kind": kind, "previous_receipt_id": previous_id})
        if receipt.get("evidence_hash") != digest:
            raise ValueError("BOUNDARY_RECEIPT_RECONSTRUCTION_MISMATCH:" + kind)
        if receipt.get("receipt_id") != kind.lower() + "-" + digest[:24]:
            raise ValueError("BOUNDARY_RECEIPT_ID_NOT_DERIVED_FROM_ITS_EVIDENCE:" + kind)
        closure = {"transition_id": kind, "state": "RECORDED",
                   "reconstruction_status": "PASS",
                   "required_evidence_validation_status": "PASS",
                   "receipt_sha256": digest, "reconstructed_receipt_sha256": digest}
        if previous_digest is not None:
            closure["predecessor_receipt_sha256"] = previous_digest
        closures.append(closure)
        previous_id, previous_digest = receipt["receipt_id"], digest
    if previous_id != crossing.get("terminal_receipt_id"):
        raise ValueError("BOUNDARY_TERMINAL_RECEIPT_DOES_NOT_CLOSE_THE_CHAIN")
    return closures


def transition_evidence(request: Mapping[str, Any], crossing: Mapping[str, Any],
                        closures: list[dict[str, Any]]) -> dict[str, Any]:
    """What this ingress transition is evidenced by, inline.

    Replay reads these bytes rather than following a reference, because a
    reachability promise is not evidence.
    """
    return {
        "receiving_operation": OPERATION_ID,
        "profile_id": PROFILE_ID,
        "profile_name": PROFILE_NAME,
        "operation": OPERATION,
        "destination_resolution_source": request.get("destination_resolution_source"),
        "request_sha256": request["request_sha256"],
        "wire_manifest_sha256": request["wire_manifest_sha256"],
        "canonical_manifest_sha256": request["canonical_manifest_sha256"],
        "graph_id": request["graph_id"],
        "processing_capability": request["processing_capability"],
        "route_id": request["route_id"],
        "crossing": {key: value for key, value in crossing.items() if key != "egress"},
        "transition_closures": closures,
    }


def runtime_result(request: Mapping[str, Any], closures: list[dict[str, Any]],
                   organization_receipt: Mapping[str, Any],
                   decision: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """What this organization observed, in the shape the SDK validates.

    `manifest_receipt_id` is the organization receipt's own digest. The receipt
    is the organization's runtime reality, so the result is bound to the receipt
    that exists rather than to an identifier minted for the occasion.
    """
    return {
        "schema": RESULT_SCHEMA,
        "state": "COMPLETE",
        "canonical_manifest_sha256": request["canonical_manifest_sha256"],
        "graph_id": request["graph_id"],
        "canonical_task_id": request["canonical_task_id"],
        "processing_capability": request["processing_capability"],
        "route_id": request["route_id"],
        "resolved_ordered_transitions": [closure["transition_id"] for closure in closures],
        "transition_closures": closures,
        "replay_status": ORGANIZATION_REPLAY,
        "reconstruction_status": "PASS",
        "terminal_state": {"records_only": True, "continued_authority": False},
        "manifest_receipt_id": organization_receipt["receipt_sha256"],
        **governance_fields(request, decision),
    }


def governance_fields(request: Mapping[str, Any], decision: Mapping[str, Any] | None) -> dict[str, Any]:
    """The governance decision, in the shape the SDK admits, recorded in org records only.

    Only a governance request carries a decision. The disposition is the one the
    organization's governance endpoint returned; nothing here grades it.
    """
    if request.get("processing_capability") != "governance":
        return {}
    disposition = (decision or {}).get("disposition")
    if disposition not in {"ALLOW", "DENY", "FAIL_CLOSED"}:
        disposition = "FAIL_CLOSED"
    return {
        "disposition": disposition,
        "state": "COMPLETE" if disposition == "ALLOW" else disposition,
        "terminal": disposition != "ALLOW",
        "communication_terminal": False,
        "failed_predicate": None if disposition == "ALLOW" else (
            (decision or {}).get("reason") or "GOVERNANCE_DECISION_ABSENT"),
        "governance_decision": dict(decision) if decision else None,
        "request_sha256": request["request_sha256"],
        "wire_manifest_sha256": request["wire_manifest_sha256"],
        "records_authority": "ORGANIZATION_RECORDS_ONLY",
        "publisher_executed": False,
        "site_propagation_executed": False,
    }


def request_digest(value: Any) -> str:
    """A governance request's digest, in the encoding both organizations bind it with."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def governance_request_payload(request: Mapping[str, Any], decision_request: Mapping[str, Any],
                               transition_id: str) -> dict[str, Any]:
    """The work request that carries a governance request to the organization that decides it.

    `ecosystem.work.request` is answered with an acknowledgement, and the
    communication id is what the closure correlates on, so the crossing is
    closable by construction.
    """
    return {
        "communication_id": "governance:" + request["request_sha256"],
        "message_class": "ecosystem.work.request",
        "subject": "governance.decision",
        "requested_action": "DECIDE_GOVERNANCE_ADMISSIBILITY",
        "audience": "TARGET",
        "target_organization": decision_request["deciding_organization"],
        "target_count": 1,
        "body": {
            "schema": GOVERNANCE_REQUEST_SCHEMA,
            "origin_organization": "StegVerse-org",
            "sdk_request_sha256": request["request_sha256"],
            "canonical_manifest_sha256": request["canonical_manifest_sha256"],
            "ingress_transition_id": transition_id,
            "governance_request": decision_request["governance_request"],
            "governance_request_sha256": decision_request["governance_request_sha256"],
        },
    }


def request_governance_decision(request: Mapping[str, Any], crossing: Mapping[str, Any],
                                receiving: Mapping[str, Any], *, transition_id: str,
                                repository_receipt: Mapping[str, Any],
                                organization_receipt: Mapping[str, Any],
                                standing: Mapping[str, Any], mesh_root: Path | None,
                                hb_epoch: int | None) -> dict[str, Any]:
    """Emit the governance request to the organization that decides it, and record the emission.

    Nothing waits. The emission is a transition here, recorded at both levels by
    the egress boundary; the decision is a transition there; its return is a
    third, recorded here when it arrives. A receiver that is not running leaves
    the frame in the mesh, which is the durable queue.
    """
    decision_request = crossing.get("application_result") or {}
    base = {
        "schema": RESULT_SCHEMA_ORG,
        "organization": "StegVerse-org",
        "receiving_operation": OPERATION_ID,
        "received": True,
        "owner_repository": OWNER_REPOSITORY,
        "resolved_service_id": crossing["resolved_service_id"],
        "destination_resolution_source": request["destination_resolution_source"],
        "destination_resolution_environment_inputs": [],
        "receiving_operation_declared": dict(receiving),
        "request_sha256": request["request_sha256"],
        "canonical_manifest_sha256": request["canonical_manifest_sha256"],
        "processing_capability": request["processing_capability"],
        "route_id": request["route_id"],
        "intr_admission_observed": True,
        "far_side_transition_observed": True,
        "boundary_receipt_chain_reconstructed_independently": True,
        "organization_receipt_observed": True,
        "organization_receipt_sha256": organization_receipt["receipt_sha256"],
        "organization_transition_id": transition_id,
        "repository_receipt_observed": True,
        "repository_receipt_sha256": repository_receipt["receipt_sha256"],
        "records_authority": "ORGANIZATION_RECORDS_ONLY",
        "master_records_organization_record_observed": False,
    }
    if (decision_request.get("schema") != GOVERNANCE_REQUEST_SCHEMA
            or decision_request.get("governance_request_sha256") != request_digest(decision_request.get("governance_request"))):
        return {**base, "disposition": "FAIL_CLOSED",
                "failed_predicate": "GOVERNANCE_REQUEST_IS_BOUND_TO_THE_SUBMITTED_MANIFEST",
                "detail": "the governance processor returned no request bound to this manifest",
                "retry_entrypoint": "resident-runtime/organization_manifest_ingress.py::receive",
                "authority_effect": "NONE_REFUSAL_ONLY"}

    egress = _module("organization_egress_boundary", "resident-runtime/organization_egress_boundary.py")
    emitted = egress.emit(decision_request["deciding_organization"],
                          governance_request_payload(request, decision_request, transition_id),
                          standing=dict(standing), capability="governance",
                          transition_reference="ecosystem.transition.governance.v1",
                          mesh_root=mesh_root, hb_epoch=hb_epoch)
    emission = {key: emitted.get(key) for key in (
        "emission_transition_class", "emission_repository_receipt_sha256",
        "emission_organization_receipt_sha256")}
    if emitted["disposition"] != "ALLOW":
        # Recorded by the egress boundary as a refused emission. The ingress
        # transition stands; the request did not leave, and says why.
        return {**base, **emission, "disposition": "FAIL_CLOSED",
                "failed_predicate": emitted.get("failed_predicate"),
                "detail": emitted.get("detail"),
                "governance_decision_state": "REQUEST_NOT_EMITTED",
                "required_evidence_or_repair": (
                    "materialize this node with its federation mesh location"
                    if "mesh_location_required" in str(emitted.get("detail"))
                    else "satisfy the egress boundary's failed predicate: "
                         + str(emitted.get("failed_predicate"))),
                "retry_entrypoint": "resident-runtime/organization_manifest_ingress.py::receive",
                "authority_effect": "NONE_REFUSAL_ONLY"}
    return {**base, **emission,
            "disposition": "ALLOW",
            "governance_decision_state": "REQUESTED_OF_DECIDING_ORGANIZATION",
            "deciding_organization": emitted["destination_organization"],
            "deciding_service": emitted["destination_service"],
            "decision_authority": decision_request["decision_authority"],
            "decision_authority_repository": decision_request["decision_authority_repository"],
            "evaluator_imported_in_this_organization": False,
            "governance_request_packet_id": emitted["packet_id"],
            "governance_communication_id": emitted["communication_id"],
            "governance_request_sha256": decision_request["governance_request_sha256"],
            "awaits_the_decision": False,
            "receiver_unavailable_disposition": "DURABLE_QUEUE_OR_EVENT_EPHEMERAL_MATERIALIZATION",
            "sdk_admission": "AT_DECISION_RETURN",
            "decision_return_entrypoint": "resident-runtime/governance_decision_return.py::return_decision",
            "authority_effect": "NONE_RECEIVING_OPERATION_ONLY"}


def receive(manifest: Mapping[str, Any], *, registry: Mapping[str, Any], standing: Mapping[str, Any] | None = None,
            packet_id: str = "organization-sdk-manifest-ingress",
            hb_epoch: int | None = None, mesh_root: Path | None = None) -> dict[str, Any]:
    """Receive a submitted manifest on this organization's ingress operation.

    `mesh_root` is the federation mesh the node was materialized with. Only a
    capability another organization decides needs it: the request leaves on it.
    """
    refused = functools.partial(_refused, manifest=manifest, hb_epoch=hb_epoch)
    try:
        request = derive_execution_request(manifest, boundary())
    except ValueError as exc:
        return refused("ORGANIZATION_RESOLVES_ITS_OWN_INGRESS_DESTINATION", str(exc))
    try:
        receiving = bound_here(request)
    except ValueError as exc:
        return refused("CAPABILITY_IS_BOUND_TO_THIS_RECEIVING_OPERATION", str(exc),
                       request_sha256=request.get("request_sha256"))

    try:
        crossing = crossing_module.cross(manifest, registry=dict(registry), standing=standing, packet_id=packet_id)
    except SystemExit as exc:
        # The crossing refuses a manifest it cannot drive as declared -- no
        # egress, a non-InTr transport, an unresolvable surface, no declared
        # standing. Those are dispositions of this submission, so they are
        # recorded here rather than leaving the operation by exception with
        # nothing written.
        return refused("CROSSING_IS_DRIVABLE_FROM_THE_MANIFEST_AS_DECLARED", str(exc))
    if not crossing.get("crossing_completed"):
        # The far side refused. That is its disposition to state, not something
        # this operation rewrites into an admission -- but the submission still
        # arrived here, so the refusal is recorded.
        return refused("ADMITTED_CROSSING_REACHES_ITS_INTERNAL_ENDPOINT",
                       str(crossing.get("far_side_disposition")),
                       request_sha256=request["request_sha256"],
                       resolved_service_id=crossing.get("resolved_service_id"),
                       crossing=crossing)

    try:
        closures = reconstruct_closures(crossing)
    except ValueError as exc:
        return refused("BOUNDARY_RECEIPT_CHAIN_RECONSTRUCTS_INDEPENDENTLY", str(exc),
                       request_sha256=request["request_sha256"])

    # The transition occurred in this repository, so the repository ledger
    # records it first and the organization ledger consumes that receipt. The
    # organization authoring its own source receipt and then recording it as its
    # own was one writer standing in for two levels: it left
    # `preserves_repo_receipt` with nothing to preserve, and left organization
    # replay resting on a receipt the same call had just minted, when the
    # replay rule asks for verified repo receipts beneath the organization ones.
    transition_id = "ORGANIZATION-SDK-MANIFEST-INGRESS-" + request["request_sha256"][:16]
    predecessor_state = "sha256:" + request["canonical_manifest_sha256"]
    successor_state = "sha256:" + closures[-1]["receipt_sha256"]
    repository_receipt = repository_ledger.append(
        transition_id, "ORGANIZATION_SDK_MANIFEST_INGRESS",
        predecessor_state, successor_state,
        transition_evidence(request, crossing, closures),
        "NONE", hb_epoch=hb_epoch)
    organization_receipt = organization_ledger.append(
        repository_receipt, "REPO_STATE_PROPAGATION",
        predecessor_state, successor_state,
        {"receiving_operation": OPERATION_ID,
         "resolved_service_id": crossing["resolved_service_id"],
         "ingress_packet_id": crossing["ingress_packet_id"],
         "egress_packet_id": crossing["egress_packet_id"]},
        "NONE", hb_epoch=hb_epoch)

    # Governance is decided by the organization that owns StegCore. The ingress
    # transition above occurred here and is recorded; the request now leaves
    # through this organization's egress, and the SDK is handed the decision
    # when it returns, not before.
    if request.get("processing_capability") == "governance":
        return request_governance_decision(
            request, crossing, receiving, transition_id=transition_id,
            repository_receipt=repository_receipt, organization_receipt=organization_receipt,
            standing=crossing_module.manifest_standing(manifest, standing),
            mesh_root=mesh_root, hb_epoch=hb_epoch)

    # The SDK decides whether this closes the transition. Its refusal is the
    # answer, returned as it was given.
    try:
        admitted = admit_runtime_result(
            manifest, request, runtime_result(request, closures, organization_receipt,
                           crossing.get("application_result")))
    except ValueError as exc:
        return {
            "schema": RESULT_SCHEMA_ORG,
            "organization": "StegVerse-org",
            "receiving_operation": OPERATION_ID,
            "disposition": "FAIL_CLOSED",
            "received": True,
            "failed_predicate": "SDK_ADMITS_THE_ORGANIZATION_RUNTIME_RESULT",
            "detail": str(exc),
            # The receipt was appended before the SDK was asked. The organization
            # ledger is its own runtime reality authority, so a refusal upstream
            # does not unmake a transition that occurred here.
            "organization_receipt_observed": True,
            "organization_receipt_sha256": organization_receipt["receipt_sha256"],
            "repository_receipt_sha256": repository_receipt["receipt_sha256"],
            "request_sha256": request["request_sha256"],
            "authority_effect": "NONE_REFUSAL_ONLY",
        }

    return {
        "schema": RESULT_SCHEMA_ORG,
        "organization": "StegVerse-org",
        "receiving_operation": OPERATION_ID,
        "disposition": "ALLOW",
        "received": True,
        "owner_repository": OWNER_REPOSITORY,
        "resolved_service_id": crossing["resolved_service_id"],
        "destination_resolution_source": request["destination_resolution_source"],
        "destination_resolution_environment_inputs": [],
        "receiving_operation_declared": receiving,
        "request_sha256": request["request_sha256"],
        "canonical_manifest_sha256": request["canonical_manifest_sha256"],
        "processing_capability": request["processing_capability"],
        "route_id": request["route_id"],
        "intr_admission_observed": True,
        "far_side_transition_observed": True,
        "boundary_receipt_chain_reconstructed_independently": True,
        "transition_closures": closures,
        "organization_receipt_observed": True,
        "organization_receipt_sha256": organization_receipt["receipt_sha256"],
        "organization_transition_id": transition_id,
        # Both levels, so a reader can see the organization consumed a receipt
        # from the level below rather than one it wrote itself.
        "repository_receipt_observed": True,
        "repository_receipt_sha256": repository_receipt["receipt_sha256"],
        "repository": repository_receipt["repository"],
        "organization_receipt_preserves_repository_receipt":
            organization_receipt["repo_receipt_sha256"] == repository_receipt["receipt_sha256"],
        "replay_requires_only_verified_repo_and_organization_receipts": True,
        "sdk_admitted_result": admitted,
        # Organization records are published to Master Records separately and
        # are not awaited here:
        # `propagation_gates_organization_runtime_reality` is false and Master
        # Records `may_be_awaited_by_a_transition` is false.
        "master_records_organization_record_observed": False,
        "master_records_propagation_entrypoint":
            "resident-runtime/submit_org_transition_to_master_records.py",
        "authority_effect": "NONE_RECEIVING_OPERATION_ONLY",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Receive a submitted SDK manifest on this organization's ingress operation.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True,
                        help="materialized capability map supplied by the organization boundary")
    parser.add_argument("--standing", type=Path, default=None,
                        help="JSON declaring mode, node_ref and the predecessor key; "
                             "required unless the manifest declares its own chain position")
    parser.add_argument("--packet-id", default="organization-sdk-manifest-ingress")
    parser.add_argument("--hb-epoch", type=int, default=None,
                        help="heartbeat epoch; derived from the host clock, and marked as "
                             "derived, when absent")
    parser.add_argument("--mesh-root", type=Path, default=None,
                        help="federation mesh this node was materialized with; a governance "
                             "request leaves on it")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    result = receive(
        json.loads(args.manifest.read_text(encoding="utf-8")),
        registry=json.loads(args.registry.read_text(encoding="utf-8")),
        standing=(json.loads(args.standing.read_text(encoding="utf-8"))
                  if args.standing else None),
        packet_id=args.packet_id, hb_epoch=args.hb_epoch, mesh_root=args.mesh_root)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered)
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("transition_closures", "sdk_admitted_result", "crossing")},
                     sort_keys=True))
    return 0 if result.get("disposition") == "ALLOW" else 1


if __name__ == "__main__":
    sys.exit(main())
