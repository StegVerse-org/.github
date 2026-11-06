"""B1: a repository receipt is timed only by the epoch its caller supplies.

`.stegverse/transition-ledger/emit.py::append` used to stamp a receipt with a
host-clock epoch (`kernel.hb_reference()`, marked derived_from_clock) when no
epoch was supplied. It now refuses six-field FAIL_CLOSED before the store is
opened (SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH, shared rule
capability_ingress.supplied_epoch_failure); nothing is written and no clock is read.
"""
import importlib.util, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMIT = ROOT / ".stegverse/transition-ledger/emit.py"
BEFORE, AFTER = "sha256:" + "1" * 64, "sha256:" + "2" * 64
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair",
       "retry_entrypoint", "owning_existing_goal", "next_attempt")


def load():
    spec = importlib.util.spec_from_file_location("b1_emit", EMIT)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class EmitSuppliedEpochTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.ledger = Path(self.tmp.name) / "repo-ledger"
        os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = str(self.ledger)
        self.emit = load()

    def test_no_epoch_is_refused_six_field_and_nothing_is_written(self):
        with self.assertRaises(self.emit.RepoLedgerEpochRefused) as caught:
            self.emit.append("B1-1", "TEST", BEFORE, AFTER, {}, "NONE")
        refusal = caught.exception.refusal
        for field in SIX:
            self.assertTrue(refusal.get(field), field)
        self.assertEqual(refusal["failure_code"], "HB_EPOCH_NOT_SUPPLIED")
        self.assertEqual(refusal["failed_predicate"], "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH")
        self.assertIs(refusal["derived_from_clock"], False)
        self.assertIs(refusal["consequence_committed"], False)
        self.assertFalse(self.ledger.exists(), "refused before the store is opened")

    def test_coerced_or_pre_anchor_epochs_are_invalid(self):
        for value in ("+33", " 33", "3_3", "33.0", 31, True, 33.0):
            with self.subTest(value=value):
                with self.assertRaises(self.emit.RepoLedgerEpochRefused) as caught:
                    self.emit.append("B1-2", "TEST", BEFORE, AFTER, {}, "NONE", hb_epoch=value)
                self.assertEqual(caught.exception.refusal["failure_code"], "HB_EPOCH_INVALID")
        self.assertFalse(self.ledger.exists())

    def test_a_supplied_epoch_is_used_as_given_and_not_derived(self):
        receipt = self.emit.append("B1-3", "TEST", BEFORE, AFTER, {}, "NONE", hb_epoch="4200")
        reference = receipt["hb_reference"]
        self.assertEqual(reference["epoch"], 4200)
        self.assertIs(reference["derived_from_clock"], False)
        self.assertNotIn("sampled_unix_ns", reference)

    def test_the_cli_without_hb_epoch_prints_the_refusal_and_exits_1(self):
        run = subprocess.run([sys.executable, str(EMIT), "--transition-id", "B1-4", "--transition-class", "TEST",
                              "--predecessor-state-sha256", BEFORE, "--successor-state-sha256", AFTER],
                             capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertEqual(json.loads(run.stdout)["failure_code"], "HB_EPOCH_NOT_SUPPLIED")
        self.assertFalse(self.ledger.exists())

    def test_the_rule_is_byte_identical_to_the_shared_one(self):
        import hashlib
        def body(path):
            lines = path.read_text().splitlines(keepends=True)
            s = next(i for i, l in enumerate(lines) if l.startswith("def supplied_epoch_failure("))
            e = s + 1
            while e < len(lines) and (lines[e].startswith((" ", "\t")) or not lines[e].strip()):
                e += 1
            while not lines[e - 1].strip():
                e -= 1
            return hashlib.sha256("".join(lines[s:e]).encode()).hexdigest()
        shared = body(ROOT / "org-boundary/runtime/capability_ingress.py")
        self.assertEqual(body(EMIT), shared)
        self.assertTrue(shared.startswith("7f36f0e6"))

    def test_append_reads_no_clock(self):
        source = EMIT.read_text()
        start = source.index("def append("); end = source.index("def main(")
        self.assertNotIn("kernel.hb_reference()", source[start:end])
        for forbidden in ("datetime", "time.time", "time_ns"):
            self.assertNotIn(forbidden, source[start:end])


if __name__ == "__main__":
    unittest.main()
