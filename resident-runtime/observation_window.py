#!/usr/bin/env python3
"""A bounded observation window: a snapshot, then what moved it, for ΔHB.

A reviewer handed a snapshot reviews a still frame of something that is
moving. `CANONICAL-NODE-INGRESS-CONTRACT-001` is under review *while* the
surface implementing it changes, and the reviewer's own objection to a static
artifact is the right one:

    absence of supplied evidence is not evidence of failure, but it is a limit
    on what they can independently reproduce

This window is the direct answer to the second half. It does not widen what is
supplied; it *states the bound*. The observer receives a baseline at a declared
heartbeat epoch, then the transitions that entered the declared scope, in HB
order, until a declared countdown reaches zero. What was observed, and what the
window could not see, are both recorded rather than left for the reader to
infer.

Four things it deliberately does not do.

* **It does not push.** There is no host, and the contract's own
  `no_new_host_required` means there is not supposed to be one. Delivery is a
  pull: the observer supplies the chain at each epoch it samples, and the
  window orders and binds what it is given. Calling that real-time delivery
  would be claiming a channel that does not exist, so every record says
  `delivery_is_pull_not_push`.

* **It does not make an absence into a transition.** A window that closes
  having observed nothing in scope reports *the window*, not an event. The
  close is itself a disposition and is recorded as one; the zero is carried on
  it. And a zero is not proof the ecosystem was still -- it is proof this
  observer, reading this source, through this scope, saw nothing. Both are
  stated.

* **It does not grant anything.** The heartbeat carrier already declares six
  times over that carrying a packet grants no authority. An observation window
  is weaker still: it admits nothing, routes nothing, executes nothing, and
  authorises nothing. `NONE_OBSERVATION_ONLY`.

* **It does not silently rebase.** Every report binds the snapshot it extends.
  An observer can prove the sequence it received describes the baseline it was
  given, rather than some later state the window quietly moved to.

Ordering is the contract's: `OSCILLATOR_HEARTBEAT_EPOCH_ONLY`, and
`wall_clock_ordering_permitted` is false. An epoch supplied from the carrier is
reproducible; an epoch sampled from a host clock is not, and the kernel's
reference already carries `derived_from_clock` to say which it was. That flag
is carried onto every record here rather than dropped, because a window whose
bounds came from a clock has a weaker claim than one whose bounds came from the
oscillator, and the difference is the reader's to weigh.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]

WINDOW_SCHEMA = "stegverse.observation-window.v1"
SNAPSHOT_SCHEMA = "stegverse.observation-window-snapshot.v1"
REPORT_SCHEMA = "stegverse.observation-window-report.v1"
CLOSE_SCHEMA = "stegverse.observation-window-close.v1"

AUTHORITY_EFFECT = "NONE_OBSERVATION_ONLY"


class WindowRefused(SystemExit):
    """A window that cannot be opened on the terms declared."""


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kernel = _module("org_kernel", "org-kernel/kernel.py")
lineage = _module("receipt_lineage_projection",
                  "resident-runtime/receipt_lineage_projection.py")

#: The scope vocabulary is the lineage projection's own event types. A second
#: taxonomy here would be a second authority on what a transition is.
EVENT_TYPES = (lineage.ORIGINAL, lineage.CORRECTION,
               lineage.INVALIDATION, lineage.SUPPLEMENT)


def scope(event_types: Sequence[str] | None = None) -> dict[str, Any]:
    """Declare what this window is watching.

    An omitted `event_types` watches all of them, and says so explicitly rather
    than leaving the reader to infer that an absent filter means everything.
    """
    if event_types is None:
        selected = tuple(EVENT_TYPES)
        narrowed = False
    else:
        selected = tuple(dict.fromkeys(str(name) for name in event_types))
        unknown = [name for name in selected if name not in EVENT_TYPES]
        if unknown:
            raise WindowRefused("observation-window-refused:unknown-event-type:"
                                + ",".join(sorted(unknown)))
        if not selected:
            raise WindowRefused("observation-window-refused:empty-scope")
        narrowed = set(selected) != set(EVENT_TYPES)
    return {"event_types": sorted(selected),
            "scope_is_narrowed": narrowed,
            "declared_event_type_vocabulary": sorted(EVENT_TYPES)}


def in_scope(record: Mapping[str, Any], declared: Mapping[str, Any]) -> bool:
    return record.get("event_type") in set(declared.get("event_types") or ())


def _reference(epoch: int | None) -> dict[str, Any]:
    """The heartbeat reference for a boundary of this window.

    Supplied epochs go through the kernel unchanged, so a window declared from
    the carrier is reproducible. A window with no epoch samples, and the
    reference it gets back says it sampled.
    """
    return kernel.hb_reference(epoch=epoch) if epoch is not None else kernel.hb_reference()


def open_window(chain: Sequence[Mapping[str, Any]], *, countdown_hb: int,
                epoch: int | None = None, declared_scope: Mapping[str, Any] | None = None,
                observed_through: str) -> dict[str, Any]:
    """Open the window and take the baseline the reports will extend.

    `countdown_hb` is a count of heartbeat periods, not a duration: at 100 Hz a
    countdown of 1000 spans ten seconds of oscillator, and the window closes on
    the epoch it reaches rather than on a clock reading.

    `observed_through` names the source this baseline was read from. It is
    mandatory because the whole point of the window is to bound a claim, and a
    claim with no stated source cannot be bounded -- a reviewer reading a stale
    checkout and a reviewer reading a live ledger receive different evidence,
    and the record has to say which one this is.
    """
    if not isinstance(countdown_hb, int) or isinstance(countdown_hb, bool) or countdown_hb < 1:
        raise WindowRefused("observation-window-refused:countdown-hb-below-1")
    source = str(observed_through).strip()
    if not source:
        raise WindowRefused("observation-window-refused:observed-through-not-declared")

    declared = dict(declared_scope) if declared_scope is not None else scope()
    reference = _reference(epoch)
    records = lineage.project(list(chain))
    baseline = [record for record in records if in_scope(record, declared)]
    head = baseline[-1] if baseline else None

    snapshot = {
        "schema": SNAPSHOT_SCHEMA,
        "opened_at_epoch": reference["epoch"],
        "countdown_hb": countdown_hb,
        "closes_at_epoch": reference["epoch"] + countdown_hb,
        "scope": declared,
        "observed_through": source,
        "baseline_record_count": len(baseline),
        "baseline_head_receipt_id": head["receipt_id"] if head else None,
        "baseline_head_payload_hash": head["payload_hash"] if head else None,
        "baseline_cursor": baseline[-1]["sequence"] if baseline else 0,
        "heartbeat": reference,
        "epoch_derived_from_clock": bool(reference.get("derived_from_clock")),
        "ordering": "OSCILLATOR_HEARTBEAT_EPOCH_ONLY",
        "wall_clock_ordering_permitted": False,
        "delivery_is_pull_not_push": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
    snapshot["snapshot_id"] = kernel.sha({
        "opened_at_epoch": snapshot["opened_at_epoch"],
        "countdown_hb": countdown_hb,
        "scope": declared,
        "observed_through": source,
        "baseline_head_receipt_id": snapshot["baseline_head_receipt_id"],
        "baseline_record_count": snapshot["baseline_record_count"],
    })
    return snapshot


def remaining_hb(snapshot: Mapping[str, Any], epoch: int) -> int:
    """Heartbeats left, floored at zero. A window never runs negative."""
    return max(0, int(snapshot["closes_at_epoch"]) - int(epoch))


def observe(snapshot: Mapping[str, Any], chain: Sequence[Mapping[str, Any]], *,
            epoch: int, cursor: int | None = None) -> dict[str, Any]:
    """Report the in-scope transitions this observer can see past `cursor`.

    The caller supplies both the epoch and the chain, because the caller is the
    one doing the sampling -- this is a pull. What the window contributes is
    ordering, scope, binding to the baseline, and an honest statement of what
    the observation does and does not establish.

    An epoch past the close reports nothing and says the window is closed
    rather than quietly continuing to emit.
    """
    position = snapshot["baseline_cursor"] if cursor is None else int(cursor)
    left = remaining_hb(snapshot, epoch)
    closed = left == 0

    reports: list[dict[str, Any]] = []
    if not closed:
        for record in lineage.project(list(chain)):
            if record["sequence"] <= position or not in_scope(record, snapshot["scope"]):
                continue
            position = record["sequence"]
            reports.append({
                "schema": REPORT_SCHEMA,
                # Binds the baseline, so a reader can prove this report
                # describes the snapshot it was given and not a later one.
                "snapshot_id": snapshot["snapshot_id"],
                "observed_at_epoch": int(epoch),
                "remaining_hb": left,
                "transition": dict(record),
                "observed_through": snapshot["observed_through"],
                "delivery_is_pull_not_push": True,
                "authority_effect": AUTHORITY_EFFECT,
            })

    return {
        "schema": WINDOW_SCHEMA,
        "snapshot_id": snapshot["snapshot_id"],
        "observed_at_epoch": int(epoch),
        "remaining_hb": left,
        "window_closed": closed,
        "reports": reports,
        "observed_count": len(reports),
        "cursor": position,
        "observed_through": snapshot["observed_through"],
        "delivery_is_pull_not_push": True,
        "authority_effect": AUTHORITY_EFFECT,
    }


def close(snapshot: Mapping[str, Any], *, epoch: int, observed_count: int,
          cursor: int) -> dict[str, Any]:
    """The window's own disposition at zero.

    Opening and closing a window are dispositions of an intended action, so the
    close is recorded whether or not anything was observed. What it is *not* is
    a transition in the observed scope: an absence does not become an event by
    being looked for, and a zero here is a statement about this observer
    reading this source through this scope, not about the ecosystem being
    still.
    """
    left = remaining_hb(snapshot, epoch)
    return {
        "schema": CLOSE_SCHEMA,
        "snapshot_id": snapshot["snapshot_id"],
        "opened_at_epoch": snapshot["opened_at_epoch"],
        "closed_at_epoch": int(epoch),
        "countdown_hb": snapshot["countdown_hb"],
        "countdown_reached_zero": left == 0,
        "remaining_hb": left,
        "observed_count": int(observed_count),
        "final_cursor": int(cursor),
        "scope": snapshot["scope"],
        "observed_through": snapshot["observed_through"],
        "epoch_derived_from_clock": snapshot["epoch_derived_from_clock"],
        # The two statements that keep a quiet window from reading as proof.
        "no_observed_transition_is_not_proof_none_occurred": True,
        "window_bounds_what_this_observer_could_reproduce": True,
        "close_is_a_disposition_not_an_observed_transition": True,
        "delivery_is_pull_not_push": True,
        "ordering": "OSCILLATOR_HEARTBEAT_EPOCH_ONLY",
        "authority_effect": AUTHORITY_EFFECT,
    }


def follow(snapshot: Mapping[str, Any],
           supplier: Callable[[int], Sequence[Mapping[str, Any]]],
           epochs: Sequence[int]) -> dict[str, Any]:
    """Run the window across the epochs the observer actually sampled.

    `supplier` is the observer's own read of the chain at an epoch. Threading
    it in keeps the loop host-free and makes the sampling explicit: the record
    that comes out says which epochs were sampled, so a reader can see the
    resolution of the observation rather than assuming it was continuous.

    Sampling is not continuity. A window that sampled twice over a thousand
    heartbeats says so, and the gaps it could not see are part of what it
    reports.
    """
    sampled = [int(value) for value in epochs]
    if sampled != sorted(sampled):
        raise WindowRefused("observation-window-refused:epochs-not-in-heartbeat-order")

    cursor = snapshot["baseline_cursor"]
    observations: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    for value in sampled:
        observation = observe(snapshot, supplier(value), epoch=value, cursor=cursor)
        cursor = observation["cursor"]
        observations.append(observation)
        reports.extend(observation["reports"])

    last = sampled[-1] if sampled else snapshot["opened_at_epoch"]
    return {
        "schema": WINDOW_SCHEMA,
        "snapshot": dict(snapshot),
        "sampled_epochs": sampled,
        "sample_count": len(sampled),
        "observation_is_sampled_not_continuous": True,
        "observations": observations,
        "reports": reports,
        "observed_count": len(reports),
        "close": close(snapshot, epoch=last, observed_count=len(reports), cursor=cursor),
        "authority_effect": AUTHORITY_EFFECT,
    }
