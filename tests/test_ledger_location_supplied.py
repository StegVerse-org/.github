"""The organization and repository ledgers are written only where they were supplied.

A ledger is the organization's runtime reality. Its location is supplied by
whatever materialized the execution, as the federation mesh is; it is never
derived from the host. With no supplied root an append fails closed, names
the missing location, writes nothing and leaves the host untouched.

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
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LEDGER_VARIABLES = ("STEGVERSE_ORG_LEDGER_ROOT", "STEGVERSE_REPO_LEDGER_ROOT")


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


organization = _load("aggregate_repo_transition", "resident-runtime/aggregate_repo_transition.py")
propagation = _load("propagate_repository_receipts", "resident-runtime/propagate_repository_receipts.py")
repository = _load("transition_ledger_emit", ".stegverse/transition-ledger/emit.py")


def unsupplied(home):
    """An environment with no ledger root and a host home that must stay empty."""
    env = {key: value for key, value in os.environ.items()
           if key not in LEDGER_VARIABLES + ("XDG_STATE_HOME", propagation.LEDGER_HOME_VARIABLE)}
    env["HOME"] = home
    return env


class LedgerLocationIsSuppliedTests(unittest.TestCase):
    def test_an_unsupplied_organization_ledger_root_fails_closed_by_name(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, unsupplied(home), clear=True):
            with self.assertRaises(organization.LedgerLocationRequired) as raised:
                organization.ledger_root()
            self.assertEqual(raised.exception.failed_predicate, "LEDGER_LOCATION_REQUIRED_FROM_MATERIALIZER")
            self.assertEqual(raised.exception.variable, "STEGVERSE_ORG_LEDGER_ROOT")
            self.assertEqual(list(Path(home).iterdir()), [])

    def test_an_unsupplied_repository_ledger_home_fails_closed_by_name(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, unsupplied(home), clear=True):
            with self.assertRaises(propagation.organization_ledger.LedgerLocationRequired) as raised:
                propagation.repository_ledger_home()
            self.assertEqual(raised.exception.variable, propagation.LEDGER_HOME_VARIABLE)
            self.assertEqual(list(Path(home).iterdir()), [])

    def test_an_unsupplied_repository_ledger_root_fails_closed(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, unsupplied(home), clear=True):
            with self.assertRaisesRegex(ValueError, "ledger_location_required_from_materializer"):
                repository.lr()

    def test_a_supplied_root_is_used_as_given(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as supplied:
            env = {**unsupplied(home), "STEGVERSE_ORG_LEDGER_ROOT": supplied, "STEGVERSE_REPO_LEDGER_ROOT": supplied}
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(organization.ledger_root(), Path(supplied).resolve())
                self.assertEqual(repository.lr(), Path(supplied).resolve())

    def test_the_append_command_records_its_refusal_and_commits_nothing(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as work:
            body = {"schema": "stegverse.repo-transition-receipt/v1",
                    "repository": "StegVerse-org/StegVerse-SDK", "transition_id": "unsupplied-ledger"}
            receipt = Path(work) / "receipt.json"
            receipt.write_text(json.dumps({**body, "receipt_sha256": organization.sha(body)}))
            completed = subprocess.run(
                [sys.executable, "-B", str(ROOT / "resident-runtime/aggregate_repo_transition.py"),
                 "--repo-receipt", str(receipt), "--predecessor-org-state-sha256", "GENESIS",
                 "--successor-org-state-sha256", "sha256:" + "b" * 64, "--hb-epoch", "32"],
                capture_output=True, text=True, env=unsupplied(home), cwd=work, timeout=120)
            self.assertEqual(completed.returncode, 1, completed.stderr)
            refusal = json.loads(completed.stdout)
            self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
            self.assertEqual(refusal["failed_predicate"], "LEDGER_LOCATION_REQUIRED_FROM_MATERIALIZER")
            self.assertIs(refusal["consequence_committed"], False)
            self.assertTrue(refusal["retry_entrypoint"])
            self.assertEqual(list(Path(home).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
