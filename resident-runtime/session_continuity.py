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

**And here is what this projection cannot do, which is the point of writing it.**
A standing disposition carries `standing_generation` and `standing_predecessor`,
and it does *not* carry the `manifest_sha256` or `result_sha256` that its own
successor's predecessor binding will name. So when generation 2 states what
generation 1 was, there is nothing in generation 1's disposition to check that
statement against. Continuity across a series is therefore *declared by each
successor* and recomputed against nothing -- the same narrowness
`declared_predecessor_lineage_recomputed: false` already admits for a single
crossing, now visible across a series where it matters more, because a session
is exactly the claim that a later generation belongs with an earlier one.

This module reports that limit on every record rather than presenting a
well-formed series as a proven one. Closing it means a disposition carrying the
digests its successor will name, which is a change to what standing emits and
is not taken here.
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

BREAK_REASONS = (NODE_REF_CHANGED, SECOND_GENESIS, GENERATION_NOT_SUCCESSOR,
                 PREDECESSOR_NAMES_A_DIFFERENT_GENERATION, HEARTBEAT_EPOCH_WENT_BACKWARDS)


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
        sessions.append({
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
        # The limit, on every record. A well-formed series is not a proven one.
        "predecessor_digests_recomputed_against_the_prior_disposition": False,
        "why_not": ("a standing disposition carries neither the manifest nor the "
                    "result digest that its successor's predecessor binding names, "
                    "so the successor's statement about its predecessor is checkable "
                    "against nothing here"),
        "continuity_is_declared_by_each_successor_not_proven_against_its_predecessor": True,
        "newest_generation_epoch_is_not_carried_by_its_own_disposition": True,
        "a_break_is_reported_not_refused": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
