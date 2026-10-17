#!/usr/bin/env python3
"""``ORGANIZATION_INTR_DESTINATION_INGRESS`` -- acknowledge a purpose-neutral diagnostic.

``intr-destination`` is the capability every organization can advertise so a
peer can address it without a purpose-specific route. Governance stays a
purpose route, bound to the organization that owns the decider. A
route-related NON-ALLOW is a disposition delivered on the manifest-calculated
InTr route, not a classification request and not a route this diagnostic
binds. This operation is the mesh primitive underneath purpose routes: a
diagnostic crossing arrives, both ledger levels record the disposition, and
the disposition is transition evidence only. Authority and time stay
constraint variables. This operation does not touch governance or
remediation routing.

The payload is an ``ecosystem.communication``. That is a request class the
transport profile answers, and it carries the ``communication_id`` a closure
correlates on, so an outbound diagnostic can be emitted and closed. The body
schema is ``stegverse.org-intr-destination-diagnostic/v1``. A body that is not
that schema is a refusal, recorded, not an acknowledgement.

The profile name ``InTr:Destination`` is local to this binding. The pinned SDK
baseline does not declare the profile, and the canonical StegOS connector
registry was not readable from the change that added it, so this repository
does not claim StegOS already named it.

``closure`` is the diagnostic self-closure. It addresses this organization's
own intr-destination, derived as ``organization_slug + "." + profile_id``, and
records the acknowledgement on the repository ledger and the organization
ledger. Both receipts carry the ``communication_id``. No peer is named and
``federation.json`` is not read. A ``workflow_dispatch`` of
``.github/workflows/organization-ledger-transition.yml`` runs that closure
against the designated ledger ref, publishes the ref fast-forward only, and
reads the receipts back from a fresh fetch.

Authority and time are constraint variables. The address did not select a
processor, standing was already required at ingress, and this operation does
not re-decide either. The disposition is transition evidence only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]

OPERATION_ID = "ORGANIZATION_INTR_DESTINATION_INGRESS"
REFUSED_CLASS = "ORGANIZATION_INTR_DESTINATION_INGRESS_REFUSED"
OWNER_REPOSITORY = "StegVerse-org/.github"
PROFILE_ID = "intr-destination"
PROFILE_NAME = "InTr:Destination"
OPERATION = "DIAGNOSTIC_CROSSING"
PAYLOAD_SCHEMA = "stegverse.org-intr-destination-diagnostic/v1"
RESULT_SCHEMA = "stegverse.org-intr-destination-result/v1"
COMMUNICATION_CLASS = "ecosystem.communication"
ALLOW = "ALLOW"
DENY = "DENY"
FAIL_CLOSED = "FAIL_CLOSED"
ACK_EFFECT = "NONE_DIAGNOSTIC_ACK_ONLY"
REFUSAL_EFFECT = "NONE_REFUSAL_ONLY"
CLOSURE_SCHEMA = "stegverse.org-intr-destination-self-closure/v1"
CLOSURE_RETRY = "resident-runtime/intr_destination_ingress.py::closure"
CLOSURE_GOAL = "LLMA-DECLARED-PATH-CONFORMANCE-368"
CONSTRAINT = "CONSTRAINT_VARIABLE"
DISPOSITION_ROLE = "TRANSITION_EVIDENCE_ONLY"
CONSTRAINT_FIELDS = {
    "routing_authority_constraint": CONSTRAINT,
    "admission_authority_constraint": CONSTRAINT,
    "execution_authority_constraint": CONSTRAINT,
    "time_constraint": CONSTRAINT,
    "disposition_role": DISPOSITION_ROLE,
}


class SelfClosureRefused(Exception):
    """A self-closure that stopped before it could be recorded."""

    def __init__(self, failed_predicate: str, detail: str) -> None:
        super().__init__(failed_predicate + ": " + detail)
        self.failed_predicate = failed_predicate
        self.detail = detail


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


repository_ledger = _module("repo_transition_emit", ".stegverse/transition-ledger/emit.py")
organization_ledger = _module("aggregate_repo_transition",
                              "resident-runtime/aggregate_repo_transition.py")


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canon(value)).hexdigest()


def payload_sha(payload: Any) -> str:
    if isinstance(payload, Mapping):
        return sha(dict(payload))
    return sha(payload)


def shape_refusal(payload: Any) -> tuple[str, str] | None:
    """Why this payload is not a diagnostic this operation acknowledges."""
    if not isinstance(payload, Mapping):
        return ("SUBMISSION_IS_AN_ECOSYSTEM_COMMUNICATION", "payload is not an object")
    if payload.get("message_class") != COMMUNICATION_CLASS:
        return ("SUBMISSION_DECLARES_A_RESPONDED_REQUEST_CLASS",
                str(payload.get("message_class")))
    identifier = payload.get("communication_id")
    if not isinstance(identifier, str) or not identifier.strip():
        return ("SUBMISSION_CARRIES_THE_COMMUNICATION_ID_CLOSURE_CORRELATES_ON",
                repr(identifier))
    body = payload.get("body")
    observed = body.get("schema") if isinstance(body, Mapping) else body
    if not isinstance(body, Mapping) or observed != PAYLOAD_SCHEMA:
        return ("SUBMISSION_BODY_DECLARES_THE_BOUND_PAYLOAD_SCHEMA", str(observed))
    return None


def _evidence(payload: Any, packet_id: str, disposition: str, *,
              failed_predicate: str | None = None, detail: str | None = None) -> dict[str, Any]:
    communication_id = payload.get("communication_id") if isinstance(payload, Mapping) else None
    effect = ACK_EFFECT if disposition == ALLOW else REFUSAL_EFFECT
    record: dict[str, Any] = {
        "profile_id": PROFILE_ID,
        "profile_name": PROFILE_NAME,
        "operation": OPERATION,
        "receiving_operation": OPERATION_ID,
        "owner_repository": OWNER_REPOSITORY,
        "packet_id": packet_id,
        "communication_id": communication_id if isinstance(communication_id, str) else None,
        "payload_sha256": payload_sha(payload),
        "payload_schema": PAYLOAD_SCHEMA,
        "disposition": disposition,
        "authority_effect": effect,
        **CONSTRAINT_FIELDS,
        "selects_processing": False,
        "purpose_specific_route": False,
        "standing_rechecked_here": False,
    }
    if failed_predicate is not None:
        record["failed_predicate"] = failed_predicate
        record["detail"] = detail
    return record


def _result(evidence: Mapping[str, Any], appended: Mapping[str, Any] | None, *,
            replayed: bool, received: bool) -> dict[str, Any]:
    disposition = evidence["disposition"]
    acknowledged = disposition == ALLOW and received
    result = {
        "schema": RESULT_SCHEMA,
        "organization": organization_ledger.C["organization"],
        "receiving_operation": OPERATION_ID,
        "owner_repository": OWNER_REPOSITORY,
        "profile_id": PROFILE_ID,
        "profile_name": PROFILE_NAME,
        "operation": OPERATION,
        "disposition": disposition,
        "received": received,
        "communication_acknowledged": acknowledged,
        "communication_id": evidence.get("communication_id"),
        "payload_schema": PAYLOAD_SCHEMA,
        "payload_sha256": evidence["payload_sha256"],
        "transition_replayed": replayed,
        "standing_rechecked_here": False,
        "selects_processing": False,
        "purpose_specific_route": False,
        **CONSTRAINT_FIELDS,
        "authority_effect": evidence["authority_effect"],
    }
    if evidence.get("failed_predicate") is not None:
        result["failed_predicate"] = evidence["failed_predicate"]
        result["detail"] = evidence.get("detail")
    if appended is None:
        result["repository_receipt_observed"] = False
        result["organization_receipt_observed"] = False
        result["refusal_recorded"] = False
        return result
    repository_receipt = appended["repository_receipt"]
    organization_receipt = appended["organization_receipt"]
    result.update({
        "repository_receipt_observed": True,
        "organization_receipt_observed": True,
        "repository_receipt_sha256": repository_receipt["receipt_sha256"],
        "organization_receipt_sha256": organization_receipt["receipt_sha256"],
        "organization_receipt_preserves_repository_receipt":
            organization_receipt["repo_receipt_sha256"] == repository_receipt["receipt_sha256"],
        "refusal_recorded": disposition != ALLOW,
    })
    return result


def _append(transition_class: str, packet_id: str, evidence: Mapping[str, Any],
            hb_epoch: int | None) -> tuple[dict[str, Any], bool]:
    """Append at both levels. A replay of the same packet returns the recorded pair."""
    predecessor = evidence["payload_sha256"]
    successor = sha({"disposition": evidence["disposition"], "packet_id": packet_id,
                     "communication_id": evidence.get("communication_id"),
                     "payload_sha256": evidence["payload_sha256"]})
    transition_id = transition_class + ":" + packet_id
    store = repository_ledger.ledger_store.open_store(repository_ledger.lr())
    head = store.get(repository_ledger.ledger_store.HEAD_KEY)
    prior = repository_ledger.recorded(store, head, transition_id, transition_class)
    repository_receipt = repository_ledger.append(
        transition_id, transition_class, predecessor, successor, dict(evidence),
        "NONE", hb_epoch=hb_epoch,
        idempotent_on=("communication_id", "payload_sha256", "disposition"))
    # The organization receipt takes the repository receipt's epoch, so a replay
    # rebuilds the same organization receipt rather than one stamped later.
    epoch = repository_receipt["hb_reference"]["epoch"]
    organization_receipt = organization_ledger.append(
        repository_receipt, "REPO_STATE_PROPAGATION", predecessor, successor,
        {"operation": OPERATION_ID, "profile_id": PROFILE_ID,
         "disposition": evidence["disposition"],
         "communication_id": evidence.get("communication_id")},
        "NONE", hb_epoch=epoch, idempotent=True)
    return ({"repository_receipt": repository_receipt,
             "organization_receipt": organization_receipt}, prior is not None)


def _recorded(disposition: str, payload: Any, packet_id: str, hb_epoch: int | None, *,
              failed_predicate: str | None = None, detail: str | None = None) -> dict[str, Any]:
    evidence = _evidence(payload, packet_id, disposition,
                         failed_predicate=failed_predicate, detail=detail)
    transition_class = OPERATION_ID if disposition == ALLOW else REFUSED_CLASS
    try:
        appended, replayed = _append(transition_class, packet_id, evidence, hb_epoch)
    except ValueError as exc:
        if str(exc) != "ledger_receipt_collision":
            raise
        # The packet id already bound a different diagnostic. The recorded
        # transition stands; this attempt is not a second one.
        collided = _evidence(payload, packet_id, FAIL_CLOSED,
                             failed_predicate="ONE_PACKET_ID_BINDS_ONE_DIAGNOSTIC",
                             detail=str(exc))
        return _result(collided, None, replayed=False, received=False)
    return _result(evidence, appended, replayed=replayed, received=disposition == ALLOW)


def receive(payload: Any, *, registry: Mapping[str, Any], standing: Mapping[str, Any] | None = None,
            packet_id: str = "organization-intr-destination",
            hb_epoch: int | None = None, mesh_root: Path | None = None) -> dict[str, Any]:
    """Acknowledge one diagnostic, or record the refusal.

    ``standing`` and ``mesh_root`` are accepted because the capability resolver
    passes them to every receiving operation. Standing was required at ingress.
    A diagnostic does not leave, so the mesh is not used.
    """
    del standing, mesh_root
    if not isinstance(registry, Mapping):
        return _recorded(DENY, payload, packet_id, hb_epoch,
                         failed_predicate="CAPABILITY_MAP_IS_A_MAPPING",
                         detail="registry is not an object")
    refusal = shape_refusal(payload)
    if refusal is not None:
        return _recorded(DENY, payload, packet_id, hb_epoch,
                         failed_predicate=refusal[0], detail=refusal[1])
    return _recorded(ALLOW, payload, packet_id, hb_epoch)


def _organization_slug(organization: str) -> str:
    """Same derivation as the kernel's ``organization_slug``."""
    kernel = _module("org_kernel_intr_destination", "org-kernel/kernel.py")
    return kernel.organization_slug(organization)


def _token(value: Any, failed_predicate: str) -> str:
    if (not isinstance(value, str) or not value
            or any(ord(character) <= 32 or ord(character) > 126 for character in value)):
        raise SelfClosureRefused(
            failed_predicate,
            "expected one line of printable characters with no spaces")
    return value


def _served_address(registry: Mapping[str, Any]) -> str:
    """This organization's intr-destination address, derived from its own name.

    The registry must already serve that address. Peers are not consulted.
    """
    if not isinstance(registry, Mapping):
        raise SelfClosureRefused("CAPABILITY_MAP_IS_A_MAPPING", "registry is not an object")
    organization = registry.get("organization")
    if organization != organization_ledger.C["organization"]:
        raise SelfClosureRefused(
            "REGISTRY_IS_THIS_ORGANIZATION",
            str(organization))
    if not isinstance(organization, str):
        raise SelfClosureRefused("REGISTRY_IS_THIS_ORGANIZATION", str(organization))
    address = _organization_slug(organization) + "." + PROFILE_ID
    services = registry.get("services")
    served = isinstance(services, list) and any(
        isinstance(row, Mapping) and row.get("service_id") == address
        and row.get("capability_profile_id") == PROFILE_ID for row in services)
    if not served:
        raise SelfClosureRefused(
            "THIS_ORGANIZATION_SERVES_INTR_DESTINATION", address)
    return address


def _closure_payload(communication_id: str, addressed_service: str) -> dict[str, Any]:
    return {
        "message_class": COMMUNICATION_CLASS,
        "communication_id": communication_id,
        "subject": "purpose-neutral intr-destination diagnostic self-closure",
        "body": {
            "schema": PAYLOAD_SCHEMA,
            "probe": "diagnostic-self-closure",
            "addressed_service": addressed_service,
        },
    }


def _closure_result(address: str, communication_id: str, packet_id: str,
                    recorded: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "schema": CLOSURE_SCHEMA,
        "organization": organization_ledger.C["organization"],
        "receiving_operation": OPERATION_ID,
        "owner_repository": OWNER_REPOSITORY,
        "profile_id": PROFILE_ID,
        "profile_name": PROFILE_NAME,
        "operation": OPERATION,
        "self_closure": True,
        "addressed_service": address,
        "peer_enumerated": False,
        "communication_id": communication_id,
        "packet_id": packet_id,
        "disposition": recorded.get("disposition"),
        "received": recorded.get("received"),
        "communication_acknowledged": recorded.get("communication_acknowledged"),
        "transition_replayed": recorded.get("transition_replayed"),
        "payload_sha256": recorded.get("payload_sha256"),
        "repository_receipt_sha256": recorded.get("repository_receipt_sha256"),
        "organization_receipt_sha256": recorded.get("organization_receipt_sha256"),
        "authority_effect": recorded.get("authority_effect"),
        "selects_processing": False,
        "purpose_specific_route": False,
        "standing_rechecked_here": False,
        **CONSTRAINT_FIELDS,
    }
    if recorded.get("failed_predicate") is not None:
        result["failed_predicate"] = recorded["failed_predicate"]
        result["detail"] = recorded.get("detail")
    return result


def closure(communication_id: Any, *, registry: Mapping[str, Any], packet_id: Any,
            hb_epoch: int | None = None) -> dict[str, Any]:
    """Acknowledge a diagnostic this organization addresses to itself.

    The destination is this organization's served intr-destination. Both ledger
    levels append, and both receipts carry ``communication_id``. An existing
    chain is extended: the predecessor link is the published HEAD, and an empty
    chain is not reopened over receipts that are already there.
    """
    address = _served_address(registry)
    communication_id = _token(communication_id, "COMMUNICATION_ID_REQUIRED")
    packet_id = _token(packet_id, "PACKET_ID_REQUIRED")
    recorded = receive(_closure_payload(communication_id, address), registry=registry,
                       packet_id=packet_id, hb_epoch=hb_epoch)
    return _closure_result(address, communication_id, packet_id, recorded)


def closure_refusal(exc: SelfClosureRefused, location: str | None = None) -> dict[str, Any]:
    """A refusal that stopped the closure. Nothing in this document was appended by it."""
    return {
        "schema": CLOSURE_SCHEMA,
        "organization": organization_ledger.C["organization"],
        "location": location,
        "disposition": FAIL_CLOSED,
        "failure_code": "INTR_DESTINATION_SELF_CLOSURE_REFUSED",
        "failed_predicate": exc.failed_predicate,
        "required_evidence_or_repair": exc.detail,
        "retry_entrypoint": CLOSURE_RETRY,
        "owning_existing_goal": CLOSURE_GOAL,
        "next_attempt": "correct the closure input and run it again; a published chain is left as it was",
        "self_closure": True,
        "peer_enumerated": False,
        "authority_effect": REFUSAL_EFFECT,
        **CONSTRAINT_FIELDS,
    }


def verify_closure(location: str, closure_result: Mapping[str, Any], *,
                   repository_namespace: str) -> dict[str, Any]:
    """Read the ledger back and require this closure's receipts on that chain.

    The chain walk is ``organization_ledger_readback``. This checks that the
    closure's repository and organization receipts are on the verified chains
    and that both carry ``communication_id``. It reports what that location
    holds. It does not assert anything about a receipt that was not read back
    from ``location``.
    """
    if closure_result.get("disposition") != ALLOW:
        raise SelfClosureRefused(
            "SELF_CLOSURE_DISPOSITION_IS_ALLOW", str(closure_result.get("disposition")))
    communication_id = closure_result.get("communication_id")
    org_digest = closure_result.get("organization_receipt_sha256")
    repo_digest = closure_result.get("repository_receipt_sha256")
    if not all(isinstance(value, str) and value
               for value in (communication_id, org_digest, repo_digest)):
        raise SelfClosureRefused(
            "SELF_CLOSURE_NAMES_BOTH_RECEIPTS_AND_COMMUNICATION_ID",
            "communication_id, organization_receipt_sha256, repository_receipt_sha256")
    readback_mod = _module("organization_ledger_readback_closure",
                           "resident-runtime/organization_ledger_readback.py")
    try:
        verified = readback_mod.readback(location)
    except readback_mod.ReadbackRefused as exc:
        raise SelfClosureRefused(exc.failed_predicate, exc.detail) from None
    if not any(item["receipt_sha256"] == org_digest for item in verified["chain"]):
        raise SelfClosureRefused(
            "SELF_CLOSURE_ORGANIZATION_RECEIPT_IS_IN_THE_CHAIN", str(org_digest))
    locator = organization_ledger.parse_locator(location)
    org_store = organization_ledger.open_store(locator)
    org_receipt = org_store.get(organization_ledger.receipt_key(org_digest)) or {}
    boundary = org_receipt.get("boundary_evidence") or {}
    if boundary.get("communication_id") != communication_id:
        raise SelfClosureRefused(
            "ORGANIZATION_RECEIPT_CARRIES_THE_COMMUNICATION_ID", str(communication_id))
    if org_receipt.get("repo_receipt_sha256") != repo_digest:
        raise SelfClosureRefused(
            "ORGANIZATION_RECEIPT_PRESERVES_THE_REPOSITORY_RECEIPT", str(repo_digest))
    previous = org_receipt.get("previous_receipt_sha256")
    if previous is not None and not any(item["receipt_sha256"] == previous
                                        for item in verified["chain"]):
        raise SelfClosureRefused(
            "SELF_CLOSURE_EXTENDS_THE_PUBLISHED_CHAIN", str(previous))
    try:
        repository = readback_mod.repository_readback(location, repository_namespace, verified)
    except readback_mod.ReadbackRefused as exc:
        raise SelfClosureRefused(exc.failed_predicate, exc.detail) from None
    if not any(item["receipt_sha256"] == repo_digest for item in repository["chain"]):
        raise SelfClosureRefused(
            "SELF_CLOSURE_REPOSITORY_RECEIPT_IS_IN_THE_CHAIN", str(repo_digest))
    repo_store = organization_ledger.open_store(
        organization_ledger.parse_locator(str(locator) + ":" + repository_namespace))
    repo_receipt = repo_store.get(organization_ledger.receipt_key(repo_digest)) or {}
    if (repo_receipt.get("evidence") or {}).get("communication_id") != communication_id:
        raise SelfClosureRefused(
            "REPOSITORY_RECEIPT_CARRIES_THE_COMMUNICATION_ID", str(communication_id))
    verified = dict(verified)
    verified.update({
        "repository_ledger": repository,
        "self_closure_communication_id": communication_id,
        "self_closure_organization_receipt_sha256": org_digest,
        "self_closure_repository_receipt_sha256": repo_digest,
        "self_closure_receipts_in_chain": True,
        "communication_id_on_organization_receipt": True,
        "communication_id_on_repository_receipt": True,
        "self_closure_extends_published_chain": True,
        "authority_effect": "NONE_READBACK_ONLY",
    })
    return verified


def _emit(result: Mapping[str, Any], out: Path | None) -> None:
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--packet-id", default=None)
    parser.add_argument("--hb-epoch", type=int, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--self-close", action="store_true",
                        help="append an intr-destination diagnostic self-closure")
    parser.add_argument("--communication-id")
    parser.add_argument("--verify-self-closure", action="store_true",
                        help="read a self-closure back from a ledger location")
    parser.add_argument("--location", help="ledger locator, e.g. git+<repo>#<ref>")
    parser.add_argument("--repository-namespace")
    parser.add_argument("--closure", type=Path, help="closure result JSON to read back")
    args = parser.parse_args()
    try:
        if args.verify_self_closure:
            if not args.location or not args.repository_namespace or args.closure is None:
                raise SelfClosureRefused(
                    "SELF_CLOSURE_READBACK_INPUTS_PRESENT",
                    "--location, --repository-namespace, and --closure are required")
            result = verify_closure(
                args.location,
                json.loads(args.closure.read_text(encoding="utf-8")),
                repository_namespace=args.repository_namespace)
            code = 0
        elif args.self_close:
            if args.registry is None:
                raise SelfClosureRefused("REGISTRY_REQUIRED", "--registry is required")
            result = closure(
                args.communication_id,
                registry=json.loads(args.registry.read_text(encoding="utf-8")),
                packet_id=args.packet_id, hb_epoch=args.hb_epoch)
            code = 0 if result.get("disposition") == ALLOW else 1
        else:
            if args.payload is None or args.registry is None:
                raise SelfClosureRefused(
                    "PAYLOAD_AND_REGISTRY_REQUIRED", "--payload and --registry are required")
            result = receive(
                json.loads(args.payload.read_text(encoding="utf-8")),
                registry=json.loads(args.registry.read_text(encoding="utf-8")),
                packet_id=args.packet_id or "organization-intr-destination",
                hb_epoch=args.hb_epoch)
            code = 0 if result.get("disposition") == ALLOW else 1
    except SelfClosureRefused as exc:
        result = closure_refusal(exc, args.location)
        code = 1
    _emit(result, args.out)
    return code


if __name__ == "__main__":
    sys.exit(main())
