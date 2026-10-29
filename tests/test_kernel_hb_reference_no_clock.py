"""kernel.hb_reference (L76-77) has no clock fallback; its callers supply the epoch."""
import importlib.util, json, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("nc_kernel", ROOT / "org-kernel/kernel.py")
kernel = importlib.util.module_from_spec(spec); spec.loader.exec_module(kernel)
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair",
       "retry_entrypoint", "owning_existing_goal", "next_attempt")


class HbReferenceNoClockTests(unittest.TestCase):
    def test_neither_epoch_nor_sample_is_refused_six_field_without_reading_a_clock(self):
        with mock.patch.object(kernel, "datetime", wraps=kernel.datetime) as clock:
            with self.assertRaises(kernel.HbEpochNotSupplied) as caught:
                kernel.hb_reference()
        clock.now.assert_not_called()
        refusal = caught.exception.refusal
        for field in SIX:
            self.assertTrue(refusal[field], field)
        self.assertEqual(refusal["failure_code"], "HB_EPOCH_NOT_SUPPLIED")
        self.assertIs(refusal["derived_from_clock"], False)

    def test_a_carrier_frame_without_an_epoch_is_refused(self):
        with self.assertRaises(kernel.HbEpochNotSupplied):
            kernel.carrier_frame({"payload": {}})

    def test_a_supplied_epoch_is_reproducible_and_not_derived(self):
        a, b = kernel.hb_reference(epoch=4200), kernel.hb_reference(epoch=4200)
        self.assertEqual(a, b)
        self.assertIs(a["derived_from_clock"], False)
        self.assertNotIn("sampled_unix_ns", a)

    def test_the_kernel_source_calls_no_clock(self):
        source = (ROOT / "org-kernel/kernel.py").read_text()
        for forbidden in ("datetime.now(", "time.time(", "time_ns(", "hb_reference()"):
            self.assertNotIn(forbidden, source)

    def test_ecosystem_control_send_without_an_epoch_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as work:
            mesh = Path(work) / "mesh"; mesh.mkdir()
            run = subprocess.run([sys.executable, str(ROOT / "resident-runtime/ecosystem_control.py"), "--mesh-root", str(mesh),
                                  "send-message", "--subject", "s", "--body-json", "{}",
                                  "--standing", str(ROOT / "tests/fixtures/crossing-standing-genesis.json")],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 1, run.stderr)
            self.assertEqual(json.loads(run.stdout)["failure_code"], "HB_EPOCH_NOT_SUPPLIED")
            self.assertFalse((mesh / "frames.d").exists())

    def test_sv002_submission_without_an_epoch_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as work:
            mesh = Path(work) / "mesh"; mesh.mkdir()
            run = subprocess.run([sys.executable, str(ROOT / "resident-runtime/run_sv002_self_characterization_roundtrip.py"),
                                  "--sdk-root", work, "--mesh-root", str(mesh), "--state-root", str(Path(work) / "s")],
                                 capture_output=True, text=True,
                                 env={"PATH": "/usr/bin:/bin"})
            self.assertEqual(run.returncode, 1, run.stderr)
            out = json.loads(run.stdout.strip().splitlines()[-1])
            self.assertEqual(out["failure_code"], "HB_EPOCH_NOT_SUPPLIED")
            self.assertFalse((mesh / "frames.d").exists())


if __name__ == "__main__":
    unittest.main()
