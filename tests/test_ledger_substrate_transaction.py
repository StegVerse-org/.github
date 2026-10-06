"""Portable ledger transaction regressions for SVORG-STEGOS-PORTABILITY-001.

The appenders below share no filesystem and hold no caller-side lock. They
share only a storage substrate whose transaction primitive atomically compares
HEAD and publishes receipt + HEAD. A lost comparison writes nothing.
"""
import importlib.util
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

repo_emit = load("portable_repo_emit", ".stegverse/transition-ledger/emit.py")
org_emit = load("portable_org_emit", "resident-runtime/aggregate_repo_transition.py")
ledger = load("portable_ledger_store", "resident-runtime/ledger_store.py")

STATE_BEFORE = "sha256:" + "a" * 64
STATE_AFTER = "sha256:" + "b" * 64
EPOCH = 4400

class TransactionalMemoryStore:
    kind = "TRANSACTIONAL_MEMORY_TEST_SUBSTRATE"

    def __init__(self):
        self.docs = {}
        self._transaction = threading.Lock()

    def initialize(self):
        return None

    def locator(self, key):
        return "memory://" + key

    def get(self, key):
        value = self.docs.get(key)
        return None if value is None else dict(value)

    def exists(self, key):
        return key in self.docs

    def list_prefix(self, prefix):
        return {key for key in self.docs if key.startswith(prefix)}

    def append_transaction(self, receipt_key_name, receipt, expected_head, new_head):
        with self._transaction:
            current = self.docs.get(ledger.HEAD_KEY)
            if current != expected_head:
                return False
            existing = self.docs.get(receipt_key_name)
            if existing is not None and existing != receipt:
                raise ValueError("ledger_receipt_collision")
            self.docs[receipt_key_name] = dict(receipt)
            self.docs[ledger.HEAD_KEY] = dict(new_head)
            return True

def reachable(store):
    head = store.get(ledger.HEAD_KEY)
    cursor = (head or {}).get("receipt_sha256")
    visited = []
    while cursor:
        if cursor in visited:
            raise AssertionError("cycle")
        visited.append(cursor)
        record = store.get(ledger.receipt_key(cursor))
        if record is None:
            raise AssertionError("missing receipt " + cursor)
        cursor = record.get("previous_receipt_sha256")
    return visited

class PortableRepositoryAppendTests(unittest.TestCase):
    def test_appenders_sharing_no_filesystem_leave_one_reconstructable_chain(self):
        store = TransactionalMemoryStore()
        errors = []
        def worker(index):
            try:
                repo_emit.append("portable-repo-" + str(index), "CONCURRENCY",
                                 STATE_BEFORE, STATE_AFTER, {}, "NONE",
                                 hb_epoch=EPOCH, store=store)
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(errors, [])
        visited = reachable(store)
        self.assertEqual(len(visited), 12)
        self.assertEqual(store.list_prefix(ledger.RECEIPT_PREFIX),
                         {ledger.receipt_key(digest) for digest in visited})

class PortableOrganizationAppendTests(unittest.TestCase):
    def source_receipt(self, index):
        body = {
            "schema": "stegverse.repo-transition-receipt/v1",
            "repository": "StegVerse-org/StegVerse-SDK",
            "transition_id": "portable-org-" + str(index),
        }
        return {**body, "receipt_sha256": org_emit.sha(body)}

    def test_organization_appenders_use_the_same_transaction_contract(self):
        store = TransactionalMemoryStore()
        errors = []
        def worker(index):
            try:
                org_emit.append(self.source_receipt(index), "REPO_STATE_PROPAGATION",
                                STATE_BEFORE, STATE_AFTER, {}, "NONE",
                                hb_epoch=EPOCH, store=store)
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(errors, [])
        visited = reachable(store)
        self.assertEqual(len(visited), 12)
        self.assertEqual(store.list_prefix(ledger.RECEIPT_PREFIX),
                         {ledger.receipt_key(digest) for digest in visited})

if __name__ == "__main__":
    unittest.main()
