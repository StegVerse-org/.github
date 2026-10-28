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
    body = {"schema": "stegverse.repo-transition-receipt/v1", "hb_reference": {"epoch": 4096, "generation": 4096, "heartbeat_id": "HB:4096", "phase_offset_ns": 0, "frequency_hz": 100, "progression_dependency": "OSCILLATOR_ONLY", "derived_from_clock": False, "authority_effect": "NONE"},
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
    def assertSixFieldRefusal(self, refusal, code, predicate=PREDICATE):
        self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
        self.assertEqual(refusal["failure_code"], code)
        self.assertEqual(refusal["failed_predicate"], predicate)
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
        # The StegVerse-Labs/.github#3282 FINAL text (SHARED_VALIDATOR_SHA256).
        self.assertTrue(hashlib.sha256(shared.encode()).hexdigest().startswith("ad8ff529"))


class SourceEpochTests(SixFields, unittest.TestCase):
    """Repair (a): the two-level binders pass the repository receipt's epoch."""

    def append(self, root, source, hb_epoch=EPOCH):
        with patch.dict(os.environ, {"STEGVERSE_ORG_LEDGER_ROOT": root}):
            return org.append(source, "REPO_STATE_PROPAGATION", STATE_BEFORE, STATE_AFTER,
                              {}, "NONE", hb_epoch=hb_epoch)

    def source(self, reference):
        body = {"schema": "stegverse.repo-transition-receipt/v1",
                "repository": "StegVerse-org/StegVerse-SDK", "transition_id": "pr1c-source",
                "hb_reference": reference}
        return {**body, "receipt_sha256": org.sha(body)}

    def test_a_clock_derived_source_epoch_is_refused_and_writes_nothing(self):
        # The repository receipt was stamped from the clock (emit.py with no
        # epoch, as in P1's HB:478117838 reproduction); its epoch is not a
        # supplied one, so the organization append refuses it.
        derived = {"epoch": 478117838, "derived_from_clock": True, "sampled_unix_ns": 1}
        with tempfile.TemporaryDirectory() as root:
            # B-P31 (StegVerse-org/.github#207, O-1): refused at source verification,
            # before the epoch check, as SOURCE_RECEIPT_IS_CLOCK_PROVENANCE.
            with self.assertRaises(org.SourceReceiptRefused) as refused:
                self.append(root, self.source(derived), hb_epoch=478117838)
            self.assertSixFieldRefusal(refused.exception.refusal, "SOURCE_RECEIPT_IS_CLOCK_PROVENANCE",
                                       "SOURCE_RECEIPT_CARRIES_A_SUPPLIED_EPOCH")
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_a_source_reference_that_is_not_an_object_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            # B-P31 (#207, F5): a reference with no derived_from_clock marker is unmarked.
            with self.assertRaises(org.SourceReceiptRefused) as refused:
                self.append(root, self.source("HB:4128"))
            self.assertSixFieldRefusal(refused.exception.refusal, "HB_EPOCH_PROVENANCE_UNMARKED",
                                       "SOURCE_RECEIPT_CARRIES_A_SUPPLIED_EPOCH")

    def test_a_supplied_source_epoch_is_admitted(self):
        with tempfile.TemporaryDirectory() as root:
            receipt = self.append(root, self.source({"epoch": EPOCH, "derived_from_clock": False}))
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)

    def test_the_two_level_pattern_with_no_epoch_appends_no_organization_receipt(self):
        with tempfile.TemporaryDirectory() as work:
            emit = _load("pr1c_emit", ".stegverse/transition-ledger/emit.py")
            env = {"STEGVERSE_REPO_LEDGER_ROOT": str(Path(work) / "repo"),
                   "STEGVERSE_ORG_LEDGER_ROOT": str(Path(work) / "org")}
            # B-P31 (#207): the repository append itself refuses an absent epoch, so
            # no clock-derived repository receipt exists to propagate.
            with patch.dict(os.environ, env):
                with self.assertRaises(emit.RepoLedgerEpochRefused) as refused:
                    emit.append("PR1C-TWO-LEVEL", "DEMO", STATE_BEFORE, STATE_AFTER, {}, "NONE")
            self.assertSixFieldRefusal(refused.exception.refusal, "HB_EPOCH_NOT_SUPPLIED")
            self.assertFalse((Path(work) / "repo").exists())
            self.assertFalse((Path(work) / "org").exists())


class FederationCyclePropagationTests(SixFields, unittest.TestCase):
    """The cycle supplies its epoch to propagation; without a valid one it refuses before anything runs.

    B-P31 (StegVerse-org/.github#207, §Q/F7): the cycle's own epoch stamps every
    receipt it writes, so an absent or invalid epoch is the cycle's six-field
    OrgLedgerEpochRefused, raised before any frame is consumed or anything written.
    """

    def cycle(self, hb_epoch):
        work = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, work, True)
        repository = "StegVerse-org/StegVerse-SDK"
        body = {"schema": "stegverse.repo-transition-receipt/v1", "repository": repository,
                "transition_id": "NODE_INGRESS_ADMITTED:pr1c", "transition_class": "NODE_INGRESS_ADMITTED",
                "predecessor_state_sha256": STATE_BEFORE, "successor_state_sha256": STATE_AFTER,
                "evidence": {}, "authority_effect": "NONE",
                "hb_reference": {"epoch": 32, "derived_from_clock": False,
                                 "progression_dependency": "OSCILLATOR_ONLY"},
                "ordering": "OSCILLATOR_HEARTBEAT_EPOCH_ONLY", "previous_receipt_sha256": None}
        digest = org.sha(body)
        receipts = work / "homes" / repository / "receipts"
        receipts.mkdir(parents=True)
        (receipts / (digest.split(":", 1)[1] + ".json")).write_text(json.dumps({**body, "receipt_sha256": digest}))
        (receipts.parent / "HEAD.json").write_text(json.dumps({"repository": repository, "receipt_sha256": digest}))
        env = {"STEGVERSE_REPO_LEDGER_HOME": str(work / "homes"), "STEGVERSE_ORG_LEDGER_ROOT": str(work / "org")}
        self.work, self.seeded = work, self.tree(work)
        with patch.dict(os.environ, env):
            cycle = _load("pr1c_federation_cycle", "resident-runtime/federation_cycle.py")
            with patch("sys.stdout"):
                reported = cycle.main(mesh_root=work / "mesh", node_state_root=work / "node", hb_epoch=hb_epoch)
        return reported["repository_propagation"], work

    @staticmethod
    def tree(root):
        return {str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
                for path in sorted(root.rglob("*"))}

    def refused(self, hb_epoch):
        # The cycle loads its own copy of the organization writer, so its
        # OrgLedgerEpochRefused is a different class object; both are SystemExit.
        with self.assertRaises(SystemExit) as refused:
            self.cycle(hb_epoch)
        self.assertEqual(type(refused.exception).__name__, "OrgLedgerEpochRefused")
        # Nothing is written: the seeded repository store is byte-identical and
        # no organization ledger, mesh or node-state path was created.
        self.assertEqual(self.tree(self.work), self.seeded)
        return refused.exception.refusal

    def test_no_epoch_is_refused_before_anything_is_written(self):
        refusal = self.refused(None)
        self.assertSixFieldRefusal(refusal, "HB_EPOCH_NOT_SUPPLIED")

    def test_no_epoch_records_a_six_field_refusal_instead_of_stopping(self):
        """Base name kept (required-verification TEST_PRESENT_AT_BASE_RUNS_AT_HEAD); it asserts the rule that
        replaced the old one, never the old rule. The old rule recorded a six-field refusal and let
        the cycle continue. #207 refuses the cycle before anything is written.
        """
        self.test_no_epoch_is_refused_before_anything_is_written()

    def test_an_invalid_epoch_is_hb_epoch_invalid(self):
        self.assertSixFieldRefusal(self.refused("+33"), "HB_EPOCH_INVALID")

    def test_an_invalid_epoch_records_hb_epoch_invalid(self):
        """Base name kept (required-verification TEST_PRESENT_AT_BASE_RUNS_AT_HEAD); it asserts the rule that
        replaced the old one, never the old rule. The old rule recorded HB_EPOCH_INVALID in a cycle
        record that still ran. #207 refuses an invalid epoch as HB_EPOCH_INVALID before anything
        runs.
        """
        self.test_an_invalid_epoch_is_hb_epoch_invalid()

    def test_a_supplied_epoch_carries_the_receipt(self):
        propagation, _ = self.cycle(4200)
        self.assertEqual(propagation["disposition"], "ALLOW")
        self.assertEqual(propagation["receipts_propagated"], 1)


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
