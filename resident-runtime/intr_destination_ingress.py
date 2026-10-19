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
import inspect
import json
import re
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
    """A self-closure that stopped before it could be recorded.

    `failure_code` is the refusal's own code when it has one (a readback
    refusal, e.g. ORGANIZATION_LEDGER_HEAD_ABSENT); otherwise the closure's
    INTR_DESTINATION_SELF_CLOSURE_REFUSED.
    """

    def __init__(self, failed_predicate: str, detail: str, failure_code: str | None = None) -> None:
        super().__init__(failed_predicate + ": " + detail)
        self.failed_predicate = failed_predicate
        self.detail = detail
        self.failure_code = failure_code


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


repository_ledger = _module("repo_transition_emit", ".stegverse/transition-ledger/emit.py")
organization_ledger = _module("aggregate_repo_transition",
                              "resident-runtime/aggregate_repo_transition.py")

INTR_PROTOCOL_GOAL = "INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001"


#: P1 interface (#163): where the ledger writers load from and where their
#: contracts resolve. Both default to this checkout, which is today's
#: behaviour. A consumer that carries this operation without carrying the
#: writers names them with `--ledger-component <path>` (a root holding
#: `.stegverse/transition-ledger/emit.py` and
#: `resident-runtime/aggregate_repo_transition.py`) and the root its contracts
#: live in with `--consumer-root <path>` (a root holding
#: `.stegverse/transition-ledger/contract.json` and `org-contract.json`). The
#: ledger *locations* stay STEGVERSE_REPO_LEDGER_ROOT / STEGVERSE_ORG_LEDGER_ROOT.
#: A path that is given and does not hold those files fails closed.
LEDGER_COMPONENT_PATH_INVALID = "LEDGER_COMPONENT_PATH_INVALID"
CONSUMER_ROOT_PATH_INVALID = "CONSUMER_ROOT_PATH_INVALID"
LEDGER_COMPONENT_FILES = (".stegverse/transition-ledger/emit.py",
                          "resident-runtime/aggregate_repo_transition.py")
#: The flat layout of the shared ledger component (as in
#: org-kernel/organization-ledger/): the same two writers as siblings. Either
#: layout is accepted for --ledger-component.
LEDGER_COMPONENT_FLAT_FILES = ("emit.py", "aggregate_repo_transition.py")
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
LEDGER_COMPONENT_LAYOUTS = (" and ".join(LEDGER_COMPONENT_FILES)
                            + ", or as siblings " + " and ".join(LEDGER_COMPONENT_FLAT_FILES),)
CONSUMER_ROOT_FILES = (".stegverse/transition-ledger/contract.json",
                       ".stegverse/transition-ledger/org-contract.json")
#: The org contract the ledger readback is given (--org-contract), by default
#: under the consumer root (--consumer-root) or this checkout.
ORG_CONTRACT_RELATIVE = CONSUMER_ROOT_FILES[1]
ORG_CONTRACT_PATH_INVALID = "ORG_CONTRACT_PATH_INVALID"
#: The readback the bound ledger component carries, if it carries one (flat:
#: a sibling of emit.py; nested: where this checkout keeps it). Otherwise
#: this checkout's readback reads the ledger back.
READBACK_FILES = {"FLAT": "organization_ledger_readback.py",
                  "NESTED": "resident-runtime/organization_ledger_readback.py"}
#: An empty ledger: the readback finds no HEAD.
LEDGER_HEAD_PRESENT = "ORGANIZATION_LEDGER_HEAD_PRESENT"
LEDGER_HEAD_ABSENT = "ORGANIZATION_LEDGER_HEAD_ABSENT"
#: Where the bound writers came from (bind_ledger_writers); None is this checkout.
LEDGER_BINDING: dict[str, Any] = {"component": None, "layout": "NESTED", "consumer_root": None}


class LedgerPathRefused(SystemExit):
    """A FAIL_CLOSED refusal of a given ledger path; `.refusal` carries the six fields."""

    def __init__(self, refusal: Mapping[str, Any]):
        super().__init__(refusal["failure_code"] + ":" + refusal["detail"])
        self.refusal = dict(refusal)


def _ledger_path_refusal(code: str, predicate: str, option: str, path: Any,
                         required: tuple[str, ...], entrypoint: str, goal: str) -> LedgerPathRefused:
    return LedgerPathRefused({
        "disposition": "FAIL_CLOSED",
        "failure_code": code,
        "failed_predicate": predicate,
        "detail": option + " " + str(path) + " does not hold " + ", ".join(required),
        "required_evidence_or_repair": (
            "give " + option + " a directory holding " + ", ".join(required)
            + ", or omit it to use this checkout"),
        "retry_entrypoint": entrypoint,
        "owning_existing_goal": goal,
        "next_attempt": "run again with a valid " + option + "; nothing was loaded or appended",
    })


def ledger_writer_refusal(exc: SystemExit, entrypoint: str,
                          goal: str) -> tuple[dict[str, Any], bool] | None:
    """A ledger writer's refusal and whether it carried its own record, or None.

    The ledger component's LedgerRefusal (ledger_common.py, flat next to
    emit.py) subclasses SystemExit and carries its refusal as `.refusal`, a
    dict: that is returned as given, (refusal, True), and printed unchanged.
    An old-layout writer raises a plain SystemExit(message): only when it
    came out of a ledger writer call itself (`_ledger_write`, which marks it
    LedgerWriterExit) is the message given the six fields here, FAIL_CLOSED,
    (fields, False). Any other SystemExit -- an int or None code, or a message
    from anything but a writer call (e.g. repository-receipt-failed) -- is not
    a ledger refusal (None) and is re-raised by the caller.
    """
    refusal = getattr(exc, "refusal", None)
    if isinstance(refusal, dict):
        return refusal, True
    if not isinstance(exc, LedgerWriterExit) or not isinstance(exc.code, str):
        return None
    message = exc.code
    head = message.split(":", 1)[0].strip()
    code = head if re.fullmatch(r"[A-Z][A-Z0-9_]*", head) else "LEDGER_WRITER_REFUSED"
    return {
        "disposition": "FAIL_CLOSED",
        "failure_code": code,
        "failed_predicate": "LEDGER_WRITER_ADMITS_THE_APPEND",
        "detail": message,
        "required_evidence_or_repair": "repair what the ledger writer refused (" + message + ") and run again",
        "retry_entrypoint": entrypoint,
        "owning_existing_goal": goal,
        "next_attempt": "run again once the ledger writer's refusal is repaired; nothing was written",
    }, False


class LedgerWriterExit(SystemExit):
    """A plain SystemExit(message) that a ledger writer call itself raised (old layout)."""


def _ledger_write(call: Any, *args: Any, **kwargs: Any) -> Any:
    """Run one ledger writer call; a plain SystemExit(message) from it is marked as the writer's.

    Only a plain SystemExit is marked. A LedgerRefusal (it carries
    `.refusal`), the writer's other SystemExit subclasses (e.g.
    OrgLedgerAppendRefused) and an exit with no message pass through unchanged.
    """
    try:
        return call(*args, **kwargs)
    except SystemExit as exc:
        if type(exc) is not SystemExit or not isinstance(exc.code, str):
            raise
        raise LedgerWriterExit(exc.code) from exc


def cli_hb_epoch(text: str | None, entrypoint: str,
                 goal: str) -> tuple[int | None, dict[str, Any] | None]:
    """--hb-epoch as typed, checked by the shared rule: (epoch, None) or (None, refusal).

    argparse hands over the raw text (type=str), so the shared validator
    (supplied_epoch_failure, the egress boundary's copy) sees it uncoerced:
    '+33', ' 33' and '3_3' are HB_EPOCH_INVALID, and '0033' is 33. An absent
    --hb-epoch stays None, as before.
    """
    if text is None:
        return None, None
    rule = _module("organization_egress_boundary_cli_epoch",
                   "resident-runtime/organization_egress_boundary.py").supplied_epoch_failure
    failure = rule(text)
    if failure is None:
        return int(text), None  # admitted as ASCII digits
    code, detail = failure
    return None, {
        "disposition": "FAIL_CLOSED",
        "failure_code": code,
        "failed_predicate": "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH",
        "detail": detail,
        "required_evidence_or_repair": ("pass --hb-epoch as the carrier supplied it: ASCII digits "
                                        "with value >= 32"),
        "retry_entrypoint": entrypoint,
        "owning_existing_goal": goal,
        "next_attempt": "run again with the supplied epoch; nothing was received or appended",
    }


def bind_ledger_writers(ledger_component: Path | str | None = None,
                        consumer_root: Path | str | None = None) -> dict[str, Any]:
    """Load the ledger writers from `ledger_component`, their contracts from `consumer_root`.

    Either left None keeps this checkout. Both are checked before anything is
    loaded, so a refused path leaves the writers already bound in place.
    """
    global repository_ledger, organization_ledger
    entrypoint = "resident-runtime/intr_destination_ingress.py (--ledger-component, --consumer-root)"
    component = Path(ledger_component).expanduser().resolve() if ledger_component is not None else None
    consumer = Path(consumer_root).expanduser().resolve() if consumer_root is not None else None
    layout = (None if component is None
              else LEDGER_COMPONENT_FILES if all((component / name).is_file() for name in LEDGER_COMPONENT_FILES)
              else LEDGER_COMPONENT_FLAT_FILES
              if all((component / name).is_file() for name in LEDGER_COMPONENT_FLAT_FILES)
              else ())
    if component is not None and not layout:
        raise _ledger_path_refusal(LEDGER_COMPONENT_PATH_INVALID, "LEDGER_COMPONENT_PATH_HOLDS_THE_LEDGER_WRITERS",
                                   "--ledger-component", ledger_component, LEDGER_COMPONENT_LAYOUTS,
                                   entrypoint, INTR_PROTOCOL_GOAL)
    if consumer is not None and not all((consumer / name).is_file() for name in CONSUMER_ROOT_FILES):
        raise _ledger_path_refusal(CONSUMER_ROOT_PATH_INVALID, "CONSUMER_ROOT_PATH_HOLDS_THE_LEDGER_CONTRACTS",
                                   "--consumer-root", consumer_root, CONSUMER_ROOT_FILES,
                                   entrypoint, INTR_PROTOCOL_GOAL)
    try:
        contracts = ({name: json.loads((consumer / name).read_text(encoding="utf-8"))
                      for name in CONSUMER_ROOT_FILES} if consumer is not None else None)
    except ValueError as exc:
        raise _ledger_path_refusal(CONSUMER_ROOT_PATH_INVALID, "CONSUMER_ROOT_PATH_HOLDS_THE_LEDGER_CONTRACTS",
                                   "--consumer-root", str(consumer_root) + " (" + str(exc) + ")",
                                   CONSUMER_ROOT_FILES, entrypoint, INTR_PROTOCOL_GOAL) from None
    base = component if component is not None else ROOT
    files = layout or LEDGER_COMPONENT_FILES
    repository = _module_at("repo_transition_emit_bound", base / files[0])
    organization = _module_at("aggregate_repo_transition_bound", base / files[1])
    if contracts is not None:
        repository.ROOT, repository.C = consumer, contracts[CONSUMER_ROOT_FILES[0]]
        organization.ROOT, organization.C = consumer, contracts[CONSUMER_ROOT_FILES[1]]
    repository_ledger, organization_ledger = repository, organization
    LEDGER_BINDING.update({"component": component,
                           "layout": "FLAT" if files == LEDGER_COMPONENT_FLAT_FILES else "NESTED",
                           "consumer_root": consumer})
    return {"ledger_component": str(base), "consumer_root": str(consumer if consumer is not None else ROOT),
            "ledger_component_is_this_checkout": component is None,
            "ledger_component_layout": "FLAT" if files == LEDGER_COMPONENT_FLAT_FILES else "NESTED",
            "consumer_root_is_this_checkout": consumer is None}


def _module_at(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


_LEDGER_GITSTORE: Any = None


def _two_level_atomic():
    """resident-runtime/ledger_gitstore.py two_level_atomic: both halves' locations are resolved and
    checked before either is written, and a failure after the repository half rolls its ref back."""
    global _LEDGER_GITSTORE
    if _LEDGER_GITSTORE is None:
        _LEDGER_GITSTORE = _module("ledger_gitstore_for_intr_destination_ingress", "resident-runtime/ledger_gitstore.py")
    return _LEDGER_GITSTORE.two_level_atomic(ROOT, surface=_LEDGER_GITSTORE.BoundSurface(emit=repository_ledger, aggregate=organization_ledger))


def _append(transition_class: str, packet_id: str, evidence: Mapping[str, Any],
            hb_epoch: int | None, *, operation: str = OPERATION_ID, profile_id: str = PROFILE_ID,
            boundary_extra: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
    """Append at both levels, all or nothing (see _two_level_atomic); a refusal of either
    location raises ledger_gitstore.TwoLevelAppendRefused (a ValueError) before any write."""
    with _two_level_atomic():
        return _append_halves(transition_class, packet_id, evidence, hb_epoch, operation=operation,
                              profile_id=profile_id, boundary_extra=boundary_extra)


def _append_halves(transition_class: str, packet_id: str, evidence: Mapping[str, Any],
                   hb_epoch: int | None, *, operation: str = OPERATION_ID, profile_id: str = PROFILE_ID,
                   boundary_extra: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
    """Append at both levels. A replay of the same packet returns the recorded pair.

    ``operation``, ``profile_id`` and ``boundary_extra`` name another operation
    on the same two-level append (resident-runtime/merge_transfer.py); their
    defaults are this ingress, so its receipts are unchanged."""
    predecessor = evidence["payload_sha256"]
    successor = sha({"disposition": evidence["disposition"], "packet_id": packet_id,
                     "communication_id": evidence.get("communication_id"),
                     "payload_sha256": evidence["payload_sha256"]})
    transition_id = transition_class + ":" + packet_id
    store = repository_ledger.ledger_store.open_store(repository_ledger.lr())
    head = store.get(repository_ledger.ledger_store.HEAD_KEY)
    prior = _ledger_write(repository_ledger.recorded, store, head, transition_id, transition_class)
    repository_receipt = _ledger_write(repository_ledger.append,
        transition_id, transition_class, predecessor, successor, dict(evidence),
        "NONE", hb_epoch=hb_epoch,
        idempotent_on=("communication_id", "payload_sha256", "disposition"))
    # The organization receipt takes the repository receipt's epoch, so a replay
    # rebuilds the same organization receipt rather than one stamped later.
    epoch = repository_receipt["hb_reference"]["epoch"]
    organization_receipt = _ledger_write(organization_ledger.append,
        repository_receipt, "REPO_STATE_PROPAGATION", predecessor, successor,
        {"operation": operation, "profile_id": profile_id,
         "disposition": evidence["disposition"],
         "communication_id": evidence.get("communication_id"), **dict(boundary_extra or {})},
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
        "failure_code": getattr(exc, "failure_code", None) or "INTR_DESTINATION_SELF_CLOSURE_REFUSED",
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


def default_org_contract_path() -> Path:
    """<consumer root, or this checkout>/.stegverse/transition-ledger/org-contract.json."""
    return (LEDGER_BINDING["consumer_root"] or ROOT) / ORG_CONTRACT_RELATIVE


def load_org_contract(path: Path | str | None = None) -> tuple[dict[str, Any], Path]:
    """The org contract the readback is given, and where it was read (default above)."""
    resolved = Path(path).expanduser().resolve() if path is not None else default_org_contract_path()
    try:
        contract = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SelfClosureRefused("ORG_CONTRACT_IS_A_READABLE_JSON_OBJECT",
                                 "--org-contract " + str(resolved) + ": " + str(exc),
                                 ORG_CONTRACT_PATH_INVALID) from None
    if not isinstance(contract, dict):
        raise SelfClosureRefused("ORG_CONTRACT_IS_A_READABLE_JSON_OBJECT",
                                 "--org-contract " + str(resolved) + " is not a JSON object",
                                 ORG_CONTRACT_PATH_INVALID)
    return contract, resolved


def readback_module():
    """The bound ledger component's readback when it carries one, else this checkout's."""
    component = LEDGER_BINDING["component"]
    if component is not None:
        carried = component / READBACK_FILES[LEDGER_BINDING["layout"]]
        if carried.is_file():
            return _module_at("organization_ledger_readback_bound", carried)
    return _module("organization_ledger_readback_closure",
                   "resident-runtime/organization_ledger_readback.py")


def _given(function: Any, **context: Any) -> dict[str, Any]:
    """The readback context (org_contract, repository_namespace) this readback declares it takes."""
    parameters = inspect.signature(function).parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return context
    return {name: value for name, value in context.items() if name in parameters}


def _readback_refusal(exc: Any) -> SelfClosureRefused:
    """A readback refusal, keeping its own code; an empty ledger is ORGANIZATION_LEDGER_HEAD_ABSENT."""
    code = getattr(exc, "failure_code", None)
    if not code and exc.failed_predicate == LEDGER_HEAD_PRESENT:
        code = LEDGER_HEAD_ABSENT
    return SelfClosureRefused(exc.failed_predicate, exc.detail, code or None)


def verify_closure(location: str, closure_result: Mapping[str, Any], *,
                   repository_namespace: str,
                   org_contract: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Read the ledger back and require this closure's receipts on that chain.

    The readback is given the org contract (default: load_org_contract()) and
    the repository namespace: a ledger that declares a legacy segment is read
    with its namespace, and without its contract a readback cannot tell what
    the ledger declares. The chain walk is ``organization_ledger_readback``
    (the bound component's, when it carries one). This checks that the
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
    contract_path = None
    if org_contract is None:
        org_contract, contract_path = load_org_contract()
    context = {"org_contract": dict(org_contract), "repository_namespace": repository_namespace}
    readback_mod = readback_module()
    try:
        verified = readback_mod.readback(location, **_given(readback_mod.readback, **context))
    except readback_mod.ReadbackRefused as exc:
        raise _readback_refusal(exc) from None
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
        repository = readback_mod.repository_readback(
            location, repository_namespace, verified,
            **_given(readback_mod.repository_readback, org_contract=context["org_contract"]))
    except readback_mod.ReadbackRefused as exc:
        raise _readback_refusal(exc) from None
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
        "readback_repository_namespace": repository_namespace,
        "readback_org_contract": str(contract_path) if contract_path is not None else "GIVEN",
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
    parser.add_argument("--hb-epoch", type=str, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--self-close", action="store_true",
                        help="append an intr-destination diagnostic self-closure")
    parser.add_argument("--communication-id")
    parser.add_argument("--verify-self-closure", action="store_true",
                        help="read a self-closure back from a ledger location")
    parser.add_argument("--location", help="ledger locator, e.g. git+<repo>#<ref>")
    parser.add_argument("--repository-namespace",
                        help="repository ledger namespace; forwarded to the readback")
    parser.add_argument("--org-contract", type=Path, default=None,
                        help="org contract the readback is given; default: <consumer-root or this "
                             "checkout>/" + ORG_CONTRACT_RELATIVE)
    parser.add_argument("--closure", type=Path, help="closure result JSON to read back")
    parser.add_argument("--ledger-component", type=Path, default=None,
                        help="root the ledger writers load from (.stegverse/transition-ledger/emit.py, "
                             "resident-runtime/aggregate_repo_transition.py); default: this checkout")
    parser.add_argument("--consumer-root", type=Path, default=None,
                        help="root the ledger contracts resolve from (.stegverse/transition-ledger/"
                             "contract.json, org-contract.json); default: this checkout")
    args = parser.parse_args()
    hb_epoch, epoch_refused = cli_hb_epoch(args.hb_epoch, "resident-runtime/intr_destination_ingress.py (--hb-epoch)", INTR_PROTOCOL_GOAL)
    if epoch_refused is not None:
        # Nothing is received, appended or written (no --out); the exit is 1.
        print(json.dumps({"schema": CLOSURE_SCHEMA, **epoch_refused, "appended": False,
                          "authority_effect": "NONE_REFUSAL_ONLY"}, sort_keys=True))
        return 1
    if args.ledger_component is not None or args.consumer_root is not None:
        try:
            bind_ledger_writers(args.ledger_component, args.consumer_root)
        except LedgerPathRefused as refused:
            _emit({"schema": CLOSURE_SCHEMA, "location": args.location, **refused.refusal,
                   "appended": False, "authority_effect": "NONE_REFUSAL_ONLY"}, args.out)
            return 1
    try:
        if args.verify_self_closure:
            if not args.location or not args.repository_namespace or args.closure is None:
                raise SelfClosureRefused(
                    "SELF_CLOSURE_READBACK_INPUTS_PRESENT",
                    "--location, --repository-namespace, and --closure are required")
            contract, contract_path = load_org_contract(args.org_contract)
            result = verify_closure(
                args.location,
                json.loads(args.closure.read_text(encoding="utf-8")),
                repository_namespace=args.repository_namespace, org_contract=contract)
            result["readback_org_contract"] = str(contract_path)
            code = 0
        elif args.self_close:
            if args.registry is None:
                raise SelfClosureRefused("REGISTRY_REQUIRED", "--registry is required")
            result = closure(
                args.communication_id,
                registry=json.loads(args.registry.read_text(encoding="utf-8")),
                packet_id=args.packet_id, hb_epoch=hb_epoch)
            code = 0 if result.get("disposition") == ALLOW else 1
        else:
            if args.payload is None or args.registry is None:
                raise SelfClosureRefused(
                    "PAYLOAD_AND_REGISTRY_REQUIRED", "--payload and --registry are required")
            result = receive(
                json.loads(args.payload.read_text(encoding="utf-8")),
                registry=json.loads(args.registry.read_text(encoding="utf-8")),
                packet_id=args.packet_id or "organization-intr-destination",
                hb_epoch=hb_epoch)
            code = 0 if result.get("disposition") == ALLOW else 1
    except SelfClosureRefused as exc:
        result = closure_refusal(exc, args.location)
        code = 1
    except SystemExit as exc:
        refused = ledger_writer_refusal(
            exc, "resident-runtime/intr_destination_ingress.py (--self-close, --hb-epoch)", INTR_PROTOCOL_GOAL)
        if refused is None:
            raise
        refusal, carried = refused
        # The ledger writer refused (e.g. HB_EPOCH_NOT_SUPPLIED). A carried
        # refusal is printed exactly as given; an old-layout message gets the
        # six fields. Nothing is written (no --out), and the exit is 1.
        print(json.dumps(refusal) if carried else json.dumps(
            {"schema": CLOSURE_SCHEMA, **refusal, "appended": False, "refusal_source": "LEDGER_WRITER",
             "authority_effect": "NONE_REFUSAL_ONLY"}, sort_keys=True))
        return 1
    _emit(result, args.out)
    return code


if __name__ == "__main__":
    sys.exit(main())
