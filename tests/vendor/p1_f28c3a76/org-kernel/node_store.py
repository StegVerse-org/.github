#!/usr/bin/env python3
"""State for a StegOS node, addressed rather than located.

StegOS lives on the network. A StegNode is where it takes entry or egress,
ephemeral, materializing at whatever point is needed -- including on a physical
device at the boundary between the network and a KV. Neither is a host, so
neither can be addressed by a path on one machine.

The kernel's semantics already hold that: frames are content addressed, the
packet digest is recomputed on recovery, receipts are hash linked, and the
heartbeat is an oscillator count rather than a clock read. What bound the
kernel to one machine was its state. The federation mesh resolved under
`Path.home()`, consumption markers and the outbox resolved under a repository
checkout, and a directory glob was the enumeration. None of those survive a
node that materializes somewhere else.

This module is the seam, and it is deliberately the same seam
`resident-runtime/ledger_store.py` cut for the ledger: address by key, let a
store map keys onto whatever substrate it has, and keep the POSIX filesystem
as a first-class implementation rather than a legacy path.

Two stores, because there are two lifetimes:

* The **mesh store** carries frames. It is the network between nodes, and it
  outlives any node that reads it.
* A **node store** carries one node's own consumption markers, outbox and
  work intake. It belongs to that node instance and is expected to be
  ephemeral.

Keys keep the names the filesystem already gave these documents, so an
existing mesh or checkout resolves to the same paths and nothing migrates.

Nothing here grants authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

MESH_FRAME_PREFIX = "frames.d/"
NODE_SEEN_PREFIX = "federation/seen.d/"
NODE_OUTBOX_PREFIX = "federation/outbox/"
NODE_INTAKE_PREFIX = "control/inbox/"
NODE_CYCLE_PREFIX = "federation/cycles.d/"

# How a store came to know where it is. A node that was told is portable; a
# node that derived its location from the host it happens to be running on is
# not, and says so rather than appearing equivalent.
SUPPLIED = "SUPPLIED"
FROM_ENVIRONMENT = "DERIVED_FROM_ENVIRONMENT"
FROM_HOME_DIRECTORY = "DERIVED_FROM_HOME_DIRECTORY"
PORTABLE_PROVENANCE = frozenset({SUPPLIED})


def frame_key(frame):
    """Address a frame by what it carries, not by when it arrived."""
    digest = hashlib.sha256(
        (frame["packet_id"] + "|" + frame["frame_sha256"]).encode()).hexdigest()
    return MESH_FRAME_PREFIX + digest + ".json"


def frame_name(key):
    """The basename a frame key ends in.

    Consumption markers record this name, so it stays the dedup identity: a
    mesh already carrying markers must not re-consume every frame in it.
    """
    return key.rsplit("/", 1)[-1]


def seen_key(name):
    return NODE_SEEN_PREFIX + hashlib.sha256(name.encode()).hexdigest() + ".json"


def outbox_key(packet_id):
    return NODE_OUTBOX_PREFIX + hashlib.sha256(packet_id.encode()).hexdigest() + ".json"


def intake_key(packet_id, communication_id):
    digest = hashlib.sha256((packet_id + "|" + str(communication_id)).encode()).hexdigest()
    return NODE_INTAKE_PREFIX + digest + ".json"


def cycle_key(receipt):
    """Address a resident cycle by what it reported.

    A cycle receipt is this node's own record of one pass, so it belongs with
    the node's other markers rather than in a checkout. Addressed by content
    for the same reason frames are: two writers of the same report agree byte
    for byte, and a report that differs is a different cycle rather than an
    overwrite of the last one. A `latest` file would keep only the most recent
    pass and lose every one before it.
    """
    digest = hashlib.sha256(json.dumps(
        receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return NODE_CYCLE_PREFIX + digest + ".json"


class WriteOnceCollision(ValueError):
    """A key already holds something different from what is being written."""


class PosixStateStore:
    """Node or mesh state on one POSIX filesystem.

    Durability is same-directory atomic replacement plus an fsync of the file
    and its directory, which is what the kernel's bare `write_text` did not
    give it. Writes are write-once by key: a key that already holds an equal
    document is a no-op, and one that holds a different document is a
    collision rather than an overwrite.

    There is no lock here. Frames and markers are content addressed, so two
    writers of the same document agree byte for byte and two writers of
    different documents use different keys. A networked store needs the same
    property and gets it the same way.
    """

    kind = "POSIX_FILESYSTEM"

    def __init__(self, root, *, provenance=SUPPLIED):
        self.root = Path(root)
        self.provenance = provenance

    @property
    def portable(self):
        """Whether this store's location would survive moving the node."""
        return self.provenance in PORTABLE_PROVENANCE

    def _path(self, key):
        return self.root / key

    def locator(self, key):
        """How this substrate names the key, for a reader outside the kernel."""
        return str(self._path(key))

    def exists(self, key):
        return self._path(key).is_file()

    def get(self, key):
        path = self._path(key)
        if not path.is_file():
            return None
        return json.loads(path.read_text())

    def put_once(self, key, value):
        """Write `value` at `key` unless it already holds something else.

        The document is written and synced in full under a temporary name, then
        linked to the key. `os.link` refuses an existing target, so two writers
        racing for one key cannot both win: the loser finds the key held and
        compares, exactly as a later writer would. A crash before the link
        leaves only a temporary, which no listing returns; a crash after it
        leaves the complete document.
        """
        existing = self.get(key)
        if existing is not None:
            if existing != value:
                raise WriteOnceCollision(key)
            return key
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".node-put-", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(json.dumps(value, indent=2, sort_keys=True).encode() + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temp, path)
            except FileExistsError:
                if self.get(key) != value:
                    raise WriteOnceCollision(key)
                return key
            self._sync_directory(path.parent)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return key

    def list_prefix(self, prefix):
        """Every key under `prefix`, sorted, so enumeration is reproducible."""
        directory = self._path(prefix.rstrip("/"))
        if not directory.is_dir():
            return []
        return sorted(prefix + item.name for item in directory.glob("*.json"))

    @staticmethod
    def _sync_directory(directory):
        fd = os.open(str(directory), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
