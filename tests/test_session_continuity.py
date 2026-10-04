"""A console session is a chain of standing declarations, and the chain names it.

There is no connection to hold open and no clock to tail, so a console that
keeps working keeps declaring: genesis, then successive VERIFY_EXISTING
generations, each naming the previous one and the heartbeat epoch it stood at.
These cases hold that series to being one session -- and, more importantly,
hold the projection to saying what it cannot establish.

What it cannot establish is the part worth testing hardest. A standing
disposition does not carry the manifest or result digest that its successor's
predecessor binding will name, so a successor's statement about its predecessor
is checkable against nothing. A well-formed series is therefore declared
continuous by each successor rather than proven against each predecessor, and a
record that implied otherwise would be the defect class this surface exists to
expose.

Source validation only. No authority effect is claimed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SC = _module("session_continuity", "resident-runtime/session_continuity.py")
NS = _module("node_standing_for_sessions", "org-boundary/runtime/node_standing.py")
CONTRACT = NS.load_contract(ROOT)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def genesis(node_ref="mir-console"):
    return NS.require(CONTRACT, {"standing": {
        "mode": "ESTABLISH_GENESIS", "node_ref": node_ref, "predecessor": None}})


def successor(node_ref, generation, predecessor_generation, epoch):
    binding = {"generation": predecessor_generation,
               "manifest_sha256": _digest({node_ref: predecessor_generation}),
               "result_sha256": _digest({node_ref: "r%d" % predecessor_generation}),
               "heartbeat_epoch": epoch}
    return NS.require(CONTRACT, {"standing": {
        "mode": "VERIFY_EXISTING", "node_ref": node_ref,
        "generation": generation, "predecessor": binding}})


def chain(node_ref="mir-console", start=32, delta=500, generations=4):
    series, epoch = [genesis(node_ref)], start
    for generation in range(2, generations + 1):
        series.append(successor(node_ref, generation, generation - 1, epoch))
        epoch += delta
    return series


class OneSessionTests(unittest.TestCase):

    def test_a_well_formed_series_is_one_session(self):
        resolved = SC.continuity(chain())
        self.assertTrue(resolved["continuous"])
        self.assertEqual(resolved["session_count"], 1)
        self.assertEqual(resolved["breaks"], [])
        self.assertEqual(resolved["sessions"][0]["generations"], [1, 2, 3, 4])

    def test_a_lone_genesis_is_already_a_session(self):
        resolved = SC.continuity([genesis()])
        self.assertTrue(resolved["continuous"])
        self.assertEqual(resolved["sessions"][0]["generation_count"], 1)

    def test_the_span_comes_from_the_epochs_the_bindings_carry(self):
        session = SC.continuity(chain(start=32, delta=500, generations=4))["sessions"][0]
        self.assertEqual(session["heartbeat_epochs_carried"], [32, 532, 1032])
        self.assertEqual(session["span_hb"], 1000)

    def test_the_newest_generations_own_epoch_is_not_carried(self):
        # Only a predecessor binding carries an epoch, so the latest generation
        # has not yet said where it stood. Stated rather than filled in.
        resolved = SC.continuity(chain(generations=4))
        self.assertTrue(resolved["newest_generation_epoch_is_not_carried_by_its_own_disposition"])
        self.assertEqual(len(resolved["sessions"][0]["heartbeat_epochs_carried"]), 3)


class IdentityTests(unittest.TestCase):

    def test_the_root_is_derived_from_the_declaration_that_opened_the_session(self):
        resolved = SC.continuity(chain(), declared_label="richard-review-console")
        self.assertTrue(resolved["sessions"][0]["session_root"].startswith("sha256:"))
        self.assertTrue(resolved["session_identity_is_derived_from_the_chain_not_declared"])

    def test_a_label_distinguishes_two_consoles_sharing_a_node_ref(self):
        first = SC.continuity(chain(), declared_label="alpha")["sessions"][0]["session_root"]
        second = SC.continuity(chain(), declared_label="beta")["sessions"][0]["session_root"]
        self.assertNotEqual(first, second)

    def test_a_label_establishes_nothing(self):
        # Carried like `origin` is. The contract refuses caller-editable
        # classification as identity, so a label that could select a session
        # would be the bypass that rule exists to prevent.
        resolved = SC.continuity(chain(), declared_label="anything-at-all")
        self.assertTrue(resolved["declared_label_establishes_nothing"])
        self.assertEqual(resolved["declared_label"], "anything-at-all")

    def test_an_absent_label_is_carried_as_absent(self):
        self.assertIsNone(SC.continuity(chain())["declared_label"])


class BreakTests(unittest.TestCase):

    def test_a_different_node_ref_breaks_the_series(self):
        resolved = SC.continuity(chain("mir-console", generations=3)
                                 + chain("other-console", start=9000, generations=2))
        self.assertFalse(resolved["continuous"])
        self.assertEqual(resolved["session_count"], 2)
        self.assertEqual(resolved["breaks"][0]["reason"], SC.NODE_REF_CHANGED)

    def test_a_second_genesis_opens_a_second_session_rather_than_failing_one(self):
        resolved = SC.continuity(chain(generations=2) + [genesis()])
        self.assertEqual(resolved["breaks"][0]["reason"], SC.SECOND_GENESIS)
        self.assertEqual(resolved["session_count"], 2)

    def test_a_skipped_generation_breaks_the_series(self):
        series = [genesis(), successor("mir-console", 4, 3, 532)]
        self.assertEqual(SC.continuity(series)["breaks"][0]["reason"],
                         SC.GENERATION_NOT_SUCCESSOR)

    def test_the_standing_gate_already_refuses_a_mismatched_predecessor(self):
        """The local gate is stronger than this projection needs.

        `require` compares the resolved predecessor's generation to the
        declared one and fails closed, so a disposition it produced can never
        carry this mismatch. The projection keeps the check anyway, because a
        series can arrive from a peer or a log without having crossed this
        organization's gate -- but nobody should read its presence as implying
        the gate is weaker than it is.
        """
        with self.assertRaises(SystemExit):
            successor("mir-console", 2, 2, 532)

    def test_a_predecessor_naming_the_wrong_generation_breaks_a_supplied_series(self):
        # Constructed directly rather than through `require`, which is the only
        # way this shape exists: a series supplied from outside the gate.
        opened = genesis()
        forged = {**opened, "standing_mode": "VERIFY_EXISTING", "standing_generation": 2,
                  "standing_predecessor": {"generation": 2, "heartbeat_epoch": 532}}
        resolved = SC.continuity([opened, forged])
        self.assertEqual(resolved["breaks"][0]["reason"],
                         SC.PREDECESSOR_NAMES_A_DIFFERENT_GENERATION)
        self.assertFalse(resolved["continuous"])

    def test_epochs_running_backwards_break_the_series(self):
        # Ordering is the oscillator's, so a series whose carried epochs
        # reverse is not one session however well its generations count.
        series = [genesis(),
                  successor("mir-console", 2, 1, 5000),
                  successor("mir-console", 3, 2, 1000)]
        reasons = [item["reason"] for item in SC.continuity(series)["breaks"]]
        self.assertIn(SC.HEARTBEAT_EPOCH_WENT_BACKWARDS, reasons)

    def test_a_break_is_reported_not_refused(self):
        resolved = SC.continuity(chain(generations=2) + [genesis()])
        self.assertTrue(resolved["a_break_is_reported_not_refused"])
        # Both sides survive as sessions; nothing was discarded.
        self.assertEqual(sum(s["generation_count"] for s in resolved["sessions"]), 3)

    def test_every_break_names_a_declared_reason(self):
        resolved = SC.continuity(chain(generations=2) + chain("other", generations=2))
        for item in resolved["breaks"]:
            with self.subTest(reason=item["reason"]):
                self.assertIn(item["reason"], SC.BREAK_REASONS)
                self.assertEqual(len(item["between_positions"]), 2)


class WhatItCannotEstablishTests(unittest.TestCase):
    """The limit is the point. A well-formed series is not a proven one."""

    def test_predecessor_digests_are_not_recomputed_against_the_prior_disposition(self):
        resolved = SC.continuity(chain())
        self.assertFalse(resolved["predecessor_digests_recomputed_against_the_prior_disposition"])
        self.assertIn("checkable against nothing", resolved["why_not"])

    def test_the_prior_disposition_genuinely_lacks_those_digests(self):
        # Held against the standing surface itself, so if a disposition ever
        # starts carrying them this case stops being true and must be revisited.
        opened = genesis()
        self.assertNotIn("manifest_sha256", opened)
        self.assertNotIn("result_sha256", opened)

    def test_continuity_is_declared_by_the_successor(self):
        resolved = SC.continuity(chain())
        self.assertTrue(
            resolved["continuity_is_declared_by_each_successor_not_proven_against_its_predecessor"])

    def test_the_narrowness_matches_what_standing_already_admits(self):
        # `declared_predecessor_lineage_recomputed` is false per crossing; this
        # projection carries the same narrowness across a series.
        self.assertFalse(genesis()["declared_predecessor_lineage_recomputed"])
        self.assertFalse(
            SC.continuity(chain())["predecessor_digests_recomputed_against_the_prior_disposition"])

    def test_an_empty_series_is_not_continuous(self):
        # A vacuous pass would be the shape of claim this effort refuses.
        resolved = SC.continuity([])
        self.assertFalse(resolved["continuous"])
        self.assertEqual(resolved["session_count"], 0)
        self.assertTrue(resolved["series_is_empty"])

    def test_the_projection_grants_nothing(self):
        self.assertEqual(SC.continuity(chain())["authority_effect"], "NONE_CONTINUITY_ONLY")


if __name__ == "__main__":
    unittest.main()
