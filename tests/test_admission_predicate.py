"""Selftests for resident-runtime/admission_predicate.py (offline, temp git repos, no clock)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "resident-runtime" / "admission_predicate.py"
spec = importlib.util.spec_from_file_location("admission_predicate", SCRIPT)
ap = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ap
spec.loader.exec_module(ap)

SIX = set(ap.SIX_FIELDS)
SESSION = "grok:p4-maintenance-lane/a65c67bf"


def run(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, name: str, data: bytes | None, msg: str, when: str) -> str:
    if data is None:
        run(repo, "rm", "-q", name)
    else:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_bytes(data)
        run(repo, "add", name)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=repo, check=True,
                   env={"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when, "PATH": "/usr/bin:/bin",
                        "HOME": str(repo), "GIT_CONFIG_NOSYSTEM": "1"})
    return run(repo, "rev-parse", "HEAD")


def cfg(repo: Path) -> None:
    run(repo, "config", "user.name", "t")
    run(repo, "config", "user.email", "t@example.invalid")


class Fixture:
    def __init__(self, td: Path):
        self.td = td
        self.origin = td / "origin.git"
        run(td, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.seed = td / "seed"
        run(td, "clone", "-q", str(self.origin), str(self.seed))
        cfg(self.seed)
        commit(self.seed, "README", b"base\n", "base", "2026-10-01T00:00:00Z")
        commit(self.seed, "old.txt", b"old\n", "old", "2026-10-01T00:00:10Z")
        run(self.seed, "push", "-q", "origin", "HEAD:main")
        self.clone = td / "clone"
        run(td, "clone", "-q", str(self.origin), str(self.clone))
        cfg(self.clone)
        self.base = run(self.clone, "rev-parse", "origin/main")
        self.base_time = int(run(self.clone, "show", "-s", "--format=%ct", self.base))
        run(self.clone, "checkout", "-q", "-b", "lane/x")
        self.vendored = b"vendored bytes\n"
        pin = {"vendored_path": "vendor/v.txt", "sha256": hashlib.sha256(self.vendored).hexdigest()}
        commit(self.clone, "vendor/v.txt", self.vendored, "vendor", "2026-10-02T00:00:00Z")
        commit(self.clone, "old.txt", None, "drop old", "2026-10-02T00:00:30Z")
        self.head = commit(self.clone, "pin.json", json.dumps(pin).encode(), "pin", "2026-10-02T00:01:00Z")
        run(self.clone, "push", "-q", "-u", "origin", "lane/x")

    def checks(self, conclusions: dict[str, str], sha: str | None = None) -> str:
        path = self.td / "checks.json"
        path.write_text(json.dumps({"check_runs": [
            {"name": n, "status": "completed", "conclusion": c, "head_sha": sha or self.head}
            for n, c in conclusions.items()]}))
        return str(path)

    def args(self, *extra: str, checks: str | None = None, epoch: str = "1000", session: str = SESSION,
             base: tuple | None = None):
        b = base or (self.base, self.base_time)
        return ap.parse(["--clone", str(self.clone), "--branch", "lane/x", "--session-id", session,
                         "--hb-epoch", epoch, "--check-runs", checks or self.checks({"a": "success"}),
                         "--base-sha", b[0], "--base-commit-time", str(b[1]), *extra])


def pred(out: dict, name: str) -> dict:
    return next(p for p in out["predicates"] if p["predicate"] == name)


class AdmissionPredicateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.f = Fixture(Path(self._td.name))

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_own_branch_all_pass_is_ready_and_sealed(self) -> None:
        out = ap.evaluate(self.f.args("--pin", "pin.json"))
        self.assertEqual("admission-input-ready", out["admission_input"], out["fail_closed"])
        self.assertEqual("ALLOW", out["disposition"])
        self.assertEqual(SESSION, out["declared_session"])
        self.assertEqual(1000, out["hb_epoch"])
        self.assertTrue(ap.seal_verifies(out))
        tampered = dict(out, head="0" * 40)
        self.assertFalse(ap.seal_verifies(tampered))
        self.assertEqual(ap.SCHEMA, out["schema"])
        self.assertEqual("StegVerse-org/.github#166", out["owning_existing_goal"])

    def test_content_paths_digests_and_change_digest(self) -> None:
        out = ap.evaluate(self.f.args())
        content = {e["path"]: e for e in out["content"]}
        self.assertEqual({"old.txt", "pin.json", "vendor/v.txt"}, set(content))
        self.assertTrue(content["old.txt"]["deleted"])
        self.assertIsNone(content["old.txt"]["blob_digest"])
        self.assertEqual("sha256:" + hashlib.sha256(self.f.vendored).hexdigest(), content["vendor/v.txt"]["blob_digest"])
        self.assertEqual({SESSION}, {e["writer_session"] for e in out["content"]})
        self.assertEqual({"path", "blob_digest", "writer_session", "deleted"}, set(out["content"][0]))
        # deterministic, TVC rule: digest over content sorted by path
        expected = "sha256:" + hashlib.sha256(json.dumps(sorted(out["content"], key=lambda e: e["path"]),
                                              sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(expected, out["change_digest"])
        self.assertEqual(out["change_digest"], ap.evaluate(self.f.args())["change_digest"])
        writer = pred(out, "BRANCH_WRITER_IS_BRANCH_OWNER")
        self.assertEqual(3, len(writer["commits"]))
        self.assertTrue(all(c["paths"] for c in writer["commits"]))

    def test_check_runs_input_is_bound_by_digest_not_embedded(self) -> None:
        path = self.f.checks({"a": "success"})
        out = ap.evaluate(self.f.args(checks=path))
        self.assertEqual("sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest(), out["check_runs_input"]["digest"])
        with self.assertRaises(SystemExit):
            ap.parse(["--clone", "x", "--branch", "y", "--session-id", SESSION, "--hb-epoch", "100"])

    def test_hb_epoch_missing_or_invalid_fails_closed(self) -> None:
        for epoch, code in (("", "HB_EPOCH_NOT_SUPPLIED"), ("12", "HB_EPOCH_INVALID"), ("1e3", "HB_EPOCH_INVALID")):
            out = ap.evaluate(self.f.args(epoch=epoch))
            self.assertEqual("FAIL_CLOSED", out["disposition"])
            self.assertEqual(code, out["failure_code"])
            self.assertIsNone(out["hb_epoch"])
            self.assertTrue(ap.seal_verifies(out))

    def test_session_not_declared(self) -> None:
        out = ap.evaluate(self.f.args(session="x"))
        self.assertEqual("AUTHOR_SESSION_NOT_DECLARED", out["failure_code"])
        self.assertEqual({ap.UNKNOWN}, {e["writer_session"] for e in out["content"]})

    def test_skipped_job_is_never_a_pass(self) -> None:
        out = ap.evaluate(self.f.args(checks=self.f.checks({"a": "success", "scan": "skipped"})))
        p = pred(out, "ALL_JOBS_RAN_AND_PASSED")
        self.assertEqual("CHECK_SKIPPED_OR_UNOBSERVED", p["failure_code"])
        self.assertTrue(SIX <= p.keys())
        self.assertEqual("not-ready", out["admission_input"])

    def test_failed_job_is_denied_and_wrong_head_unobserved(self) -> None:
        out = ap.evaluate(self.f.args(checks=self.f.checks({"a": "failure"})))
        self.assertEqual("REQUIRED_CHECK_DENIED", pred(out, "ALL_JOBS_RAN_AND_PASSED")["failure_code"])
        out = ap.evaluate(self.f.args(checks=self.f.checks({"a": "success"}, sha="1" * 40)))
        self.assertEqual("CHECK_SKIPPED_OR_UNOBSERVED", pred(out, "ALL_JOBS_RAN_AND_PASSED")["failure_code"])

    def test_foreign_writer_fails_closed(self) -> None:
        other = self.f.td / "other"
        run(self.f.td, "clone", "-q", "-b", "lane/x", str(self.f.origin), str(other))
        cfg(other)
        commit(other, "x.txt", b"x", "foreign", "2026-10-03T00:00:00Z")
        run(other, "push", "-q", "origin", "lane/x")
        run(self.f.clone, "pull", "-q", "--ff-only")
        out = ap.evaluate(self.f.args())
        p = pred(out, "BRANCH_WRITER_IS_BRANCH_OWNER")
        self.assertEqual("BRANCH_HAS_FOREIGN_WRITER", p["failure_code"])
        self.assertTrue(SIX <= p.keys())
        self.assertEqual({ap.UNKNOWN}, {e["writer_session"] for e in out["content"]})

    def test_server_push_without_local_push_fails_closed(self) -> None:
        act = self.f.td / "act.json"
        act.write_text(json.dumps([{"activity_type": "force_push", "after": "f" * 40, "timestamp": "t", "actor": {"login": "x"}}]))
        out = ap.evaluate(self.f.args("--activity", str(act)))
        self.assertEqual("BRANCH_HAS_FOREIGN_WRITER", pred(out, "BRANCH_WRITER_IS_BRANCH_OWNER")["failure_code"])

    def test_base_stale_against_supplied_base_ref(self) -> None:
        moved = commit(self.f.seed, "README", b"moved\n", "base moves", "2026-10-20T00:00:00Z")
        run(self.f.seed, "push", "-q", "origin", "HEAD:main")
        run(self.f.clone, "fetch", "-q", "origin", "main")
        moved_time = int(run(self.f.clone, "show", "-s", "--format=%ct", moved))
        out = ap.evaluate(self.f.args("--stale-days", "7", base=(moved, moved_time)))
        p = pred(out, "HEAD_CURRENT_WITH_BASE")
        self.assertEqual("BASE_STALE", p["failure_code"])
        self.assertEqual("DENY", p["disposition"])
        self.assertEqual(1, p["behind_base"])
        self.assertGreater(p["head_age_days_vs_base"], 7)
        # the old supplied base_ref still holds, whatever the local branch state is
        self.assertTrue(pred(ap.evaluate(self.f.args()), "HEAD_CURRENT_WITH_BASE")["holds"])

    def test_base_ref_not_observed(self) -> None:
        out = ap.evaluate(self.f.args(base=("2" * 40, 1)))
        self.assertEqual("BASE_STATE_NOT_OBSERVED", pred(out, "HEAD_CURRENT_WITH_BASE")["failure_code"])

    def test_binder_pin_mismatch(self) -> None:
        commit(self.f.clone, "vendor/v.txt", b"tampered\n", "tamper", "2026-10-02T00:02:00Z")
        run(self.f.clone, "push", "-q", "origin", "lane/x")
        out = ap.evaluate(self.f.args("--pin", "pin.json", checks=self.f.checks({"a": "success"},
                                      sha=run(self.f.clone, "rev-parse", "HEAD"))))
        p = pred(out, "BINDER_PINS_MATCH")
        self.assertEqual("BINDER_PIN_MISMATCH", p["failure_code"])
        self.assertTrue(p["pins"][0]["pin_file_digest"].startswith("sha256:"))

    def test_no_clock_or_network_in_source(self) -> None:
        src = SCRIPT.read_text()
        for forbidden in ("import time", "datetime", "urllib", "socket", "http.client", "AI_SESSION_GATE"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
