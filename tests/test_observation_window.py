"""A window bounds a claim; it does not widen one.

The reviewer's objection to a static artifact is the one these cases answer:
"absence of supplied evidence is not evidence of failure, but it is a limit on
what they can independently reproduce." A window states that limit in its own
record -- the scope it watched, the source it read, the epochs it actually
sampled, and the heartbeat it closed on -- so a reader can see the resolution
of the observation instead of assuming it was continuous.

The cases that matter most here are the negative ones. A window that observes
nothing must not read as proof that nothing happened, and a window must not
quietly keep reporting past the countdown it declared.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OW = _module("observation_window", "resident-runtime/observation_window.py")

SOURCE = "git:StegVerse-org/.github@main"


def receipt(index, previous, successor, **extra):
    return {"receipt_sha256": f"r{index}", "previous_receipt_sha256": previous,
            "successor_state_sha256": successor, **extra}


def chain(length):
    built = [receipt(1, None, "s1")]
    for index in range(2, length + 1):
        built.append(receipt(index, f"r{index - 1}", f"s{index}"))
    return built


def opened(**overrides):
    kwargs = {"countdown_hb": 300, "epoch": 5000, "observed_through": SOURCE}
    kwargs.update(overrides)
    base = kwargs.pop("chain", chain(1))
    return OW.open_window(base, **kwargs)


class SnapshotTests(unittest.TestCase):

    def test_the_baseline_is_bound_to_scope_source_and_countdown(self):
        snapshot = opened()
        self.assertEqual(snapshot["opened_at_epoch"], 5000)
        self.assertEqual(snapshot["closes_at_epoch"], 5300)
        self.assertEqual(snapshot["observed_through"], SOURCE)
        self.assertEqual(snapshot["baseline_record_count"], 1)
        self.assertEqual(snapshot["baseline_head_receipt_id"], "r1")
        self.assertTrue(snapshot["snapshot_id"].startswith("sha256:"))

    def test_a_different_source_is_a_different_snapshot(self):
        # Two reviewers reading different sources do not share a baseline, and
        # the identity says so rather than colliding.
        self.assertNotEqual(opened()["snapshot_id"],
                            opened(observed_through="git:fork@main")["snapshot_id"])

    def test_a_supplied_epoch_is_not_clock_derived(self):
        self.assertFalse(opened()["epoch_derived_from_clock"])

    def test_a_sampled_epoch_says_it_sampled(self):
        # No epoch supplied: the kernel samples, and the weaker claim is
        # carried rather than dropped.
        self.assertTrue(opened(epoch=None)["epoch_derived_from_clock"])

    def test_ordering_is_the_contracts_and_wall_clock_is_refused(self):
        snapshot = opened()
        self.assertEqual(snapshot["ordering"], "OSCILLATOR_HEARTBEAT_EPOCH_ONLY")
        self.assertFalse(snapshot["wall_clock_ordering_permitted"])

    def test_a_source_must_be_declared(self):
        for value in ("", "   "):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                opened(observed_through=value)

    def test_a_countdown_must_be_a_positive_heartbeat_count(self):
        for value in (0, -1, True, 1.5):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                opened(countdown_hb=value)


class ScopeTests(unittest.TestCase):

    def test_an_omitted_filter_watches_all_and_says_so(self):
        declared = OW.scope()
        self.assertEqual(set(declared["event_types"]), set(OW.EVENT_TYPES))
        self.assertFalse(declared["scope_is_narrowed"])

    def test_a_narrowed_scope_is_marked_narrowed(self):
        declared = OW.scope(["CORRECTION"])
        self.assertTrue(declared["scope_is_narrowed"])

    def test_the_vocabulary_is_the_lineage_projections_own(self):
        lineage = _module("rlp", "resident-runtime/receipt_lineage_projection.py")
        self.assertEqual(set(OW.EVENT_TYPES), {lineage.ORIGINAL, lineage.CORRECTION,
                                               lineage.INVALIDATION, lineage.SUPPLEMENT})

    def test_an_unknown_event_type_is_refused(self):
        with self.assertRaises(SystemExit):
            OW.scope(["NOT_A_LINEAGE_EVENT"])

    def test_an_empty_scope_is_refused(self):
        # Watching nothing is not a window; it is a window that can only ever
        # report zero, which would read as evidence.
        with self.assertRaises(SystemExit):
            OW.scope([])

    def test_out_of_scope_transitions_are_not_reported(self):
        snapshot = opened(declared_scope=OW.scope(["CORRECTION"]), chain=[])
        observed = OW.observe(snapshot, chain(3), epoch=5100)
        # chain(3) is an ORIGINAL followed by SUPPLEMENTs -- none in scope.
        self.assertEqual(observed["observed_count"], 0)


class ReportTests(unittest.TestCase):

    def test_each_report_binds_the_snapshot_it_extends(self):
        snapshot = opened()
        observed = OW.observe(snapshot, chain(3), epoch=5100)
        self.assertEqual(observed["observed_count"], 2)
        for report in observed["reports"]:
            self.assertEqual(report["snapshot_id"], snapshot["snapshot_id"])
            self.assertEqual(report["observed_through"], SOURCE)
            self.assertTrue(report["delivery_is_pull_not_push"])
            self.assertEqual(report["authority_effect"], "NONE_OBSERVATION_ONLY")

    def test_remaining_heartbeats_count_down(self):
        snapshot = opened()
        self.assertEqual(OW.remaining_hb(snapshot, 5000), 300)
        self.assertEqual(OW.remaining_hb(snapshot, 5250), 50)
        self.assertEqual(OW.remaining_hb(snapshot, 5300), 0)

    def test_a_window_never_runs_negative(self):
        self.assertEqual(OW.remaining_hb(opened(), 9999), 0)

    def test_the_cursor_stops_a_transition_being_reported_twice(self):
        snapshot = opened()
        first = OW.observe(snapshot, chain(2), epoch=5100)
        self.assertEqual(first["observed_count"], 1)
        again = OW.observe(snapshot, chain(2), epoch=5200, cursor=first["cursor"])
        self.assertEqual(again["observed_count"], 0)

    def test_nothing_is_reported_past_the_countdown(self):
        # The declared bound is the bound. A window that kept emitting would be
        # reporting outside the limit it told the reader it was keeping.
        snapshot = opened()
        observed = OW.observe(snapshot, chain(5), epoch=5300)
        self.assertTrue(observed["window_closed"])
        self.assertEqual(observed["observed_count"], 0)
        self.assertEqual(observed["reports"], [])


class CloseTests(unittest.TestCase):

    def test_a_quiet_window_reports_the_window_not_an_event(self):
        snapshot = opened()
        run = OW.follow(snapshot, lambda epoch: chain(1), [5100, 5200])
        self.assertEqual(run["observed_count"], 0)
        closed = run["close"]
        self.assertEqual(closed["observed_count"], 0)
        self.assertTrue(closed["close_is_a_disposition_not_an_observed_transition"])

    def test_a_zero_is_not_proof_the_ecosystem_was_still(self):
        closed = OW.follow(opened(), lambda epoch: chain(1), [5100])["close"]
        self.assertTrue(closed["no_observed_transition_is_not_proof_none_occurred"])
        self.assertTrue(closed["window_bounds_what_this_observer_could_reproduce"])

    def test_the_close_carries_the_source_and_the_epoch_provenance(self):
        closed = OW.follow(opened(), lambda epoch: chain(1), [5100])["close"]
        self.assertEqual(closed["observed_through"], SOURCE)
        self.assertFalse(closed["epoch_derived_from_clock"])

    def test_reaching_zero_is_recorded_as_reached(self):
        closed = OW.follow(opened(), lambda epoch: chain(1), [5300])["close"]
        self.assertTrue(closed["countdown_reached_zero"])
        self.assertEqual(closed["remaining_hb"], 0)

    def test_a_window_abandoned_early_does_not_claim_it_reached_zero(self):
        closed = OW.follow(opened(), lambda epoch: chain(1), [5100])["close"]
        self.assertFalse(closed["countdown_reached_zero"])
        self.assertEqual(closed["remaining_hb"], 200)


class FollowTests(unittest.TestCase):

    def test_the_snapshot_comes_first_then_what_moved_it(self):
        snapshot = opened()
        supply = {5100: chain(2), 5200: chain(3)}
        run = OW.follow(snapshot, lambda epoch: supply[epoch], [5100, 5200])
        self.assertEqual(run["snapshot"]["snapshot_id"], snapshot["snapshot_id"])
        self.assertEqual([report["transition"]["sequence"] for report in run["reports"]], [2, 3])
        self.assertEqual([report["observed_at_epoch"] for report in run["reports"]], [5100, 5200])

    def test_sampling_is_recorded_as_sampling(self):
        # Two samples over three hundred heartbeats is not continuous
        # observation, and the record does not let it read as if it were.
        run = OW.follow(opened(), lambda epoch: chain(1), [5100, 5200])
        self.assertTrue(run["observation_is_sampled_not_continuous"])
        self.assertEqual(run["sampled_epochs"], [5100, 5200])
        self.assertEqual(run["sample_count"], 2)

    def test_epochs_out_of_heartbeat_order_are_refused(self):
        # Ordering is the oscillator's. Accepting a reversed sample would be
        # accepting a wall clock that stepped backwards.
        with self.assertRaises(SystemExit):
            OW.follow(opened(), lambda epoch: chain(1), [5200, 5100])

    def test_the_window_grants_nothing_at_every_level(self):
        run = OW.follow(opened(), lambda epoch: chain(2), [5100])
        self.assertEqual(run["authority_effect"], "NONE_OBSERVATION_ONLY")
        self.assertEqual(run["close"]["authority_effect"], "NONE_OBSERVATION_ONLY")
        self.assertEqual(run["snapshot"]["authority_effect"], "NONE_OBSERVATION_ONLY")
        for report in run["reports"]:
            self.assertEqual(report["authority_effect"], "NONE_OBSERVATION_ONLY")

    def test_delivery_is_never_described_as_push(self):
        run = OW.follow(opened(), lambda epoch: chain(2), [5100])
        self.assertTrue(run["snapshot"]["delivery_is_pull_not_push"])
        self.assertTrue(run["close"]["delivery_is_pull_not_push"])
        for report in run["reports"]:
            self.assertTrue(report["delivery_is_pull_not_push"])


if __name__ == "__main__":
    unittest.main()
