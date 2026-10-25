"""tools/tasks/writer_plan.py selects writer jobs from the registry manifest."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/tasks"))
import writer_plan  # noqa: E402


class WriterPlanTests(unittest.TestCase):
    def setUp(self):
        self.jobs = json.loads((ROOT / "control/workflow-surface-registry.json").read_text())["writer_jobs"]

    def test_transition_request_selects_ledger_transition_only(self):
        got = writer_plan.select([".stegverse/transition-requests/a/b.json"], self.jobs)
        self.assertEqual(got, {"ledger-transition": True, "governance-return": False, "ledger-ingest": False})

    def test_return_request_selects_governance_return_only(self):
        got = writer_plan.select([".stegverse/governance-return-requests/x.json"], self.jobs)
        self.assertEqual(got, {"ledger-transition": False, "governance-return": True, "ledger-ingest": False})

    def test_other_paths_select_neither(self):
        got = writer_plan.select(["README.md", ".stegverse/transition-requests"], self.jobs)
        self.assertEqual(got, {"ledger-transition": False, "governance-return": False, "ledger-ingest": False})

    def test_ingest_request_selects_ledger_ingest_only(self):
        got = writer_plan.select([".stegverse/organization-ledger-ingest/request.json"], self.jobs)
        self.assertEqual(got, {"ledger-transition": False, "governance-return": False, "ledger-ingest": True})

    def test_every_writer_job_is_a_job_of_the_writer_workflow(self):
        text = (ROOT / ".github/workflows/organization-ledger-writer.yml").read_text()
        for job in self.jobs:
            self.assertIn("\n  %s:\n" % job["job"], text)


if __name__ == "__main__":
    unittest.main()
