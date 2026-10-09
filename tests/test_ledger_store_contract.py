"""Contract regressions for an organization ledger store.

The ledger's model is substrate-neutral already -- content-addressed, hash
linked, verified by recomputing digests. Its storage was not: a POSIX
filesystem under a home directory, an advisory lock as the whole concurrency
model, same-filesystem rename for durability, directory enumeration as the
integrity check.

These tests fix the contract a store must satisfy, so a key-value
implementation for ephemeral nodes can be validated against the same suite
rather than against a reading of the filesystem one. `StoreContractTests` is
written against `make_store` and is the part a sibling implementation
inherits -- `GitStoreContractTests` runs it unchanged against a git ref;
`PosixLayoutTests` pins what is specific to the filesystem.

Source validation only. No authority effect is claimed.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ledger_store", ROOT / "resident-runtime/ledger_store.py")
ledger_store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger_store)

DIGEST = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64


class StoreContractTests(unittest.TestCase):
    """What any ledger store must do, whatever it stores onto."""

    def make_store(self, root):
        store = ledger_store.PosixLedgerStore(root)
        store.initialize()
        return store

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.store = self.make_store(self._dir.name)

    def test_a_key_that_was_never_written_reads_as_absent(self):
        self.assertIsNone(self.store.get(ledger_store.HEAD_KEY))
        self.assertIsNone(self.store.get(ledger_store.receipt_key(DIGEST)))
        self.assertFalse(self.store.exists(ledger_store.HEAD_KEY))

    def test_a_document_round_trips_unchanged(self):
        value = {"organization": "StegVerse-org", "receipt_sha256": DIGEST, "nested": {"n": [1, 2]}}
        self.store.put(ledger_store.HEAD_KEY, value)
        self.assertEqual(self.store.get(ledger_store.HEAD_KEY), value)
        self.assertTrue(self.store.exists(ledger_store.HEAD_KEY))

    def test_a_receipt_key_is_derived_from_its_own_digest(self):
        self.assertEqual(ledger_store.receipt_key(DIGEST), ledger_store.receipt_key(DIGEST))
        self.assertNotEqual(ledger_store.receipt_key(DIGEST), ledger_store.receipt_key(OTHER))
        self.assertTrue(ledger_store.receipt_key(DIGEST).startswith(ledger_store.RECEIPT_PREFIX))

    def test_listing_a_prefix_returns_exactly_the_keys_written_under_it(self):
        self.assertEqual(self.store.list_prefix(ledger_store.RECEIPT_PREFIX), set())
        for digest in (DIGEST, OTHER):
            self.store.put(ledger_store.receipt_key(digest), {"receipt_sha256": digest})
        # HEAD is not under the receipt prefix and must not appear in it.
        self.store.put(ledger_store.HEAD_KEY, {"receipt_sha256": DIGEST})
        self.assertEqual(
            self.store.list_prefix(ledger_store.RECEIPT_PREFIX),
            {ledger_store.receipt_key(DIGEST), ledger_store.receipt_key(OTHER)},
        )

    def test_compare_and_swap_publishes_only_from_the_expected_value(self):
        head = ledger_store.HEAD_KEY
        self.assertTrue(self.store.compare_and_swap(head, None, {"receipt_sha256": DIGEST}))
        self.assertEqual(self.store.get(head), {"receipt_sha256": DIGEST})
        # A writer holding a stale view must not publish over the newer one.
        self.assertFalse(self.store.compare_and_swap(head, None, {"receipt_sha256": OTHER}))
        self.assertFalse(self.store.compare_and_swap(
            head, {"receipt_sha256": "sha256:" + "c" * 64}, {"receipt_sha256": OTHER}))
        self.assertEqual(self.store.get(head), {"receipt_sha256": DIGEST})
        # From the value it actually holds, the swap lands.
        self.assertTrue(self.store.compare_and_swap(
            head, {"receipt_sha256": DIGEST}, {"receipt_sha256": OTHER}))
        self.assertEqual(self.store.get(head), {"receipt_sha256": OTHER})

    def test_exclusive_is_reentrant_so_a_nested_swap_does_not_deadlock(self):
        """compare_and_swap serializes internally and may be called from inside
        an append that already holds the store."""
        with self.store.exclusive():
            self.assertTrue(self.store.compare_and_swap(
                ledger_store.HEAD_KEY, None, {"receipt_sha256": DIGEST}))
            with self.store.exclusive():
                self.store.put(ledger_store.receipt_key(DIGEST), {"receipt_sha256": DIGEST})
        self.assertEqual(self.store.get(ledger_store.HEAD_KEY), {"receipt_sha256": DIGEST})

    def test_a_locator_names_the_key_for_a_reader_outside_the_ledger(self):
        locator = self.store.locator(ledger_store.receipt_key(DIGEST))
        self.assertIsInstance(locator, str)
        self.assertTrue(locator)


class GitStoreContractTests(StoreContractTests):
    """The same contract, on a ref in a temporary bare repository."""

    def make_store(self, root):
        store = ledger_store.GitLedgerStore(Path(root) / "ledger.git", "refs/test/contract-ledger")
        store.initialize()
        return store


class PosixLayoutTests(unittest.TestCase):
    """What is specific to the filesystem store, pinned so the indirection
    cannot quietly rename an existing ledger root."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)
        self.store = ledger_store.PosixLedgerStore(self.root)
        self.store.initialize()

    def test_keys_land_on_the_paths_the_ledger_has_always_used(self):
        self.store.put(ledger_store.HEAD_KEY, {"receipt_sha256": DIGEST})
        self.store.put(ledger_store.receipt_key(DIGEST), {"receipt_sha256": DIGEST})
        self.assertTrue((self.root / "HEAD.json").is_file())
        self.assertTrue((self.root / "receipts" / ("a" * 64 + ".json")).is_file())

    def test_a_document_is_written_as_readable_sorted_json(self):
        self.store.put(ledger_store.HEAD_KEY, {"b": 2, "a": 1})
        text = (self.root / "HEAD.json").read_text()
        self.assertEqual(json.loads(text), {"a": 1, "b": 2})
        self.assertLess(text.index('"a"'), text.index('"b"'))
        self.assertTrue(text.endswith("\n"))

    def test_a_put_leaves_no_temporary_file_behind(self):
        self.store.put(ledger_store.HEAD_KEY, {"receipt_sha256": DIGEST})
        self.assertEqual([p.name for p in self.root.glob(".org-append-*")], [])

    def test_a_replacement_put_does_not_duplicate_the_key(self):
        self.store.put(ledger_store.HEAD_KEY, {"receipt_sha256": DIGEST})
        self.store.put(ledger_store.HEAD_KEY, {"receipt_sha256": OTHER})
        self.assertEqual(self.store.get(ledger_store.HEAD_KEY), {"receipt_sha256": OTHER})
        self.assertEqual(len(list(self.root.glob("HEAD*"))), 1)


if __name__ == "__main__":
    unittest.main()
