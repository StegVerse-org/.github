"""B1b push-receipt session binder (#160 issuecomment-6353130407 rank 3; correction issuecomment-6354202109): the
authoring session is derived from the ledgered sv-push-receipt.v1 chain over base..head, replacing the LLM-typed
PR_AUTHOR_SESSION_DECLARED; gaps, foreign writers and unledgered receipts FAIL_CLOSED with six fields; E0."""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("push_receipt_session_binder", ROOT / "resident-runtime/push_receipt_session_binder.py")
b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(b)
REPO, REF = "StegVerse-org/.github", "refs/heads/p4/x"
SHA = [f"{i:040x}" for i in range(1, 6)]
CHANGE = "svc:" + "c" * 64


def receipt(old, new, session, **extra):
    return b.seal({"schema": b.PUSH_RECEIPT_SCHEMA, "repository": REPO, "ref": REF, "old_sha": old, "new_sha": new,
                   "pusher_session": session, "pushed_commits": [new], "hb_epoch": "446655631", **extra})


def grant(by, to, change=CHANGE):
    return b.seal({"schema": b.CO_AUTHOR_GRANT_SCHEMA, "change_id": change, "granted_by_session": by,
                   "co_author_session": to}, "receipt_sha256")


def bind(receipts, **kw):
    return b.bind(target_repository=REPO, base_sha=SHA[0], head_sha=SHA[2], receipts=receipts,
                  ledgered=kw.pop("ledgered", True), **kw)


class BinderTest(unittest.TestCase):
    def assertSix(self, r, code):
        self.assertEqual((r["disposition"], r["failure_code"]), ("FAIL_CLOSED", code))
        self.assertTrue(all(isinstance(r[k], str) and r[k] for k in b.SIX_FIELDS))
        self.assertEqual(r["authoring_session"], b.UNKNOWN)
        self.assertTrue(b.seal_verifies(r))

    def test_the_session_is_derived_from_the_chain_not_declared(self):
        r = bind([receipt(SHA[0], SHA[1], "p4"), receipt(SHA[1], SHA[2], "p4")])
        self.assertEqual((r["disposition"], r["authoring_session"]), ("ALLOW", "p4"))
        self.assertEqual((r["replaces"], r["session_source"], r["lowest_supported_mode"]),
                         ("PR_AUTHOR_SESSION_DECLARED", "PUSH_RECEIPT_CHAIN", "E0"))
        self.assertTrue(b.seal_verifies(r))

    def test_a_gap_is_branch_writer_unobserved(self):
        r = bind([receipt(SHA[0], SHA[1], "p4"), receipt(SHA[3], SHA[2], "p4")])
        self.assertSix(r, "BRANCH_WRITER_UNOBSERVED")
        self.assertEqual(r["detail"]["writer_evidence"], "WRITER_EVIDENCE_GAP")
        self.assertSix(bind([]), "BRANCH_WRITER_UNOBSERVED")
        self.assertSix(b.bind(target_repository=REPO, base_sha="x", head_sha=SHA[2], receipts=[], ledgered=True),
                       "BRANCH_WRITER_UNOBSERVED")

    def test_a_receipt_outside_the_range_or_for_another_repository_is_a_gap(self):
        self.assertSix(bind([receipt(SHA[0], SHA[1], "p4"), receipt(SHA[1], SHA[2], "p4"), receipt(SHA[2], SHA[3], "p4")]),
                       "BRANCH_WRITER_UNOBSERVED")
        other = b.seal({**receipt(SHA[0], SHA[2], "p4"), "repository": "o/other"})
        self.assertSix(bind([other]), "BRANCH_WRITER_UNOBSERVED")

    def test_a_tampered_or_open_receipt_is_a_gap(self):
        r = receipt(SHA[0], SHA[2], "p4")
        self.assertSix(bind([{**r, "pusher_session": "someone"}]), "BRANCH_WRITER_UNOBSERVED")
        self.assertSix(bind([b.seal({**r, "extra": 1})]), "BRANCH_WRITER_UNOBSERVED")
        self.assertSix(bind([b.seal({**r, "hb_epoch": "7"})]), "BRANCH_WRITER_UNOBSERVED")

    def test_a_foreign_writer_fails_closed_unless_granted_by_the_derived_session(self):
        chain = [receipt(SHA[0], SHA[1], "p4"), receipt(SHA[1], SHA[2], "laneC")]
        self.assertSix(bind(chain), "BRANCH_HAS_FOREIGN_WRITER")
        self.assertSix(bind(chain, change_id=CHANGE, co_author_grant_receipts=[grant("laneB", "laneC")]), "BRANCH_HAS_FOREIGN_WRITER")
        self.assertSix(bind(chain, change_id=CHANGE, co_author_grant_receipts=[grant("p4", "laneC", "svc:" + "d" * 64)]),
                       "BRANCH_HAS_FOREIGN_WRITER")
        ok = bind(chain, change_id=CHANGE, co_author_grant_receipts=[grant("p4", "laneC")])
        self.assertEqual((ok["disposition"], ok["authoring_session"], ok["co_authors"]), ("ALLOW", "p4", ["laneC"]))

    def test_a_supplied_unledgered_chain_does_not_bind(self):
        self.assertSix(bind([receipt(SHA[0], SHA[2], "p4")], ledgered=False), "PUSH_RECEIPT_NOT_LEDGERED")

    def test_the_cli_binds_only_from_a_ledger_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True, capture_output=True,
                                            env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                                                 "GIT_COMMITTER_EMAIL": "t@t", "HOME": tmp, "PATH": "/usr/bin:/bin"})
            run("init", "-q", "-b", "ledger")
            Path(tmp, "receipts").mkdir()
            earlier = receipt(SHA[4], SHA[0], "p4")  # an earlier push to the branch, not this range
            for i, r in enumerate([earlier, receipt(SHA[0], SHA[1], "p4"), receipt(SHA[1], SHA[2], "p4")]):
                Path(tmp, "receipts", f"{i}.json").write_text(json.dumps(r))
            run("add", ".")
            run("commit", "-q", "-m", "l")
            out = subprocess.run(["python3", str(ROOT / "resident-runtime/push_receipt_session_binder.py"), "--repository", REPO,
                                  "--base-sha", SHA[0], "--head-sha", SHA[2], "--branch", REF, "--ledger-git-dir", tmp,
                                  "--ledger-ref", "refs/heads/ledger"], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            result = json.loads(out.stdout)
            self.assertEqual((result["authoring_session"], len(result["push_receipts"])), ("p4", 2))

    def test_the_binder_is_stdlib_only_and_reads_no_clock(self):
        tree = ast.parse((ROOT / "resident-runtime/push_receipt_session_binder.py").read_text())
        imports = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imports |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertEqual(imports, {"__future__", "argparse", "hashlib", "json", "re", "subprocess", "sys", "pathlib", "typing"})


if __name__ == "__main__":
    unittest.main()
