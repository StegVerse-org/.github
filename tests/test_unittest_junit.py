"""The stdlib unittest runner records every outcome, by id, with no timings."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "unittest_junit.py"

SAMPLE = '''import unittest


class Sample(unittest.TestCase):
    def test_passes(self):
        pass

    def test_fails(self):
        self.assertEqual(1, 2)

    @unittest.skip("needs a thing this runner does not have")
    def test_skipped(self):
        pass

    @unittest.expectedFailure
    def test_xfail(self):
        self.assertTrue(False)
'''


class UnittestJunitTests(unittest.TestCase):
    def run_in(self, files: dict[str, str], selected: list[str] | None = None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, text in files.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(text, encoding="utf-8")
            args = [sys.executable, str(SCRIPT), "--root", str(root), "--out", str(root / "out.xml")]
            if selected is not None:
                (root / "sel.txt").write_text("\n".join(selected) + "\n", encoding="utf-8")
                args += ["--tests-from", str(root / "sel.txt")]
            done = subprocess.run(args, capture_output=True, text=True, cwd=root)
            xml = (root / "out.xml").read_bytes() if (root / "out.xml").exists() else b""
            return done, xml

    def outcomes(self, xml: bytes) -> dict[str, str]:
        found = {}
        for case in ET.fromstring(xml).iter("testcase"):
            child = next(iter(case), None)
            kind = "passed" if child is None else (child.get("type") or child.tag)
            found[f"{case.get('classname')}::{case.get('name')}"] = kind
        return found

    def test_every_outcome_is_recorded_under_its_own_id(self):
        done, xml = self.run_in({"tests/test_sample.py": SAMPLE})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.outcomes(xml), {
            "tests.test_sample.Sample::test_passes": "passed",
            "tests.test_sample.Sample::test_fails": "failure",
            "tests.test_sample.Sample::test_skipped": "unittest.skip",
            "tests.test_sample.Sample::test_xfail": "pytest.xfail",
        })
        self.assertIn(b"needs a thing this runner does not have", xml)
        self.assertNotIn(b"time=", xml)

    def test_a_module_that_fails_to_import_is_an_error_under_its_name(self):
        done, xml = self.run_in({"tests/test_broken.py": "import not_a_module_anywhere_xyz\n"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.outcomes(xml), {"::tests.test_broken": "error"})

    def test_only_the_selected_files_run(self):
        done, xml = self.run_in({"tests/test_sample.py": SAMPLE,
                                 "tests/test_other.py": SAMPLE.replace("Sample", "Other")},
                                selected=["tests/test_other.py"])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual({k.split("::")[0] for k in self.outcomes(xml)}, {"tests.test_other.Other"})

    def test_the_same_run_gives_the_same_bytes(self):
        first = self.run_in({"tests/test_sample.py": SAMPLE})[1]
        second = self.run_in({"tests/test_sample.py": SAMPLE})[1]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
