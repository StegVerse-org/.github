"""Regression: a failing catalog group without source workflow/job (a catalog_additions
group) returns DENY with the six non-ALLOW fields instead of raising KeyError
(StegVerse-org/.github#238 comment 6383204701). Stdlib only."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools/tasks/run_catalog.py"
NON_ALLOW_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
                    "retry_entrypoint", "owning_existing_goal", "next_attempt")


class RunCatalogDenyWithoutSourceTests(unittest.TestCase):
    def run_group(self, group):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "tools/tasks/steps/g").mkdir(parents=True)
            shutil.copy2(RUNNER, repo / "tools/tasks/run_catalog.py")
            step = repo / "tools/tasks/steps/g/01-fail.sh"
            step.write_text("exit 3\n", encoding="utf-8")
            group["steps"] = [{"name": "fail", "run_file": "tools/tasks/steps/g/01-fail.sh",
                               "run_sha256": hashlib.sha256(step.read_bytes()).hexdigest()}]
            (repo / "tools/tasks/task_catalog.json").write_text(json.dumps({"groups": [group]}), encoding="utf-8")
            temp = Path(tmp) / "runner-temp"
            env = dict(os.environ, RUNNER_TEMP=str(temp))
            env.pop("GITHUB_STEP_SUMMARY", None)
            proc = subprocess.run([sys.executable, str(repo / "tools/tasks/run_catalog.py"), "run", "--group", group["id"]],
                                  cwd=repo, env=env, capture_output=True, text=True)
            receipt_path = temp / "catalog-receipts" / f"{group['id']}.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else None
            return proc, receipt

    def assert_six_field_deny(self, proc, receipt):
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIsNotNone(receipt)
        self.assertNotEqual(receipt["disposition"], "ALLOW")
        for field in NON_ALLOW_FIELDS:
            self.assertTrue(receipt["refusal"].get(field), field)

    def test_group_without_source_denies_with_six_fields(self):
        proc, receipt = self.run_group({"id": "addition.validate", "events": ["pull_request"]})
        self.assert_six_field_deny(proc, receipt)
        self.assertIn("catalog addition", receipt["refusal"]["failed_predicate"])

    def test_group_with_null_source_fields_denies_with_six_fields(self):
        proc, receipt = self.run_group({"id": "addition.nulls", "events": ["pull_request"],
                                        "source": {"workflow": None, "job": None}})
        self.assert_six_field_deny(proc, receipt)

    def test_folded_group_still_names_its_source(self):
        proc, receipt = self.run_group({"id": "folded.job", "events": ["pull_request"],
                                        "source": {"workflow": ".github/workflows/x.yml", "job": "j"}})
        self.assert_six_field_deny(proc, receipt)
        self.assertIn("folded from .github/workflows/x.yml job j", receipt["refusal"]["failed_predicate"])


if __name__ == "__main__":
    unittest.main()
