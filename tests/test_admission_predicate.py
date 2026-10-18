"""Selftests for resident-runtime/admission_predicate.py (offline, temp git repos)."""

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

SIX = {"failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
       "owning_existing_goal", "next_attempt"}


def run(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, name: str, data: bytes, msg: str, when: str) -> str:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_bytes(data)
    run(repo, "add", name)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=repo, check=True,
                   env={"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when, "PATH": "/usr/bin:/bin",
                        "HOME": str(repo), "GIT_CONFIG_NOSYSTEM": "1"})
    return run(repo, "rev-parse", "HEAD")


class Fixture:
    def __init__(self, td: Path):
        self.origin = td / "origin.git"
        run(td, "init", "-q", "--bare", "-b", "main", str(self.origin))
        seed = td / "seed"
        run(td, "clone", "-q", str(self.origin), str(seed))
        self.cfg(seed)
        commit(seed, "README", b"base\n", "base", "2026-10-01T00:00:00Z")
        run(seed, "push", "-q", "origin", "HEAD:main")
        self.clone = td / "clone"
        run(td, "clone", "-q", str(self.origin), str(self.clone))
        self.cfg(self.clone)
        run(self.clone, "checkout", "-q", "-b", "lane/x")
        vendored = b"vendored bytes\n"
        pin = {"vendored_path": "vendor/v.txt", "sha256": hashlib.sha256(vendored).hexdigest()}
        commit(self.clone, "vendor/v.txt", vendored, "vendor", "2026-10-02T00:00:00Z")
        self.head = commit(self.clone, "pin.json", json.dumps(pin).encode(), "pin", "2026-10-02T00:01:00Z")
        run(self.clone, "push", "-q", "-u", "origin", "lane/x")
        self.td = td

    @staticmethod
    def cfg(repo: Path) -> None:
        run(repo, "config", "user.name", "t")
        run(repo, "config", "user.email", "t@example.invalid")

    def args(self, *extra: str):
        return ap.parse(["--clone", str(self.clone), "--branch", "lane/x", *extra])


class AdmissionPredicateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.f = Fixture(Path(self._td.name))

    def tearDown(self) -> None:
        self._td.cleanup()

    def checks(self, conclusions: dict[str, str]) -> str:
        path = self.f.td / "checks.json"
        path.write_text(json.dumps({"check_runs": [
            {"name": n, "status": "completed", "conclusion": c, "head_sha": self.f.head} for n, c in conclusions.items()]}))
        return str(path)

    def test_own_branch_all_pass_is_ready(self) -> None:
        out = ap.evaluate(self.f.args("--check-runs", self.checks({"a": "success"}), "--pin", "pin.json"))
        self.assertEqual("admission-input-ready", out["admission_input"], out["fail_closed"])
        writer = out["predicates"][0]
        self.assertTrue(writer["branch_created"])
        self.assertEqual(self.f.head, writer["pushes"][-1]["sha"])
        self.assertTrue(all(c["in_local_branch_reflog"] for c in writer["commits"]))

    def test_skipped_job_is_never_a_pass(self) -> None:
        out = ap.evaluate(self.f.args("--check-runs", self.checks({"a": "success", "scan": "skipped"})))
        self.assertEqual("not-ready", out["admission_input"])
        self.assertEqual("REQUIRED_JOB_NOT_PASSED", out["fail_closed"][0]["failure_code"])
        self.assertTrue(SIX <= out["fail_closed"][0].keys())

    def test_missing_required_job(self) -> None:
        out = ap.evaluate(self.f.args("--check-runs", self.checks({"a": "success"}), "--required", "a", "b"))
        self.assertEqual("not-ready", out["admission_input"])

    def test_foreign_writer_fails_closed(self) -> None:
        other = self.f.td / "other"
        run(self.f.td, "clone", "-q", "-b", "lane/x", str(self.f.origin), str(other))
        Fixture.cfg(other)
        commit(other, "x.txt", b"x", "foreign", "2026-10-03T00:00:00Z")
        run(other, "push", "-q", "origin", "lane/x")
        run(self.f.clone, "pull", "-q", "--ff-only")
        out = ap.evaluate(self.f.args())
        self.assertEqual("not-ready", out["admission_input"])
        fc = out["fail_closed"][0]
        self.assertEqual("BRANCH_WRITER_EVIDENCE_ABSENT", fc["failure_code"])
        self.assertTrue(SIX <= fc.keys())

    def test_server_push_without_local_push_fails_closed(self) -> None:
        act = self.f.td / "act.json"
        act.write_text(json.dumps([{"activity_type": "force_push", "after": "f" * 40, "timestamp": "t", "actor": {"login": "x"}}]))
        out = ap.evaluate(self.f.args("--activity", str(act)))
        self.assertEqual("not-ready", out["admission_input"])

    def test_stale_behind_base_and_age(self) -> None:
        seed = self.f.td / "seed"
        commit(seed, "README", b"moved\n", "base moves", "2026-10-20T00:00:00Z")
        run(seed, "push", "-q", "origin", "HEAD:main")
        run(self.f.clone, "fetch", "-q", "origin", "main")
        out = ap.evaluate(self.f.args("--stale-days", "7"))
        st = next(p for p in out["predicates"] if p["predicate"] == "PR_NOT_STALE")
        self.assertFalse(st["holds"])
        self.assertEqual(1, st["behind_base"])
        self.assertGreater(st["head_age_days_vs_base_tip"], 7)

    def test_binder_pin_mismatch(self) -> None:
        commit(self.f.clone, "vendor/v.txt", b"tampered\n", "tamper", "2026-10-02T00:02:00Z")
        run(self.f.clone, "push", "-q", "origin", "lane/x")
        out = ap.evaluate(self.f.args("--pin", "pin.json"))
        self.assertEqual("BINDER_PIN_MISMATCH", out["fail_closed"][0]["failure_code"])


if __name__ == "__main__":
    unittest.main()
