#!/usr/bin/env python3
"""Resolve canonical node standing at ingress, from the contract rather than from code here.

`CANONICAL-NODE-INGRESS-CONTRACT-001` records this exact gap as its own
finding and names the fix:

    BOUNDARY_CANNOT_CARRY_CANONICAL_PREDECESSOR -> "Require a canonical
    predecessor carrier/validation seam using SDK semantics; do not equate
    lane-local receipt chaining with cross-lane predecessor standing."

and states the boundary's obligation directly:

    organization_boundary_must_carry_predecessor: true
    receiving_boundary_must_validate_predecessor: true
    current_organization_boundary_support: NOT_PROVEN

The kernel minted a five-receipt chain for every crossing and called that
lineage. It is not: those receipts chain *within* one dispatch, which is the
lane-local chaining the finding above explicitly refuses to accept as
predecessor standing. Nothing carried a predecessor across a crossing, and
nothing validated one.

This module is the seam. What it deliberately does not do is restate the
rules. The modes, the mandatory-predecessor rule, the field set, the ordering
rule and the disposition vocabulary are all already declared in the contract
document, so they are read from it. A second copy here would be a second
authority on standing, which is the same defect in a different place -- and
`local_second_predecessor_semantics_permitted` is false, so for the lineage
field set it would also be a direct violation.

Two refusals this makes structural, both named by the contract:

* `CALLER_EDITABLE_CLASSIFICATION_DOES_NOT_ESTABLISH_IDENTITY`. A packet's
  `origin` is written by whoever built the packet. Using it to decide that a
  crossing is internal, and therefore exempt, would let a caller opt out of
  standing by naming this organization as its own origin -- the bypass the
  contract records as `LIVE_GATEWAY_ACCEPTS_CALLER_FABRICATED_IDENTITY`. So
  there is no origin-based exemption: every dispatched packet declares
  standing, and `origin` stays a descriptive hint.

* Silence. `silent_fallback` and `silent_reenrollment` are both FORBIDDEN, and
  a failed `VERIFY_EXISTING` therefore stays failed rather than becoming a
  genesis.

What an ALLOW here means is narrow, and the disposition says so in its own
fields. `automatic_authoritative_source_classification` and
`attestation_owner` are both NOT_PROVEN in the contract, and this module does
not manufacture either: a declaration is checked for shape and internal
coherence, not authenticated. `NO_ATTESTATION_OWNER` -> "Retain NOT_PROVEN and
FAIL_CLOSED; do not manufacture an attestation owner."

Standing grants nothing. It is a precondition of ingress, not a capability,
and not an authority.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

CONTRACT_PATH = "docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json"
DISPOSITION_SCHEMA = "stegverse.node-standing-disposition.v1"

# The one mode name that is not a mode: the contract lists the refusal class
# alongside the two standing paths.
REFUSAL_CLASS = "INVALID_OR_UNRESOLVED"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def load_contract(root: Path) -> dict[str, Any]:
    """Load the ingress contract from the dispatch root.

    Resolved from the root rather than from beside this file, for the same
    reason `services.json` and `manifest_selection.py` are: the kernel is
    organization-neutral and runs against whichever root it is handed. A root
    with no contract fails closed -- a boundary that cannot state what standing
    requires must not admit a crossing claiming to have it.
    """
    path = root / CONTRACT_PATH
    if not path.is_file():
        raise SystemExit("org_boundary_node_ingress_contract_missing")
    contract = json.loads(path.read_text())
    if not isinstance(contract, dict):
        raise SystemExit("org_boundary_node_ingress_contract_invalid")
    return contract


def _section(contract: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = contract.get(key)
    if not isinstance(value, Mapping):
        raise SystemExit("node-ingress-contract-missing-section:" + key)
    return value


def standing_modes(contract: Mapping[str, Any]) -> tuple[str, ...]:
    """The declared standing paths, in the contract's own order."""
    declared = _section(contract, "standing_modes")
    return tuple(name for name in declared if name != REFUSAL_CLASS)


def predecessor_fields(contract: Mapping[str, Any]) -> tuple[str, ...]:
    """The lineage owner's predecessor field set, as the contract records it."""
    fields = _section(contract, "lineage_contract").get("predecessor_fields")
    if not isinstance(fields, list) or not fields:
        raise SystemExit("node-ingress-contract-missing-predecessor-fields")
    return tuple(str(name) for name in fields)


def dispositions(contract: Mapping[str, Any]) -> dict[str, str]:
    """The disposition vocabulary, so this module names refusals the contract's way."""
    declared = _section(contract, "required_dispositions")
    resolved = {}
    for key in ("success", "policy_or_admissibility_rejection",
                "missing_or_unverifiable_required_evidence"):
        value = declared.get(key)
        if not isinstance(value, str) or not value.strip():
            raise SystemExit("node-ingress-contract-missing-disposition:" + key)
        resolved[key] = value.strip()
    return resolved


def _refuse(disposition: str, reason: str) -> None:
    raise SystemExit("node-standing-" + disposition.lower() + ":" + reason)


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _validate_predecessor(predecessor: Any, fields: tuple[str, ...], fail_closed: str) -> dict[str, Any]:
    """Hold a declared predecessor to the owner's field set, exactly.

    This checks a shape. It does not recompute the binding: the owner's
    `successor_predecessor_binding` consumes the predecessor manifest and its
    result, while a crossing carries their digests only. The disposition
    records which of the two happened rather than letting the stronger reading
    stand.
    """
    if not isinstance(predecessor, Mapping):
        _refuse(fail_closed, "non-genesis-predecessor-invalid:not-an-object")
    unknown = sorted(set(predecessor) - set(fields))
    if unknown:
        _refuse(fail_closed, "non-genesis-predecessor-invalid:unknown-fields:" + ",".join(unknown))
    missing = [name for name in fields if name not in predecessor]
    if missing:
        _refuse(fail_closed, "non-genesis-predecessor-invalid:missing-fields:" + ",".join(missing))
    generation = predecessor.get("generation")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        _refuse(fail_closed, "non-genesis-predecessor-invalid:generation")
    for name in ("manifest_sha256", "result_sha256"):
        if name in fields and not _HEX64.match(str(predecessor.get(name))):
            _refuse(fail_closed, "non-genesis-predecessor-invalid:" + name)
    # Ordering is OSCILLATOR_HEARTBEAT_EPOCH_ONLY and wall-clock ordering is
    # forbidden, so the epoch is an oscillator count and nothing else.
    epoch = predecessor.get("heartbeat_epoch")
    if "heartbeat_epoch" in fields:
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
            _refuse(fail_closed, "non-genesis-predecessor-invalid:heartbeat_epoch")
    return dict(predecessor)


# Where an SDK generation manifest sits once it has been carried as payload.
# The lineage is already inside it -- `generation` and `predecessor` are the
# owner's own fields -- so the envelope seam must agree with it rather than
# become a second place to declare a chain position.
_MANIFEST_LOCATIONS = (
    ("manifest",),
    ("request", "payload", "manifest"),
    ("request", "manifest"),
    (),
)


def carried_manifest(payload: Any) -> Mapping[str, Any] | None:
    """Return a generation manifest carried in this payload, if one is there.

    A manifest is recognised by declaring both of the owner's lineage fields.
    A payload carrying none is not an error: not every crossing carries a
    generation manifest, and this seam is about agreement when one is present,
    not about requiring one.
    """
    for path in _MANIFEST_LOCATIONS:
        candidate: Any = payload
        for key in path:
            if not isinstance(candidate, Mapping):
                candidate = None
                break
            candidate = candidate.get(key)
        if isinstance(candidate, Mapping) and "generation" in candidate and "predecessor" in candidate:
            return candidate
    return None


def _agree_with_carried_manifest(payload: Any, *, generation: int, predecessor: Any,
                                 fail_closed: str) -> dict[str, Any]:
    """Refuse an envelope whose chain position contradicts the manifest it carries.

    Without this, the seam is a bypass rather than a gate: a caller could
    declare explicit genesis in the envelope while the manifest it carries
    claims generation 5, and the boundary would admit the crossing on the
    envelope and process the manifest. Agreement is the whole value of carrying
    standing at the envelope at all.
    """
    manifest = carried_manifest(payload)
    if manifest is None:
        return {"carried_generation_manifest": False,
                "standing_agrees_with_carried_manifest": None}
    if manifest.get("generation") != generation:
        _refuse(fail_closed,
                "claimed-standing-not-provable:carried-manifest-generation-disagrees")
    if manifest.get("predecessor") != predecessor:
        _refuse(fail_closed,
                "claimed-standing-not-provable:carried-manifest-predecessor-disagrees")
    return {"carried_generation_manifest": True,
            "standing_agrees_with_carried_manifest": True}


def require(contract: Mapping[str, Any], packet: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the standing a packet declares, or refuse the crossing.

    Returns the ALLOW disposition. Raises SystemExit, carrying the contract's
    own disposition name, on anything else.
    """
    verdicts = dispositions(contract)
    allow = verdicts["success"]
    deny = verdicts["policy_or_admissibility_rejection"]
    fail_closed = verdicts["missing_or_unverifiable_required_evidence"]
    modes = standing_modes(contract)
    fields = predecessor_fields(contract)

    declared = packet.get("standing")
    if not isinstance(declared, Mapping):
        # Not an absent predecessor -- an absent standing declaration. The
        # crossing never entered the contract at all.
        _refuse(fail_closed, "claimed-standing-not-provable:no-standing-declared")

    mode = _text(declared.get("mode"))
    if mode is None:
        _refuse(fail_closed, "claimed-standing-not-provable:no-mode-declared")
    if mode not in modes:
        _refuse(deny, "unsupported-standing-mode:" + mode)
    node_ref = _text(declared.get("node_ref"))
    if node_ref is None:
        _refuse(fail_closed, "claimed-standing-not-provable:no-node-ref-declared")

    if "predecessor" not in declared:
        # The contract's first refusal condition, verbatim. An absent key is an
        # unstated chain position; reading it as genesis is the defaulting that
        # `predecessor_key: REQUIRED` exists to prevent.
        _refuse(fail_closed, "predecessor-key-absent")
    predecessor = declared["predecessor"]
    generation = declared.get("generation")

    genesis, verify = modes[0], modes[1]
    if mode == genesis:
        if predecessor is not None:
            _refuse(deny, "explicit-genesis-declares-no-predecessor")
        if generation is not None and generation != 1:
            _refuse(deny, "explicit-genesis-is-generation-1")
        resolved_generation, resolved_predecessor = 1, None
    else:
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 2:
            _refuse(fail_closed, "claimed-standing-not-provable:generation-below-2")
        resolved_predecessor = _validate_predecessor(predecessor, fields, fail_closed)
        if resolved_predecessor["generation"] != generation - 1:
            # A failed verification is a failure. It does not re-enroll.
            _refuse(fail_closed, "non-genesis-predecessor-invalid:generation-not-successor")
        resolved_generation = generation

    agreement = _agree_with_carried_manifest(
        packet.get("payload"), generation=resolved_generation,
        predecessor=resolved_predecessor, fail_closed=fail_closed)

    lineage = _section(contract, "lineage_contract")
    return {
        **agreement,
        "schema": DISPOSITION_SCHEMA,
        "contract_id": str(contract.get("document_id") or "CANONICAL-NODE-INGRESS-CONTRACT-001"),
        "node_standing_disposition": allow,
        "standing_mode": mode,
        "standing_node_ref": node_ref,
        "standing_generation": resolved_generation,
        "standing_predecessor": resolved_predecessor,
        "boundary_carried_predecessor": True,
        "boundary_validated_predecessor": True,
        # Narrow by construction, and said plainly rather than left to be read
        # as more than it is.
        "declared_predecessor_lineage_recomputed": False,
        "structural_standing_only": True,
        "structural_standing_is_authenticated_standing": False,
        "authoritative_source_classification": "NOT_PROVEN",
        "attestation_owner_state": "NOT_PROVEN",
        "caller_editable_origin_established_identity": False,
        "silent_reenrollment_occurred": False,
        "ordering": str(lineage.get("ordering") or "OSCILLATOR_HEARTBEAT_EPOCH_ONLY"),
        "standing_authority_effect": "NONE_STANDING_ONLY",
    }


def readiness(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Publish what standing requires, straight from the contract.

    A caller should be able to satisfy the requirement on its first attempt
    rather than learning the shape by being refused. Readiness is not standing
    and grants nothing.
    """
    lineage = _section(contract, "lineage_contract")
    refusal = _section(contract, "standing_modes").get(REFUSAL_CLASS) or {}
    return {
        "schema": "stegverse.node-standing-readiness.v1",
        "contract_id": str(contract.get("document_id") or "CANONICAL-NODE-INGRESS-CONTRACT-001"),
        "standing_modes": list(standing_modes(contract)),
        "standing_declaration_required_on_every_crossing": True,
        "predecessor_key_required": True,
        "null_predecessor_means": "EXPLICIT_GENESIS_ONLY",
        "refusal_conditions": list(refusal.get("conditions") or []),
        "refusal_disposition": refusal.get("disposition"),
        "predecessor_fields_for_verify_existing": list(predecessor_fields(contract)),
        "lineage_owner": lineage.get("owner"),
        "ordering": lineage.get("ordering"),
        "wall_clock_ordering_permitted": lineage.get("wall_clock_ordering_permitted"),
        "local_second_predecessor_semantics_permitted": lineage.get(
            "local_second_predecessor_semantics_permitted"),
        "declared_predecessor_lineage_recomputed": False,
        "structural_standing_is_authenticated_standing": False,
        "attestation_owner_state": "NOT_PROVEN",
        "readiness_is_not_standing": True,
        "authority_effect": "NONE_READINESS_ONLY",
    }
