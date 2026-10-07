#!/usr/bin/env python3
"""Storage for an append-only organization ledger, addressed rather than located.

The ledger's own model is already substrate-neutral: receipts are content
addressed and hash linked, and the chain is verified by recomputing digests.
What bound it to one machine was its storage, not its model -- a POSIX
filesystem under a home directory, a `fcntl` advisory lock as the whole
concurrency model, same-filesystem atomic rename for durability, and
directory enumeration as the integrity check. None of those survive a move to
ephemeral nodes that share no filesystem.

This module is the seam. The ledger addresses documents by key; a store maps
keys onto whatever substrate it has. `PosixLedgerStore` keeps today's exact
behaviour, so the filesystem remains a first-class implementation rather than
a legacy path, and a key-value store is a sibling rather than a rewrite.

Keys are `HEAD`, `receipts/<hex>` and `source-receipts/<hex>`. Nothing here
grants authority.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

HEAD_KEY = "HEAD.json"
RECEIPT_PREFIX = "receipts/"
SOURCE_PREFIX = "source-receipts/"


def receipt_key(digest):
    """Address a receipt by its own digest, so the key carries the content.

    The key keeps the `.json` suffix a filesystem store would give the file
    anyway, so a POSIX store's paths are unchanged by this indirection and an
    existing ledger root stays readable.
    """
    return RECEIPT_PREFIX + digest.split(":", 1)[1] + ".json"


def source_key(digest):
    """Address an exact retained source transition receipt by its source digest."""
    return SOURCE_PREFIX + digest.split(":", 1)[1] + ".json"


class PosixLedgerStore:
    """A ledger store on one POSIX filesystem.

    Durability is same-directory atomic replacement plus an fsync of the file
    and its directory. Appenders are serialized by an advisory lock, which
    holds only within one kernel -- two nodes on separate filesystems would
    each take "the lock" and both append. A networked store implements
    `exclusive` as a no-op and serializes through `compare_and_swap` instead.
    """

    kind = "POSIX_FILESYSTEM"

    def __init__(self, root):
        self.root = Path(root)
        self._lock_path = self.root / ".append.lock"
        self._held = 0

    def _path(self, key):
        return self.root / key

    def initialize(self):
        (self.root / RECEIPT_PREFIX.rstrip("/")).mkdir(parents=True, exist_ok=True)

    def locator(self, key):
        """How this substrate names the key, for a reader outside the ledger."""
        return str(self._path(key))

    def exists(self, key):
        return self._path(key).is_file()

    def get(self, key):
        path = self._path(key)
        if not path.is_file():
            return None
        return json.loads(path.read_text())

    def put(self, key, value):
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".org-append-", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(json.dumps(value, indent=2, sort_keys=True).encode() + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
            self._sync_directory(path.parent)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def list_prefix(self, prefix):
        directory = self._path(prefix.rstrip("/"))
        if not directory.is_dir():
            return set()
        return {prefix + item.name for item in directory.glob("*.json")}

    @contextmanager
    def exclusive(self):
        """Serialize appenders, re-entrantly within one store instance.

        `flock` is held per open file description, so a second acquisition
        from the same process would block on the first forever. Callers nest
        legitimately -- compare_and_swap serializes internally and may be
        invoked from inside an append -- so re-entry is counted rather than
        re-locked.
        """
        if self._held:
            self._held += 1
            try:
                yield self
            finally:
                self._held -= 1
            return
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            self._held = 1
            try:
                yield self
            finally:
                self._held = 0

    def compare_and_swap(self, key, expected, value):
        """Publish `value` at `key` only if it still holds `expected`.

        Serialization a networked store gets natively. Here it is the advisory
        lock again, so the guarantee is the same one `exclusive` gives and no
        stronger.
        """
        with self.exclusive():
            if self.get(key) != expected:
                return False
            self.put(key, value)
            return True


    def append_transaction(self, receipt_key_name, receipt, expected_head, new_head, immutable=None):
        """Atomically publish a receipt and HEAD if HEAD still equals expected_head.

        This is the substrate portability contract. A lost comparison writes
        nothing, so a competing writer cannot leave an orphan receipt. A
        network/KV sibling implements this with its native transaction/CAS;
        POSIX uses its local lock only inside the storage primitive.

        `immutable` maps further content-addressed keys (the exact source
        transition receipt under `source-receipts/`) to their documents. They
        are inside the same boundary: every collision is checked before any
        write, so a refused or lost append writes none of them, and HEAD is
        written last, so a document is published only once HEAD names its
        receipt.
        """
        documents = dict(immutable or {})
        documents[receipt_key_name] = receipt
        with self.exclusive():
            if self.get(HEAD_KEY) != expected_head:
                return False
            missing = []
            for key, value in documents.items():
                existing = self.get(key)
                if existing is not None and existing != value:
                    raise ValueError("ledger_receipt_collision")
                if existing is None:
                    missing.append(key)
            for key in missing:
                self.put(key, documents[key])
            self.put(HEAD_KEY, new_head)
            return True

    @staticmethod
    def _sync_directory(directory):
        fd = os.open(str(directory), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
