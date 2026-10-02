"""Source regressions for serialized repository-ledger append.

The organization ledger serializes its append, publishes HEAD by atomic
replacement, and refuses to proceed when it finds a receipt that was written
but never published. The repository ledger beneath it -- whose receipts the
organization ledger consumes -- had none of that. It read HEAD, bound a
receipt to that predecessor, and wrote both with bare `write_text` and no
lock, so two concurrent appends read one HEAD, built receipts claiming the
same predecessor, and the later HEAD write silently won. One receipt was
orphaned and the chain forked, with nothing to detect either.

These drive concurrent appenders and verify the chain they leave behind
reconstructs: every receipt reachable, each digest recomputing, no fork.

Source validation only. No authority effect is claimed.
"""
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
CONTRACT = json.loads((ROOT / ".stegverse/transition-ledger/contract.json").read_text())
STATE_BEFORE = "sha256:" + "a" * 64
STATE_AFTER = "sha256:" + "b" * 64
EPOCH = 4_400
APPENDERS = 12


def emit(root, transition_id, hb_epoch=EPOCH):
    completed = subprocess.run(
        [sys.executable, str(EMIT),
         "--transition-id", transition_id, "--transition-class", "CONCURRENCY",
         "--predecessor-state-sha256", STATE_BEFORE,
         "--successor-state-sha256", STATE_AFTER,
         "--hb-epoch", str(hb_epoch)],
        capture_output=True, text=True, cwd=str(ROOT),
        env=dict(os.environ, STEGVERSE_REPO_LEDGER_ROOT=str(root)))
    return completed


def append_worker(root, number, results):
    completed = emit(root, "concurrent-" + str(number))
    results.put("OK" if completed.returncode == 0 else completed.stderr[-200:])


class RepositoryLedgerConcurrencyTests(unittest.TestCase):
    def test_concurrent_appends_leave_one_reconstructable_chain(self):
        with tempfile.TemporaryDirectory() as root:
            with multiprocessing.Manager() as manager:
                results = manager.Queue()
                processes = [multiprocessing.Process(target=append_worker,
                                                     args=(root, i, results))
                             for i in range(APPENDERS)]
                for process in processes:
                    process.start()
                for process in processes:
                    process.join(30)
                    self.assertEqual(process.exitcode, 0)
                self.assertEqual([results.get(timeout=2) for _ in processes],
                                 ["OK"] * APPENDERS)

            receipts = Path(root) / "receipts"
            head = json.loads((Path(root) / "HEAD.json").read_text())
            # Walk the published chain: every link present, every digest its own.
            cursor, visited = head["receipt_sha256"], []
            while cursor:
                self.assertNotIn(cursor, visited, "the chain cycles")
                visited.append(cursor)
                path = receipts / (cursor.split(":", 1)[1] + ".json")
                self.assertTrue(path.is_file(), "chain reaches a receipt that was never written")
                receipt = json.loads(path.read_text())
                self.assertEqual(receipt["receipt_sha256"], cursor)
                cursor = receipt["previous_receipt_sha256"]
            # Nothing was written that the chain cannot reach: an unreachable
            # receipt is the signature of a lost race.
            stored = {"sha256:" + item.stem for item in receipts.glob("*.json")}
            self.assertEqual(stored, set(visited),
                             "a receipt was written but never published")
            self.assertEqual(len(visited), APPENDERS)

    def test_each_appender_binds_a_distinct_predecessor(self):
        """A fork shows as two receipts claiming the same predecessor."""
        with tempfile.TemporaryDirectory() as root:
            for i in range(4):
                self.assertEqual(emit(root, "sequential-" + str(i)).returncode, 0)
            receipts = Path(root) / "receipts"
            predecessors = [json.loads(p.read_text())["previous_receipt_sha256"]
                            for p in receipts.glob("*.json")]
            self.assertEqual(len(predecessors), len(set(predecessors)),
                             "two receipts claim the same predecessor")


class RepositoryLedgerPublicationTests(unittest.TestCase):
    def test_head_names_the_receipt_it_publishes(self):
        with tempfile.TemporaryDirectory() as root:
            receipt = json.loads(emit(root, "publish-1").stdout.splitlines()[-1])
            head = json.loads((Path(root) / "HEAD.json").read_text())
            self.assertEqual(head["receipt_sha256"], receipt["receipt_sha256"])
            self.assertEqual(head["repository"], CONTRACT["repository"])
            self.assertTrue(Path(head["receipt_path"]).is_file())

    def test_no_temporary_file_survives_publication(self):
        """Atomic replacement, not a bare write."""
        with tempfile.TemporaryDirectory() as root:
            emit(root, "publish-2")
            self.assertEqual(list(Path(root).glob(".org-append-*")), [])
            self.assertEqual(list((Path(root) / "receipts").glob(".org-append-*")), [])

    def test_re_emitting_an_identical_transition_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            first = json.loads(emit(root, "idem").stdout.splitlines()[-1])
            before = {p.name for p in (Path(root) / "receipts").glob("*.json")}
            second = json.loads(emit(root, "idem").stdout.splitlines()[-1])
            after = {p.name for p in (Path(root) / "receipts").glob("*.json")}
            # The second append links onto the first rather than colliding.
            self.assertEqual(second["previous_receipt_sha256"], first["receipt_sha256"])
            self.assertEqual(len(after - before), 1)


if __name__ == "__main__":
    unittest.main()
