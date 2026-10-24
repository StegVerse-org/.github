import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "resident-runtime"))

import merge_transfer_dry_run_check as gate  # noqa: E402
from merge_transfer import NOT_LEDGERED, SIX_FIELDS  # noqa: E402

VERIFIED = {"merge_commit": "a" * 40, "disposition": "ALLOW", "transfer": "VERIFIED"}
NOT_LEDGERED_RECORD = {"merge_commit": "b" * 40, "disposition": "FAIL_CLOSED", "transfer": "UNVERIFIED",
                       "failure_code": NOT_LEDGERED, "failed_predicate": "MAIN_MERGE_HAS_AN_ORGANIZATION_LEDGER_RECEIPT",
                       "required_evidence_or_repair": "run the writer", "retry_entrypoint": "merge_transfer.py append",
                       "owning_existing_goal": "StegVerse-org/.github#162", "next_attempt": "next push to main"}


def variant(base, **changes):
    out = copy.deepcopy(base)
    for key, value in changes.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


class DryRunGateTests(unittest.TestCase):
    def test_the_two_stated_shapes_pass(self):
        self.assertEqual(gate.check([VERIFIED, NOT_LEDGERED_RECORD]), [])

    def test_allow_requires_verified(self):
        for record in (variant(VERIFIED, transfer="UNVERIFIED"), variant(VERIFIED, transfer=None),
                       variant(VERIFIED, transfer="UNVERIFIED", failure_code=NOT_LEDGERED)):
            self.assertFalse(gate.record_ok(record), record)

    def test_fail_closed_requires_not_ledgered(self):
        for code in ("MERGE_TRANSFER_RECEIPT_LINK_UNVERIFIED", "X", " " + NOT_LEDGERED, None):
            self.assertFalse(gate.record_ok(variant(NOT_LEDGERED_RECORD, failure_code=code)), code)

    def test_partial_or_malformed_six_fields_fail(self):
        for field in SIX_FIELDS:
            for bad in (None, "", " ", 1, ["x"], " padded", "padded "):
                with self.subTest(field=field, value=bad):
                    if field == "failure_code" and isinstance(bad, str) and bad.strip() == NOT_LEDGERED:
                        continue
                    self.assertFalse(gate.record_ok(variant(NOT_LEDGERED_RECORD, **{field: bad})))

    def test_deny_and_other_dispositions_fail(self):
        for disposition in ("DENY", "allow", "FAIL_CLOSED ", "", None):
            self.assertFalse(gate.record_ok(variant(VERIFIED, disposition=disposition)), disposition)
            self.assertFalse(gate.record_ok(variant(NOT_LEDGERED_RECORD, disposition=disposition)), disposition)

    def test_one_bad_record_fails_the_whole_result(self):
        failures = gate.check([VERIFIED, variant(NOT_LEDGERED_RECORD, next_attempt=" ")])
        self.assertEqual(len(failures), 1)

    def test_non_list_and_non_object_shapes_fail(self):
        for results in ({}, "x", None, 1, []):
            self.assertTrue(gate.check(results), results)
        self.assertTrue(gate.check([["x"]]))
        self.assertTrue(gate.check(["x"]))

    def test_cli_exit_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "real-state.json"
            script = ROOT / "resident-runtime" / "merge_transfer_dry_run_check.py"
            path.write_text(json.dumps([VERIFIED, NOT_LEDGERED_RECORD]), encoding="utf-8")
            self.assertEqual(subprocess.run([sys.executable, str(script), str(path)], capture_output=True).returncode, 0)
            path.write_text(json.dumps([variant(NOT_LEDGERED_RECORD, failure_code="X")]), encoding="utf-8")
            result = subprocess.run([sys.executable, str(script), str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("DRY_RUN_GATE_FAIL", result.stdout)


# -- regression: SV-LLM/.github main a6503e37 (push run 40123764551) and every PR on it -------------------
# 1. A PR whose base is already ledgered selects an empty range; verify got no commits and wrote no file, and
#    the gate raised FileNotFoundError. 2. The writer appended to the published ref during the push dry run,
#    and "published tip == copied tip" failed on a correct writer append. Clock-free, network-free.

import importlib.util  # noqa: E402
import os  # noqa: E402
from unittest import mock  # noqa: E402

GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
           "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rng = _load("merge_transfer_range_under_test", "resident-runtime/merge_transfer_range.py")
guard = _load("ledger_publish_guard_under_test", "resident-runtime/ledger_publish_guard.py")


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                          env=GIT_ENV).stdout.strip()


def _commit(cwd, message, parent=None):
    tree = _git(cwd, "write-tree")
    return _git(cwd, "commit-tree", tree, "-m", message, *(["-p", parent] if parent else []))


class _Repo:
    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name)
        _git(self.path, "init", "-q")
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()


def _six_ok(record):
    return all(isinstance(record.get(f), str) and record.get(f) and record[f].strip() == record[f] for f in SIX_FIELDS)


class EmptyRangeSelectionTests(unittest.TestCase):
    """--before BASE --after BASE on a ledgered BASE: select BASE (no-op verify), never an empty list."""

    def _select(self, git_dir, base, verify):
        with mock.patch.object(rng.mt, "verify_merge_transfer", side_effect=verify), \
                mock.patch.object(rng.mt, "repository", return_value="SV-LLM/.github"):
            return rng.dry_run_selection(base, None, object(), object(), git_dir)

    def test_ledgered_base_with_empty_range_selects_the_base(self):
        with _Repo() as repo:
            base = _commit(repo.path, "Merge pull request #55 from SV-LLM/x")
            self.assertEqual(rng.mt.pushed_commits(base, base, None, git_dir=repo.path), [])
            allow = {"disposition": "ALLOW", "transfer": "VERIFIED", "merge_commit": base}
            commits, refused = self._select(repo.path, base, lambda *a: allow)
            self.assertEqual((commits, refused), ([base], None))

    def test_unreceipted_base_is_still_selected_by_the_range(self):
        with _Repo() as repo:
            base = _commit(repo.path, "m")
            commits, refused = self._select(repo.path, base, lambda *a: dict(NOT_LEDGERED_RECORD, merge_commit=base))
            self.assertEqual((commits, refused), ([base], None))

    def test_deny_or_other_fail_closed_base_is_six_field_fail_closed(self):
        with _Repo() as repo:
            base = _commit(repo.path, "m")
            for answer in ({"disposition": "DENY", "failure_code": "MERGE_TRANSFER_RECEIPT_LINK_UNVERIFIED"},
                           {"disposition": "FAIL_CLOSED", "failure_code": "HB_EPOCH_SOURCE_UNOBSERVED"},
                           {"disposition": "ALLOW", "transfer": "UNVERIFIED"}):
                commits, refused = self._select(repo.path, base, lambda *a, r=answer: r)
                self.assertEqual(commits, [], answer)
                self.assertEqual(refused["disposition"], "FAIL_CLOSED")
                self.assertEqual(refused["failure_code"], rng.SELECTION_EMPTY)
                self.assertTrue(_six_ok(refused), refused)

    def test_absent_or_malformed_base_is_six_field_fail_closed(self):
        with _Repo() as repo:
            _commit(repo.path, "m")
            for base in ("", None, "0" * 40, "abc", "f" * 40):
                commits, refused = self._select(repo.path, base, lambda *a: self.fail("verify must not run"))
                self.assertEqual(commits, [], base)
                self.assertTrue(_six_ok(refused), refused)


class EmptyCommitsNeverRaiseTests(unittest.TestCase):
    def test_verify_with_no_commits_is_six_field_and_the_gate_fails_closed(self):
        # merge_transfer.py is the pinned shared verifier (sha256 032ed727...); it is not changed here. With no
        # commits it prints a six-field refusal and writes no --out; the gate reads that as six-field FAIL_CLOSED.
        with tempfile.TemporaryDirectory() as tmp:
            empty, out = Path(tmp) / "commits.txt", Path(tmp) / "real-state.json"
            empty.write_text("\n", encoding="utf-8")
            script = ROOT / "resident-runtime" / "merge_transfer.py"
            result = subprocess.run([sys.executable, str(script), "verify", "--commits-file", str(empty),
                                     "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("Traceback", result.stderr)
            self.assertTrue(_six_ok(json.loads(result.stdout)), result.stdout)
            gated = subprocess.run([sys.executable, str(ROOT / "resident-runtime/merge_transfer_dry_run_check.py"),
                                    str(out)], capture_output=True, text=True)
            self.assertEqual(gated.returncode, 1)
            self.assertNotIn("Traceback", gated.stderr)
            line = gated.stdout.strip()
            self.assertTrue(line.startswith("DRY_RUN_GATE_FAIL: "), line)
            self.assertTrue(_six_ok(json.loads(line.split(": ", 1)[1])), line)

    def test_gate_on_a_missing_result_is_six_field_fail_closed_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            for content in (None, "", "{not json"):
                path = Path(tmp) / "real-state.json"
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(content, encoding="utf-8")
                buffer = __import__("io").StringIO()
                with mock.patch("sys.stdout", buffer):
                    self.assertEqual(gate.main([str(path)]), 1)
                line = buffer.getvalue().strip()
                self.assertTrue(line.startswith("DRY_RUN_GATE_FAIL: "), line)
                record = json.loads(line.split(": ", 1)[1])
                self.assertEqual(record["failure_code"], gate.RESULT_UNREADABLE)
                self.assertTrue(_six_ok(record), record)


class PublishGuardTests(unittest.TestCase):
    """The writer may append to the published ref during a dry run; a scratch append must never be published."""

    def setUp(self):
        self.repo = _Repo().__enter__()
        p = self.repo.path
        self.copied = _commit(p, "ledger append 1")
        self.writer = _commit(p, "ledger append 2 (writer, published)", self.copied)
        self.scratch = _commit(p, "ledger append 2 (dry run, scratch)", self.copied)
        self.rewritten = _commit(p, "rewritten ledger root")

    def tearDown(self):
        self.repo.__exit__(None, None, None)

    def check(self, copied, now, scratch):
        return guard.check(str(self.repo.path), copied, now, scratch)

    def test_unchanged_published_tip_allows(self):
        self.assertEqual(self.check(self.copied, self.copied, self.scratch)["disposition"], "ALLOW")
        self.assertEqual(self.check(self.copied, self.copied, self.copied)["disposition"], "ALLOW")

    def test_writer_append_during_the_dry_run_allows(self):
        result = self.check(self.copied, self.writer, self.scratch)
        self.assertEqual(result["disposition"], "ALLOW", result)
        self.assertEqual(result["published_grew_by"], 1)
        self.assertEqual(result["scratch_appends"], 1)

    def test_published_scratch_append_denies(self):
        for now in (self.scratch, _commit(self.repo.path, "on top of scratch", self.scratch)):
            result = self.check(self.copied, now, self.scratch)
            self.assertEqual((result["disposition"], result["failure_code"]), ("DENY", "DRY_RUN_APPEND_PUBLISHED"))
            self.assertTrue(_six_ok(result), result)

    def test_rewritten_published_ref_denies(self):
        result = self.check(self.copied, self.rewritten, self.scratch)
        self.assertEqual((result["disposition"], result["failure_code"]), ("DENY", "LEDGER_PUBLISHED_REF_NOT_APPEND_ONLY"))
        self.assertTrue(_six_ok(result), result)

    def test_unreadable_tips_fail_closed(self):
        for args in (("", self.writer, self.scratch), (self.copied, "", self.scratch), (self.copied, "e" * 40, self.scratch),
                     (self.copied, self.writer, "not-a-sha")):
            result = self.check(*args)
            self.assertEqual((result["disposition"], result["failure_code"]), ("FAIL_CLOSED", "LEDGER_PUBLISHED_TIP_UNREADABLE"))
            self.assertTrue(_six_ok(result), result)

    def test_guard_reads_no_clock_and_no_network(self):
        source = (ROOT / "resident-runtime/ledger_publish_guard.py").read_text(encoding="utf-8")
        for token in ("import time", "datetime", "urllib", "socket", "requests", '"ls-remote"', '"fetch"', '"push"'):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
