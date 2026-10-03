"""A receipt chain projects into lineage records, deriving what it does not store.

`Admissible-Existence/RE`'s lineage contract asks for `receipt_id`,
`event_type`, `predecessor_id`, `payload_hash` and `sequence`. A StegVerse
receipt carries three of those under its own names and neither of the other
two, so a chain fed to RE's validator as stored returns `FAIL_CLOSED`.

These assert the derivation rather than RE's verdict. The verdict is RE's to
give, and CI pins RE and runs its own validator against these records -- a copy
of its rules here would be a second authority on that shape, and the stale one.

What is asserted here is that the projection is faithful: the first receipt is
the chain's ORIGINAL, an ordinary append is a SUPPLEMENT, a receipt naming what
it supersedes is a CORRECTION or an INVALIDATION, the order is the chain's own,
every receipt is verified against its own body, and the ledger is unchanged.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lineage = _module("receipt_lineage_projection",
                  "resident-runtime/receipt_lineage_projection.py")
repository_ledger = _module("repo_transition_emit", ".stegverse/transition-ledger/emit.py")
ledger_store = _module("ledger_store", "resident-runtime/ledger_store.py")


class LineageProjectionTests(unittest.TestCase):
    def setUp(self):
        self._ledger = tempfile.TemporaryDirectory()
        self.root = str(Path(self._ledger.name) / "repo-ledger")
        self._previous = os.environ.get("STEGVERSE_REPO_LEDGER_ROOT")
        os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = self.root
        self.addCleanup(self._restore)

    def _restore(self):
        if self._previous is None:
            os.environ.pop("STEGVERSE_REPO_LEDGER_ROOT", None)
        else:
            os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = self._previous
        self._ledger.cleanup()

    def append(self, transition_class, evidence=None, index=0):
        return repository_ledger.append(
            transition_class + ":" + str(index), transition_class,
            "sha256:" + str(index) * 64, "sha256:" + str(index + 1) * 64,
            evidence if evidence is not None else {"n": index}, "NONE", hb_epoch=32)

    def chain_of(self, count):
        return [self.append("TEST_TRANSITION", index=i) for i in range(count)]

    # --- the derivation ----------------------------------------------------

    def test_the_first_receipt_of_a_chain_is_its_original(self):
        """What RE requires a new process to mark, derived from having no predecessor."""
        self.chain_of(3)
        records = lineage.projection()["records"]
        self.assertEqual(records[0]["event_type"], "ORIGINAL")
        self.assertIsNone(records[0]["predecessor_id"])

    def test_an_ordinary_append_is_a_supplement(self):
        """It adds to the chain without superseding anything."""
        self.chain_of(3)
        records = lineage.projection()["records"]
        self.assertEqual([r["event_type"] for r in records],
                         ["ORIGINAL", "SUPPLEMENT", "SUPPLEMENT"])

    def test_sequence_is_chain_position_starting_at_one(self):
        self.chain_of(4)
        records = lineage.projection()["records"]
        self.assertEqual([r["sequence"] for r in records], [1, 2, 3, 4])

    def test_a_receipt_naming_what_it_corrects_is_a_correction(self):
        """Nothing writes this field yet; the projection reflects it when something does."""
        first = self.append("TEST_TRANSITION", index=0)
        self.append("TEST_CORRECTION",
                    {"n": 1, lineage.CORRECTS_FIELD: first["receipt_sha256"]}, index=1)
        records = lineage.projection()["records"]
        self.assertEqual([r["event_type"] for r in records], ["ORIGINAL", "CORRECTION"])
        self.assertEqual(records[1][lineage.CORRECTS_FIELD], first["receipt_sha256"])

    def test_a_receipt_naming_what_it_voids_is_an_invalidation(self):
        first = self.append("TEST_TRANSITION", index=0)
        self.append("TEST_INVALIDATION",
                    {"n": 1, lineage.INVALIDATES_FIELD: first["receipt_sha256"]}, index=1)
        records = lineage.projection()["records"]
        self.assertEqual([r["event_type"] for r in records], ["ORIGINAL", "INVALIDATION"])
        self.assertEqual(records[1][lineage.INVALIDATES_FIELD], first["receipt_sha256"])

    def test_an_invalidation_outranks_a_correction_on_one_receipt(self):
        """Voiding is the stronger claim, so a receipt doing both reads as voiding."""
        first = self.append("TEST_TRANSITION", index=0)
        self.append("TEST_BOTH", {"n": 1,
                                  lineage.CORRECTS_FIELD: first["receipt_sha256"],
                                  lineage.INVALIDATES_FIELD: first["receipt_sha256"]}, index=1)
        self.assertEqual(lineage.projection()["records"][1]["event_type"], "INVALIDATION")

    def test_the_first_receipt_is_original_even_if_it_names_a_supersession(self):
        """There is nothing earlier in the chain for it to correct."""
        self.append("TEST_TRANSITION",
                    {"n": 0, lineage.CORRECTS_FIELD: "sha256:" + "9" * 64}, index=0)
        self.assertEqual(lineage.projection()["records"][0]["event_type"], "ORIGINAL")

    def test_an_ordinary_append_projects_without_supersession_fields(self):
        self.chain_of(2)
        for record in lineage.projection()["records"]:
            self.assertNotIn(lineage.CORRECTS_FIELD, record)
            self.assertNotIn(lineage.INVALIDATES_FIELD, record)

    # --- faithfulness ------------------------------------------------------

    def test_the_payload_hash_is_the_successor_state(self):
        """What the transition produced, under whichever name its level gives it."""
        self.chain_of(2)
        chain = lineage.repository_chain()
        records = lineage.projection()["records"]
        self.assertEqual([r["payload_hash"] for r in records],
                         [c["successor_state_sha256"] for c in chain])
        self.assertTrue(all(r["payload_hash"] for r in records))

    def test_the_organization_namings_are_read_rather_than_assumed(self):
        """An organization receipt names its successor `successor_org_state_sha256`.

        Projecting only the repository spelling silently produced a null
        `payload_hash`, which RE fails closed on.
        """
        self.assertEqual(lineage.successor_state({"successor_state_sha256": "sha256:a"}),
                         "sha256:a")
        self.assertEqual(lineage.successor_state({"successor_org_state_sha256": "sha256:b"}),
                         "sha256:b")
        self.assertIsNone(lineage.successor_state({}))

    def test_the_order_is_the_chains_own_from_head_backwards(self):
        """A directory listing would offer whatever order the filesystem has."""
        appended = self.chain_of(4)
        records = lineage.projection()["records"]
        self.assertEqual([r["receipt_id"] for r in records],
                         [a["receipt_sha256"] for a in appended])

    def test_the_projection_leaves_the_ledger_unchanged(self):
        self.chain_of(3)
        store = ledger_store.PosixLedgerStore(Path(self.root))
        before = set(store.list_prefix(ledger_store.RECEIPT_PREFIX))
        head = store.get(ledger_store.HEAD_KEY)
        report = lineage.projection()
        self.assertIs(report["ledger_unchanged_by_this_projection"], True)
        self.assertEqual(set(store.list_prefix(ledger_store.RECEIPT_PREFIX)), before)
        self.assertEqual(store.get(ledger_store.HEAD_KEY), head)

    def test_a_receipt_that_does_not_verify_against_its_own_body_is_refused(self):
        """A projection built on a tampered receipt would present a lineage that is not held."""
        appended = self.chain_of(2)
        store = ledger_store.PosixLedgerStore(Path(self.root))
        key = ledger_store.receipt_key(appended[-1]["receipt_sha256"])
        tampered = {**store.get(key), "transition_class": "SOMETHING_ELSE"}
        store.put(key, tampered)
        with self.assertRaises(lineage.LineageRefused) as refused:
            lineage.projection()
        self.assertIn("RECEIPT_DOES_NOT_VERIFY_AGAINST_ITS_OWN_BODY",
                      str(refused.exception))

    # --- what the projection does not do -----------------------------------

    def test_the_projection_does_not_give_the_verdict(self):
        """RE's validator judges; restating its rules here would be a second authority."""
        self.chain_of(2)
        report = lineage.projection()
        self.assertIs(report["verdict_is_res_to_give_not_this_projections"], True)
        self.assertEqual(report["lineage_contract"],
                         "Admissible-Existence/RE:data/re-lineage-contract.json")
        for absent in ("verdict", "lineage_reconstructable", "outcome"):
            self.assertNotIn(absent, report, absent)

    def test_the_projection_grants_nothing(self):
        """RE's own contract says lineage reconstruction creates no authority."""
        self.chain_of(2)
        report = lineage.projection()
        self.assertIs(report["lineage_reconstruction_creates_authority"], False)
        self.assertEqual(report["authority_effect"], "NONE_PROJECTION_ONLY")

    def test_nothing_is_stored_to_make_this_work(self):
        """The receipts carry no event_type or sequence, and are not asked to."""
        self.chain_of(2)
        for receipt in lineage.repository_chain():
            self.assertNotIn("event_type", receipt)
            self.assertNotIn("sequence", receipt)
            self.assertNotIn("event_type", receipt.get("evidence") or {})

    def test_an_unknown_ledger_level_is_refused(self):
        with self.assertRaises(lineage.LineageRefused) as refused:
            lineage.projection("SOMETHING_ELSE")
        self.assertIn("UNKNOWN_LEDGER_LEVEL", str(refused.exception))


if __name__ == "__main__":
    unittest.main()
