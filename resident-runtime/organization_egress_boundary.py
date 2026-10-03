#!/usr/bin/env python3
"""`ORGANIZATION_INTER_ORG_EGRESS` -- cross an organization boundary outbound, on the record.

Inter-organization transport already worked as a mechanism. A packet addressed
to another organization publishes into the federation mesh, that organization's
resident cycle consumes frames addressed to it, and its response comes back
addressed to the origin. A two-organization round trip completes today with no
new transport.

What it did not do was leave a record. `publish_packet` appends to no ledger and
`collect_ecosystem_responses` only reads the mesh, so the single most
consequential transition in the ecosystem -- leaving the organization -- emitted
nothing, while `organization_scope_rule` is that *every* state transition
occurring within the organization emits an organization receipt. The three
inbound boundaries were corrected to record every arrival under its disposition.
This is the outbound one, which was never built.

An outbound crossing is two transitions, not one, because they are separated in
time and either can be refused on its own:

    emit    CROSS_AN_ORGANIZATION_BOUNDARY_OUTBOUND
            ORGANIZATION_EGRESS_EMITTED  / ORGANIZATION_EGRESS_REFUSED
    close   OBSERVE_THE_FAR_SIDE_CLOSURE_OF_AN_OUTBOUND_CROSSING
            ORGANIZATION_EGRESS_CLOSED   / ORGANIZATION_EGRESS_CLOSURE_REFUSED

A transition is the disposition of an intended action, so both dispositions are
recorded at both levels -- the repository ledger first and the organization
ledger consuming that receipt, because a crossing is not an exception to the
layering `preserves_repo_receipt` requires.

What is deliberately *not* recorded is an absence. `close` returns `PENDING` and
writes nothing when no response frame is in the mesh yet: nothing crossed the
boundary, so there is no arrival to dispose of, and a chain that appended a
refusal on every poll would record the polling rather than the crossing. A
response that *is* present and does not verify is a crossing with disposition
DENY, and is recorded.

The destination is resolved from `org-boundary/registry/federation.json`, which
is the organization's own directory of its peers, and never from a caller's
argument alone. An organization absent from the directory is refused, and so is
one whose declared `transport_profile` is not the profile this boundary speaks:
a peer that cannot be addressed is a refusal to record, not a packet to send
hopefully.

Two things this records honestly rather than claiming:

* **Origin is asserted, not attested.** The frame says it came from this
  organization and nothing verifies that. Any writer of the shared mesh can
  publish a frame claiming any origin. Intra-organization that was tolerable;
  across a boundary it is the whole trust question, and it is the same rule as
  `caller_editable_ingress_source_field: FORBIDDEN_AS_AUTHORITATIVE_EVIDENCE`
  one level up. `credential_authority` is TV/TVC and
  `origin_attestation_state` stays `NOT_PROVEN`, so the record says the
  crossing was unattested instead of reading as though it were signed.
* **The far side's receipt is reconstructed, not carried.** A boundary receipt
  id is derived from the packet id, the service id and the payload digest, all
  of which this organization already holds, so the terminal id that comes back
  is recomputed and compared rather than trusted. That proves a boundary ran
  this packet and minted the chain this packet determines. It does *not* prove
  which organization that boundary belongs to, and it does not prove the far
  side persisted the chain on its own ledger -- that is the bilateral match,
  which needs the far side's chain readable and is not available at closure.

Nothing here grants authority. It records a crossing that occurred and the
disposition it reached.
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

OPERATION_ID = "ORGANIZATION_INTER_ORG_EGRESS"
OWNER_REPOSITORY = "StegVerse-org/.github"
RESULT_SCHEMA = "stegverse.organization-egress-result/v1"
EMISSION_SCHEMA = "stegverse.organization-egress-emission-record/v1"
CLOSURE_SCHEMA = "stegverse.organization-egress-closure-record/v1"
TRANSPORT_PROFILE = "stegverse.intr.org-boundary.v1"
BOUNDARY_RELATIVE = "org-runtime/interlock-intr.json"
#: How a peer's address for a declared capability is spelled. Derived by the
#: kernel's own slug rule, which is how every `.org-control` address has always
#: been derived and how this organization's own capability address is spelled.
CAPABILITY_ADDRESS_FORM = "ORGANIZATION_SLUG_DOT_CAPABILITY_PROFILE_ID"
CREDENTIAL_AUTHORITY = "TV/TVC"

#: The intended action each half of an outbound crossing carries.
INTENDED_ACTION_EMIT = "CROSS_AN_ORGANIZATION_BOUNDARY_OUTBOUND"
INTENDED_ACTION_CLOSE = "OBSERVE_THE_FAR_SIDE_CLOSURE_OF_AN_OUTBOUND_CROSSING"

#: One class per disposition, so no reader can mistake a refusal for a crossing
#: that left, or an unverified response for a closed one.
EMITTED_CLASS = "ORGANIZATION_EGRESS_EMITTED"
EMIT_REFUSED_CLASS = "ORGANIZATION_EGRESS_REFUSED"
CLOSED_CLASS = "ORGANIZATION_EGRESS_CLOSED"
CLOSURE_REFUSED_CLASS = "ORGANIZATION_EGRESS_CLOSURE_REFUSED"

ALLOW = "ALLOW"
DENY = "DENY"
PENDING = "PENDING"

#: The acknowledgement classes a response may carry, as the kernel maps them.
ACK_CLASSES = frozenset({"ecosystem.monitor.response", "ecosystem.work.ack",
                         "ecosystem.communication.ack"})


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kernel = _module("org_kernel", "org-kernel/kernel.py")
repository_ledger = _module("repo_transition_emit", ".stegverse/transition-ledger/emit.py")
organization_ledger = _module("aggregate_repo_transition",
                              "resident-runtime/aggregate_repo_transition.py")
ledger_store = _module("ledger_store", "resident-runtime/ledger_store.py")


class EgressRefused(Exception):
    """A refusal carrying its own disposition, so a caller is never left guessing."""

    def __init__(self, failed_predicate: str, reason: str) -> None:
        super().__init__(reason)
        self.failed_predicate = failed_predicate
        self.reason = reason


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canon(value)).hexdigest()


def this_organization(root: Path | None = None) -> str:
    return kernel.load_registry(root or ROOT)["organization"]


def declared_capabilities(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """The capabilities this organization's own overlay declares, by profile id.

    The overlay is the authority on which capabilities exist and what each is
    called. Emitting under a name taken from a caller's argument alone would
    address a capability nothing declares -- the same error, in the outbound
    direction, as letting a caller name its own peer.
    """
    boundary = json.loads((Path(root or ROOT) / BOUNDARY_RELATIVE).read_text())
    declared = (boundary.get("ingress") or {}).get("capability_endpoint_bindings") or []
    return {entry["profile_id"]: entry for entry in declared
            if isinstance(entry, dict) and entry.get("profile_id")}


def peer_capability_service(organization: str, capability: str) -> str:
    """The address a peer answers this capability at.

    Derived, not enumerated, and derived by the same rule this organization
    answers at: `kernel.organization_slug(org) + "." + profile_id` is exactly
    how `stegverse-org.sdk-manifest-ingress` is spelled in this organization's
    own registry, and how `organization_slug(org) + ".org-control"` has always
    been derived for every peer. Enumerating a service per peer in this
    organization's directory would be this organization writing down what its
    peers serve, which is a declaration none of them made.
    """
    return kernel.organization_slug(organization) + "." + capability


def resolve_destination(organization: str, *, capability: str | None = None,
                        root: Path | None = None) -> dict[str, Any]:
    """Resolve a peer organization from this organization's own peer directory.

    The directory is the authority on who this organization's peers are and how
    each is addressed. A destination taken from a caller's argument alone would
    let the caller name its own peer, which is the same error as letting a
    caller name its own organization at ingress.

    With no `capability`, the destination is the peer's organization control
    service, which is what every outbound crossing addressed before capabilities
    were addressable at all. With one, the destination is the peer's address for
    that capability -- which is what a *manifest* needs, because a manifest
    delivered to a control service arrives somewhere that does not receive
    manifests.

    What this resolution proves and does not prove is recorded with it. The
    address form is the organization's own, shared by every peer that declares
    this transport profile, and it is the form this organization itself answers
    at. It is not evidence that a given peer has installed that receiving
    operation; that is the peer's own registry to declare and this boundary
    cannot read it. The gap is observable rather than silent: a peer that does
    not serve the capability mints no boundary chain, so the crossing never
    closes and `close` records the refusal.
    """
    directory = kernel.load_federation_directory(root or ROOT)
    if capability is not None and capability not in declared_capabilities(root):
        raise EgressRefused(
            "CAPABILITY_IS_DECLARED_IN_THIS_ORGANIZATIONS_OVERLAY",
            "no capability_endpoint_binding declares profile_id " + str(capability))
    for row in directory.get("organizations", []):
        if row.get("organization") != organization:
            continue
        profile = row.get("transport_profile")
        if profile != TRANSPORT_PROFILE:
            raise EgressRefused(
                "DESTINATION_SPEAKS_THIS_BOUNDARY_TRANSPORT_PROFILE",
                "peer declares transport_profile " + str(profile)
                + "; this boundary speaks " + TRANSPORT_PROFILE)
        control = row.get("org_control_service")
        service = control if capability is None else peer_capability_service(organization, capability)
        return {
            "destination_organization": organization,
            "destination_repository": row.get("repository"),
            "destination_org_control_service": control,
            "destination_kernel_required": row.get("kernel_required"),
            "transport_profile": profile,
            "destination_resolution_source": "ORGANIZATION_FEDERATION_DIRECTORY",
            "destination_resolved_from_caller_argument": False,
            "destination_capability_profile_id": capability,
            "destination_service": service,
            "destination_capability_address_form": CAPABILITY_ADDRESS_FORM,
            "destination_capability_declared_by_the_peer_directory": False,
            "peer_serves_this_capability_is_proven_here": False,
            "unserved_capability_is_observable_as_an_unclosed_crossing": True,
        }
    raise EgressRefused(
        "DESTINATION_IS_A_DECLARED_PEER_OF_THIS_ORGANIZATION",
        "organization not in org-boundary/registry/federation.json: " + str(organization))


def _attestation() -> dict[str, Any]:
    """What this boundary can and cannot say about who sent the packet."""
    return {
        # The gap, recorded rather than hidden. A frame in a shared mesh carries
        # whatever origin its writer put in it.
        "origin_attestation_state": "NOT_PROVEN",
        "origin_is_asserted_by_the_sender": True,
        "origin_is_verified_by_this_boundary": False,
        "credential_authority": CREDENTIAL_AUTHORITY,
        "attestation_is_required_before_an_unattested_crossing_confers_trust": True,
    }


def emission_record(resolved: Mapping[str, Any], origin: str, packet: Mapping[str, Any],
                    frame: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    """What an emitted crossing recorded.

    Digests, not payloads: the body a caller sent is its own, and what the chain
    needs is that this organization addressed that peer and what left, bound so
    neither can be swapped afterwards.
    """
    return {
        "schema": EMISSION_SCHEMA,
        "operation": OPERATION_ID,
        "owner_repository": OWNER_REPOSITORY,
        "intended_action": INTENDED_ACTION_EMIT,
        "disposition": ALLOW,
        "transition_is_the_disposition_of_the_intended_action": True,
        "origin_organization": origin,
        **dict(resolved),
        "packet_id": packet["packet_id"],
        "frame_sha256": frame.get("frame_sha256"),
        "payload_sha256": sha(dict(payload)),
        # The digest the far side's boundary will bind into its own receipt
        # chain, in the kernel's own canonical form. Recorded at emission so a
        # closure reconstructs against this organization's own record of what
        # it sent rather than against anything the response carries.
        "far_side_payload_hash": kernel.sha(dict(payload)),
        # The service actually addressed, which is the peer's capability
        # address when one was declared and its control service otherwise. The
        # closure reconstructs against this, so recording the control service
        # while having addressed a capability would make every capability
        # crossing unclosable.
        "far_side_service_id": resolved["destination_service"],
        "transition_reference": (packet.get("transition") or {}).get("reference"),
        # This one really does cross an organization boundary, unlike repository
        # propagation, which records that it crossed none.
        "crossed_an_organization_boundary": True,
        "interlock_intr_involved": True,
        **_attestation(),
        "authority_effect": "NONE_EGRESS_RECORD_ONLY",
    }


def emit_refusal_record(failed_predicate: str, reason: str, organization: Any,
                        origin: str, payload: Any) -> dict[str, Any]:
    """What a refused emission recorded.

    No packet id, frame digest or resolved peer appears: this boundary emitted
    nothing, and a record naming them would read as a crossing that left.
    """
    return {
        "schema": EMISSION_SCHEMA,
        "operation": OPERATION_ID,
        "owner_repository": OWNER_REPOSITORY,
        "intended_action": INTENDED_ACTION_EMIT,
        "disposition": DENY,
        "transition_is_the_disposition_of_the_intended_action": True,
        "origin_organization": origin,
        "requested_destination_organization": organization
            if isinstance(organization, str) else None,
        "failed_predicate": failed_predicate,
        "refusal_reason": reason,
        "refusal_is_verbatim": True,
        "payload_sha256": sha(dict(payload) if isinstance(payload, Mapping) else payload),
        "packet_emitted": False,
        "crossed_an_organization_boundary": False,
        "retry_is_a_transition_not_a_lost_signal": True,
        "authority_effect": "NONE_EGRESS_RECORD_ONLY",
    }


def closure_record(resolved: Mapping[str, Any], origin: str, packet_id: str,
                   communication_id: str, response: Mapping[str, Any],
                   findings: list[str], recomputed: list[str]) -> dict[str, Any]:
    """What an observed closure recorded, verified or refused."""
    verified = not findings
    return {
        "schema": CLOSURE_SCHEMA,
        "operation": OPERATION_ID,
        "owner_repository": OWNER_REPOSITORY,
        "intended_action": INTENDED_ACTION_CLOSE,
        "disposition": ALLOW if verified else DENY,
        "transition_is_the_disposition_of_the_intended_action": True,
        "origin_organization": origin,
        "destination_organization": resolved["destination_organization"],
        "request_packet_id": packet_id,
        "communication_id": communication_id,
        "responding_organization": response.get("organization"),
        "response_packet_id": response.get("response_packet_id"),
        "response_message_class": response.get("message_class"),
        "response_frame_sha256": response.get("frame_sha256"),
        # Reconstructed, not carried. A boundary receipt id is derived from the
        # packet id, the service id and the payload digest -- all of which this
        # organization already holds -- so the terminal id that came back is
        # recomputed here and compared. An earlier version of this record said
        # the far side's receipt could not be verified here, which understated
        # the chain: it can, and a response that does not recompute did not come
        # from a boundary that ran this packet.
        "far_side_terminal_receipt": response.get("receipt_terminal"),
        "far_side_terminal_receipt_recomputed": recomputed[-1] if recomputed else None,
        "far_side_receipt_chain_recomputed": recomputed,
        "far_side_receipt_reconstructed_here": True,
        "far_side_chain_recomputed_from_emitter_held_inputs": True,
        "verified_the_response_answers_the_emitted_packet": True,
        "verified_the_response_came_from_the_resolved_peer": True,
        "verified_the_response_carries_an_acknowledgement_class": True,
        "verified_the_far_side_terminal_receipt_recomputes": not findings,
        # What reconstruction establishes, and what it does not. It proves a
        # boundary ran this packet and minted the chain this packet determines.
        # It does not prove which organization that boundary belongs to, and it
        # does not prove the far side persisted the chain on its own ledger --
        # that is the bilateral match, which needs the far side's chain to be
        # readable and is not available at this moment.
        "reconstruction_proves_the_boundary_ran_this_packet": True,
        "reconstruction_proves_who_the_far_side_is": False,
        "reconstruction_proves_the_far_side_persisted_its_chain": False,
        "bilateral_match_requires_the_far_side_chain_to_be_readable": True,
        "closure_findings": findings,
        "crossed_an_organization_boundary": True,
        "interlock_intr_involved": True,
        **_attestation(),
        "authority_effect": "NONE_CLOSURE_RECORD_ONLY",
    }


def _record(transition_id: str, transition_class: str, predecessor: str, successor: str,
            record: Mapping[str, Any], hb_epoch: int | None) -> dict[str, Any]:
    """Append at both levels: the repository first, the organization consuming it."""
    repository_receipt = repository_ledger.append(
        transition_id, transition_class, predecessor, successor,
        dict(record), "NONE", hb_epoch=hb_epoch)
    organization_receipt = organization_ledger.append(
        repository_receipt, "REPO_STATE_PROPAGATION", predecessor, successor,
        {"operation": OPERATION_ID,
         "intended_action": record["intended_action"],
         "disposition": record["disposition"],
         "crossed_an_organization_boundary": record["crossed_an_organization_boundary"]},
        "NONE", hb_epoch=hb_epoch)
    return {"repository_receipt": repository_receipt,
            "organization_receipt": organization_receipt}


def emit(destination_organization: Any, payload: Mapping[str, Any], *,
         standing: Mapping[str, Any], capability: str | None = None,
         transition_reference: str = "ecosystem.transition.interorg.v1",
         root: Path | None = None, mesh_root: Path | None = None,
         hb_epoch: int | None = None) -> dict[str, Any]:
    """Emit an outbound crossing to a declared peer, and record its disposition.

    `capability` is the profile id of a capability this organization's overlay
    declares, and it selects the peer address the crossing is sent to. Without
    one the crossing addresses the peer's organization control service, which
    is correct for a control message and wrong for a manifest: a submission
    delivered to a control service arrives at a surface that does not receive
    submissions, and the crossing completes as a control acknowledgement rather
    than as the capability it declared.

    The origin service is addressed symmetrically. A reply to a capability
    crossing belongs at this organization's own address for that capability,
    not at its control service.

    The record is appended *after* the frame is published, because the record is
    of an emission and carries the frame's digest. Minting it first would be a
    receipt claiming a crossing that had not happened yet.
    """
    origin = this_organization(root)
    try:
        resolved = resolve_destination(destination_organization, capability=capability,
                                       root=root)
        packet = kernel.build_packet(
            origin_org=origin,
            origin_service=peer_capability_service(origin, capability) if capability
                           else kernel.organization_slug(origin) + ".org-control",
            destination_org=resolved["destination_organization"],
            destination_service=resolved["destination_service"],
            payload=dict(payload), standing=dict(standing),
            transition_reference=transition_reference, authority_effect="NONE")
        published = kernel.publish_packet(packet, root=mesh_root)
    except EgressRefused as exc:
        record = emit_refusal_record(exc.failed_predicate, exc.reason,
                                     destination_organization, origin, payload)
        appended = _record(EMIT_REFUSED_CLASS + ":" + sha(record)[7:23], EMIT_REFUSED_CLASS,
                           record["payload_sha256"], sha(record), record, hb_epoch)
        return _refusal_result(record, appended)
    except (ValueError, KeyError, TypeError) as exc:
        record = emit_refusal_record("PACKET_IS_BUILDABLE_AND_PUBLISHABLE_AS_DECLARED",
                                     str(exc), destination_organization, origin, payload)
        appended = _record(EMIT_REFUSED_CLASS + ":" + sha(record)[7:23], EMIT_REFUSED_CLASS,
                           record["payload_sha256"], sha(record), record, hb_epoch)
        return _refusal_result(record, appended)

    record = emission_record(resolved, origin, packet, published["frame"], payload)
    appended = _record(EMITTED_CLASS + ":" + packet["packet_id"], EMITTED_CLASS,
                       record["payload_sha256"], sha(record), record, hb_epoch)
    return {
        "schema": RESULT_SCHEMA,
        "operation": OPERATION_ID,
        "disposition": ALLOW,
        "emitted": True,
        "packet_id": packet["packet_id"],
        "communication_id": (payload or {}).get("communication_id"),
        **{k: record[k] for k in ("destination_organization", "destination_repository",
                                  "destination_org_control_service", "destination_service",
                                  "destination_capability_profile_id",
                                  "peer_serves_this_capability_is_proven_here",
                                  "transport_profile",
                                  "destination_resolution_source", "frame_sha256",
                                  "crossed_an_organization_boundary",
                                  "origin_attestation_state")},
        "emission_record": record,
        "emission_transition_class": EMITTED_CLASS,
        "emission_repository_receipt_sha256": appended["repository_receipt"]["receipt_sha256"],
        "emission_organization_receipt_sha256": appended["organization_receipt"]["receipt_sha256"],
        "authority_effect": "NONE_EGRESS_RECORD_ONLY",
    }


def _refusal_result(record: Mapping[str, Any], appended: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA,
        "operation": OPERATION_ID,
        "disposition": DENY,
        "emitted": False,
        "failed_predicate": record["failed_predicate"],
        "detail": record["refusal_reason"],
        "refusal_recorded": True,
        "emission_transition_class": EMIT_REFUSED_CLASS,
        "emission_record": dict(record),
        "emission_repository_receipt_sha256": appended["repository_receipt"]["receipt_sha256"],
        "emission_organization_receipt_sha256": appended["organization_receipt"]["receipt_sha256"],
        "authority_effect": "NONE_EGRESS_RECORD_ONLY",
    }


#: The boundary receipt kinds every organization's process boundary mints, in
#: order. Fixed by `org-boundary/runtime/process_boundary.py`, which is the same
#: module every peer runs, so the sequence is not a guess about the far side.
FAR_SIDE_RECEIPT_KINDS = ("INGRESS_ACCEPTED", "DISPATCHED", "CONSUMED",
                          "RESULT_BOUND", "EGRESS_EMITTED")


def reconstruct_far_side_chain(packet_id: str, service_id: str,
                               payload_hash: str) -> list[str]:
    """Recompute the receipt chain the far side must have minted for this packet.

    Not a claim about the far side's honesty -- a recomputation. A boundary
    receipt id is `kind-sha256(canon({kind, packet_id, subject,
    previous_receipt_id, detail}))[:24]`, and every input is something this
    organization already holds: the packet id it minted, the service id it
    resolved from its own directory, and the digest of its own payload. So the
    terminal id that comes back on the response is checkable rather than
    carried, and a response that does not recompute did not come from a boundary
    that ran this packet.

    This is the same move `organization_manifest_ingress.reconstruct_closures`
    already makes inbound, which is why the inbound path never had to trust a
    chain it was handed. The outbound path was shipped saying the far side's
    receipt could not be verified here. It can.
    """
    chain, previous = [], None
    for kind in FAR_SIDE_RECEIPT_KINDS:
        receipt = kernel.receipt(kind, packet_id, service_id, previous,
                                 {"payload_hash": payload_hash})
        chain.append(receipt["receipt_id"])
        previous = receipt["receipt_id"]
    return chain


def recorded_emission(packet_id: str) -> dict[str, Any] | None:
    """This organization's own emission record for a packet, read off its chain.

    Returns the emission record the receipt carries as its evidence, or None
    when this organization's chain holds no emission for that packet.

    A closure is verified against what this organization recorded emitting, not
    against what the response asserts. Walking its own chain is also the local
    half of the bilateral match: a crossing with no emission receipt here is one
    this organization has no record of making, and it cannot be closed.
    """
    store = ledger_store.PosixLedgerStore(repository_ledger.lr())
    head = store.get(ledger_store.HEAD_KEY)
    cursor = (head or {}).get("receipt_sha256")
    wanted = EMITTED_CLASS + ":" + packet_id
    while cursor:
        receipt = store.get(ledger_store.receipt_key(cursor))
        if receipt is None:
            return None
        if (receipt.get("transition_class") == EMITTED_CLASS
                and receipt.get("transition_id") == wanted):
            # The emission record itself, which the receipt carries as its
            # evidence. Callers need what was recorded, not its envelope.
            evidence = receipt.get("evidence")
            return dict(evidence) if isinstance(evidence, Mapping) else None
        cursor = receipt.get("previous_receipt_sha256")
    return None


def verify_closure(resolved: Mapping[str, Any], packet_id: str,
                   response: Mapping[str, Any],
                   emission: Mapping[str, Any] | None = None) -> list[str]:
    """What fails to hold about a response that arrived. Empty means it closes."""
    findings = []
    if response.get("request_packet_id") != packet_id:
        findings.append("RESPONSE_ANSWERS_A_DIFFERENT_PACKET:"
                        + str(response.get("request_packet_id")))
    if response.get("organization") != resolved["destination_organization"]:
        findings.append("RESPONSE_CAME_FROM_A_DIFFERENT_ORGANIZATION:"
                        + str(response.get("organization")))
    if response.get("message_class") not in ACK_CLASSES:
        findings.append("RESPONSE_CARRIES_NO_ACKNOWLEDGEMENT_CLASS:"
                        + str(response.get("message_class")))
    terminal = response.get("receipt_terminal")
    if not isinstance(terminal, str) or not terminal.strip():
        findings.append("RESPONSE_CARRIES_NO_FAR_SIDE_TERMINAL_RECEIPT")
        return findings
    # Reconstructed, not trusted. Without this organization's own emission
    # record there is nothing to reconstruct against, and a crossing it has no
    # record of emitting is not one it can close.
    if emission is None:
        findings.append("THIS_ORGANIZATION_HAS_NO_EMISSION_RECORD_FOR_THIS_PACKET")
        return findings
    recomputed = reconstruct_far_side_chain(
        packet_id, emission["far_side_service_id"], emission["far_side_payload_hash"])
    if terminal != recomputed[-1]:
        findings.append("FAR_SIDE_TERMINAL_RECEIPT_DOES_NOT_RECOMPUTE:" + terminal)
    return findings


def close(destination_organization: str, packet_id: str, communication_id: str, *,
          root: Path | None = None, mesh_root: Path | None = None,
          hb_epoch: int | None = None) -> dict[str, Any]:
    """Observe the far side's closure of an emitted crossing, and record it.

    Returns `PENDING` and records nothing when no response is in the mesh. An
    absence is not an arrival: nothing crossed the boundary, so there is no
    disposition to record, and appending a refusal per poll would record the
    polling rather than the crossing.
    """
    origin = this_organization(root)
    resolved = resolve_destination(destination_organization, root=root)
    collected = kernel.collect_ecosystem_responses(origin, communication_id,
                                                   mesh_root=mesh_root)
    responses = [row for row in collected.get("organizations", [])
                 if row.get("organization") == resolved["destination_organization"]]
    if not responses:
        return {
            "schema": RESULT_SCHEMA,
            "operation": OPERATION_ID,
            "disposition": PENDING,
            "closed": False,
            "closure_recorded": False,
            "absence_is_not_a_transition": True,
            "communication_id": communication_id,
            "request_packet_id": packet_id,
            "destination_organization": resolved["destination_organization"],
            "authority_effect": "NONE_OBSERVATION_ONLY",
        }
    response = responses[0]
    emission = recorded_emission(packet_id)
    findings = verify_closure(resolved, packet_id, response, emission)
    recomputed = reconstruct_far_side_chain(
        packet_id, emission["far_side_service_id"], emission["far_side_payload_hash"]
    ) if emission else []
    record = closure_record(resolved, origin, packet_id, communication_id, response,
                            findings, recomputed)
    transition_class = CLOSED_CLASS if not findings else CLOSURE_REFUSED_CLASS
    appended = _record(transition_class + ":" + packet_id, transition_class,
                       sha({"packet_id": packet_id, "communication_id": communication_id}),
                       sha(record), record, hb_epoch)
    return {
        "schema": RESULT_SCHEMA,
        "operation": OPERATION_ID,
        "disposition": record["disposition"],
        "closed": not findings,
        "closure_recorded": True,
        "closure_findings": findings,
        "communication_id": communication_id,
        "request_packet_id": packet_id,
        "destination_organization": resolved["destination_organization"],
        "responding_organization": response.get("organization"),
        "far_side_terminal_receipt": response.get("receipt_terminal"),
        "far_side_receipt_reconstructed_here": True,
        "far_side_terminal_receipt_recomputed": recomputed[-1] if recomputed else None,
        "closure_record": record,
        "closure_transition_class": transition_class,
        "closure_repository_receipt_sha256": appended["repository_receipt"]["receipt_sha256"],
        "closure_organization_receipt_sha256": appended["organization_receipt"]["receipt_sha256"],
        "authority_effect": "NONE_CLOSURE_RECORD_ONLY",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--destination-organization", required=True)
    parser.add_argument("--payload", required=True, help="JSON file carrying the payload")
    parser.add_argument("--standing", required=True,
                        help="JSON file declaring mode, node_ref and the predecessor key")
    parser.add_argument("--transition-reference", default="ecosystem.transition.interorg.v1")
    parser.add_argument("--hb-epoch", type=int, default=None)
    parser.add_argument("--close", action="store_true",
                        help="observe the far side's closure of --packet-id instead of emitting")
    parser.add_argument("--packet-id")
    parser.add_argument("--communication-id")
    parser.add_argument("--capability",
                        help="profile_id of a capability this organization's overlay declares; "
                             "selects the peer address the crossing is sent to")
    parser.add_argument("--out")
    args = parser.parse_args()

    standing = json.loads(Path(args.standing).read_text(encoding="utf-8"))
    if not isinstance(standing, dict) or "predecessor" not in standing:
        raise SystemExit("standing must declare the predecessor key; null is explicit genesis")

    if args.close:
        if not args.packet_id or not args.communication_id:
            raise SystemExit("--close requires --packet-id and --communication-id")
        result = close(args.destination_organization, args.packet_id, args.communication_id,
                       hb_epoch=args.hb_epoch)
    else:
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
        result = emit(args.destination_organization, payload, standing=standing,
                      capability=args.capability,
                      transition_reference=args.transition_reference, hb_epoch=args.hb_epoch)
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["disposition"] in (ALLOW, PENDING) else 1


if __name__ == "__main__":
    sys.exit(main())
