"""TEST_SUITE_BASELINE_REFRESH: the main receipt refreshed on push to main as a manifest transition through the
B1 writer and the drift receipt appender, admission FAIL_CLOSED pending genesis (StegVerse-org/.github#166).
Stdlib only, no network: the committed main receipt (main 907f4305) is the payload."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "resident-runtime"))
import test_suite_baseline_refresh as refresh  # noqa: E402

DECL = json.loads((ROOT / refresh.DECLARATION).read_text())
WF = (ROOT / refresh.WORKFLOW).read_text()
MAIN_RECEIPT = ROOT / ".stegverse/test-suite-baseline/main-receipt.json"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_NOSYSTEM": "1"}


class DeclarationTests(unittest.TestCase):
    def test_the_declaration_is_valid_and_pins_the_reused_writer_and_appender_by_sha256(self) -> None:
        self.assertIsNone(refresh.check_declaration(ROOT, DECL))
        for key, path in (("writer", "resident-runtime/main_change_receipt.py"),
                          ("appender", "resident-runtime/drift_receipt_appender.py")):
            self.assertEqual(DECL["reuses"][key]["path"], path)
            self.assertEqual(DECL["reuses"][key]["sha256"], hashlib.sha256((ROOT / path).read_bytes()).hexdigest())
        self.assertEqual(DECL["reuses"]["writer"]["sha256"],
                         "884168399f8ac54309aac86af6ab34481635de54426f635bb2229eb5073e2ebf")
        self.assertEqual(DECL["reuses"]["drift_tool"]["pin"], ".stegverse/test-suite-baseline/labs-tool-pin.json")

    def test_admission_is_fail_closed_pending_genesis_with_six_fields_and_no_effect(self) -> None:
        adm = DECL["admission"]
        self.assertEqual((adm["disposition"], adm["failure_code"]),
                         ("FAIL_CLOSED", "TEST_SUITE_BASELINE_REFRESH_ADMISSION_PENDING_GENESIS"))
        self.assertTrue(all(adm[k] for k in refresh.SIX_FIELDS))
        for k in ("organization_ledger_effect", "registry_generation_effect", "authority_effect"):
            self.assertEqual(DECL[k], "NONE")

    def test_a_changed_pin_or_admission_is_refused(self) -> None:
        for mutate in (lambda d: d["reuses"]["writer"].update(sha256="0" * 64),
                       lambda d: d["reuses"]["appender"].update(sha256="0" * 64),
                       lambda d: d["admission"].update(disposition="ALLOW"),
                       lambda d: d["admission"].pop("next_attempt"),
                       lambda d: d.update(organization_ledger_effect="APPEND"),
                       lambda d: d["trigger"].update(event="schedule"),
                       lambda d: d.update(operation="OTHER")):
            d = copy.deepcopy(DECL)
            mutate(d)
            refusal = refresh.check_declaration(ROOT, d)
            self.assertIsNotNone(refusal)
            self.assertTrue(all(refusal[k] for k in refresh.SIX_FIELDS))


class WorkflowTests(unittest.TestCase):
    def test_the_workflow_triggers_on_push_to_main_only(self) -> None:
        self.assertEqual(refresh.workflow_triggers(WF), ["push"])
        self.assertIn("on:\n  push:\n    branches: [main]\n", WF)
        for word in ("schedule:", "cron", "workflow_dispatch", "repository_dispatch", "workflow_run", "pull_request"):
            self.assertNotIn(word, WF)
        self.assertEqual(refresh.workflow_triggers(WF.replace("  push:\n", "  push:\n  schedule:\n")),
                         ["push", "schedule"])

    def test_the_workflow_publishes_nothing_and_reuses_the_pinned_tools(self) -> None:
        self.assertIn("permissions:\n  contents: read\n", WF)
        for word in ("contents: write", "git push", "update-ref", "gh api", "gh pr", "GITHUB_TOKEN", "secrets."):
            self.assertNotIn(word, WF)
        for needle in ("resident-runtime/pinned_labs.py fetch", '"$LABS/scripts/test_set_selection.py" select',
                       '"$LABS/scripts/test_suite_baseline_drift.py" detect',
                       "--writer resident-runtime/main_change_receipt.py",
                       "resident-runtime/drift_receipt_appender.py dry-run",
                       "resident-runtime/test_suite_baseline_refresh.py transition",
                       "resident-runtime/test_suite_baseline_refresh.py check", "persist-credentials: false"):
            self.assertIn(needle, WF)


class TransitionTests(unittest.TestCase):
    """The committed main receipt goes through the unmodified appender (scratch only) and the refresh record."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.tmp)])
        self.receipt = json.loads(MAIN_RECEIPT.read_text())
        self.head = self.receipt["head"]
        found = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", self.head + "^{commit}"])
        self.assertEqual(found.returncode, 0, f"the main head {self.head} must be in this checkout (fetch-depth: 0)")

    def appender(self, payload: Path) -> Path:
        for name in ("s.git", "f.git"):
            subprocess.run(["git", "init", "-q", "--bare", str(self.tmp / name)], check=True, env=ENV)
        out = self.tmp / "appender.json"
        done = subprocess.run([sys.executable, str(ROOT / "resident-runtime/drift_receipt_appender.py"), "dry-run",
                               "--root", str(ROOT), "--payload", str(payload), "--writer-ref", "test",
                               "--scratch", str(self.tmp / "s.git"), "--fresh", str(self.tmp / "f.git"),
                               "--out", str(out)], capture_output=True, text=True, env=ENV)
        self.assertEqual(done.returncode, 0, done.stdout[-2000:] + done.stderr[-2000:])
        return out

    def run_transition(self, detect: Path, appended: Path, head: str | None = None) -> tuple[int, dict]:
        out = self.tmp / "refresh.json"
        code = refresh.main(["transition", "--root", str(ROOT), "--head", head or self.head, "--detect-receipt",
                             str(detect), "--appender-result", str(appended), "--previous", str(MAIN_RECEIPT),
                             "--out", str(out), "--candidate-out", str(self.tmp / "candidate.json")])
        return code, json.loads(out.read_text())

    def test_the_committed_main_receipt_is_receipted_through_the_appender_into_a_sealed_refresh_record(self) -> None:
        appended = self.appender(MAIN_RECEIPT)
        code, record = self.run_transition(MAIN_RECEIPT, appended)
        self.assertEqual(code, 0, record)
        writer = refresh.load_writer(ROOT, DECL)
        self.assertTrue(writer.seal_verifies(record))
        self.assertEqual((record["schema"], record["operation"], record["head"]),
                         (refresh.SCHEMA, refresh.OPERATION, self.head))
        self.assertEqual(record["candidate_main_receipt"]["receipt_sha256"], self.receipt["receipt_sha256"])
        self.assertEqual(record["replaces"]["receipt_sha256"], self.receipt["receipt_sha256"])
        self.assertTrue(record["replaces"]["seal_verifies"])
        self.assertEqual(record["scratch_readback"], "ALLOW")
        drift = json.loads(appended.read_text())["receipts"][0]
        self.assertEqual(record["drift_transition_receipt_sha256"], drift["receipt_sha256"])
        self.assertEqual(drift["admission"]["failure_code"], "DRIFT_RECEIPT_APPENDER_ADMISSION_PENDING_GENESIS")
        self.assertEqual((record["disposition"], record["failure_code"]),
                         ("FAIL_CLOSED", "TEST_SUITE_BASELINE_REFRESH_ADMISSION_PENDING_GENESIS"))
        self.assertTrue(all(record[k] for k in refresh.SIX_FIELDS))
        self.assertEqual((record["published"], record["organization_ledger_effect"]), ("NONE", "NONE"))
        self.assertEqual(json.loads((self.tmp / "candidate.json").read_text()), self.receipt)

    def test_a_tampered_receipt_another_head_or_a_mismatched_appender_result_is_refused(self) -> None:
        appended = self.appender(MAIN_RECEIPT)
        tampered = self.tmp / "tampered.json"
        tampered.write_text(json.dumps(dict(self.receipt, disposition="ALLOW")))
        code, record = self.run_transition(tampered, appended)
        self.assertEqual((code, record["failure_code"]), (1, "REFRESH_DETECT_RECEIPT_NOT_SEALED"))
        parent = subprocess.run(["git", "-C", str(ROOT), "rev-parse", self.head + "^1"], capture_output=True,
                                text=True, check=True).stdout.strip()
        code, record = self.run_transition(MAIN_RECEIPT, appended, head=parent)
        self.assertEqual((code, record["failure_code"]), (1, "REFRESH_DETECT_RECEIPT_NOT_FOR_THIS_HEAD"))
        other = json.loads(appended.read_text())
        other["receipts"][0]["payload"]["receipt_sha256"] = "sha256:" + "0" * 64
        bad = self.tmp / "bad-appender.json"
        bad.write_text(json.dumps(other))
        code, record = self.run_transition(MAIN_RECEIPT, bad)
        self.assertEqual((code, record["failure_code"]), (1, "REFRESH_DRIFT_TRANSITION_NOT_RECEIPTED"))
        self.assertTrue(all(record[k] for k in refresh.SIX_FIELDS))
        self.assertFalse((self.tmp / "candidate.json").exists())     # a refused run retains no candidate


if __name__ == "__main__":
    unittest.main()
