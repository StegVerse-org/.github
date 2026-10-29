"""resident_status (kernel L569) reads no clock: a supplied epoch or no reference with a six-field reason."""
import json, subprocess, sys, unittest, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rs_kernel", ROOT / "org-kernel/kernel.py")
kernel = importlib.util.module_from_spec(spec); spec.loader.exec_module(kernel)
CONTROL = ROOT / "resident-runtime/ecosystem_control.py"


class ResidentStatusSuppliedEpochTests(unittest.TestCase):
    def test_supplied_epoch_is_used_and_not_derived(self):
        status = kernel.resident_status(ROOT, epoch=4200)
        self.assertEqual(status["heartbeat_reference"]["epoch"], 4200)
        self.assertIs(status["heartbeat_reference"]["derived_from_clock"], False)
        self.assertNotIn("heartbeat_reference_refusal", status)

    def test_status_cli_without_epoch_prints_null_reference_and_reason(self):
        run = subprocess.run([sys.executable, str(CONTROL), "status"], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        out = json.loads(run.stdout)
        self.assertIsNone(out["heartbeat_reference"])
        self.assertEqual(out["heartbeat_reference_refusal"]["failure_code"], "HB_EPOCH_NOT_SUPPLIED")

    def test_status_cli_with_epoch_text(self):
        run = subprocess.run([sys.executable, str(CONTROL), "status", "--hb-epoch", "4200"], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["heartbeat_reference"]["epoch"], 4200)

    def test_status_cli_refuses_coerced_epoch_text(self):
        for text in ("+33", " 33", "3_3", "31"):
            with self.subTest(text=text):
                run = subprocess.run([sys.executable, str(CONTROL), "status", "--hb-epoch", text], capture_output=True, text=True)
                self.assertEqual(run.returncode, 1)
                self.assertEqual(json.loads(run.stdout)["failure_code"], "HB_EPOCH_INVALID")

    def test_resident_status_source_reads_no_clock(self):
        source = (ROOT / "org-kernel/kernel.py").read_text()
        body = source[source.index("def resident_status("):source.index("def resident_status_epoch_refusal(")]
        self.assertNotIn("hb_reference()", body)
        self.assertNotIn("datetime", body)


if __name__ == "__main__":
    unittest.main()
