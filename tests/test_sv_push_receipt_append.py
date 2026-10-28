"""sv_push_receipt: each push to a PR branch is one sealed sv-push-receipt.v1 on the organization ledger.

Temp ledgers are the pinned ledger tip (tests/test_merge_transfer.Ledger), never
the published ref. Pushes are made in a scratch git repository; the receipt is
emitted by the vendored Labs#3267 producer (bb780200) and appended through the
existing two-level append. The chain is then checked with the rule TVC#531's
BRANCH_WRITER_IS_BRANCH_OWNER applies (contiguous, ends at head, covers every
commit, one pusher_session).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_merge_transfer import FIXTURES, Ledger, load

ROOT = Path(__file__).resolve().parents[1]
sp = load("sv_push_receipt_append_under_test", "resident-runtime/sv_push_receipt_append.py")
# G17: the writer workflow is retained verbatim as a non-executing record (its push-to-any-branch
# trigger is on no registered surface; FAIL_CLOSED pending in control/workflow-surface-registry.json).
# WorkflowShape checks the retained bytes, so the writer that is admitted is the one reviewed here.
WORKFLOW = ROOT / "tools/tasks/retired/organization-ledger-push-receipt.yml"
SIX = sp.SIX_FIELDS


def run(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout.strip()


class Scratch:
    """main with one commit; branch feature with commits added by commit()."""

    def __init__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name)
        run(self.path, "init", "-q", "-b", "main")
        self.main = self.commit("base")
        run(self.path, "update-ref", "refs/remotes/origin/main", self.main)
        run(self.path, "checkout", "-q", "-b", "feature")

    def commit(self, name):
        (self.path / name).write_text(name)
        run(self.path, "add", name)
        run(self.path, "commit", "-q", "-m", name)
        return run(self.path, "rev-parse", "HEAD")

    def close(self):
        self.dir.cleanup()


def chain_rule(receipts, repository, ref, head, commits):
    """TVC#531 sv_merge_admission.p_writer, reduced to its ALLOW condition."""
    if {r["repository"] for r in receipts} != {repository} or {r["ref"] for r in receipts} != {ref}:
        return "scope"
    news = {r["new_sha"] for r in receipts}
    starts = [r for r in receipts if r["old_sha"] not in news]
    by_old = {r["old_sha"]: r for r in receipts}
    if len(starts) != 1 or len(by_old) != len(receipts):
        return "contiguous"
    chain, at = [starts[0]], starts[0]["new_sha"]
    while at in by_old:
        chain.append(by_old[at])
        at = by_old[at]["new_sha"]
    if len(chain) != len(receipts) or at != head:
        return "head"
    covered = {c for r in chain for c in r["pushed_commits"]}
    if any(c not in covered for c in commits):
        return "coverage"
    if len({r["pusher_session"] for r in chain}) != 1:
        return "session"
    return None


class Base(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURES[0].read_text())
        self.repo = sp.mt.repository()
        self.ledger = Ledger(self.fixture)
        self.git = Scratch()

    def tearDown(self):
        self.ledger.close()
        self.git.close()

    def push(self, before, after, ref="refs/heads/feature", login="StegVerse", account="1"):
        return sp.emit_and_append(self.git.path, repository=self.repo, ref=ref, before=before, after=after,
                                  base_ref="refs/remotes/origin/main", sender_login=login, sender_id=account)

    def six(self, result, code, disposition="FAIL_CLOSED"):
        self.assertEqual((result["disposition"], result["failure_code"]), (disposition, code), result)
        for f in SIX:
            self.assertTrue(result.get(f), f)
        self.assertIn(result["failed_predicate"], sp.PREDICATES)
        self.assertIs(result["consequence_committed"], False)


class Pins(unittest.TestCase):
    def test_the_vendored_producer_matches_its_pins(self):
        self.assertIsNone(sp.pin_failure())
        pins = json.loads(sp.PINS_FILE.read_text())
        self.assertEqual(pins["source_commit"], "bb780200862c76cd29e081c595beb29bf18527c6")
        self.assertEqual(sp.producer().RECEIPT_SCHEMA, sp.RECEIPT_SCHEMA)

    def test_a_pin_mismatch_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            pins = json.loads(sp.PINS_FILE.read_text())
            pins["files"]["resident-runtime/sv_push_receipt.py"]["git_blob"] = "0" * 40
            p = Path(d) / "pins.json"
            p.write_text(json.dumps(pins))
            self.assertIn("git blob", sp.pin_failure(p))

    def test_every_predicate_declares_its_lowest_mode_and_its_e0_form(self):
        for pid, modes in sp.PREDICATES.items():
            self.assertEqual(modes["lowest_supported_mode"], "E0", pid)
            for rung in ("E3", "E2", "E1", "E0"):
                self.assertTrue(modes[rung], pid + " " + rung)
            self.assertIn("none", modes["llm_inputs"])


class Append(Base):
    def test_two_pushes_form_the_chain_branch_writer_consumes(self):
        a = self.git.commit("a")
        first = self.push(sp.ZERO, a)  # new branch: old_sha is the fork base
        self.assertEqual(first["disposition"], "ALLOW", first)
        self.assertEqual(first["old_sha"], self.git.main)
        b = self.git.commit("b")
        c = self.git.commit("c")
        second = self.push(a, c)
        self.assertEqual(second["disposition"], "ALLOW", second)
        self.assertEqual(second["pushed_commits"], 2)
        key = sp.mt.store_module().receipt_key
        receipts = []
        for res in (first, second):
            org = self.ledger.read(key(res["organization_receipt_sha256"]))
            rep = self.ledger.read(key(res["repository_receipt_sha256"]), repo=True)
            self.assertTrue(sp.mt.sealed(org) and sp.mt.sealed(rep))
            self.assertEqual(sp.mt._boundary(org)["operation"], "sv_push_receipt")
            self.assertEqual(org["repo_receipt_sha256"], rep["receipt_sha256"])
            self.assertIs(org["hb_reference"]["derived_from_clock"], False)
            r = rep["evidence"]["push_receipt"]
            self.assertIsNone(sp.producer().receipt_problem(r))
            self.assertEqual(r["hb_epoch"], str(org["hb_reference"]["epoch"]))
            self.assertEqual(r["pusher_session"], "github-push-sender:StegVerse#1")
            receipts.append(r)
            verified = sp.verify_push_receipt(self.repo, res["ref"], res["old_sha"], res["new_sha"])
            self.assertEqual(verified["disposition"], "ALLOW", verified)
        self.assertIsNone(chain_rule(receipts, self.repo, "refs/heads/feature", c, [a, b, c]))

    def test_a_replay_is_answered_from_the_ledger(self):
        a = self.git.commit("a")
        first = self.push(sp.ZERO, a)
        files = self.ledger.files()
        again = self.push(sp.ZERO, a)
        self.assertEqual(again["disposition"], "ALLOW")
        self.assertIs(again["replayed"], True)
        self.assertEqual(again["organization_receipt_sha256"], first["organization_receipt_sha256"])
        self.assertEqual(self.ledger.files(), files)

    def test_a_second_pusher_is_a_foreign_writer_for_the_consumer(self):
        a = self.git.commit("a")
        self.push(sp.ZERO, a)
        b = self.git.commit("b")
        self.push(a, b, login="other-lane", account="2")
        key = sp.mt.store_module().receipt_key
        receipts = [rep["evidence"]["push_receipt"] for rep in
                    (json.loads(p.read_text()) for p in self.ledger.repo_root.rglob("*.json"))
                    if isinstance(rep, dict) and isinstance(rep.get("evidence"), dict) and "push_receipt" in rep["evidence"]]
        self.assertEqual(chain_rule(receipts, self.repo, "refs/heads/feature", b, [a, b]), "session")


class Refusals(Base):
    def test_a_force_push_is_not_receipted(self):
        a = self.git.commit("a")
        self.push(sp.ZERO, a)
        run(self.git.path, "reset", "-q", "--hard", self.git.main)
        x = self.git.commit("x")
        files = self.ledger.files()
        self.six(self.push(a, x), "PUSH_NOT_FAST_FORWARD")
        self.assertEqual(self.ledger.files(), files)

    def test_main_is_not_a_pr_branch(self):
        a = self.git.commit("a")
        self.six(self.push(self.git.main, a, ref="refs/heads/main"), "PUSH_RECEIPT_REF_IS_MAIN", "DENY")

    def test_a_deletion_or_an_unobserved_sender_moves_nothing(self):
        self.six(self.push(self.git.main, sp.ZERO), "PUSH_NOT_OBSERVED")
        a = self.git.commit("a")
        self.six(self.push(sp.ZERO, a, login=""), "PUSH_NOT_OBSERVED")

    def test_an_empty_ledger_has_no_epoch_and_nothing_is_written(self):
        self.ledger.close()
        self.ledger = Ledger(self.fixture, empty=True)
        a = self.git.commit("a")
        self.six(self.push(sp.ZERO, a), "HB_EPOCH_SOURCE_UNOBSERVED")
        self.assertEqual(self.ledger.files(), {})

    def test_a_receipt_at_another_epoch_or_for_another_repository_is_refused(self):
        a = self.git.commit("a")
        r = sp.producer().emit(self.git.path, repository_name=self.repo, ref="refs/heads/feature",
                               old_sha=self.git.main, pusher_session="github-push-sender:StegVerse#1",
                               hb_epoch="33", after_ref=a)
        self.six(sp.append_push_receipt(r), "HB_EPOCH_MISMATCH", "DENY")
        r2 = sp.producer().emit(self.git.path, repository_name="StegVerse-org/other", ref="refs/heads/feature",
                                old_sha=self.git.main, pusher_session="s", hb_epoch="33", after_ref=a)
        self.six(sp.append_push_receipt(r2), "PUSH_RECEIPT_INVALID")
        tampered = dict(r, pusher_session="someone-else")
        self.six(sp.append_push_receipt(tampered), "PUSH_RECEIPT_INVALID")

    def test_an_unledgered_push_does_not_verify(self):
        a = self.git.commit("a")
        self.six(sp.verify_push_receipt(self.repo, "refs/heads/feature", self.git.main, a), "PUSH_RECEIPT_NOT_LEDGERED")


class WorkflowShape(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()

    def test_trigger_is_a_branch_push_never_main_dispatch_or_schedule(self):
        self.assertRegex(self.text, r"(?m)^on:\n  push:\n    branches-ignore:\n      - main\n")
        for word in ("workflow_dispatch", "schedule:", "pull_request_target", "repository_dispatch", "cron"):
            self.assertNotIn(word, self.text)

    def test_least_privilege_and_the_shared_ledger_lock(self):
        self.assertRegex(self.text, r"(?m)^permissions:\n  contents: read\n")
        self.assertEqual(self.text.count("contents: write"), 1)
        self.assertIn("group: organization-ledger", self.text)
        self.assertIn("cancel-in-progress: false", self.text)

    def test_the_writer_runs_mains_code_and_publishes_fast_forward_only(self):
        self.assertIn("git worktree add", self.text)
        self.assertIn("origin/main", self.text)
        self.assertIn("SV_PUSH_RECEIPT_WRITER_NOT_ON_MAIN", self.text)
        self.assertIn('git push origin "$LEDGER_REF:$LEDGER_REF"', self.text)
        self.assertNotIn("--force", self.text)
        self.assertNotIn("+$LEDGER_REF:$LEDGER_REF\"\n          if", self.text)
        self.assertIn("sv_push_receipt_append.py\" verify", self.text)


if __name__ == "__main__":
    unittest.main()
