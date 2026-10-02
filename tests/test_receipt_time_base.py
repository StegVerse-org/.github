"""The time base of a canonical receipt is the heartbeat, not a wall clock.

No real-world clock is necessary for the ecosystem: the heartbeat is the
reference, declared `OSCILLATOR_ONLY` in the organization boundary contract,
in every InTr envelope and in the carrier frame. The receipt emitters
contradicted that. Both stamped `datetime.now()` into the hashed body, and the
repository ledger contract went further -- it listed `observed_at` among its
required fields while leaving `hb_reference` optional, so every receipt
carried a mandatory clock reading beside a heartbeat that defaulted to null.

A receipt whose body carries a clock reading cannot be reproduced: two nodes
emitting the same transition disagree in the digest, and a replay cannot
recompute what it is checking.

`.stegverse/transition-ledger/emit.py` had no test and no workflow before
this, so the repository-receipt cases here are its first coverage.

Source validation only. No authority effect is claimed.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMIT = ROOT / ".stegverse/transition-ledger/emit.py"
REPO_CONTRACT = json.loads((ROOT / ".stegverse/transition-ledger/contract.json").read_text())

spec = importlib.util.spec_from_file_location("org_append_time", ROOT / "resident-runtime/aggregate_repo_transition.py")
org = importlib.util.module_from_spec(spec)
spec.loader.exec_module(org)

EPOCH = 4_200
STATE_BEFORE = "sha256:" + "a" * 64
STATE_AFTER = "sha256:" + "b" * 64
CLOCK_FIELDS = ("observed_at", "timestamp", "emitted_at", "sampled_at")


def repo_receipt(transition_id="time-base-1"):
    body = {
        "schema": "stegverse.repo-transition-receipt/v1",
        "repository": "StegVerse-org/StegVerse-SDK",
        "transition_id": transition_id,
    }
    return {**body, "receipt_sha256": org.sha(body)}


def emit_repo_receipt(root, transition_id="t-1", hb_epoch=EPOCH):
    command = [sys.executable, str(EMIT),
               "--transition-id", transition_id, "--transition-class", "TEST",
               "--predecessor-state-sha256", STATE_BEFORE,
               "--successor-state-sha256", STATE_AFTER]
    if hb_epoch is not None:
        command += ["--hb-epoch", str(hb_epoch)]
    environment = dict(os.environ, STEGVERSE_REPO_LEDGER_ROOT=str(root))
    completed = subprocess.run(command, capture_output=True, text=True, env=environment, cwd=str(ROOT))
    if completed.returncode != 0:
        raise AssertionError("emit failed: " + completed.stderr)
    return json.loads(completed.stdout.splitlines()[-1])


class RepositoryLedgerContractTests(unittest.TestCase):
    def test_the_contract_requires_the_heartbeat_and_not_a_clock(self):
        required = REPO_CONTRACT["required_fields"]
        self.assertIn("hb_reference", required)
        for field in CLOCK_FIELDS:
            self.assertNotIn(field, required)


class RepositoryReceiptTests(unittest.TestCase):
    def test_a_repository_receipt_carries_no_clock_reading(self):
        with tempfile.TemporaryDirectory() as root:
            receipt = emit_repo_receipt(root)
            for field in CLOCK_FIELDS:
                self.assertNotIn(field, receipt)
            self.assertEqual(receipt["hb_reference"]["epoch"], EPOCH)
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)

    def test_a_repository_receipt_satisfies_its_own_contract(self):
        with tempfile.TemporaryDirectory() as root:
            receipt = emit_repo_receipt(root)
            for field in REPO_CONTRACT["required_fields"]:
                self.assertIn(field, receipt, field)

    def test_the_same_repository_transition_at_the_same_tick_is_reproducible(self):
        """Two emitters of one transition must agree in the digest."""
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            a = emit_repo_receipt(first)
            b = emit_repo_receipt(second)
            self.assertEqual(a["receipt_sha256"], b["receipt_sha256"])

    def test_a_repository_receipt_without_a_tick_marks_itself_derived(self):
        with tempfile.TemporaryDirectory() as root:
            receipt = emit_repo_receipt(root, hb_epoch=None)
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], True)
            self.assertIn("sampled_unix_ns", receipt["hb_reference"])


class OrganizationReceiptTests(unittest.TestCase):
    def _append(self, root, transition_id="time-base-1", hb_epoch=EPOCH):
        os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = root
        return org.append(repo_receipt(transition_id), "REPO_STATE_PROPAGATION",
                          STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=hb_epoch)

    def test_an_organization_receipt_carries_no_clock_reading(self):
        with tempfile.TemporaryDirectory() as root:
            receipt = self._append(root)
            for field in CLOCK_FIELDS:
                self.assertNotIn(field, receipt)
            self.assertEqual(receipt["hb_reference"]["epoch"], EPOCH)
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)

    def test_the_same_organization_transition_at_the_same_tick_is_reproducible(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            a = self._append(first)
            b = self._append(second)
            self.assertEqual(a["receipt_sha256"], b["receipt_sha256"])

    def test_a_different_tick_gives_a_different_organization_receipt(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            a = self._append(first, hb_epoch=EPOCH)
            b = self._append(second, hb_epoch=EPOCH + 1)
            self.assertNotEqual(a["receipt_sha256"], b["receipt_sha256"])

    def test_an_organization_receipt_without_a_tick_marks_itself_derived(self):
        with tempfile.TemporaryDirectory() as root:
            receipt = self._append(root, hb_epoch=None)
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], True)

    def test_the_chain_still_links_and_validates_across_appends(self):
        """Replacing the time field must not disturb the hash chain."""
        with tempfile.TemporaryDirectory() as root:
            first = self._append(root, "chain-1")
            second = self._append(root, "chain-2")
            self.assertIsNone(first["previous_receipt_sha256"])
            self.assertEqual(second["previous_receipt_sha256"], first["receipt_sha256"])
            for receipt in (first, second):
                body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
                self.assertEqual(org.sha(body), receipt["receipt_sha256"])


if __name__ == "__main__":
    unittest.main()
