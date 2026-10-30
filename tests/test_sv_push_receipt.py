"""sv-push-receipt.v1: schema and push-time producer (resident-runtime/sv_push_receipt.py).

Every repository here is a temporary local git repository; the "remote" is a local bare repository, so
the pushes in these tests are local and use no network.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "sv-push-receipt.v1.schema.json"
_spec = importlib.util.spec_from_file_location("sv_push_receipt", ROOT / "resident-runtime" / "sv_push_receipt.py")
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint", "owning_existing_goal", "next_attempt")
SESSION = "grok-lane-c"
NAME = "StegVerse-Labs/fixture"
REF = "refs/heads/feature"
TRACK = "refs/remotes/origin/feature"


def git(repo, *args, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
                "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    p = subprocess.run(["git", "-C", str(repo), *args], env=env, capture_output=True, text=True, check=check)
    return p.stdout.strip()


def schema_errors(schema, r):
    """Checks every keyword sv-push-receipt.v1 uses (closed object, required, const, pattern, minLength, items)."""
    errs = []
    props = schema["properties"]
    if not isinstance(r, dict):
        return ["type"]
    errs += [f"extra:{k}" for k in r if k not in props]
    errs += [f"missing:{k}" for k in schema["required"] if k not in r]
    for k, v in r.items():
        s = props.get(k, {})
        if "const" in s and v != s["const"]:
            errs.append(f"const:{k}")
        if s.get("type") == "string":
            if not isinstance(v, str) or len(v) < s.get("minLength", 0) or ("pattern" in s and not re.search(s["pattern"], v)):
                errs.append(f"string:{k}")
        if s.get("type") == "array":
            if not isinstance(v, list) or len(v) < s.get("minItems", 0) or (s.get("uniqueItems") and len(set(v)) != len(v)) \
                    or any(not re.search(s["items"]["pattern"], x) for x in v if isinstance(x, str)):
                errs.append(f"array:{k}")
    return errs


class PushReceiptTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        t = Path(self._tmp.name)
        self.remote, self.work = t / "remote.git", t / "work"
        git(t, "init", "--bare", "-q", str(self.remote))
        git(t, "init", "-q", "-b", "main", str(self.work))
        git(self.work, "config", "core.logAllRefUpdates", "false")  # no reflog anywhere: the receipt must not need one
        git(self.work, "remote", "add", "origin", str(self.remote))
        self.base = self.commit("base")
        git(self.work, "push", "-q", "origin", "main")
        git(self.work, "checkout", "-q", "-b", "feature")
        self.out = t / "receipt.json"
        self.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    def tearDown(self):
        self._tmp.cleanup()

    def commit(self, name):
        (self.work / name).write_text(name + "\n")
        git(self.work, "add", name)
        git(self.work, "commit", "-q", "-m", name)
        return git(self.work, "rev-parse", "HEAD")

    def push_and_emit(self, old, *names, force=False, **kw):
        made = [self.commit(n) for n in names]
        git(self.work, "push", "-q", *(["--force"] if force else []), "origin", "feature")
        kw.setdefault("hb_epoch", "1024")
        return made, P.emit(self.work, repository_name=NAME, ref=REF, old_sha=old, pusher_session=SESSION,
                            after_ref=TRACK, out=kw.pop("out", self.out), **kw)

    def assert_refusal(self, r, code):
        self.assertEqual((r["schema"], r["disposition"], r["failure_code"]), (P.REFUSAL_SCHEMA, "FAIL_CLOSED", code), r)
        for f in SIX:
            self.assertTrue(isinstance(r[f], str) and r[f].strip(), f)
        self.assertEqual(r["owning_existing_goal"], "StegVerse-org/.github#164")
        self.assertFalse(r["receipt_written"])
        self.assertTrue(P.seal_verifies(r))

    def test_new_branch_receipt_from_the_push(self):
        self.assertIsNone(P.read_ref(self.work, TRACK))  # new branch: the caller names the fork base as old_sha
        made, r = self.push_and_emit(self.base, "a", "b", change_id="svc:" + "1" * 64)
        self.assertEqual(schema_errors(self.schema, r), [])
        self.assertIsNone(P.receipt_problem(r))
        self.assertEqual((r["old_sha"], r["new_sha"], r["pushed_commits"]), (self.base, made[-1], made))
        self.assertEqual((r["repository"], r["ref"], r["pusher_session"], r["hb_epoch"]), (NAME, REF, SESSION, "1024"))
        self.assertEqual(json.loads(self.out.read_text()), r)
        self.assertFalse((self.work / ".git" / "logs" / "refs" / "remotes").exists())  # produced with no reflog

    def test_chain_of_pushes_is_contiguous(self):
        _, first = self.push_and_emit(self.base, "a")
        before = P.read_ref(self.work, TRACK)  # read BEFORE the second push
        made, second = self.push_and_emit(before, "b", "c", out=None)
        self.assertEqual(first["new_sha"], second["old_sha"])
        self.assertEqual(second["pushed_commits"], made)
        self.assertNotIn("change_id", second)
        self.assertEqual(schema_errors(self.schema, second), [])

    def test_force_push_is_refused_and_writes_nothing(self):
        _, first = self.push_and_emit(self.base, "a")
        self.out.unlink()
        git(self.work, "reset", "-q", "--hard", self.base)
        _, r = self.push_and_emit(first["new_sha"], "rewrite", force=True)
        self.assert_refusal(r, "PUSH_NOT_FAST_FORWARD")
        self.assertFalse(self.out.exists())

    def test_hb_epoch_is_supplied_or_fail_closed(self):
        for epoch, code in ((None, "HB_EPOCH_NOT_SUPPLIED"), ("31", "HB_EPOCH_INVALID"), ("abc", "HB_EPOCH_INVALID"), (True, "HB_EPOCH_INVALID")):
            with self.subTest(epoch=epoch):
                r = P.emit(self.work, repository_name=NAME, ref=REF, old_sha=self.base, pusher_session=SESSION,
                           hb_epoch=epoch, after_ref="refs/heads/main", out=self.out)
                self.assert_refusal(r, code)
                self.assertFalse(self.out.exists())

    def test_unmoved_ref_bad_inputs_and_unreadable_repository(self):
        r = P.emit(self.work, repository_name=NAME, ref=REF, old_sha=self.base, pusher_session=SESSION, hb_epoch="1024", after_ref="refs/heads/main")
        self.assert_refusal(r, "PUSH_NOT_OBSERVED")
        self.assertEqual(r["failed_predicate"], "PUSH_MOVED_REF")
        for field, kw in (("repository_name", {"repository_name": "x"}), ("ref", {"ref": "main"}), ("pusher_session", {"pusher_session": " "}),
                          ("change_id", {"change_id": "SV-CHANGE-1"}), ("old_sha", {"old_sha": "abc"})):
            with self.subTest(field):
                args = dict(repository_name=NAME, ref=REF, old_sha=self.base, pusher_session=SESSION, hb_epoch="1024", after_ref="refs/heads/main")
                args.update(kw)
                self.assert_refusal(P.emit(self.work, **args), "PUSH_RECEIPT_INPUT_INVALID")
        self.assert_refusal(P.emit(self.work.parent / "nope", repository_name=NAME, ref=REF, old_sha=self.base, pusher_session=SESSION,
                                   hb_epoch="1024"), "PUSH_NOT_OBSERVED")

    def test_tampering_breaks_the_receipt(self):
        _, r = self.push_and_emit(self.base, "a")
        for field, value in (("pusher_session", "someone-else"), ("pushed_commits", ["0" * 40]), ("extra", 1)):
            with self.subTest(field):
                bad = dict(r, **{field: value})
                self.assertIsNotNone(P.receipt_problem(bad))
        self.assertIn("extra:extra", schema_errors(self.schema, dict(r, extra=1)))

    def test_read_only_no_clock_no_network_no_append(self):
        refs = git(self.work, "for-each-ref")
        self.push_and_emit(self.base, "a")
        refs_after_push = git(self.work, "for-each-ref")
        P.emit(self.work, repository_name=NAME, ref=REF, old_sha=self.base, pusher_session=SESSION, hb_epoch="1024", after_ref=TRACK)
        self.assertEqual(git(self.work, "for-each-ref"), refs_after_push)
        self.assertNotEqual(refs, refs_after_push)  # only the test's own push moved refs
        src = (ROOT / "resident-runtime" / "sv_push_receipt.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^\s*(import|from)\s+(time|datetime|urllib|http|socket|requests|random)\b", src, re.M))
        self.assertEqual(set(re.findall(r'_git\(repo, "([a-z-]+)"', src)), {"rev-parse", "cat-file", "merge-base", "rev-list"})
        code = src.split('"""', 2)[2]
        for token in ("reflog", "logs/", "update-ref", '"push"', "organization-ledger", "urlopen"):
            self.assertNotIn(token, code, token)
        self.assertEqual(code.count("write_bytes("), 1)  # the receipt file is the only write
        self.assertIn("StegVerse-Labs/.github#3255", P.APPENDER)

    def test_schema_is_closed_and_matches_the_producer(self):
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(set(self.schema["properties"]), set(P.RECEIPT_FIELDS))
        self.assertEqual(set(self.schema["required"]), set(P.RECEIPT_FIELDS) - {"change_id"})
        self.assertEqual(self.schema["properties"]["schema"]["const"], P.RECEIPT_SCHEMA)


if __name__ == "__main__":
    unittest.main()
