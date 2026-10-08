"""Exact-retry hardening of the repository transition ledger (E1).

`recorded()` walked back from HEAD and treated a missing node as the end of
the chain, so a lookup over a broken chain answered "never recorded" and the
append minted a fresh receipt on top of it. Nodes were believed as read: a
body edited in place, or a stored `receipt_sha256` that was not the node's own
digest, passed. And an exact retry was matched on the predecessor and the
named evidence only, so the same transition id arriving with another successor
or another authority effect was returned the earlier receipt as though it were
a replay.

These pin the hardened behaviour: every node reachable from HEAD is recomputed
and must be the receipt its address names, or the attempt fails closed with
`REPO_LEDGER_CHAIN_BREAK` and writes nothing; an exact retry returns the prior
receipt only when predecessor, successor, authority effect and the identity
evidence all match, and any divergence is `ledger_receipt_collision`.

Source validation only. No authority effect is claimed.
"""
import importlib.util
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMIT = ROOT / ".stegverse/transition-ledger/emit.py"
_spec = importlib.util.spec_from_file_location("exact_retry_emit", EMIT)
emit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(emit)
ledger_store = emit.ledger_store

BEFORE = "sha256:" + "a" * 64
AFTER = "sha256:" + "b" * 64
OTHER = "sha256:" + "c" * 64
EVIDENCE = {"request_sha256": "d" * 64, "carrier": "first"}
IDENTITY = ("request_sha256",)
# Heartbeat epochs count from the HB32 anchor; tests offset from it.
E0 = emit.kernel.HB_ANCHOR_EPOCH


def race_worker(root, results):
    store = ledger_store.PosixLedgerStore(root)
    receipt = emit.append("RACE-1", "TEST_CLASS", BEFORE, AFTER, dict(EVIDENCE), "NONE",
                          hb_epoch=E0 + 70, store=store, idempotent_on=IDENTITY)
    results.put(receipt["receipt_sha256"])


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self._work = tempfile.TemporaryDirectory()
        self.addCleanup(self._work.cleanup)
        self.root = Path(self._work.name)
        self.store = ledger_store.PosixLedgerStore(self.root)

    def append(self, transition_id, epoch, **kwargs):
        args = dict(predecessor=BEFORE, successor=AFTER, evidence=dict(EVIDENCE),
                    authority_effect="NONE")
        args.update(kwargs)
        return emit.append(transition_id, "TEST_CLASS", args["predecessor"], args["successor"],
                           args["evidence"], args["authority_effect"], hb_epoch=E0 + epoch,
                           store=self.store, idempotent_on=args.get("idempotent_on"))

    def three(self):
        return [self.append("T-" + str(n), 10 + n) for n in range(3)]

    def head(self):
        return self.store.get(ledger_store.HEAD_KEY)

    def path(self, receipt):
        return self.root / ledger_store.receipt_key(receipt["receipt_sha256"])

    def receipt_count(self):
        return len(self.store.list_prefix(ledger_store.RECEIPT_PREFIX))

    def assert_breaks(self, detail):
        head, count = self.head(), self.receipt_count()
        with self.assertRaises(emit.RepoLedgerChainBreak) as raised:
            emit.recorded(self.store, head, "T-2", "TEST_CLASS")
        self.assertEqual(raised.exception.failed_predicate, "REPO_LEDGER_CHAIN_BREAK")
        self.assertEqual(raised.exception.detail, detail)
        for idempotent_on in (IDENTITY, None):
            with self.assertRaises(emit.RepoLedgerChainBreak):
                self.append("T-NEW", 99, idempotent_on=idempotent_on)
        # Nothing was minted after the break: no receipt, no HEAD movement.
        self.assertEqual(self.head(), head)
        self.assertEqual(self.receipt_count(), count)
        return raised.exception


class ChainBreakTests(LedgerCase):
    def test_a_valid_chain_still_verifies(self):
        receipts = self.three()
        self.assertEqual(emit.recorded(self.store, self.head(), "T-0", "TEST_CLASS"), receipts[0])
        self.assertEqual([r["receipt_sha256"] for r in emit.chain(self.store, self.head())],
                         [r["receipt_sha256"] for r in reversed(receipts)])

    def test_a_historical_receipt_of_another_shape_still_verifies(self):
        """Verification is the digest over whatever body was minted, not a schema."""
        body = {"schema": "stegverse.repo-transition-receipt/v1", "repository": "historical",
                "transition_id": "OLD-1", "transition_class": "TEST_CLASS",
                "predecessor_state_sha256": BEFORE, "successor_state_sha256": AFTER,
                "evidence": {}, "authority_effect": "NONE", "previous_receipt_sha256": None}
        old = {**body, "receipt_sha256": emit.sha(body)}
        self.store.initialize()
        self.store.put(ledger_store.receipt_key(old["receipt_sha256"]), old)
        self.store.put(ledger_store.HEAD_KEY, {"receipt_sha256": old["receipt_sha256"]})
        self.assertEqual(emit.recorded(self.store, self.head(), "OLD-1", "TEST_CLASS"), old)
        appended = self.append("T-AFTER", 30)
        self.assertEqual(appended["previous_receipt_sha256"], old["receipt_sha256"])

    def test_a_missing_middle_node_fails_closed(self):
        receipts = self.three()
        self.path(receipts[1]).unlink()
        exc = self.assert_breaks("missing_receipt")
        self.assertEqual(exc.receipt_sha256, receipts[1]["receipt_sha256"])

    def test_a_missing_node_behind_the_match_still_fails_closed(self):
        """A match near HEAD is not an answer read off a chain broken further back."""
        receipts = self.three()
        self.path(receipts[0]).unlink()
        with self.assertRaises(emit.RepoLedgerChainBreak):
            emit.recorded(self.store, self.head(), "T-2", "TEST_CLASS")
        with self.assertRaises(emit.RepoLedgerChainBreak):
            self.append("T-2", 12, idempotent_on=IDENTITY)

    def test_a_corrupted_body_under_an_unchanged_key_fails_closed(self):
        receipts = self.three()
        edited = {**receipts[1], "evidence": {**receipts[1]["evidence"], "carrier": "edited"}}
        self.path(receipts[1]).write_text(json.dumps(edited))
        self.assert_breaks("receipt_body_does_not_hash_to_its_address")

    def test_a_mismatched_stored_receipt_sha256_fails_closed(self):
        receipts = self.three()
        self.path(receipts[1]).write_text(json.dumps({**receipts[1], "receipt_sha256": OTHER}))
        self.assert_breaks("stored_receipt_sha256_is_not_its_address")

    def test_an_unreadable_node_fails_closed(self):
        receipts = self.three()
        self.path(receipts[1]).write_text("{not json")
        self.assert_breaks("unreadable_receipt")

    def test_a_malformed_previous_address_fails_closed(self):
        body = {"transition_id": "BAD-1", "transition_class": "TEST_CLASS",
                "previous_receipt_sha256": "sha256:../../../elsewhere"}
        bad = {**body, "receipt_sha256": emit.sha(body)}
        self.store.initialize()
        self.store.put(ledger_store.receipt_key(bad["receipt_sha256"]), bad)
        self.store.put(ledger_store.HEAD_KEY, {"receipt_sha256": bad["receipt_sha256"]})
        with self.assertRaises(emit.RepoLedgerChainBreak) as raised:
            emit.recorded(self.store, self.head(), "X", "TEST_CLASS")
        self.assertEqual(raised.exception.detail, "malformed_receipt_address")

    def test_a_head_that_names_no_receipt_is_not_genesis(self):
        self.three()
        self.store.put(ledger_store.HEAD_KEY, {"repository": "x"})
        self.assert_breaks("malformed_head")

    def test_the_command_line_records_a_fail_closed_refusal(self):
        receipts = self.three()
        self.path(receipts[1]).unlink()
        completed = subprocess.run(
            [sys.executable, str(EMIT), "--transition-id", "CLI-1", "--transition-class",
             "TEST_CLASS", "--predecessor-state-sha256", BEFORE,
             "--successor-state-sha256", AFTER, "--hb-epoch", str(E0 + 50)],
            capture_output=True, text=True, cwd=str(ROOT),
            env=dict(os.environ, STEGVERSE_REPO_LEDGER_ROOT=str(self.root)))
        self.assertEqual(completed.returncode, 1, completed.stderr)
        refusal = json.loads(completed.stdout)
        self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
        self.assertEqual(refusal["failed_predicate"], "REPO_LEDGER_CHAIN_BREAK")
        self.assertEqual(refusal["receipt_sha256"], receipts[1]["receipt_sha256"])
        self.assertFalse(refusal["consequence_committed"])


class ExactRetryTests(LedgerCase):
    def test_an_identical_retry_returns_the_prior_receipt(self):
        first = self.append("R-1", 20, idempotent_on=IDENTITY)
        # Another epoch is still the same transition: hb_reference is not identity,
        # and neither is evidence outside idempotent_on.
        again = self.append("R-1", 21, idempotent_on=IDENTITY,
                            evidence={**EVIDENCE, "carrier": "second"})
        self.assertEqual(again, first)
        self.assertEqual(self.receipt_count(), 1)

    def assert_collides(self, **divergence):
        self.append("R-1", 20, idempotent_on=IDENTITY)
        with self.assertRaises(ValueError) as raised:
            self.append("R-1", 20, idempotent_on=IDENTITY, **divergence)
        self.assertEqual(str(raised.exception), "ledger_receipt_collision")
        self.assertEqual(self.receipt_count(), 1)

    def test_a_divergent_successor_collides(self):
        self.assert_collides(successor=OTHER)

    def test_a_divergent_authority_effect_collides(self):
        self.assert_collides(authority_effect="STATE_TRANSITION")

    def test_a_divergent_predecessor_collides(self):
        self.assert_collides(predecessor=OTHER)

    def test_divergent_identity_evidence_collides(self):
        self.assert_collides(evidence={**EVIDENCE, "request_sha256": "e" * 64})

    def test_an_identity_key_present_on_one_side_only_collides(self):
        self.assert_collides(evidence={"carrier": "first"})

    def test_without_idempotency_a_repeat_is_its_own_receipt(self):
        """Callers that do not opt in keep minting, over a verified chain."""
        self.append("P-1", 20)
        self.append("P-1", 21, successor=OTHER)
        self.assertEqual(self.receipt_count(), 2)


class CompareAndSwapRaceTests(LedgerCase):
    def test_a_writer_that_loses_the_comparison_returns_the_winners_receipt(self):
        """Deterministic interleaving: the competitor lands between read and publish."""
        landed = []
        store = self.store

        class Interleaved(ledger_store.PosixLedgerStore):
            def append_transaction(inner, *args, **kwargs):
                if not landed:
                    competitor = ledger_store.PosixLedgerStore(store.root)
                    landed.append(emit.append("RACE-1", "TEST_CLASS", BEFORE, AFTER,
                                              dict(EVIDENCE), "NONE", hb_epoch=E0 + 70,
                                              store=competitor, idempotent_on=IDENTITY))
                return super().append_transaction(*args, **kwargs)

        late = emit.append("RACE-1", "TEST_CLASS", BEFORE, AFTER,
                           {**EVIDENCE, "carrier": "late"}, "NONE", hb_epoch=E0 + 71,
                           store=Interleaved(self.root), idempotent_on=IDENTITY)
        self.assertEqual(late, landed[0])
        self.assertEqual(self.receipt_count(), 1)
        self.assertEqual(self.head()["receipt_sha256"], landed[0]["receipt_sha256"])

    def test_concurrent_processes_appending_one_transition_mint_one_receipt(self):
        with multiprocessing.Manager() as manager:
            results = manager.Queue()
            processes = [multiprocessing.Process(target=race_worker, args=(str(self.root), results))
                         for _ in range(6)]
            for process in processes:
                process.start()
            for process in processes:
                process.join(30)
                self.assertEqual(process.exitcode, 0)
            digests = {results.get(timeout=2) for _ in processes}
        self.assertEqual(len(digests), 1)
        self.assertEqual(self.receipt_count(), 1)
        self.assertEqual(self.head()["receipt_sha256"], digests.pop())


if __name__ == "__main__":
    unittest.main()
