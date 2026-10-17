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
a transition whose disposition is DENY or FAIL_CLOSED, and `organization_scope_rule` makes no
exception for it. Every refusal path through `receive` -- an unresolvable
destination, a capability bound elsewhere, a crossing this manifest cannot
drive, a far side that refused, a boundary chain that does not reconstruct --
appends a repository receipt and the organization receipt that consumes it,
under `ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED`. Before this they returned a
refusal and wrote nothing, which made a held or retried submission
indistinguishable from one that never arrived.

The disposition is set per failure_code (`REFUSAL_DISPOSITIONS`) and is the
same value stored and returned: DENY for a defect of the submission, FAIL_CLOSED
for an organization-side gap -- such as a state-transition route no service here
admits (D7) -- an epoch not supplied or invalid, or a far side that did not
complete. The six fields a refusing step carried -- the crossing's
own -- are passed through rather than overwritten.

`organization_receipt_observed` stays false on a refusal regardless. It means an
admitted crossing was observed, and a refusal receipt is not that; a caller
reading one as the other would treat a refused submission as a completed
transition. The refusal's own digests are returned under their own names.

A NON-ALLOW is that receipt, on both ledgers, exposed through the existing
ledger refs. When the manifest derived an execution request, the receipt is
also a disposition this organization delivers to StegHealer. The route is the
manifest-calculated one (`stegverse.remediation_fork.remediation_route`):
where the NON-ALLOW was recognized, the manifested path, and the direct InTr
leg. The delivery carries the six-field receipt and the manifest's packet
reference. It is not a remediation decision and not a classification request.
This organization does not consume a classification or a return. A NON-ALLOW
whose manifest derives no request has no route, so it stays the receipt and
is not emitted.

Nothing here grants authority. The organization appends its own receipt, which
is its own runtime reality; it publishes its organization records to Master
Records separately and does not claim a Master Records organization record it
has not seen.
"""
from __future__ import annotations

import argparse
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
from stegverse.route_resolution import route_from_manifest

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
#: What a route-related NON-ALLOW carries outbound. A disposition, not a
#: classification request and not a remediation decision.
DISPOSITION_SCHEMA = "stegverse.org-non-allow-disposition/v1"
DISPOSITION_BINDING_ROLE = "NON_ALLOW_DISPOSITION_DELIVERY"

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
#: The declaration every non-ALLOW answers to (docs/ORGANIZATION_ROLE_RUNTIME_REALITY_DEPLOYMENT.md).
OWNING_EXISTING_GOAL = "ORGANIZATION-ROLE-RUNTIME-REALITY-DEPLOYMENT-001"
# The organization ledger is its own runtime reality locus, so replay of this
# transition terminates on this chain. That is the contract's own replay_rule,
# not a claim about any higher level.
ORGANIZATION_REPLAY = "PASS"

#: The six fields every non-ALLOW carries.
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")

#: D7. A published route bound to the state-transition runtime is processed only
#: by a service whose `admits_processing` names the declared {capability,
#: route_id}. When none does, falling back to the `completion.egress` surface
#: hands the manifest to the service its result returns to, so the crossing is
#: refused before it is driven. Routes bound to another runtime
#: (`native_source_math`, `customer_local_governance`) keep the surface
#: fallback. The check lives here, not in the crossing: the crossing is
#: stdlib-only and the boundary holds no route table (manifest_selection.py).
STATE_TRANSITION_RUNTIME_BINDING = "stegverse.manifest_state_transition_runtime.execute_manifest"
PROCESSING_NOT_DECLARED_CODE = "PROCESSING_SERVICE_NOT_DECLARED_FOR_CONSUMER_ROUTE"
PROCESSING_NOT_DECLARED_PREDICATE = "CONSUMER_ROUTE_RESOLVES_TO_A_DECLARED_PROCESSING_SERVICE"
INTR_PROTOCOL_GOAL = "INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001"
#: The refusal disposition table, keyed on the composite (failure_code,
#: failed_predicate). Neither half is unique alone: two crossing codes share one
#: predicate, and every refusal raised by this operation itself carries the one
#: code ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED. The value is both what the
#: refusal record stores and what `receive` returns. DENY is a defect of the
#: submission; FAIL_CLOSED is an organization-side gap, an append that did not
#: commit, an epoch that was not supplied or is invalid, or a far side that did
#: not complete. A pair with no row is refused FAIL_CLOSED under
#: REFUSAL_DISPOSITION_NOT_DECLARED. The same table is in both forks' ingress
#: (StegVerse-org/.github and StegVerse-Labs/.github).
REFUSAL_DISPOSITION_NOT_DECLARED = "REFUSAL_DISPOSITION_NOT_DECLARED"
REFUSAL_DISPOSITIONS = {
    # organization-side configuration gaps
    (PROCESSING_NOT_DECLARED_CODE, PROCESSING_NOT_DECLARED_PREDICATE): "FAIL_CLOSED",
    (REFUSED_CLASS, "ORGANIZATION_RESOLVES_ITS_OWN_INGRESS_DESTINATION"): "FAIL_CLOSED",
    (REFUSED_CLASS, "BOUNDARY_RECEIPT_CHAIN_RECONSTRUCTS_INDEPENDENTLY"): "FAIL_CLOSED",
    ("CROSSING_REQUIRES_MATERIALIZED_CAPABILITY_MAP", "CROSSING_IS_GIVEN_A_MATERIALIZED_CAPABILITY_MAP"): "FAIL_CLOSED",
    ("ORG_EXPOSES_NO_SUCH_TRANSITION_SURFACE", "DECLARED_SURFACE_RESOLVES_TO_EXACTLY_ONE_SERVICE"): "FAIL_CLOSED",
    ("TRANSITION_SURFACE_AMBIGUOUS_IN_REGISTRY", "DECLARED_SURFACE_RESOLVES_TO_EXACTLY_ONE_SERVICE"): "FAIL_CLOSED",
    ("PROCESSING_AMBIGUOUS_IN_REGISTRY", "DECLARED_PROCESSING_PAIR_IS_ADMITTED_BY_AT_MOST_ONE_SERVICE"): "FAIL_CLOSED",
    # the supplied epoch (the shared HB_EPOCH codes; raised by PR-1b, not here)
    ("HB_EPOCH_NOT_SUPPLIED", "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH"): "FAIL_CLOSED",
    ("HB_EPOCH_INVALID", "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH"): "FAIL_CLOSED",
    # a far side that did not complete
    ("FAR_SIDE_RECEIVER_UNAVAILABLE", "RESOLVED_SERVICE_HAS_AN_INSTALLED_ENDPOINT_ADAPTER"): "FAIL_CLOSED",
    ("FAR_SIDE_REFUSED_THE_CROSSING", "ADMITTED_CROSSING_REACHES_ITS_INTERNAL_ENDPOINT"): "FAIL_CLOSED",
    # defects of the submission
    (REFUSED_CLASS, "CAPABILITY_IS_BOUND_TO_THIS_RECEIVING_OPERATION"): "DENY",
    (REFUSED_CLASS, "CROSSING_IS_DRIVABLE_FROM_THE_MANIFEST_AS_DECLARED"): "DENY",
    (REFUSED_CLASS, "ONE_TRANSITION_ID_BINDS_ONE_MANIFEST"): "DENY",
    ("MANIFEST_DECLARES_NO_EGRESS", "MANIFEST_DECLARES_COMPLETION_EGRESS"): "DENY",
    ("MANIFEST_DECLARES_NO_TRANSITION_SURFACE", "MANIFEST_DECLARES_A_FINAL_TRANSITION_SURFACE"): "DENY",
    ("MANIFEST_DECLARES_NON_INTR_TRANSPORT", "MANIFEST_DECLARES_INTERLOCK_INTR_TRANSPORT"): "DENY",
    ("MANIFEST_DECLARES_NO_FAR_SIDE_REQUIREMENT", "MANIFEST_DECLARES_FAR_SIDE_TRANSITION_REQUIREMENT"): "DENY",
    ("CROSSING_REQUIRES_DECLARED_STANDING", "CROSSING_STANDING_IS_DERIVED_FROM_THE_MANIFEST_OR_DECLARED"): "DENY",
    ("CROSSING_STANDING_MUST_DECLARE_THE_PREDECESSOR_KEY", "CROSSING_STANDING_DECLARES_THE_PREDECESSOR_KEY"): "DENY",
}


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
                   manifest: Any, six_fields: Mapping[str, Any] | None = None,
                   *, disposition: str | None = None) -> dict[str, Any]:
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

    The disposition is set per (failure_code, failed_predicate) pair
    (`REFUSAL_DISPOSITIONS`, via `declared_refusal`). Six
    fields passed through from the refusing step are stored with the record, so
    what is stored and what is returned name the same repair.
    """
    record = {
        "schema": REFUSAL_SCHEMA,
        "receiving_operation": OPERATION_ID,
        "profile_id": PROFILE_ID,
        "operation": OPERATION,
        **submitted_capability(manifest),
        "intended_action": INTENDED_ACTION,
        "disposition": disposition if disposition is not None else (
            declared_refusal(six_fields)[0] if six_fields
            else refusal_disposition(REFUSED_CLASS, failed_predicate) or "FAIL_CLOSED"),
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
    if six_fields:
        record.update(dict(six_fields))
    return record


def refusal_disposition(failure_code: Any, failed_predicate: Any) -> str | None:
    """The table's disposition for a (failure_code, failed_predicate) pair, or None when no row declares it."""
    return REFUSAL_DISPOSITIONS.get((failure_code, failed_predicate))


def declared_refusal(fields: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """The disposition of a six-field refusal, and the six fields it is stored and returned with.

    A pair the table declares keeps its fields as given. A pair it does not
    declare is refused FAIL_CLOSED under REFUSAL_DISPOSITION_NOT_DECLARED; the
    pair it arrived with is kept under `undeclared_refusal_*`, so the refusal is
    not renamed silently.
    """
    fields = {field: fields[field] for field in SIX_FIELDS}
    disposition = refusal_disposition(fields["failure_code"], fields["failed_predicate"])
    if disposition is not None:
        return disposition, fields
    return "FAIL_CLOSED", {
        **fields,
        "failure_code": REFUSAL_DISPOSITION_NOT_DECLARED,
        "required_evidence_or_repair": (
            "declare a REFUSAL_DISPOSITIONS row for (" + str(fields["failure_code"]) + ", "
            + str(fields["failed_predicate"]) + "); the refusal it names: "
            + str(fields["required_evidence_or_repair"])),
        "undeclared_refusal_failure_code": fields["failure_code"],
        "undeclared_refusal_failed_predicate": fields["failed_predicate"],
    }


def passed_through(source: Any) -> dict[str, Any] | None:
    """The six fields a refusing step carried, or None when it carried no complete set."""
    if not isinstance(source, Mapping):
        return None
    fields = {field: source.get(field) for field in SIX_FIELDS}
    if not all(isinstance(value, str) and value.strip() for value in fields.values()):
        return None
    return fields


def processing_service_precheck(manifest: Any, registry: Mapping[str, Any]) -> dict[str, Any] | None:
    """D7: the six fields when a state-transition route has no declared processing service.

    Returns None when the check does not apply: the manifest declares no
    processing pair, its route binds another runtime, or a service admits the
    pair. A route that does not resolve, or a registry that is ambiguous, is
    left to the crossing, which refuses it with its own six fields.
    """
    if not isinstance(manifest, Mapping):
        return None
    processing = manifest.get("processing")
    if not isinstance(processing, Mapping):
        return None
    capability, route_id = processing.get("capability"), processing.get("route_id")
    if not capability or not route_id:
        return None
    try:
        route = route_from_manifest(manifest)
    except ValueError:
        return None
    if route.get("runtime_binding") != STATE_TRANSITION_RUNTIME_BINDING:
        return None
    try:
        if crossing_module.processing_service(dict(manifest), dict(registry)) is not None:
            return None
    except SystemExit:
        return None
    pair = json.dumps({"capability": capability, "route_id": route_id}, sort_keys=True)
    return {
        "failure_code": PROCESSING_NOT_DECLARED_CODE,
        "failed_predicate": PROCESSING_NOT_DECLARED_PREDICATE,
        "detail": "route " + str(route_id) + " binds " + STATE_TRANSITION_RUNTIME_BINDING
                  + " and no service in this organization's registry admits " + pair
                  + "; the completion.egress surface is not used for processing",
        "required_evidence_or_repair": "add a service row whose admits_processing names " + pair
                                       + " in org-boundary/registry/services.json, with the route "
                                         "published in the SDK (route_resolution.PUBLISHED_ROUTES)",
        "retry_entrypoint": "the same manifest, resubmitted to stegverse-org.sdk-manifest-ingress "
                            "(resident-runtime/organization_manifest_ingress.py::receive)",
        "owning_existing_goal": INTR_PROTOCOL_GOAL,
        "next_attempt": "once the admits_processing row lands; the refusal is recorded and "
                        "nothing crossed",
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
        REFUSED_CLASS, predecessor, successor, dict(record), "NONE", hb_epoch=hb_epoch,
        idempotent_on=("failed_predicate", "detail"))
    # A refusal is identified by its own record, so the same refusal delivered
    # again returns the receipts already recorded rather than a second pair.
    organization_receipt = organization_ledger.append(
        repository_receipt, "REPO_STATE_PROPAGATION", predecessor, successor,
        {"receiving_operation": OPERATION_ID,
         "intended_action": INTENDED_ACTION,
         "disposition": record["disposition"],
         "failed_predicate": record["failed_predicate"]},
        "NONE", hb_epoch=repository_receipt["hb_reference"]["epoch"], idempotent=True)
    return {"repository_receipt": repository_receipt,
            "organization_receipt": organization_receipt}


def _refused(failed_predicate: str, detail: str, *, manifest: Any,
             hb_epoch: int | None = None, six_fields: Mapping[str, Any] | None = None,
             **extra: Any) -> dict[str, Any]:
    """Record and return a refusal.

    `six_fields`, when the refusing step carried them, are passed through as
    they were given rather than replaced by this operation's generic ones.
    """
    generic = {
        "failure_code": REFUSED_CLASS,
        "failed_predicate": failed_predicate,
        "required_evidence_or_repair": "satisfy the failed predicate (" + failed_predicate + ": " + detail
                                       + ") and resubmit the manifest",
        "retry_entrypoint": "resident-runtime/organization_manifest_ingress.py::receive",
        "owning_existing_goal": OWNING_EXISTING_GOAL,
        "next_attempt": "resubmit the same manifest once the predicate is satisfied; the refusal is "
                        "recorded and nothing was admitted",
    }
    disposition, fields = declared_refusal(six_fields if six_fields else generic)
    # A step's own six fields, and any refusal whose pair is not declared, are
    # stored with the record; a declared generic refusal is stored as before.
    stored_fields = fields if (six_fields or fields["failure_code"] != REFUSED_CLASS) else None
    record = refusal_record(failed_predicate, detail, manifest, stored_fields,
                            disposition=disposition)
    appended = _record_refusal(record, hb_epoch)
    return {
        "schema": RESULT_SCHEMA_ORG,
        "organization": "StegVerse-org",
        "receiving_operation": OPERATION_ID,
        # The returned disposition is the stored one (REFUSAL_DISPOSITIONS).
        "disposition": record["disposition"],
        "received": False,
        # Every non-ALLOW carries the six fields a caller needs to repair and
        # retry (docs/ORGANIZATION_ROLE_RUNTIME_REALITY_DEPLOYMENT.md).
        **fields,
        "detail": detail,
        "refusal_stored_disposition": record["disposition"],
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


def canonical_manifest_json(manifest: Mapping[str, Any]) -> str:
    """The submitted manifest as canonical JSON, the form retained at ingress."""
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def transition_evidence(request: Mapping[str, Any], crossing: Mapping[str, Any],
                        closures: list[dict[str, Any]],
                        manifest: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """What this ingress transition is evidenced by, inline.

    Replay reads these bytes rather than following a reference, because a
    reachability promise is not evidence. The canonical manifest itself is
    retained too: a governance decision returns after this transition, and the
    return is admitted against the exact manifest that was received, which the
    digests alone cannot reproduce.
    """
    evidence = {
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
    if manifest is not None:
        evidence["canonical_manifest_json"] = canonical_manifest_json(manifest)
    return evidence


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
        # The deciding organization selects processing only from an admitted
        # capability bound to its route, never from the address it was sent to,
        # so the request carries the manifest's own declaration.
        "processing": {"capability": request["processing_capability"],
                       "route_id": request["route_id"]},
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
                                hb_epoch: int | None, replayed: bool = False) -> dict[str, Any]:
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
        "transition_replayed": replayed,
        "repository_receipt_observed": True,
        "repository_receipt_sha256": repository_receipt["receipt_sha256"],
        "records_authority": "ORGANIZATION_RECORDS_ONLY",
        "master_records_organization_record_observed": False,
    }
    if (decision_request.get("schema") != GOVERNANCE_REQUEST_SCHEMA
            or decision_request.get("governance_request_sha256") != request_digest(decision_request.get("governance_request"))):
        return {**base, "disposition": "FAIL_CLOSED",
                "failure_code": "GOVERNANCE_REQUEST_UNBOUND",
                "failed_predicate": "GOVERNANCE_REQUEST_IS_BOUND_TO_THE_SUBMITTED_MANIFEST",
                "detail": "the governance processor returned no request bound to this manifest",
                "required_evidence_or_repair": "a governance processor result carrying "
                                               "stegverse_governance_request bound to this manifest's digest",
                "retry_entrypoint": "resident-runtime/organization_manifest_ingress.py::receive",
                "owning_existing_goal": OWNING_EXISTING_GOAL,
                "next_attempt": "resubmit the same manifest once the processor binds its request; "
                                "nothing was emitted",
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
                "failure_code": "GOVERNANCE_REQUEST_NOT_EMITTED",
                "failed_predicate": emitted.get("failed_predicate"),
                "detail": emitted.get("detail"),
                "governance_decision_state": "REQUEST_NOT_EMITTED",
                "required_evidence_or_repair": egress.refusal_repair(
                    emitted.get("failed_predicate"), emitted.get("detail")),
                "retry_entrypoint": "resident-runtime/organization_manifest_ingress.py::receive",
                "owning_existing_goal": OWNING_EXISTING_GOAL,
                "next_attempt": "resubmit the same manifest once the repair is in place; the ingress "
                                "transition is recorded and the request did not leave",
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


def _disposition_binding() -> dict[str, Any]:
    """The overlay binding that carries a NON-ALLOW disposition, not a decision."""
    matches = [entry for entry in boundary()["egress"]["capability_destination_bindings"]
               if isinstance(entry, dict)
               and entry.get("binding_role") == DISPOSITION_BINDING_ROLE
               and str(entry.get("route_source") or "").startswith("MANIFEST_CALCULATED")]
    if len(matches) != 1:
        raise ValueError("NON_ALLOW_DISPOSITION_BINDING_ABSENT")
    return matches[0]


def _deliver_non_allow_disposition(result: Mapping[str, Any], request: Mapping[str, Any], *,
                                   manifest: Any, standing: Mapping[str, Any] | None,
                                   mesh_root: Path | None, hb_epoch: int | None,
                                   packet_id: str) -> dict[str, Any]:
    """Deliver a route-related NON-ALLOW on the route the manifest calculates.

    `remediation_route` is that calculation: the recognition location, the
    manifested path, and the direct InTr leg to StegHealer. This organization
    emits the egress hop that route names. It does not choose a destination,
    decide remediation, or read a classification back.
    """
    from stegverse.remediation_fork import remediation_route

    recorded = dict(result)
    recorded["classification_consumed"] = False
    recorded["expects_a_classification"] = False
    recorded["remediation_decision_made_here"] = False
    destination = request.get("manifest_declared_destination")
    if not isinstance(destination, Mapping):
        return {**recorded, "disposition_delivered": False,
                "disposition_delivery": "NO_MANIFESTED_DESTINATION"}
    non_allow = {
        "disposition": recorded["disposition"],
        "organization": recorded["organization"],
        "evaluation_boundary": OPERATION_ID,
        "request_sha256": request.get("request_sha256"),
        "failure_code": recorded.get("failure_code"),
        "failed_predicate": recorded.get("failed_predicate"),
    }
    try:
        route = remediation_route(
            non_allow,
            original_route_id=str(request.get("route_id") or ""),
            original_processing_capability=str(request.get("processing_capability") or ""),
            original_destination=destination)
        binding = _disposition_binding()
    except ValueError as exc:
        return {**recorded, "disposition_delivered": False,
                "disposition_delivery": str(exc)}
    hops = route.get("direct_route_to_steghealer") or []
    egress_hops = [hop for hop in hops
                   if hop.get("crossing") == "INTERLOCK_INTR_EGRESS"
                   and hop.get("from") == recorded["organization"]]
    internal = [hop for hop in hops if hop.get("crossing") == "INTERNAL_ENDPOINT"]
    if len(egress_hops) != 1 or len(internal) != 1:
        return {**recorded, "disposition_delivered": False,
                "disposition_route_sha256": route.get("route_sha256"),
                "disposition_delivery": "CALCULATED_ROUTE_HAS_NO_EGRESS_FROM_HERE"}
    next_organization = egress_hops[0]["to"]
    route_service = internal[0]["to"]
    if internal[0].get("from") != next_organization:
        return {**recorded, "disposition_delivered": False,
                "disposition_route_sha256": route.get("route_sha256"),
                "disposition_delivery": "CALCULATED_ROUTE_HAS_NO_EGRESS_FROM_HERE"}
    egress = _module("organization_egress_boundary", "resident-runtime/organization_egress_boundary.py")
    addressed = egress.peer_capability_service(next_organization, binding.get("profile_id"))
    agrees = (binding.get("route_must_agree_with_this_binding") is True
              and binding.get("destination_organization") == next_organization
              and binding.get("destination_service") == route_service
              and addressed == route_service
              and binding.get("request_schema") == DISPOSITION_SCHEMA
              and binding.get("expects_a_classification") is False
              and binding.get("consumes_a_return") is False)
    if not agrees:
        return {**recorded, "disposition_delivered": False,
                "disposition_route_sha256": route.get("route_sha256"),
                "disposition_delivery": "CALCULATED_ROUTE_DOES_NOT_AGREE_WITH_THE_BINDING"}
    payload = {
        "communication_id": "non-allow-disposition:" + str(request.get("request_sha256")),
        "message_class": binding.get("request_message_class"),
        "subject": "non-allow.disposition",
        "requested_action": "DELIVER_NON_ALLOW_DISPOSITION",
        "audience": "TARGET",
        "target_organization": next_organization,
        "target_count": 1,
        "body": {
            "schema": DISPOSITION_SCHEMA,
            "origin_organization": recorded["organization"],
            "delivery": "NON_ALLOW_DISPOSITION",
            "disposition": recorded.get("disposition"),
            "failure_code": recorded.get("failure_code"),
            "failed_predicate": recorded.get("failed_predicate"),
            "required_evidence_or_repair": recorded.get("required_evidence_or_repair"),
            "retry_entrypoint": recorded.get("retry_entrypoint"),
            "owning_existing_goal": recorded.get("owning_existing_goal"),
            "next_attempt": recorded.get("next_attempt"),
            "receipt": {
                "repository_receipt_sha256": recorded.get("refusal_repository_receipt_sha256"),
                "organization_receipt_sha256": recorded.get("refusal_organization_receipt_sha256"),
            },
            "manifest_reference": {
                "submitted_manifest_sha256": "sha256:" + sha(
                    dict(manifest) if isinstance(manifest, Mapping) else manifest),
                "request_sha256": request.get("request_sha256"),
                "wire_manifest_sha256": request.get("wire_manifest_sha256"),
                "canonical_manifest_sha256": request.get("canonical_manifest_sha256"),
                "data_packet_id": packet_id,
            },
            "route": route,
            "route_sha256": route.get("route_sha256"),
            "route_source": binding.get("route_source"),
            "classification_requested": False,
            "expects_a_classification": False,
            "remediation_decision_made_here": False,
        },
    }
    emitted = egress.emit(next_organization, payload,
                          standing=dict(standing) if isinstance(standing, Mapping) else standing,
                          capability=binding.get("profile_id"),
                          transition_reference="ecosystem.transition.non-allow-disposition.v1",
                          mesh_root=mesh_root, hb_epoch=hb_epoch)
    emission = {key: emitted.get(key) for key in (
        "emission_transition_class", "emission_repository_receipt_sha256",
        "emission_organization_receipt_sha256")}
    return {**recorded, **emission,
            "disposition_delivered": emitted.get("disposition") == "ALLOW",
            "disposition_route_sha256": route.get("route_sha256"),
            "disposition_destination_organization": emitted.get("destination_organization"),
            "disposition_destination_service": emitted.get("destination_service"),
            "disposition_packet_id": emitted.get("packet_id"),
            "disposition_communication_id": emitted.get("communication_id"),
            "classification_consumed": False}


def receive(manifest: Mapping[str, Any], *, registry: Mapping[str, Any], standing: Mapping[str, Any] | None = None,
            packet_id: str = "organization-sdk-manifest-ingress",
            hb_epoch: int | None = None, mesh_root: Path | None = None) -> dict[str, Any]:
    """Receive a submitted manifest on this organization's ingress operation.

    `mesh_root` is the federation mesh the node was materialized with. A
    governance request leaves on it. A route-related NON-ALLOW leaves on it
    too, as a disposition delivery on the manifest-calculated route. A
    NON-ALLOW with no derivable request is recorded here and is not emitted.
    """
    request: dict[str, Any] | None = None
    submitted_epoch = hb_epoch

    def refused(failed_predicate: str, detail: str,
                six_fields: Mapping[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
        # Every NON-ALLOW is a six-field receipt on both ledgers. A route-related
        # one, a manifest that derived a request, is then delivered on the
        # route that request calculates. No request means no route, and the
        # receipt is the whole record.
        recorded = _refused(failed_predicate, detail, manifest=manifest,
                            hb_epoch=submitted_epoch, six_fields=six_fields, **extra)
        if request is None:
            return recorded
        return _deliver_non_allow_disposition(
            recorded, request, manifest=manifest, standing=standing,
            mesh_root=mesh_root, hb_epoch=submitted_epoch, packet_id=packet_id)

    try:
        request = derive_execution_request(manifest, boundary())
    except ValueError as exc:
        return refused("ORGANIZATION_RESOLVES_ITS_OWN_INGRESS_DESTINATION", str(exc))
    try:
        receiving = bound_here(request)
    except ValueError as exc:
        return refused("CAPABILITY_IS_BOUND_TO_THIS_RECEIVING_OPERATION", str(exc),
                       request_sha256=request.get("request_sha256"))

    # D7: a state-transition route with no declared processing service fails
    # closed here, before the crossing could fall back to the egress surface.
    precheck = processing_service_precheck(manifest, registry)
    if precheck is not None:
        return refused(precheck["failed_predicate"], precheck["detail"], six_fields=precheck,
                       request_sha256=request["request_sha256"])

    try:
        crossing = crossing_module.cross(manifest, registry=dict(registry), standing=standing, packet_id=packet_id)
    except SystemExit as exc:
        # The crossing refuses a manifest it cannot drive as declared -- no
        # egress, a non-InTr transport, an unresolvable surface, no declared
        # standing. Those are dispositions of this submission, so they are
        # recorded here rather than leaving the operation by exception with
        # nothing written. The crossing's own six fields are passed through;
        # only a refusal that carried none takes this operation's predicate.
        carried = passed_through(getattr(exc, "refusal", None))
        if carried is not None:
            return refused(carried["failed_predicate"], str(exc), six_fields=carried)
        return refused("CROSSING_IS_DRIVABLE_FROM_THE_MANIFEST_AS_DECLARED", str(exc))
    if not crossing.get("crossing_completed"):
        # The far side refused. That is its disposition to state, not something
        # this operation rewrites into an admission -- but the submission still
        # arrived here, so the refusal is recorded, with the crossing's six fields.
        carried = passed_through(crossing)
        return refused(carried["failed_predicate"] if carried
                       else "ADMITTED_CROSSING_REACHES_ITS_INTERNAL_ENDPOINT",
                       str(crossing.get("far_side_disposition")), six_fields=carried,
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
    #
    # The transition id is derived from the request, so one manifest is one
    # transition however many times it is delivered. A delivery the chain
    # already records returns the recorded receipts instead of minting more:
    # identity is the id, the canonical manifest it starts from and the full
    # request digest; the same id over anything else is a collision. A run that
    # recorded the repository receipt and stopped before the organization
    # receipt is completed here, from the retained repository receipt, rather
    # than recorded twice.
    chain = repository_ledger.ledger_store.open_store(repository_ledger.lr())
    # The successor state is the last closure of the crossing that carried the
    # manifest, and a redelivery is carried again: another packet, another
    # closure. The repository ledger compares the successor on every exact
    # retry, so a redelivery of the request already recorded names the
    # successor that delivery recorded rather than its own carrier's. A
    # different request under this id keeps its own successor and collides.
    # The lookup is read again after a collision once, because a concurrent
    # delivery of the same request may have recorded it in between.
    evidence = transition_evidence(request, crossing, closures, manifest)
    for resolution in range(2):
        prior = repository_ledger.recorded(
            chain, chain.get(repository_ledger.ledger_store.HEAD_KEY),
            transition_id, OPERATION_ID)
        replayed = prior is not None
        if replayed and (prior.get("evidence") or {}).get("request_sha256") == request["request_sha256"]:
            successor_state = prior["successor_state_sha256"]
        try:
            repository_receipt = repository_ledger.append(
                transition_id, OPERATION_ID,
                predecessor_state, successor_state, evidence,
                "NONE", hb_epoch=hb_epoch, idempotent_on=("request_sha256",))
            break
        except ValueError as exc:
            if str(exc) != "ledger_receipt_collision":
                raise
            if resolution:
                return refused("ONE_TRANSITION_ID_BINDS_ONE_MANIFEST", str(exc),
                               request_sha256=request["request_sha256"])
    # Everything after the repository receipt takes its epoch from that receipt,
    # so a replay rebuilds the same organization receipt and the same outbound
    # frame rather than ones stamped with whatever epoch this attempt carried.
    hb_epoch = repository_receipt["hb_reference"]["epoch"]
    organization_receipt = organization_ledger.append(
        repository_receipt, "REPO_STATE_PROPAGATION",
        predecessor_state, successor_state,
        {"receiving_operation": OPERATION_ID,
         "resolved_service_id": crossing["resolved_service_id"],
         "ingress_packet_id": crossing["ingress_packet_id"],
         "egress_packet_id": crossing["egress_packet_id"]},
        "NONE", hb_epoch=hb_epoch, idempotent=True)

    # Governance is decided by the organization that owns StegCore. The ingress
    # transition above occurred here and is recorded; the request now leaves
    # through this organization's egress, and the SDK is handed the decision
    # when it returns, not before.
    if request.get("processing_capability") == "governance":
        return request_governance_decision(
            request, crossing, receiving, transition_id=transition_id,
            repository_receipt=repository_receipt, organization_receipt=organization_receipt,
            standing=crossing_module.manifest_standing(manifest, standing),
            mesh_root=mesh_root, hb_epoch=hb_epoch, replayed=replayed)

    # The SDK decides whether this closes the transition. Its refusal is the
    # answer, returned as it was given. A NON-ALLOW stays the receipt already
    # written above. This organization does not build or receive a remediation fork.
    try:
        admitted = admit_runtime_result(
            manifest, request, runtime_result(request, closures, organization_receipt,
                           crossing.get("application_result")), boundary())
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
        "transition_replayed": replayed,
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
