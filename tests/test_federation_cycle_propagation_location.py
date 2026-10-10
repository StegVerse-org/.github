"""A federation cycle without a supplied repository ledger home records why it did not propagate.

Receipt propagation is a separate attempted transition from frame consumption.
With no STEGVERSE_REPO_LEDGER_HOME supplied it fails closed with its own
predicate and retry edge; the cycle still completes and reports the frames it
handled. With the location supplied it propagates as before.

Source validation only. No authority effect is claimed.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CYCLE = ROOT / "resident-runtime/federation_cycle.py"


def run_cycle(work, **extra):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("STEGVERSE_") and k != "XDG_STATE_HOME"}
    env.update({"HOME": work,
                "STEGVERSE_ORG_LEDGER_ROOT": str(Path(work) / "org-ledger"),
                "STEGVERSE_REPO_LEDGER_ROOT": str(Path(work) / "repo-ledger")}, **extra)
    mesh = Path(work) / "mesh"
    mesh.mkdir(exist_ok=True)
    return subprocess.run([sys.executable, "-B", str(CYCLE), "--mesh-root", str(mesh),
                           "--node-state-root", str(Path(work) / "state")],
                          capture_output=True, text=True, env=env, cwd=work, timeout=120)


class PropagationLocationTests(unittest.TestCase):
    def test_an_unsupplied_repository_ledger_home_fails_propagation_closed_not_the_cycle(self):
        with tempfile.TemporaryDirectory() as work:
            completed = run_cycle(work)
            self.assertEqual(completed.returncode, 0, completed.stderr[-800:])
            receipt = json.loads(completed.stdout.strip().splitlines()[-1])
            propagation = receipt["repository_propagation"]
            self.assertEqual(propagation["disposition"], "FAIL_CLOSED")
            self.assertEqual(propagation["failed_predicate"], "LEDGER_LOCATION_REQUIRED_FROM_MATERIALIZER")
            self.assertIs(propagation["consequence_committed"], False)
            for field in ("failure_code", "failed_predicate", "required_evidence_or_repair",
                          "retry_entrypoint", "owning_existing_goal", "next_attempt"):
                self.assertTrue(propagation[field], field)
            self.assertEqual(propagation["failure_code"], "LEDGER_LOCATION_NOT_SUPPLIED")
            self.assertTrue(propagation["retry_entrypoint"])
            self.assertIn("frames_consumed", receipt)
            self.assertFalse((Path(work) / ".local").exists())

    def test_a_supplied_repository_ledger_home_propagates(self):
        with tempfile.TemporaryDirectory() as work:
            completed = run_cycle(work, STEGVERSE_REPO_LEDGER_HOME=str(Path(work) / "repo-ledgers"))
            self.assertEqual(completed.returncode, 0, completed.stderr[-800:])
            propagation = json.loads(completed.stdout.strip().splitlines()[-1])["repository_propagation"]
            self.assertEqual(propagation["disposition"], "ALLOW")
            self.assertIn("repositories_declared", propagation)


if __name__ == "__main__":
    unittest.main()
