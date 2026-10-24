"""B1 main-change receipt writer (#160 issuecomment-6353130407 section 1.3): one sealed receipt per commit a push to
main introduces (merge, squash, direct push), appended fast-forward to the repository's own receipt ref, verified
from the published ref, idempotent, no clock, E0; a forced update of main is receipted as MAIN_HISTORY_REWRITTEN."""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("main_change_receipt", ROOT / "resident-runtime/main_change_receipt.py")
mcr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mcr)
WRITER = {"repository": "StegVerse-org/.github", "path": "resident-runtime/main_change_receipt.py", "ref": "a" * 40, "sha256": "b" * 64}
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
       "GIT_AUTHOR_DATE": "1700000000 +0000", "GIT_COMMITTER_DATE": "1700000000 +0000"}


def git(root, *a):
    return subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, env=ENV).stdout.decode().strip()


def commit(root, name, msg):
    (Path(root) / name).write_text(name)
    git(root, "add", name)
    git(root, "commit", "-q", "-m", msg)
    return git(root, "rev-parse", "HEAD")


class MainChangeReceiptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "r"
        git(self.tmp.name, "init", "-q", "-b", "main", str(self.root))
        self.base = commit(self.root, "a", "genesis")

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_kind_of_main_change_is_receipted_once(self):
        git(self.root, "checkout", "-q", "-b", "feature")
        commit(self.root, "f", "feature work")
        git(self.root, "checkout", "-q", "main")
        git(self.root, "merge", "-q", "--no-ff", "feature", "-m", "Merge pull request #5 from org/feature")
        merge = git(self.root, "rev-parse", "HEAD")
        direct = commit(self.root, "d", "direct push")
        receipts = mcr.observe(self.root, repository="o/r", before=self.base, after=direct, writer=WRITER)
        self.assertEqual([r["commit"] for r in receipts], [merge, direct])  # first parent only
        self.assertEqual([(r["merge_kind"], r["pull_request"]) for r in receipts], [("MERGE_COMMIT", 5), ("DIRECT_PUSH", None)])
        for r in receipts:
            self.assertTrue(mcr.seal_verifies(r))
            self.assertEqual(r["lowest_supported_mode"], "E0")
            self.assertIsNone(r["admission_record_ref"])
            self.assertEqual(r["disposition"], "FAIL_CLOSED")
            self.assertEqual(r["first_item"]["failure_code"], "ADMISSION_CHECKPOINT_NOT_INSTALLED")
            codes = [i["failure_code"] for i in r["items"]]
            self.assertEqual(codes, ["ADMISSION_CHECKPOINT_NOT_INSTALLED", "HB_EPOCH_SOURCE_UNOBSERVED",
                                     "ORGANIZATION_LEDGER_APPEND_NOT_AVAILABLE"])
            for i in r["items"]:
                self.assertTrue(all(isinstance(i[k], str) and i[k] for k in mcr.SIX_FIELDS))

    def test_a_squash_of_one_commit_names_its_pull_request(self):
        squash = commit(self.root, "s", "Add a thing (#12)")
        (r,) = mcr.observe(self.root, repository="o/r", before=self.base, after=squash, writer=WRITER)
        self.assertEqual((r["merge_kind"], r["pull_request"], r["pull_request_source"]), ("SQUASH_OR_REBASE_MERGE", 12, "COMMIT_SUBJECT"))

    def test_append_is_fast_forward_idempotent_and_verifies(self):
        c1 = commit(self.root, "b", "one")
        first = mcr.observe(self.root, repository="o/r", before=self.base, after=c1, writer=WRITER)
        out1 = mcr.append(self.root, first)
        self.assertEqual(out1["appended"], [c1])
        again = mcr.append(self.root, first)
        self.assertEqual((again["appended"], again["tip"]), ([], out1["tip"]))
        c2 = commit(self.root, "c", "two")
        out2 = mcr.append(self.root, mcr.observe(self.root, repository="o/r", before=c1, after=c2, writer=WRITER))
        self.assertEqual(git(self.root, "rev-parse", out2["tip"] + "^"), out1["tip"])
        self.assertEqual(mcr.verify(self.root, [c1, c2])["disposition"], "ALLOW")
        self.assertEqual(mcr.verify(self.root, [self.base])["failure_code"], "MAIN_CHANGE_RECEIPT_NOT_LEDGERED")

    def test_published_ref_read_back_from_a_fresh_fetch_verifies(self):
        remote = Path(self.tmp.name) / "remote.git"
        git(self.tmp.name, "init", "-q", "--bare", str(remote))
        c1 = commit(self.root, "b", "one")
        receipts = mcr.observe(self.root, repository="o/r", before=self.base, after=c1, writer=WRITER)
        mcr.append(self.root, receipts)
        git(self.root, "push", "-q", str(remote), f"{mcr.RECEIPT_REF}:{mcr.RECEIPT_REF}")
        fresh = Path(self.tmp.name) / "fresh.git"
        git(self.tmp.name, "init", "-q", "--bare", str(fresh))
        git(fresh, "fetch", "-q", str(remote), f"+{mcr.RECEIPT_REF}:{mcr.RECEIPT_REF}")
        self.assertEqual(mcr.verify(fresh, [c1])["disposition"], "ALLOW")

    def test_a_tampered_receipt_does_not_verify(self):
        c1 = commit(self.root, "b", "one")
        (r,) = mcr.observe(self.root, repository="o/r", before=self.base, after=c1, writer=WRITER)
        mcr.append(self.root, [{**r, "merge_kind": "MERGE_COMMIT"}])
        self.assertEqual(mcr.verify(self.root, [c1])["problems"], [{"commit": c1, "problem": "receipt does not verify"}])

    def test_a_forced_update_of_main_is_receipted_not_skipped(self):
        old = commit(self.root, "b", "replaced")
        git(self.root, "reset", "-q", "--hard", self.base)
        new = commit(self.root, "c", "replacement")
        (r,) = mcr.observe(self.root, repository="o/r", before=old, after=new, writer=WRITER)
        self.assertTrue(r["push"]["history_rewritten"])
        self.assertEqual(r["first_item"]["failure_code"], "MAIN_HISTORY_REWRITTEN")

    def test_the_epoch_is_the_organization_ledger_heads_never_a_clock(self):
        receipt = {"hb_reference": {"epoch": 446655631}, "x": 1}
        receipt = mcr.seal(receipt)
        hexd = receipt["receipt_sha256"].split(":")[1]
        lt = Path(self.tmp.name) / "l"
        git(self.tmp.name, "init", "-q", "-b", "l", str(lt))
        (lt / "receipts").mkdir()
        (lt / "receipts" / f"{hexd}.json").write_text(json.dumps(receipt))
        (lt / "HEAD.json").write_text(json.dumps({"receipt_sha256": receipt["receipt_sha256"]}))
        git(lt, "add", ".")
        git(lt, "commit", "-q", "-m", "ledger")
        git(self.root, "fetch", "-q", str(lt), f"+l:{mcr.ORG_LEDGER_REF}")
        c1 = commit(self.root, "b", "one")
        (r,) = mcr.observe(self.root, repository="o/r", before=self.base, after=c1, writer=WRITER,
                           organization_ledger_writer_installed=True)
        self.assertEqual(r["hb_epoch"], "446655631")
        self.assertEqual(r["hb_epoch_source"]["head_receipt_sha256"], receipt["receipt_sha256"])
        self.assertEqual([i["failure_code"] for i in r["items"]], ["ADMISSION_CHECKPOINT_NOT_INSTALLED"])

    def test_the_writer_reads_no_clock_and_imports_only_the_standard_library(self):
        tree = ast.parse((ROOT / "resident-runtime/main_change_receipt.py").read_text())
        imports = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imports |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertEqual(imports, {"__future__", "argparse", "hashlib", "json", "os", "re", "subprocess", "sys", "tempfile", "pathlib", "typing"})

    def test_the_reusable_workflow_is_call_only_pinned_and_binds_the_writer_bytes(self):
        # G17 (#238): retained as a non-executing record until the registry decision (fail_closed_pending)
        self.assertFalse((ROOT / ".github/workflows/main-change-receipt.yml").exists())
        reg = json.loads((ROOT / "control/workflow-surface-registry.json").read_text())
        row = next(r for r in reg["fail_closed_pending"] if r["surface"].startswith("main-change-receipt.yml"))
        self.assertEqual((row["disposition"], row["failure_code"]),
                         ("FAIL_CLOSED", "REUSABLE_WRITER_WORKFLOW_EXCEEDS_G17_SURFACE"))
        for key in ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
                    "owning_existing_goal", "next_attempt"):
            self.assertTrue(row[key], key)
        text = (ROOT / "tools/tasks/retired/main-change-receipt.yml").read_text()
        body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        self.assertIn("workflow_call:", body)
        for word in ("workflow_dispatch", "schedule:", "cron", "repository_dispatch", "self-hosted"):
            self.assertNotIn(word, body)
        self.assertIn("MAIN_CHANGE_RECEIPT_WRITER_NOT_AT_PIN", body)
        self.assertIn('git push origin "$RECEIPT_REF:$RECEIPT_REF"', body)  # never --force
        self.assertNotIn("--force", body)
        for line in body.splitlines():
            if line.strip().startswith(("uses:", "- uses:")):
                self.assertRegex(line, r"@[0-9a-f]{40}")


if __name__ == "__main__":
    unittest.main()
