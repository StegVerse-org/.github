"""One manifest is one transition, however many times it is delivered.

`ORGANIZATION_SDK_MANIFEST_INGRESS` derives its transition id from the request,
but appended a repository receipt and then an organization receipt on every
call. A resubmitted manifest was recorded twice at both levels; a governance
manifest asked the deciding organization a second time; and a run that stopped
between the two appends left a repository receipt the organization never
consumed, which the next delivery then duplicated.

These cases drive the real operation against supplied ledger roots and assert:
a replay returns the recorded receipts; a run that stopped between the levels
is completed rather than repeated; the same transition id over a different
manifest refuses; concurrent appenders of one transition commit it once; a
replayed refusal is recorded once; and a replayed emission at a supplied epoch
publishes no second frame and records no second pair. Without a supplied epoch
an emission is not reproducible, and each is still recorded.

Source validation only. No authority effect is claimed.
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The receiving operation's own test fixture, loaded by path as the rest of this
# directory loads modules, so the two suites cannot drift apart. Loaded as a
# module rather than imported by name, so its cases are not collected twice.
_bspec = importlib.util.spec_from_file_location(
    "manifest_ingress_fixture", ROOT / "tests/test_organization_manifest_ingress.py")
base = importlib.util.module_from_spec(_bspec)
_bspec.loader.exec_module(base)
ingress = base.ingress
organization_ledger = base.organization_ledger
repository_ledger = ingress.repository_ledger
REPO = ("STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1")
ORG = ("STEGVERSE_ORG_LEDGER_ROOT", "stegverse.organization-transition-receipt/v1")


class IdempotentIngressTests(base.ReceivingOperationTests):
    """The receiving operation's fixture; only the replay cases below run here."""

    def receipts(self, level, transition_class=None):
        found = self.ledger_receipts(*level)
        if transition_class is not None:
            found = [r for r in found if r.get("transition_class") == transition_class]
        return found

    def test_replay_of_the_same_delivery_returns_the_recorded_receipts(self):
        first = self.receive()
        second = self.receive()
        self.assertEqual(first["disposition"], "ALLOW", first.get("detail"))
        self.assertEqual(second["disposition"], "ALLOW", second.get("detail"))
        self.assertIs(first["transition_replayed"], False)
        self.assertIs(second["transition_replayed"], True)
        self.assertEqual(first["repository_receipt_sha256"], second["repository_receipt_sha256"])
        self.assertEqual(first["organization_receipt_sha256"], second["organization_receipt_sha256"])
        self.assertEqual(len(self.receipts(REPO)), 1)
        self.assertEqual(len(self.receipts(ORG)), 1)

    def test_replay_under_another_packet_id_is_the_same_transition(self):
        """The packet is the carrier; the manifest is the transition."""
        first = self.receive()
        second = self.receive(packet_id="org-ingress-redelivered")
        self.assertEqual(first["organization_receipt_sha256"], second["organization_receipt_sha256"])
        self.assertEqual(len(self.receipts(REPO)), 1)
        self.assertEqual(len(self.receipts(ORG)), 1)

    def test_replay_after_the_organization_append_failed_completes_the_chain_once(self):
        original = ingress.organization_ledger.append
        calls = {"n": 0}

        def fails_once(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise organization_ledger.OrgLedgerAppendRefused(
                    "FAIL_CLOSED", "ORG_LEDGER_GENESIS_NOT_DECLARED")
            return original(*args, **kwargs)

        ingress.organization_ledger.append = fails_once
        self.addCleanup(setattr, ingress.organization_ledger, "append", original)
        with self.assertRaises(organization_ledger.OrgLedgerAppendRefused):
            self.receive()
        self.assertEqual(len(self.receipts(REPO)), 1)
        self.assertEqual(len(self.receipts(ORG)), 0)

        completed = self.receive()
        self.assertEqual(completed["disposition"], "ALLOW", completed.get("detail"))
        self.assertIs(completed["transition_replayed"], True)
        repository, = self.receipts(REPO)
        organization, = self.receipts(ORG)
        self.assertEqual(organization["repo_receipt_sha256"], repository["receipt_sha256"])
        self.assertEqual(completed["organization_receipt_sha256"], organization["receipt_sha256"])

    def test_replay_completion_takes_its_epoch_from_the_retained_receipt(self):
        """A retry carrying a different epoch still rebuilds the first attempt's records."""
        original = ingress.organization_ledger.append
        calls = {"n": 0}

        def fails_once(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise organization_ledger.OrgLedgerAppendRefused("FAIL_CLOSED", "SIMULATED")
            return original(*args, **kwargs)

        ingress.organization_ledger.append = fails_once
        self.addCleanup(setattr, ingress.organization_ledger, "append", original)
        with self.assertRaises(organization_ledger.OrgLedgerAppendRefused):
            self.receive(hb_epoch=32)
        self.receive(hb_epoch=99)
        organization, = self.receipts(ORG)
        self.assertEqual(organization["hb_reference"]["epoch"], 32)

    def test_replay_of_one_transition_id_over_another_manifest_refuses(self):
        first = self.receive()
        repository, = self.receipts(REPO)
        # The same id, recorded over a different starting state: what a
        # truncated-digest collision would look like on the chain.
        with self.assertRaises(ValueError) as raised:
            repository_ledger.append(repository["transition_id"], repository["transition_class"],
                                     "sha256:" + "2" * 64, repository["successor_state_sha256"],
                                     repository["evidence"], "NONE", hb_epoch=34,
                                     idempotent_on=("request_sha256",))
        self.assertEqual(str(raised.exception), "ledger_receipt_collision")
        self.assertEqual(first["disposition"], "ALLOW")
        self.assertEqual(len(self.receipts(REPO)), 1)

    def test_replay_with_a_colliding_id_is_recorded_as_a_refusal_not_an_admission(self):
        self.receive()
        repository, = self.receipts(REPO)
        original = ingress.derive_execution_request

        def same_id_other_manifest(value, boundary):
            request = dict(original(value, boundary))
            request["canonical_manifest_sha256"] = "f" * 64
            return request

        ingress.derive_execution_request = same_id_other_manifest
        self.addCleanup(setattr, ingress, "derive_execution_request", original)
        refused = self.receive(packet_id="org-ingress-collision")
        self.assertEqual(refused["disposition"], "FAIL_CLOSED")
        self.assertEqual(refused["failed_predicate"], "ONE_TRANSITION_ID_BINDS_ONE_MANIFEST")
        self.assertEqual(len(self.receipts(REPO, ingress.OPERATION_ID)), 1)

    def test_replay_of_a_refusal_is_recorded_once(self):
        first = self.refuse()
        second = self.refuse()
        self.assertEqual(first["disposition"], "FAIL_CLOSED")
        self.assertEqual(first["refusal_repository_receipt_sha256"],
                         second["refusal_repository_receipt_sha256"])
        self.assertEqual(first["refusal_organization_receipt_sha256"],
                         second["refusal_organization_receipt_sha256"])
        self.assertEqual(len(self.receipts(REPO, ingress.REFUSED_CLASS)), 1)
        self.assertEqual(len(self.receipts(ORG)), 1)


class ConcurrentAppendTests(unittest.TestCase):
    """Appenders of one transition sharing one kernel commit it once."""

    def setUp(self):
        self._work = tempfile.TemporaryDirectory()
        self.addCleanup(self._work.cleanup)
        self.store = repository_ledger.ledger_store.PosixLedgerStore(Path(self._work.name) / "repo")

    def test_concurrent_appenders_of_one_transition_commit_once(self):
        results, errors = [], []

        def appender():
            try:
                results.append(repository_ledger.append(
                    "CONCURRENT-1", "TEST_CLASS", "sha256:" + "a" * 64, "sha256:" + "b" * 64,
                    {"request_sha256": "c" * 64}, "NONE", hb_epoch=40,
                    idempotent_on=("request_sha256",), store=self.store))
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [threading.Thread(target=appender) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len({r["receipt_sha256"] for r in results}), 1)
        self.assertEqual(len(self.store.list_prefix(repository_ledger.ledger_store.RECEIPT_PREFIX)), 1)

    def test_without_idempotency_each_append_is_its_own_receipt(self):
        """Callers that did not opt in keep the old behaviour."""
        for epoch in (41, 42):
            repository_ledger.append("PLAIN-1", "TEST_CLASS", "sha256:" + "a" * 64,
                                     "sha256:" + "b" * 64, {}, "NONE", hb_epoch=epoch,
                                     store=self.store)
        self.assertEqual(len(self.store.list_prefix(repository_ledger.ledger_store.RECEIPT_PREFIX)), 2)

    def test_an_organization_receipt_consuming_a_source_under_another_class_collides(self):
        org_store = repository_ledger.ledger_store.PosixLedgerStore(Path(self._work.name) / "org")
        source = repository_ledger.append("SRC-1", "TEST_CLASS", "sha256:" + "a" * 64,
                                          "sha256:" + "b" * 64, {}, "NONE", hb_epoch=43,
                                          store=self.store)
        genesis = organization_ledger.append(source, "REPO_STATE_PROPAGATION",
                                             organization_ledger.GENESIS, "sha256:" + "b" * 64,
                                             {}, "NONE", hb_epoch=43, store=org_store,
                                             idempotent=True)
        again = organization_ledger.append(source, "REPO_STATE_PROPAGATION",
                                           organization_ledger.FROM_HEAD, "sha256:" + "b" * 64,
                                           {}, "NONE", hb_epoch=44, store=org_store,
                                           idempotent=True)
        self.assertEqual(genesis["receipt_sha256"], again["receipt_sha256"])
        with self.assertRaises(ValueError) as raised:
            organization_ledger.append(source, "SOME_OTHER_CLASS", organization_ledger.FROM_HEAD,
                                       "sha256:" + "b" * 64, {}, "NONE", hb_epoch=45,
                                       store=org_store, idempotent=True)
        self.assertEqual(str(raised.exception), "ledger_receipt_collision")


def load_tests(loader, tests, pattern):
    """Only this module's cases: the inherited ones run in their own module."""
    suite = unittest.TestSuite()
    for name in loader.getTestCaseNames(IdempotentIngressTests):
        if name.startswith("test_replay"):
            suite.addTest(IdempotentIngressTests(name))
    suite.addTests(loader.loadTestsFromTestCase(ConcurrentAppendTests))
    return suite


if __name__ == "__main__":
    unittest.main()
