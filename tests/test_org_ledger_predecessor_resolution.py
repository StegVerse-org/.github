"""Predecessor resolution, explicit genesis and exact source retention for the organization ledger.

ORGANIZATION-ROLE-REFERENCE-MIGRATION-FINAL-REVIEW-002, tests T1-T4 and T8-T11:
FROM_HEAD binds the current HEAD inside each compare-and-swap attempt; GENESIS
opens an empty chain and nothing else; a refusal carries its disposition and
writes nothing; the exact source receipt is retained in the same transaction.
"""
import importlib.util
import json
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("org_append_resolution", ROOT / "resident-runtime/aggregate_repo_transition.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
store_spec = importlib.util.spec_from_file_location("ledger_store_resolution", ROOT / "resident-runtime/ledger_store.py")
ledger = importlib.util.module_from_spec(store_spec)
store_spec.loader.exec_module(ledger)

STATE_AFTER = "sha256:" + "b" * 64


def repo_receipt(number):
    body = {"schema": "stegverse.repo-transition-receipt/v1", "repository": "StegVerse-org/StegVerse-SDK",
            "transition_id": "resolution-" + str(number)}
    return {**body, "receipt_sha256": module.sha(body)}


def documents(root):
    return sorted(str(p.relative_to(root)) for p in Path(root).rglob("*.json"))


def worker(root, number, predecessor, results):
    os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = root
    try:
        receipt = module.append(repo_receipt(number), "REPO_STATE_PROPAGATION", predecessor, STATE_AFTER, {}, "NONE")
        results.put(("ALLOW", receipt["receipt_sha256"]))
    except module.OrgLedgerAppendRefused as refused:
        results.put((refused.disposition, refused.failed_predicate))
    except BaseException as error:  # noqa: BLE001 - reported to the parent
        results.put(("ERROR", type(error).__name__ + ":" + str(error)))


def run_concurrently(root, numbers, predecessor):
    with multiprocessing.Manager() as manager:
        results = manager.Queue()
        processes = [multiprocessing.Process(target=worker, args=(root, n, predecessor, results)) for n in numbers]
        for process in processes:
            process.start()
        for process in processes:
            process.join(30)
        return [results.get(timeout=5) for _ in processes]


def chain(root):
    store = ledger.PosixLedgerStore(root)
    cursor = store.get(ledger.HEAD_KEY)["receipt_sha256"]
    out = []
    while cursor:
        receipt = store.get(ledger.receipt_key(cursor))
        out.append(receipt)
        cursor = receipt["previous_receipt_sha256"]
    return list(reversed(out))


class Genesis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.store = ledger.PosixLedgerStore(self.root)

    def append(self, number, predecessor):
        return module.append(repo_receipt(number), "REPO_STATE_PROPAGATION", predecessor, STATE_AFTER, {}, "NONE",
                             store=self.store)

    def test_T8_from_head_on_empty_ledger_fails_closed_and_writes_nothing(self):
        with self.assertRaises(module.OrgLedgerAppendRefused) as refused:
            self.append(1, module.FROM_HEAD)
        self.assertEqual((refused.exception.disposition, refused.exception.failed_predicate),
                         ("FAIL_CLOSED", "ORG_LEDGER_GENESIS_NOT_DECLARED"))
        self.assertEqual(refused.exception.retry_entrypoint, "resident-runtime/aggregate_repo_transition.py::append")
        self.assertEqual(documents(self.root), [])

    def test_T9_genesis_on_empty_ledger_opens_the_chain_explicitly(self):
        receipt = self.append(1, module.GENESIS)
        self.assertIsNone(receipt["predecessor_org_state_sha256"])
        self.assertIsNone(receipt["previous_receipt_sha256"])
        self.assertIs(receipt["chain_genesis"], True)
        self.assertEqual(self.store.get(ledger.HEAD_KEY)["receipt_sha256"], receipt["receipt_sha256"])

    def test_T10_genesis_on_non_empty_ledger_is_denied_and_writes_nothing(self):
        self.append(1, module.GENESIS)
        before = documents(self.root)
        with self.assertRaises(module.OrgLedgerAppendRefused) as refused:
            self.append(2, module.GENESIS)
        self.assertEqual((refused.exception.disposition, refused.exception.failed_predicate),
                         ("DENY", "ORG_LEDGER_GENESIS_ON_NON_EMPTY_LEDGER"))
        self.assertEqual(documents(self.root), before)

    def test_explicit_digest_and_from_head_after_genesis(self):
        first = self.append(1, module.GENESIS)
        second = self.append(2, module.FROM_HEAD)
        self.assertEqual(second["predecessor_org_state_sha256"], first["receipt_sha256"])
        self.assertNotIn("chain_genesis", second)
        explicit = "sha256:" + "c" * 64
        third = self.append(3, explicit)
        self.assertEqual(third["predecessor_org_state_sha256"], explicit)
        with self.assertRaises(SystemExit):
            self.append(4, "not-a-digest")


class Retention(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.store = ledger.PosixLedgerStore(self.root)

    def test_T3_T4_exact_source_and_organization_receipt_readback(self):
        source = repo_receipt(1)
        receipt = module.append(source, "REPO_STATE_PROPAGATION", module.GENESIS, STATE_AFTER, {}, "NONE", store=self.store)
        retained = self.store.get(ledger.source_key(receipt["source_transition_sha256"]))
        self.assertEqual(retained, source)
        self.assertEqual(module.verify_source(retained)["source_transition_sha256"], receipt["source_transition_sha256"])
        self.assertEqual(self.store.get(ledger.receipt_key(receipt["receipt_sha256"])), receipt)

    def test_T2_lost_comparison_or_collision_writes_nothing(self):
        module.append(repo_receipt(1), "REPO_STATE_PROPAGATION", module.GENESIS, STATE_AFTER, {}, "NONE", store=self.store)
        before = documents(self.root)
        stale = {"organization": "StegVerse-org", "receipt_sha256": "sha256:" + "0" * 64}
        immutable = {ledger.source_key("sha256:" + "1" * 64): {"x": 1}}
        self.assertFalse(self.store.append_transaction(ledger.receipt_key("sha256:" + "2" * 64), {"y": 2}, stale,
                                                       {"receipt_sha256": "sha256:" + "2" * 64}, immutable=immutable))
        self.assertEqual(documents(self.root), before)
        head = self.store.get(ledger.HEAD_KEY)
        existing_source = sorted(self.store.list_prefix(ledger.SOURCE_PREFIX))[0]
        with self.assertRaises(ValueError):
            self.store.append_transaction(ledger.receipt_key("sha256:" + "3" * 64), {"z": 3}, head,
                                          {"receipt_sha256": "sha256:" + "3" * 64},
                                          immutable={existing_source: {"different": True}})
        self.assertEqual(documents(self.root), before)

    def test_orphan_source_copy_requires_recovery(self):
        module.append(repo_receipt(1), "REPO_STATE_PROPAGATION", module.GENESIS, STATE_AFTER, {}, "NONE", store=self.store)
        self.store.put(ledger.source_key("sha256:" + "9" * 64), {"stray": True})
        with self.assertRaisesRegex(SystemExit, "ORG_LEDGER_ORPHAN_SOURCE_RECEIPTS_RECOVERY_REQUIRED"):
            module.append(repo_receipt(2), "REPO_STATE_PROPAGATION", module.FROM_HEAD, STATE_AFTER, {}, "NONE",
                          store=self.store)


class Concurrency(unittest.TestCase):
    def test_T1_concurrent_from_head_binds_the_receipt_each_append_follows(self):
        with tempfile.TemporaryDirectory() as root:
            os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = root
            module.append(repo_receipt(0), "REPO_STATE_PROPAGATION", module.GENESIS, STATE_AFTER, {}, "NONE")
            results = run_concurrently(root, range(1, 13), module.FROM_HEAD)
            self.assertEqual(sorted(r[0] for r in results), ["ALLOW"] * 12, results)
            receipts = chain(root)
            self.assertEqual(len(receipts), 13)
            self.assertIs(receipts[0]["chain_genesis"], True)
            for receipt in receipts[1:]:
                self.assertEqual(receipt["predecessor_org_state_sha256"], receipt["previous_receipt_sha256"])
            self.assertEqual(len(ledger.PosixLedgerStore(root).list_prefix(ledger.SOURCE_PREFIX)), 13)

    def test_T11_exactly_one_concurrent_genesis_wins(self):
        with tempfile.TemporaryDirectory() as root:
            results = run_concurrently(root, range(8), module.GENESIS)
            allowed = [r for r in results if r[0] == "ALLOW"]
            denied = [r for r in results if r[0] != "ALLOW"]
            self.assertEqual(len(allowed), 1, results)
            self.assertEqual(set(denied), {("DENY", "ORG_LEDGER_GENESIS_ON_NON_EMPTY_LEDGER")}, results)
            store = ledger.PosixLedgerStore(root)
            self.assertEqual(len(store.list_prefix(ledger.RECEIPT_PREFIX)), 1)
            self.assertEqual(len(store.list_prefix(ledger.SOURCE_PREFIX)), 1)
            self.assertEqual(json.loads((Path(root) / "HEAD.json").read_text())["receipt_sha256"], allowed[0][1])


if __name__ == "__main__":
    unittest.main()
