"""Source regression tests for serialized organization-ledger append."""
import importlib.util
import json
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "resident-runtime" / "aggregate_repo_transition.py"
spec = importlib.util.spec_from_file_location("org_append", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

STATE_BEFORE = "sha256:" + "a" * 64
STATE_AFTER = "sha256:" + "b" * 64
# A supplied heartbeat epoch: an append without one is refused (PR-1c).
HB_EPOCH = 4128


def make_repo_receipt(number):
    body = {
        "schema": "stegverse.repo-transition-receipt/v1", "hb_reference": {"epoch": 4096, "generation": 4096, "heartbeat_id": "HB:4096", "phase_offset_ns": 0, "frequency_hz": 100, "progression_dependency": "OSCILLATOR_ONLY", "derived_from_clock": False, "authority_effect": "NONE"},
        "repository": "StegVerse-org/StegVerse-SDK",
        "transition_id": "test-" + str(number),
    }
    return {**body, "receipt_sha256": module.sha(body)}


def append_worker(root, number, results):
    os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = root
    try:
        module.append(make_repo_receipt(number), "REPO_STATE_PROPAGATION",
                      STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=HB_EPOCH)
        results.put("OK")
    except Exception as error:
        results.put(type(error).__name__ + ":" + str(error))


class OrgLedgerAppendTests(unittest.TestCase):
    def test_concurrent_append_is_serialized_and_reconstructable(self):
        with tempfile.TemporaryDirectory() as root:
            with multiprocessing.Manager() as manager:
                results = manager.Queue()
                processes = [
                    multiprocessing.Process(target=append_worker, args=(root, i, results))
                    for i in range(12)
                ]
                for process in processes:
                    process.start()
                for process in processes:
                    process.join(20)
                    self.assertEqual(process.exitcode, 0)
                self.assertEqual([results.get(timeout=2) for _ in processes], ["OK"] * 12)
            receipts = Path(root) / "receipts"
            head = json.loads((Path(root) / "HEAD.json").read_text())
            cursor = head["receipt_sha256"]
            visited = set()
            while cursor:
                self.assertNotIn(cursor, visited)
                visited.add(cursor)
                receipt = json.loads((receipts / (cursor.split(":", 1)[1] + ".json")).read_text())
                body = dict(receipt)
                body.pop("receipt_sha256")
                self.assertEqual(module.sha(body), cursor)
                cursor = receipt["previous_receipt_sha256"]
            self.assertEqual(len(visited), 12)

    def test_unpublished_receipt_fails_closed_without_advancing_head(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {"STEGVERSE_ORG_LEDGER_ROOT": root}):
                first = module.append(make_repo_receipt(1), "REPO_STATE_PROPAGATION",
                                      STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=HB_EPOCH)
                head = (Path(root) / "HEAD.json").read_bytes()
                orphan_body = dict(first)
                orphan_body.pop("receipt_sha256")
                orphan_body["repo_transition_id"] = "unpublished"
                orphan_digest = module.sha(orphan_body)
                orphan = {**orphan_body, "receipt_sha256": orphan_digest}
                path = Path(root) / "receipts" / (orphan_digest.split(":", 1)[1] + ".json")
                path.write_text(json.dumps(orphan))
                with self.assertRaisesRegex(SystemExit, "ORG_LEDGER_UNPUBLISHED_OR_ORPHAN"):
                    module.append(make_repo_receipt(2), "REPO_STATE_PROPAGATION",
                                  STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=HB_EPOCH)
                self.assertEqual((Path(root) / "HEAD.json").read_bytes(), head)

    def test_missing_head_with_existing_receipts_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {"STEGVERSE_ORG_LEDGER_ROOT": root}):
                module.append(make_repo_receipt(1), "REPO_STATE_PROPAGATION",
                              STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=HB_EPOCH)
                module.append(make_repo_receipt(2), "REPO_STATE_PROPAGATION",
                              STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=HB_EPOCH)
                (Path(root) / "HEAD.json").unlink()
                with self.assertRaisesRegex(SystemExit, "ORG_LEDGER_HEAD_MISSING"):
                    module.append(make_repo_receipt(3), "REPO_STATE_PROPAGATION",
                                  STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=HB_EPOCH)

    def test_a_torn_genesis_append_is_completed_not_refused(self):
        """B-P36q: the genesis receipt was written and HEAD was not; the next append publishes it."""
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {"STEGVERSE_ORG_LEDGER_ROOT": root}):
                first = module.append(make_repo_receipt(1), "REPO_STATE_PROPAGATION",
                                      STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=HB_EPOCH)
                (Path(root) / "HEAD.json").unlink()
                again = module.append(make_repo_receipt(1), "REPO_STATE_PROPAGATION",
                                      STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=HB_EPOCH,
                                      idempotent=True)
                self.assertEqual(again["receipt_sha256"], first["receipt_sha256"])
                self.assertEqual(json.loads((Path(root) / "HEAD.json").read_text())["receipt_sha256"],
                                 first["receipt_sha256"])
                self.assertEqual(len(list((Path(root) / "receipts").glob("*.json"))), 1)

    def test_missing_head_with_existing_receipt_fails_closed(self):
        """Base name kept (required-verification TEST_PRESENT_AT_BASE_RUNS_AT_HEAD); it asserts the rule that
        replaced the old one, never the old rule. The old rule refused a ledger whose single receipt
        had no HEAD. #207 (B-P36q) treats that as a torn genesis append and completes it. A missing
        HEAD over a longer chain still fails closed
        (test_missing_head_with_existing_receipts_fails_closed).
        """
        self.test_a_torn_genesis_append_is_completed_not_refused()

    def test_a_torn_append_on_a_chain_is_completed_and_the_chain_continues(self):
        """B-P36q: an OSError on the HEAD write after the receipt write; the next appends complete once."""
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {"STEGVERSE_ORG_LEDGER_ROOT": root}):
                module.append(make_repo_receipt(1), "REPO_STATE_PROPAGATION",
                              STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=HB_EPOCH)
                store_class = module.open_store(module.parse_locator(root)).__class__
                real_put = store_class.put
                armed = {"on": True}

                def torn_put(self, key, value):
                    if key == module.HEAD_KEY and armed["on"]:
                        armed["on"] = False
                        raise OSError(5, "Input/output error")
                    return real_put(self, key, value)

                with patch.object(store_class, "put", torn_put), self.assertRaises(OSError):
                    module.append(make_repo_receipt(2), "REPO_STATE_PROPAGATION",
                                  STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=HB_EPOCH, idempotent=True)
                retried = module.append(make_repo_receipt(2), "REPO_STATE_PROPAGATION",
                                        STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=HB_EPOCH, idempotent=True)
                later = module.append(make_repo_receipt(3), "REPO_STATE_PROPAGATION",
                                      STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=HB_EPOCH)
                self.assertEqual(len(list((Path(root) / "receipts").glob("*.json"))), 3)
                self.assertEqual(later["previous_receipt_sha256"], retried["receipt_sha256"])
                self.assertEqual(json.loads((Path(root) / "HEAD.json").read_text())["receipt_sha256"],
                                 later["receipt_sha256"])

    def test_a_torn_append_after_the_source_copy_is_completed_on_retry(self):
        """B-P36q: an OSError on the receipt write leaves only the pending source copy; the retry completes once."""
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {"STEGVERSE_ORG_LEDGER_ROOT": root}):
                module.append(make_repo_receipt(1), "REPO_STATE_PROPAGATION",
                              STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=HB_EPOCH)
                store_class = module.open_store(module.parse_locator(root)).__class__
                real_put = store_class.put
                armed = {"on": True}

                def torn_put(self, key, value):
                    if key.startswith(module.RECEIPT_PREFIX) and armed["on"]:
                        armed["on"] = False
                        raise OSError(5, "Input/output error")
                    return real_put(self, key, value)

                with patch.object(store_class, "put", torn_put), self.assertRaises(OSError):
                    module.append(make_repo_receipt(2), "REPO_STATE_PROPAGATION",
                                  STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=HB_EPOCH, idempotent=True)
                pending = list((Path(root) / "source-receipts").glob("*.json"))
                retried = module.append(make_repo_receipt(2), "REPO_STATE_PROPAGATION",
                                        STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=HB_EPOCH, idempotent=True)
                self.assertEqual(len(list((Path(root) / "receipts").glob("*.json"))), 2)
                self.assertEqual(sorted(pending), sorted((Path(root) / "source-receipts").glob("*.json")))
                self.assertEqual(json.loads((Path(root) / "HEAD.json").read_text())["receipt_sha256"],
                                 retried["receipt_sha256"])

    def test_malformed_repo_receipt_fails_closed_without_creating_head(self):
        """A repo receipt missing an admission field must reach a named fail-closed
        predicate, not surface as an unstructured KeyError from the receipt body."""
        cases = {
            "missing repository": {
                "schema": "stegverse.repo-transition-receipt/v1", "hb_reference": {"epoch": 4096, "generation": 4096, "heartbeat_id": "HB:4096", "phase_offset_ns": 0, "frequency_hz": 100, "progression_dependency": "OSCILLATOR_ONLY", "derived_from_clock": False, "authority_effect": "NONE"},
                "transition_id": "malformed-1",
            },
            "missing transition_id": {
                "schema": "stegverse.repo-transition-receipt/v1", "hb_reference": {"epoch": 4096, "generation": 4096, "heartbeat_id": "HB:4096", "phase_offset_ns": 0, "frequency_hz": 100, "progression_dependency": "OSCILLATOR_ONLY", "derived_from_clock": False, "authority_effect": "NONE"},
                "repository": "StegVerse-org/StegVerse-SDK",
            },
        }
        for label, body in cases.items():
            with self.subTest(label):
                receipt = {**body, "receipt_sha256": module.sha(body)}
                with tempfile.TemporaryDirectory() as root:
                    with patch.dict(os.environ, {"STEGVERSE_ORG_LEDGER_ROOT": root}):
                        with self.assertRaises(SystemExit):
                            module.append(receipt, "REPO_STATE_PROPAGATION",
                                          STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=HB_EPOCH)
                        self.assertFalse((Path(root) / "HEAD.json").exists())

    def test_non_digest_org_state_fields_fail_closed_without_creating_head(self):
        """A field named *_sha256 must carry a digest; otherwise the chain would
        record a predecessor/successor claim no replay can check."""
        cases = {
            "non-digest predecessor": ("state-before", STATE_AFTER),
            "non-digest successor": (STATE_BEFORE, "state-after"),
            "short digest": ("sha256:" + "a" * 63, STATE_AFTER),
            "none": (None, STATE_AFTER),
        }
        for label, (predecessor, successor) in cases.items():
            with self.subTest(label):
                with tempfile.TemporaryDirectory() as root:
                    with patch.dict(os.environ, {"STEGVERSE_ORG_LEDGER_ROOT": root}):
                        with self.assertRaisesRegex(SystemExit, "NOT_A_SHA256_DIGEST"):
                            module.append(make_repo_receipt(1), "REPO_STATE_PROPAGATION",
                                          predecessor, successor, {}, "NONE", hb_epoch=HB_EPOCH)
                        self.assertFalse((Path(root) / "HEAD.json").exists())


if __name__ == "__main__":
    unittest.main()
