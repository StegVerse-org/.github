#!/usr/bin/env python3
"""Whether a series of standing declarations is one session, and how strongly.

A console that keeps working is not a connection held open. There is no host
to hold one to, and the ecosystem's ordering is an oscillator count rather than
a clock, so "still here" cannot be a ping that decays. What a console does
instead is keep declaring standing: genesis, then successive `VERIFY_EXISTING`
generations, each naming the previous one and the heartbeat epoch it stood at.
The gap between two generations is the delta a caller chose, carried in the
predecessor binding rather than configured anywhere.

That series is what a session is. This module derives whether a given series is
one, and it is a projection: it reads dispositions `node_standing.require`
already returned and declares nothing of its own. Standing is the gate; nothing
here gates anything.

**A session is identified by its chain, not by its name.** A caller-supplied
label is accepted and carried, for the same reason `origin` is -- it is useful
and it is caller-editable, so it names a session without establishing one. The
contract is explicit that a caller-editable classification does not establish
identity, and a label that could select a session would be exactly the bypass
that rule exists to prevent. What binds generation 4 to generation 1 is that
each one names its predecessor's exact digests, which a forger would have to
already hold.

**How strongly continuity is held depends on what the crossings carried, and
the record says which.** An earlier revision of this module reported that a
successor's statement about its predecessor was checkable against nothing. That
was true of the only series it had been shown -- one whose envelopes carried no
generation manifest -- and false in general, which made it an overclaim in the
direction of pessimism rather than the usual direction.

Where a crossing carries a generation manifest, the boundary already refuses an
envelope whose chain position contradicts it, and now records the digest it
agreed with rather than only the verdict that it agreed. So a successor's
predecessor binding is compared to the generation it names, and a series whose
every generation did that is `PROVEN_AGAINST_CARRIED_MANIFESTS`. A series whose
crossings carried nothing is `DECLARED_ONLY` and says what that means. Reporting
both as simply continuous, as the first revision did, let a declared chain read
exactly like a checked one.

Two narrownesses survive at both strengths and are stated rather than closed.
The digest is *carried* from the manifest, not recomputed here: recomputing
would be a second authority on a digest the lineage owner already computes and
refuses on mismatch. And only the manifest digest has a counterpart on the
prior disposition -- the `result_sha256` a successor also names does not, so
that half stays uncheckable and is not claimed otherwise.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]

SESSION_SCHEMA = "stegverse.node-session-continuity.v1"
AUTHORITY_EFFECT = "NONE_CONTINUITY_ONLY"

#: Why a series stopped being one session. A break is reported, never refused:
#: two sessions are a fact about the series, not an error in it.
NODE_REF_CHANGED = "NODE_REF_CHANGED"
SECOND_GENESIS = "SECOND_GENESIS"
GENERATION_NOT_SUCCESSOR = "GENERATION_NOT_SUCCESSOR"
PREDECESSOR_NAMES_A_DIFFERENT_GENERATION = "PREDECESSOR_NAMES_A_DIFFERENT_GENERATION"
HEARTBEAT_EPOCH_WENT_BACKWARDS = "HEARTBEAT_EPOCH_WENT_BACKWARDS"
PREDECESSOR_NAMES_A_DIFFERENT_MANIFEST = "PREDECESSOR_NAMES_A_DIFFERENT_MANIFEST"

BREAK_REASONS = (NODE_REF_CHANGED, SECOND_GENESIS, GENERATION_NOT_SUCCESSOR,
                 PREDECESSOR_NAMES_A_DIFFERENT_GENERATION, HEARTBEAT_EPOCH_WENT_BACKWARDS,
                 PREDECESSOR_NAMES_A_DIFFERENT_MANIFEST)

#: How strongly a session's continuity is held. The distinction exists because
#: the first revision of this module reported a series whose dispositions
#: carried no manifest with the same `continuous: true` as one whose every
#: generation agreed with a carried manifest -- which made a declared chain
#: read exactly like a checked one.
PROVEN_AGAINST_CARRIED_MANIFESTS = "PROVEN_AGAINST_CARRIED_MANIFESTS"
DECLARED_ONLY = "DECLARED_ONLY"
MIXED = "MIXED"


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kernel = _module("org_kernel", "org-kernel/kernel.py")


def _predecessor_epoch(disposition: Mapping[str, Any]) -> int | None:
    predecessor = disposition.get("standing_predecessor")
    if isinstance(predecessor, Mapping):
        epoch = predecessor.get("heartbeat_epoch")
        if isinstance(epoch, int) and not isinstance(epoch, bool):
            return epoch
    return None


def _break_between(earlier: Mapping[str, Any], later: Mapping[str, Any]) -> dict[str, Any] | None:
    """The first reason these two dispositions are not one session, or None."""
    if later.get("standing_node_ref") != earlier.get("standing_node_ref"):
        return {"reason": NODE_REF_CHANGED,
                "detail": {"from": earlier.get("standing_node_ref"),
                           "to": later.get("standing_node_ref")}}
    if later.get("standing_predecessor") is None:
        # A genesis never continues anything. It starts a session, so a genesis
        # following a generation is a second session rather than a break in
        # one -- reported as its own reason so a reader is not told a chain
        # failed when a new chain began.
        return {"reason": SECOND_GENESIS,
                "detail": {"after_generation": earlier.get("standing_generation")}}

    expected = (earlier.get("standing_generation") or 0) + 1
    if later.get("standing_generation") != expected:
        return {"reason": GENERATION_NOT_SUCCESSOR,
                "detail": {"expected": expected, "declared": later.get("standing_generation")}}

    # `require` already compares the resolved predecessor's generation to the
    # declared one and fails closed, so a disposition this organization's gate
    # produced can never reach here carrying a mismatch. The check stays for a
    # series supplied from a peer or a log that did not cross that gate, and
    # its presence should not be read as the gate being weaker than it is.
    named = later["standing_predecessor"].get("generation")
    if named != earlier.get("standing_generation"):
        return {"reason": PREDECESSOR_NAMES_A_DIFFERENT_GENERATION,
                "detail": {"names": named, "previous": earlier.get("standing_generation")}}

    # The check the first revision could not make. When the prior generation
    # agreed with a manifest, its digest is on the disposition, so the
    # successor's predecessor binding is compared to the generation it names
    # rather than to the successor's own restatement of it.
    agreed = earlier.get("standing_agreed_manifest_sha256")
    named = later["standing_predecessor"].get("manifest_sha256")
    if agreed is not None and named is not None and named != agreed:
        return {"reason": PREDECESSOR_NAMES_A_DIFFERENT_MANIFEST,
                "detail": {"prior_generation_agreed_with": agreed, "successor_names": named}}

    earlier_epoch, later_epoch = _predecessor_epoch(earlier), _predecessor_epoch(later)
    if earlier_epoch is not None and later_epoch is not None and later_epoch < earlier_epoch:
        # Ordering is the oscillator's. A series whose carried epochs run
        # backwards is not one session however well its generations count.
        return {"reason": HEARTBEAT_EPOCH_WENT_BACKWARDS,
                "detail": {"from": earlier_epoch, "to": later_epoch}}
    return None


def session_root(genesis: Mapping[str, Any], declared_label: Any = None) -> str:
    """The derived name of a session, from the declaration that opened it.

    The label is folded in because two consoles may legitimately use one
    node_ref, and without a discriminator their genesis declarations are
    identical. Folding it in distinguishes them; it does not authenticate
    either, and the record says so.
    """
    return kernel.sha({
        "schema": SESSION_SCHEMA,
        "node_ref": genesis.get("standing_node_ref"),
        "mode": genesis.get("standing_mode"),
        "generation": genesis.get("standing_generation"),
        "declared_label": None if declared_label is None else str(declared_label),
    })


def segments(dispositions: Sequence[Mapping[str, Any]]) -> list[list[int]]:
    """Index positions grouped into the sessions the series actually forms."""
    grouped: list[list[int]] = []
    for position, disposition in enumerate(dispositions):
        if not grouped or _break_between(dispositions[position - 1], disposition) is not None:
            grouped.append([position])
        else:
            grouped[-1].append(position)
    return grouped


def continuity(dispositions: Sequence[Mapping[str, Any]], *,
               declared_label: Any = None) -> dict[str, Any]:
    """Whether this series is one session, where it broke, and what is unproven."""
    series = list(dispositions)
    grouped = segments(series)

    breaks = []
    for group in grouped[1:]:
        start = group[0]
        found = _break_between(series[start - 1], series[start])
        breaks.append({"between_positions": [start - 1, start], **found})

    sessions = []
    for group in grouped:
        members = [series[index] for index in group]
        epochs = [epoch for epoch in (_predecessor_epoch(item) for item in members)
                  if epoch is not None]
        backed = [bool(item.get("carried_generation_manifest")) for item in members]
        # A pair is checkable when the earlier generation agreed with a
        # manifest and the later one names a digest: both halves must be
        # present or there is nothing to compare.
        checkable = sum(
            1 for earlier, later in zip(members, members[1:])
            if earlier.get("standing_agreed_manifest_sha256") is not None
            and isinstance(later.get("standing_predecessor"), Mapping)
            and later["standing_predecessor"].get("manifest_sha256") is not None)
        pairs = max(0, len(members) - 1)
        if all(backed) and checkable == pairs:
            strength = PROVEN_AGAINST_CARRIED_MANIFESTS
        elif not any(backed):
            strength = DECLARED_ONLY
        else:
            strength = MIXED
        sessions.append({
            "continuity_strength": strength,
            "generations_carrying_a_manifest": sum(backed),
            "checkable_pairs": checkable,
            "pairs": pairs,
            "session_root": session_root(members[0], declared_label),
            "node_ref": members[0].get("standing_node_ref"),
            "positions": list(group),
            "generations": [item.get("standing_generation") for item in members],
            "opened_with": members[0].get("standing_mode"),
            "heartbeat_epochs_carried": epochs,
            "span_hb": (epochs[-1] - epochs[0]) if len(epochs) > 1 else 0,
            "generation_count": len(members),
        })

    return {
        "schema": SESSION_SCHEMA,
        "declared_label": None if declared_label is None else str(declared_label),
        # Carried like `origin` is: useful, caller-editable, establishing nothing.
        "declared_label_establishes_nothing": True,
        "session_identity_is_derived_from_the_chain_not_declared": True,
        "sessions": sessions,
        "session_count": len(sessions),
        # Exactly one session is continuous. An empty series forms none, and
        # calling that continuous would be a vacuous pass -- the shape of claim
        # this whole effort exists to refuse.
        "continuous": len(sessions) == 1,
        "series_is_empty": not series,
        "breaks": breaks,
        "break_reason_vocabulary": list(BREAK_REASONS),
        # The limit, stated per series rather than blanket-asserted. An earlier
        # revision said continuity was recomputed against nothing, which was
        # true only of a series whose dispositions carried no manifest -- and
        # was the only series this module had been shown. Where a manifest is
        # carried, the boundary refuses an envelope disagreeing with it and now
        # records the digest it agreed with, so successive generations are
        # compared to the chain rather than to a restatement.
        "continuity_strength": (
            sessions[0]["continuity_strength"] if len(sessions) == 1
            else (DECLARED_ONLY if all(s["continuity_strength"] == DECLARED_ONLY
                                       for s in sessions) else MIXED)
            if sessions else DECLARED_ONLY),
        "strength_vocabulary": [PROVEN_AGAINST_CARRIED_MANIFESTS, DECLARED_ONLY, MIXED],
        "declared_only_means": ("no generation carried a manifest, so each successor's "
                                "statement about its predecessor is checkable against "
                                "nothing here"),
        "proven_means": ("every generation agreed with a carried manifest and every "
                         "successor's predecessor digest matched the digest the prior "
                         "generation agreed with"),
        # Still true at both strengths, and still said: the digest is carried
        # from the manifest, not recomputed here. The lineage owner recomputes
        # it and refuses on mismatch.
        "agreed_manifest_digests_recomputed_here": False,
        "agreed_manifest_digest_owner": (
            "StegVerse-org/StegVerse-SDK:stegverse/external_interlock_bootstrap.py"
            "::validate_external_interaction_generation_manifest"),
        "newest_generation_epoch_is_not_carried_by_its_own_disposition": True,
        "a_break_is_reported_not_refused": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
