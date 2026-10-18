"""PR-1c: the organization-ledger append and the observation window read no clock.

`aggregate_repo_transition.append` and `observation_window.open_window` used to
derive the heartbeat epoch from the host clock when none was supplied (and mark
it derived_from_clock true). Both now apply the shared supplied-epoch rule
(`supplied_epoch_failure`, SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH): an absent
epoch is six-field FAIL_CLOSED HB_EPOCH_NOT_SUPPLIED, an invalid one
HB_EPOCH_INVALID, and nothing is written.

Source validation only. No runtime observation and no authority effect is
claimed.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
GOAL = "INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001"
PREDICATE = "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH"
EPOCH = 4128
STATE_BEFORE = "sha256:" + "a" * 64
STATE_AFTER = "sha256:" + "b" * 64
INVALID = ("+33", " 33", "3_3", "33.0", 33.0, True, 31, -1, "", [])


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


org = _load("pr1c_org_append", "resident-runtime/aggregate_repo_transition.py")
OW = _load("pr1c_observation_window", "resident-runtime/observation_window.py")


def repo_receipt(number=1):
    body = {"schema": "stegverse.repo-transition-receipt/v1",
            "repository": "StegVerse-org/StegVerse-SDK", "transition_id": "pr1c-" + str(number)}
    return {**body, "receipt_sha256": org.sha(body)}


def function_lines(path, name):
    """The source lines of a top-level function, as Lane B and 03dd hash them."""
    lines = (ROOT / path).read_text().splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith("def " + name + "("))
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() and not lines[i].startswith((" ", "\t", ")"))), len(lines))
    while not lines[end - 1].strip():
        end -= 1
    return "".join(lines[start:end])


class SixFields:
    def assertSixFieldRefusal(self, refusal, code):
        self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
        self.assertEqual(refusal["failure_code"], code)
        self.assertEqual(refusal["failed_predicate"], PREDICATE)
        self.assertEqual(refusal["owning_existing_goal"], GOAL)
        for field in SIX_FIELDS:
            self.assertIsInstance(refusal[field], str, field)
            self.assertTrue(refusal[field].strip(), field)


class OrganizationAppendTests(SixFields, unittest.TestCase):
    def append(self, root, hb_epoch):
        with patch.dict(os.environ, {"STEGVERSE_ORG_LEDGER_ROOT": root}):
            return org.append(repo_receipt(), "REPO_STATE_PROPAGATION", STATE_BEFORE, STATE_AFTER,
                              {}, "NONE", hb_epoch=hb_epoch)

    def test_no_epoch_is_hb_epoch_not_supplied_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(org.OrgLedgerEpochRefused) as refused:
                self.append(root, None)
            self.assertSixFieldRefusal(refused.exception.refusal, "HB_EPOCH_NOT_SUPPLIED")
            self.assertEqual(refused.exception.refusal["retry_entrypoint"],
                             "resident-runtime/aggregate_repo_transition.py::append")
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_an_invalid_epoch_is_hb_epoch_invalid_and_writes_nothing(self):
        for bad in INVALID:
            with self.subTest(repr(bad)), tempfile.TemporaryDirectory() as root:
                with self.assertRaises(org.OrgLedgerEpochRefused) as refused:
                    self.append(root, bad)
                self.assertSixFieldRefusal(refused.exception.refusal, "HB_EPOCH_INVALID")
                self.assertEqual(list(Path(root).iterdir()), [])

    def test_the_refusal_is_still_an_append_refusal(self):
        # Existing callers that catch OrgLedgerAppendRefused or SystemExit keep working.
        self.assertTrue(issubclass(org.OrgLedgerEpochRefused, org.OrgLedgerAppendRefused))
        self.assertTrue(issubclass(org.OrgLedgerEpochRefused, SystemExit))

    def test_a_supplied_epoch_reads_no_clock(self):
        for supplied in (EPOCH, str(EPOCH)):
            with self.subTest(repr(supplied)), tempfile.TemporaryDirectory() as root:
                receipt = self.append(root, supplied)
                self.assertEqual(receipt["hb_reference"]["epoch"], EPOCH)
                self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)
                self.assertNotIn("sampled_unix_ns", receipt["hb_reference"])

    def test_the_cli_without_hb_epoch_prints_the_refusal_and_exits_1(self):
        with tempfile.TemporaryDirectory() as work:
            source = Path(work) / "receipt.json"
            source.write_text(json.dumps(repo_receipt()))
            ledger = Path(work) / "ledger"
            completed = subprocess.run(
                [sys.executable, str(ROOT / "resident-runtime/aggregate_repo_transition.py"),
                 "--repo-receipt", str(source), "--predecessor-org-state-sha256", STATE_BEFORE,
                 "--successor-org-state-sha256", STATE_AFTER],
                capture_output=True, text=True,
                env={**os.environ, "STEGVERSE_ORG_LEDGER_ROOT": str(ledger)})
            self.assertEqual(completed.returncode, 1, completed.stderr)
            self.assertSixFieldRefusal(json.loads(completed.stdout.splitlines()[-1]), "HB_EPOCH_NOT_SUPPLIED")
            self.assertFalse(ledger.exists())

    def test_the_vendored_rule_is_byte_identical_to_the_shared_one(self):
        shared = function_lines("org-boundary/runtime/capability_ingress.py", "supplied_epoch_failure")
        vendored = function_lines("resident-runtime/aggregate_repo_transition.py", "supplied_epoch_failure")
        self.assertEqual(hashlib.sha256(vendored.encode()).hexdigest(),
                         hashlib.sha256(shared.encode()).hexdigest())
        self.assertTrue(hashlib.sha256(shared.encode()).hexdigest().startswith("7f36f0e6"))


class ObservationWindowTests(SixFields, unittest.TestCase):
    def open(self, epoch):
        return OW.open_window([], countdown_hb=300, epoch=epoch, observed_through="test:pr1c")

    def test_no_epoch_is_hb_epoch_not_supplied(self):
        with self.assertRaises(OW.WindowEpochRefused) as refused:
            self.open(None)
        self.assertSixFieldRefusal(refused.exception.refusal, "HB_EPOCH_NOT_SUPPLIED")
        self.assertEqual(refused.exception.refusal["retry_entrypoint"],
                         "resident-runtime/observation_window.py::open_window")
        self.assertIsInstance(refused.exception, OW.WindowRefused)

    def test_an_invalid_epoch_is_hb_epoch_invalid(self):
        for bad in INVALID:
            with self.subTest(repr(bad)):
                with self.assertRaises(OW.WindowEpochRefused) as refused:
                    self.open(bad)
                self.assertSixFieldRefusal(refused.exception.refusal, "HB_EPOCH_INVALID")

    def test_a_supplied_epoch_is_not_clock_derived(self):
        snapshot = self.open(EPOCH)
        self.assertEqual(snapshot["opened_at_epoch"], EPOCH)
        self.assertFalse(snapshot["epoch_derived_from_clock"])
        self.assertNotIn("sampled_unix_ns", snapshot["heartbeat"])


if __name__ == "__main__":
    unittest.main()
