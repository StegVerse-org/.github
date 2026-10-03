#!/usr/bin/env python3
"""Origin is attested by TV/TVC, not asserted by the sender.

Every inter-organization record this boundary writes has carried
`origin_attestation_state: NOT_PROVEN` with
`origin_is_asserted_by_the_sender: true`, because a frame in a shared mesh says
it came from this organization and nothing verified that. Measured against RE's
disorder classes, that single dimension was the entire score:
`unresolved_actor_identity` at 1.0, every other class at zero.

`docs/NODE_INGRESS_SETTLED_SPECIFICATION.md` section 4 settled how to close it,
and it required no new capability. TV/TVC already holds the primitive:

    TV_EXPORT_HMAC_SIGN     scripts/tv_credential_sign_export_resident.py
    TV_EXPORT_HMAC_VERIFY   scripts/tv_credential_verify_export_resident.py

The key is `TV_HMAC_SIGNING_KEY`, loaded from a systemd credential directory on
a TV/TVC resident host, never persisted, never exposed in a receipt, with no
development fallback. So the caller cannot forge an attestation, because it
holds no key. Neither can this boundary. It asks.

## What is attested

A statement naming the crossing and its origin. Every field is reconstructible
by the receiver from the packet it recovered, so nothing travels but the
signature:

    origin_organization        destination_organization
    destination_service        packet_id
    payload_sha256             transport_profile

The statement is canonicalized by the kernel's own `canon`, and those bytes are
what the credential authority signs. Because the whole statement is bound into
one digest, a signature cannot be moved: a forged origin, a different packet, a
tampered payload, a redirected destination or an altered transport profile each
produce a different digest, and TV/TVC's verifier refuses on the carried digest
before it ever reaches the HMAC compare.

## This module does not verify

It asks the credential authority and reads the authority's own receipt. No
signing or verification algorithm appears here, and a test asserts that: a
second implementation of the credential authority's algorithm living in this
repository would make this repository a second credential authority, which the
`credential_authority: TV/TVC` split exists to prevent. The algorithm is TVC's;
the statement shape is this boundary's.

**An unreachable authority is a hold, never a pass.** `verify` with no verifier
refuses rather than defaulting, because an attestation that silently reads as
proven when nothing checked it is worse than the honest `NOT_PROVEN` it
replaces -- it is the same defect class, with the record now claiming the
opposite of the truth.

## What attestation proves, and what it does not

It proves TV/TVC signed this statement, and that whoever assembled the frame
could not have produced the signature themselves. It does **not** prove TV/TVC
authenticated the asker as the organization the statement names: TV/TVC signs
what it is handed, and binding the asker to the claimed origin is TV/TVC's to
do. Its own receipts record `consumer_secret_received: false`, so that binding
is not yet observed anywhere. `tv_consumer_integration_observed` is a different
flag and is now true -- TV/TVC observes this consumer against its own functions
as of `StegVerse-Labs/tvc@1e6c909` -- which closes the integration question and
not the asker one.

What closes that gap is the bilateral match, which is already here: an attested
statement names a packet id, and a forged origin would need the claimed
organization's own ledger to hold an emission receipt for that packet id. So
the three layers are separate and each is necessary:

    frame digest        integrity -- the packet was not altered in the mesh
    TV/TVC signature    a credential authority attested this origin statement
    bilateral match     the claimed origin's own chain records emitting it

None of the three alone identifies an initiator. Together they do, and this
module is the second.

Nothing here grants authority. An attested origin is an identified sender, not
an authorized one.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

STATEMENT_SCHEMA = "stegverse.organization-origin-attestation-statement/v1"
RECORD_SCHEMA = "stegverse.organization-origin-attestation/v1"

CREDENTIAL_AUTHORITY = "TV/TVC"
SIGN_OPERATION = "TV_EXPORT_HMAC_SIGN"
VERIFY_OPERATION = "TV_EXPORT_HMAC_VERIFY"
AUTHORITY_SOURCE = "StegVerse-Labs/tvc:scripts/tv_credential_verify_export_resident.py"
ALGORITHM = "hmac-sha256"

#: The disposition of an origin claim. `PROVEN` is the value
#: `receipt_disorder_measurement` already reads for `unresolved_actor_identity`.
PROVEN = "PROVEN"
NOT_PROVEN = "NOT_PROVEN"
REFUSED = "REFUSED"

#: Every field of the statement, in the order it is declared. All six are
#: reconstructible by the receiver from the packet alone.
STATEMENT_FIELDS = ("origin_organization", "destination_organization",
                    "destination_service", "packet_id", "payload_sha256",
                    "transport_profile")

#: The shape of the signature artifact TV/TVC produces, which travels on the
#: packet. Checked rather than assumed: a signature of another shape is not one
#: this authority produced.
SIGNATURE_FIELDS = frozenset({"algo", "value", "sha256"})


class AttestationRefused(Exception):
    """An origin claim this boundary will not record as proven, carrying why."""

    def __init__(self, failed_predicate: str, reason: str) -> None:
        super().__init__(failed_predicate + ": " + reason)
        self.failed_predicate = failed_predicate
        self.reason = reason


def canon(value: Any) -> bytes:
    """The kernel's canonicalization, so the bytes signed are the bytes read."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def statement(*, origin_organization: str, destination_organization: str,
              destination_service: str, packet_id: str, payload_sha256: str,
              transport_profile: str) -> dict[str, Any]:
    """The statement TV/TVC is asked to sign."""
    declared = {
        "schema": STATEMENT_SCHEMA,
        "origin_organization": origin_organization,
        "destination_organization": destination_organization,
        "destination_service": destination_service,
        "packet_id": packet_id,
        "payload_sha256": payload_sha256,
        "transport_profile": transport_profile,
    }
    missing = [field for field in STATEMENT_FIELDS if not declared.get(field)]
    if missing:
        raise AttestationRefused("STATEMENT_DECLARES_EVERY_BOUND_FIELD",
                                 "absent or empty: " + ",".join(missing))
    return declared


def statement_from_packet(packet: Mapping[str, Any], payload_sha256: str) -> dict[str, Any]:
    """Reconstruct the statement from a recovered packet, as the receiver does.

    The receiver is handed a signature and nothing else. If it could not rebuild
    the signed statement from the packet itself, the attestation would have to
    carry its own copy of what it attests -- and a statement that travels beside
    its signature is one the sender can edit to match.
    """
    origin = packet.get("origin") or {}
    destination = packet.get("destination") or {}
    return statement(
        origin_organization=origin.get("org"),
        destination_organization=destination.get("org"),
        destination_service=destination.get("service"),
        packet_id=packet.get("packet_id"),
        payload_sha256=payload_sha256,
        transport_profile=packet.get("intr_profile"))


def payload_bytes(declared: Mapping[str, Any]) -> bytes:
    """The canonical bytes the credential authority signs and verifies."""
    return canon(dict(declared))


def _signature(carried: Any) -> dict[str, Any]:
    if not isinstance(carried, Mapping):
        raise AttestationRefused("SIGNATURE_IS_AN_OBJECT_OF_THE_AUTHORITYS_SHAPE",
                                 "signature is " + type(carried).__name__)
    if set(carried) != SIGNATURE_FIELDS:
        raise AttestationRefused("SIGNATURE_IS_AN_OBJECT_OF_THE_AUTHORITYS_SHAPE",
                                 "keys are " + ",".join(sorted(map(str, carried))))
    if carried.get("algo") != ALGORITHM:
        raise AttestationRefused("SIGNATURE_DECLARES_THE_AUTHORITYS_ALGORITHM",
                                 str(carried.get("algo")))
    return dict(carried)


def _authority_receipt(receipt: Any) -> dict[str, Any]:
    """The authority's own receipt, held to being one, and to saying valid."""
    if not isinstance(receipt, Mapping):
        raise AttestationRefused("CREDENTIAL_AUTHORITY_RETURNED_ITS_OWN_RECEIPT",
                                 "receipt is " + type(receipt).__name__)
    if receipt.get("credential_authority") != CREDENTIAL_AUTHORITY:
        raise AttestationRefused("RECEIPT_COMES_FROM_THE_DECLARED_CREDENTIAL_AUTHORITY",
                                 str(receipt.get("credential_authority")))
    if receipt.get("operation") != VERIFY_OPERATION:
        raise AttestationRefused("RECEIPT_IS_A_VERIFICATION_NOT_ANOTHER_OPERATION",
                                 str(receipt.get("operation")))
    if receipt.get("signature_valid") is not True:
        raise AttestationRefused("CREDENTIAL_AUTHORITY_REPORTS_THE_SIGNATURE_VALID",
                                 "signature_valid is " + str(receipt.get("signature_valid")))
    return dict(receipt)


def verify(declared: Mapping[str, Any], carried: Any,
           verifier: Callable[..., Mapping[str, Any]] | None) -> dict[str, Any]:
    """Ask the credential authority whether it signed this statement.

    `verifier` is how this process reaches TV/TVC. It is the credential boundary,
    not a convenience: the key is on a TV/TVC resident host and this boundary
    has no access to it by design. A `None` verifier is refused rather than
    treated as absent evidence, because the whole value of the field is that it
    is not writable by anything that wants it to say PROVEN.
    """
    signature = _signature(carried)
    if verifier is None:
        raise AttestationRefused(
            "CREDENTIAL_AUTHORITY_IS_REACHABLE",
            "no " + VERIFY_OPERATION + " surface was supplied; an unreachable "
            "authority is a hold, never a pass")
    try:
        receipt = verifier(payload=payload_bytes(declared),
                           signature_bytes=canon_signature(signature),
                           )
    except TypeError:
        # The authority's surface takes its key from its own credential
        # directory in production and as an argument in a conformance run. A
        # surface this boundary cannot call is a refusal, not a silent pass.
        raise AttestationRefused("CREDENTIAL_AUTHORITY_SURFACE_IS_CALLABLE_AS_DECLARED",
                                 VERIFY_OPERATION) from None
    except ValueError as refused:
        # The authority refuses a statement whose carried digest does not match
        # the payload before it reaches the signature compare. That is the
        # stronger disposition and it is reported as the authority stated it.
        raise AttestationRefused("STATEMENT_MATCHES_WHAT_THE_AUTHORITY_SIGNED",
                                 str(refused)) from None
    return _authority_receipt(receipt)


def canon_signature(signature: Mapping[str, Any]) -> bytes:
    """The signature artifact as bytes, in the authority's own serialization.

    TVC signs and verifies over `json.dumps(signature, indent=2,
    sort_keys=True)`, so its digest of the artifact is computed on that exact
    form. A different serialization of the same object is a different artifact.
    """
    return json.dumps(dict(signature), indent=2, sort_keys=True).encode("utf-8")


SIGN = "sign"
VERIFY = "verify"


def attest(declared: Mapping[str, Any],
           authority: Mapping[str, Callable[..., Any]] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Ask the credential authority to sign this statement, then confirm it.

    Two calls, deliberately. Recording `PROVEN` on the strength of having asked
    for a signature would be this boundary asserting its own origin again, one
    level up: it would be trusting its own request rather than the authority's
    answer. So the signature is obtained and then independently verified, and
    only the authority's verification receipt moves the state to `PROVEN`.

    `authority` is a mapping of the authority's two declared operations. Neither
    call takes a key: the key is loaded from a systemd credential directory on
    the TV/TVC resident host, and a surface that accepted one from here would
    let this boundary hold key material it must never hold.
    """
    if not isinstance(authority, Mapping) or not callable(authority.get(SIGN)):
        raise AttestationRefused(
            "CREDENTIAL_AUTHORITY_IS_REACHABLE",
            "no " + SIGN_OPERATION + " surface was supplied")
    try:
        signed = authority[SIGN](payload=payload_bytes(declared))
    except ValueError as refused:
        raise AttestationRefused("AUTHORITY_SIGNED_THE_STATEMENT_AS_DECLARED",
                                 str(refused)) from None
    signature = signed[0] if isinstance(signed, tuple) else signed
    receipt = verify(declared, signature, authority.get(VERIFY))
    return _signature(signature), receipt


def record(declared: Mapping[str, Any], signature: Mapping[str, Any],
           receipt: Mapping[str, Any]) -> dict[str, Any]:
    """What an attested origin records, with its own limits beside it."""
    return {
        "schema": RECORD_SCHEMA,
        "origin_attestation_state": PROVEN,
        "origin_is_asserted_by_the_sender": True,
        "origin_is_verified_by_this_boundary": False,
        "origin_is_attested_by_the_credential_authority": True,
        "credential_authority": CREDENTIAL_AUTHORITY,
        "credential_authority_operation": VERIFY_OPERATION,
        "credential_authority_source": AUTHORITY_SOURCE,
        "signature_algorithm": ALGORITHM,
        "attested_statement": dict(declared),
        "attested_statement_sha256": receipt.get("export_sha256"),
        "signature_sha256": receipt.get("signature_sha256"),
        "statement_reconstructed_from_the_packet": True,
        "statement_did_not_travel_beside_its_signature": True,
        # What this establishes, and what it leaves to the other two layers.
        "proves_the_authority_signed_this_statement": True,
        "proves_the_authority_authenticated_the_asker": False,
        "asker_binding_is_the_credential_authoritys_to_establish": True,
        "initiator_identification_also_requires_the_bilateral_match": True,
        "attested_origin_is_an_identified_sender_not_an_authorized_one": True,
        "authority_effect": "NONE_ATTESTATION_RECORD_ONLY",
    }


def refusal_record(failed_predicate: str, reason: str,
                   declared: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """What a refused attestation records.

    `origin_attestation_state` is `REFUSED` rather than `NOT_PROVEN`: an
    attestation that was offered and did not verify is a different fact from one
    that was never offered, and collapsing them would hide an attempted forgery
    behind the same value an ordinary unattested crossing carries.
    """
    return {
        "schema": RECORD_SCHEMA,
        "origin_attestation_state": REFUSED,
        "origin_is_attested_by_the_credential_authority": False,
        "credential_authority": CREDENTIAL_AUTHORITY,
        "credential_authority_operation": VERIFY_OPERATION,
        "failed_predicate": failed_predicate,
        "refusal_reason": reason,
        "refusal_is_verbatim": True,
        "an_offered_attestation_that_failed_is_not_an_absent_one": True,
        "attested_statement": dict(declared) if declared else None,
        "authority_effect": "NONE_REFUSAL_RECORD_ONLY",
    }


def unattested_record() -> dict[str, Any]:
    """What a crossing that offered no attestation records: today's state, named.

    Unchanged from what every inter-organization record has carried, and kept
    distinct from a refusal. Admitting an unattested crossing is a declared
    disposition in `org-runtime/interlock-intr.json`, not an oversight here.
    """
    return {
        "schema": RECORD_SCHEMA,
        "origin_attestation_state": NOT_PROVEN,
        "origin_is_asserted_by_the_sender": True,
        "origin_is_verified_by_this_boundary": False,
        "origin_is_attested_by_the_credential_authority": False,
        "credential_authority": CREDENTIAL_AUTHORITY,
        "no_attestation_was_offered": True,
        "attestation_is_required_before_an_unattested_crossing_confers_trust": True,
        "authority_effect": "NONE_ATTESTATION_RECORD_ONLY",
    }
