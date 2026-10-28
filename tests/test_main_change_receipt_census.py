"""B1 census: a repository without the writer is FAIL_CLOSED MAIN_CHANGE_RECEIPT_WRITER_NOT_INSTALLED with the six
#160 fields and gets a git-apply-able install patch that pins the caller by commit and writer sha256."""
from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("main_change_receipt_census", ROOT / "resident-runtime/main_change_receipt_census.py")
c = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(c)
PIN, SHA = "a" * 40, "b" * 64
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint", "owning_existing_goal", "next_attempt")


class CensusTest(unittest.TestCase):
    def test_records(self):
        out = c.census([{"repo": "o/a", "default_branch": "main", "workflows": ["organization-ledger-merge-transfer.yml"]},
                        {"repo": "o/b", "default_branch": "main", "workflows": []},
                        {"repo": "p/c", "default_branch": "dev", "workflows": ["x.yml"]},
                        {"repo": "p/d", "default_branch": "main", "workflows": ["main-change-receipt-caller.yml"]}],
                       PIN, SHA, {"file": "t"})
        self.assertEqual(out["totals"], {"repositories": 4, "ALLOW": 2, "FAIL_CLOSED": 2})
        b = next(r for r in out["records"] if r["repository"] == "o/b")
        self.assertEqual([b[k] for k in SIX], ["MAIN_CHANGE_RECEIPT_WRITER_NOT_INSTALLED", "REPO_MAIN_PUSH_EMITS_ORGANIZATION_MAIN_MERGE_TRANSFER",
                                               b["required_evidence_or_repair"], "the repo's next push to main",
                                               "STEGVERSE-CANONICAL-WORK-COORDINATION-001", "the census receipt flips to ALLOW"])
        self.assertIn("default branch is dev", next(r for r in out["records"] if r["repository"] == "p/c")["required_evidence_or_repair"])

    def test_the_install_patch_applies_and_pins(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            Path(tmp, "p.patch").write_text(c.install_patch(PIN, SHA))
            subprocess.run(["git", "-C", tmp, "apply", "p.patch"], check=True)
            text = Path(tmp, c.CALLER_PATH).read_text()
        self.assertIn(f"main-change-receipt.yml@{PIN}", text)
        self.assertIn(f"writer_sha256: {SHA}", text)
        self.assertNotIn("workflow_dispatch", text)
        with self.assertRaises(ValueError):
            c.caller_workflow("main", SHA)


if __name__ == "__main__":
    unittest.main()
