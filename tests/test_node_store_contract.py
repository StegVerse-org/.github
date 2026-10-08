"""The contract a StegOS node-state store must satisfy.

Split deliberately. `StateStoreContractTests` is the part any substrate must
honour -- a key-value store on the network inherits these cases unchanged, and
they are what make a sibling implementation a sibling rather than a rewrite.
`PosixLayoutTests` is the part that is only true of a filesystem, kept
separate so it is obvious which assertions a networked store is not expected
to reproduce.

The keys also pin the on-disk layout. The kernel wrote these documents by path
before state was addressed, so a key that resolved anywhere else would orphan
an existing mesh or checkout: the frame name is the dedup identity recorded in
every consumption marker, and changing it would make a node re-consume every
frame it had already handled.

Source validation only. No authority effect is claimed.
"""
import importlib.util
import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("node_store", ROOT / "org-kernel/node_store.py")
node_store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(node_store)

FRAME = {"packet_id": "pkt-1", "frame_sha256": "sha256:" + "a" * 64, "destination_org": "Kernel-Test"}


def store(root, **kwargs):
    return node_store.PosixStateStore(root, **kwargs)


class KeyAddressingTests(unittest.TestCase):
    def test_a_frame_key_carries_the_frame_identity(self):
        key = node_store.frame_key(FRAME)
        self.assertTrue(key.startswith(node_store.MESH_FRAME_PREFIX))
        self.assertTrue(key.endswith(".json"))
        self.assertEqual(node_store.frame_key(FRAME), key, "the same frame must address the same key")

    def test_a_different_frame_addresses_a_different_key(self):
        other = {**FRAME, "frame_sha256": "sha256:" + "b" * 64}
        self.assertNotEqual(node_store.frame_key(FRAME), node_store.frame_key(other))

    def test_the_frame_name_is_the_last_segment_of_its_key(self):
        """Consumption markers record the name, so it stays the dedup identity."""
        key = node_store.frame_key(FRAME)
        self.assertEqual(node_store.frame_name(key), key.rsplit("/", 1)[-1])
        self.assertNotIn("/", node_store.frame_name(key))

    def test_node_namespaces_do_not_collide(self):
        prefixes = {node_store.MESH_FRAME_PREFIX, node_store.NODE_SEEN_PREFIX,
                    node_store.NODE_OUTBOX_PREFIX, node_store.NODE_INTAKE_PREFIX}
        self.assertEqual(len(prefixes), 4)
        for prefix in prefixes:
            self.assertTrue(prefix.endswith("/"), prefix)


class StateStoreContractTests(unittest.TestCase):
    """Substrate-independent. A networked store inherits every case here."""

    def test_an_absent_key_reads_as_absent_rather_than_raising(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(store(root).get("federation/outbox/missing.json"))
            self.assertFalse(store(root).exists("federation/outbox/missing.json"))

    def test_a_document_round_trips(self):
        with tempfile.TemporaryDirectory() as root:
            subject = store(root)
            subject.put_once("frames.d/a.json", FRAME)
            self.assertTrue(subject.exists("frames.d/a.json"))
            self.assertEqual(subject.get("frames.d/a.json"), FRAME)

    def test_writing_an_equal_document_again_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as root:
            subject = store(root)
            subject.put_once("frames.d/a.json", FRAME)
            subject.put_once("frames.d/a.json", dict(FRAME))
            self.assertEqual(subject.get("frames.d/a.json"), FRAME)

    def test_writing_a_different_document_to_a_held_key_is_a_collision(self):
        """Write-once, not last-writer-wins: an overwrite would lose a frame."""
        with tempfile.TemporaryDirectory() as root:
            subject = store(root)
            subject.put_once("frames.d/a.json", FRAME)
            with self.assertRaises(node_store.WriteOnceCollision):
                subject.put_once("frames.d/a.json", {**FRAME, "destination_org": "Other"})
            self.assertEqual(subject.get("frames.d/a.json"), FRAME)

    def test_listing_a_prefix_returns_only_that_prefix(self):
        with tempfile.TemporaryDirectory() as root:
            subject = store(root)
            subject.put_once("frames.d/a.json", FRAME)
            subject.put_once("federation/seen.d/b.json", {"frame_name": "a.json"})
            self.assertEqual(subject.list_prefix("frames.d/"), ["frames.d/a.json"])
            self.assertEqual(subject.list_prefix(node_store.NODE_SEEN_PREFIX),
                             ["federation/seen.d/b.json"])

    def test_listing_an_empty_prefix_is_empty_rather_than_an_error(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(store(root).list_prefix("frames.d/"), [])

    def test_listing_is_sorted_so_enumeration_is_reproducible(self):
        with tempfile.TemporaryDirectory() as root:
            subject = store(root)
            for name in ("c", "a", "b"):
                subject.put_once("frames.d/" + name + ".json", {**FRAME, "packet_id": name})
            self.assertEqual(subject.list_prefix("frames.d/"),
                             ["frames.d/a.json", "frames.d/b.json", "frames.d/c.json"])

    def test_a_store_reports_whether_its_location_would_survive_a_move(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertTrue(store(root, provenance=node_store.SUPPLIED).portable)
            self.assertFalse(store(root, provenance=node_store.FROM_HOME_DIRECTORY).portable)
            self.assertFalse(store(root, provenance=node_store.FROM_ENVIRONMENT).portable)


class _CheckBypassed(node_store.PosixStateStore):
    """A store whose first read misses, as a writer racing another one would."""

    def __init__(self, root):
        super().__init__(root)
        self._missed = False

    def get(self, key):
        if not self._missed:
            self._missed = True
            return None
        return super().get(key)


def _race(root, packet_id, start, results):
    start.wait()
    try:
        store(root).put_once("frames.d/a.json", {**FRAME, "packet_id": packet_id})
        results.put("WON")
    except node_store.WriteOnceCollision:
        results.put("COLLIDED")


class WriteOnceUnderContentionTests(unittest.TestCase):
    """A held key is never overwritten, including by a writer that checked first."""

    def test_a_writer_that_missed_the_held_key_still_collides(self):
        with tempfile.TemporaryDirectory() as root:
            store(root).put_once("frames.d/a.json", FRAME)
            with self.assertRaises(node_store.WriteOnceCollision):
                _CheckBypassed(root).put_once("frames.d/a.json", {**FRAME, "destination_org": "Other"})
            self.assertEqual(store(root).get("frames.d/a.json"), FRAME)

    def test_a_writer_that_missed_an_equal_document_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as root:
            store(root).put_once("frames.d/a.json", FRAME)
            _CheckBypassed(root).put_once("frames.d/a.json", dict(FRAME))
            self.assertEqual(store(root).get("frames.d/a.json"), FRAME)

    def test_concurrent_writers_of_different_documents_leave_exactly_one(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = multiprocessing.get_context("fork")
            start, results = ctx.Event(), ctx.Queue()
            writers = [ctx.Process(target=_race, args=(root, "pkt-%d" % i, start, results)) for i in range(8)]
            for writer in writers:
                writer.start()
            start.set()
            for writer in writers:
                writer.join(30)
            outcomes = sorted(results.get(timeout=5) for _ in writers)
            self.assertEqual(outcomes.count("WON"), 1, outcomes)
            self.assertEqual(outcomes.count("COLLIDED"), 7, outcomes)
            held = store(root).get("frames.d/a.json")
            self.assertTrue(held["packet_id"].startswith("pkt-"))
            self.assertEqual(list((Path(root) / "frames.d").glob(".node-put-*")), [])

    def test_a_write_interrupted_before_the_link_leaves_the_key_absent(self):
        """A crash leaves a temporary that no listing returns; the next write proceeds."""
        with tempfile.TemporaryDirectory() as root:
            frames = Path(root) / "frames.d"
            frames.mkdir()
            (frames / ".node-put-orphan.tmp").write_text(json.dumps({**FRAME, "packet_id": "torn"}))
            subject = store(root)
            self.assertIsNone(subject.get("frames.d/a.json"))
            self.assertEqual(subject.list_prefix("frames.d/"), [])
            subject.put_once("frames.d/a.json", FRAME)
            self.assertEqual(subject.list_prefix("frames.d/"), ["frames.d/a.json"])
            self.assertEqual(subject.get("frames.d/a.json"), FRAME)


class PosixLayoutTests(unittest.TestCase):
    """Only true of a filesystem. A networked store is not expected to match."""

    def test_a_key_resolves_to_the_path_the_kernel_used_before(self):
        with tempfile.TemporaryDirectory() as root:
            subject = store(root)
            self.assertEqual(subject.locator("frames.d/a.json"), str(Path(root) / "frames.d/a.json"))

    def test_a_document_is_stored_as_sorted_readable_json(self):
        with tempfile.TemporaryDirectory() as root:
            store(root).put_once("frames.d/a.json", FRAME)
            raw = (Path(root) / "frames.d/a.json").read_text()
            self.assertEqual(raw, json.dumps(FRAME, indent=2, sort_keys=True) + "\n")

    def test_no_temporary_file_survives_a_write(self):
        """The document is complete before it is linked, so a reader never observes a partial frame."""
        with tempfile.TemporaryDirectory() as root:
            store(root).put_once("frames.d/a.json", FRAME)
            self.assertEqual(list((Path(root) / "frames.d").glob(".node-put-*")), [])

    def test_the_store_creates_the_namespace_it_writes_into(self):
        with tempfile.TemporaryDirectory() as root:
            store(root).put_once(node_store.NODE_INTAKE_PREFIX + "a.json", {"state": "QUEUED"})
            self.assertTrue((Path(root) / "control/inbox/a.json").is_file())

    def test_the_store_names_its_substrate(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(store(root).kind, "POSIX_FILESYSTEM")


if __name__ == "__main__":
    unittest.main()
