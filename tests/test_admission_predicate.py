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
             current: tuple | None = None, expect: tuple = ("a",)):
        c = current or (self.base, self.base_time)
        exp = [x for e in expect for x in ("--expect", e)]
        return ap.parse(["--clone", str(self.clone), "--branch", "lane/x", "--session-id", session,
                         "--hb-epoch", epoch, "--check-runs", checks or self.checks({"a": "success"}), *exp,
                         "--base-sha", self.base, "--base-commit-time", str(self.base_time),
                         "--current-base-sha", c[0], "--current-base-commit-time", str(c[1]), *extra])


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
        self.assertEqual([{"session": SESSION, "evidence_class": "DECLARED"}] * 3, [e["writer_session"] for e in out["content"]])
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
        self.assertEqual("stegverse.admission-job-observation/v2", out["job_observation"]["schema"])
        self.assertEqual("ADMISSION_INPUT_READY", out["job_observation"]["decision"])
        self.assertNotIn("jobs", pred(out, "ALL_JOBS_RAN_AND_PASSED"))  # no own classification rows

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
        self.assertTrue(all(e["writer_session"] == {"session": None, "evidence_class": ap.UNKNOWN} for e in out["content"]))

    def test_skipped_job_is_never_a_pass_via_lane_a(self) -> None:
        out = ap.evaluate(self.f.args(checks=self.f.checks({"a": "success", "scan": "skipped"}), expect=("a", "scan")))
        p = pred(out, "ALL_JOBS_RAN_AND_PASSED")
        self.assertEqual("CHECK_SKIPPED_OR_UNOBSERVED", p["failure_code"])
        self.assertEqual("NOT_ADMISSION_INPUT_READY", out["job_observation"]["decision"])
        self.assertTrue(SIX <= p.keys())
        self.assertEqual("not-ready", out["admission_input"])

    def test_path_filtered_expected_job_is_unobserved(self) -> None:
        out = ap.evaluate(self.f.args(expect=("a", "never-triggered")))
        self.assertEqual("CHECK_SKIPPED_OR_UNOBSERVED", pred(out, "ALL_JOBS_RAN_AND_PASSED")["failure_code"])

    def test_failed_job_is_denied_and_wrong_head_unobserved(self) -> None:
        out = ap.evaluate(self.f.args(checks=self.f.checks({"a": "failure"})))
        self.assertEqual("REQUIRED_CHECK_DENIED", pred(out, "ALL_JOBS_RAN_AND_PASSED")["failure_code"])
        self.assertEqual("DENY", pred(out, "ALL_JOBS_RAN_AND_PASSED")["disposition"])
        out = ap.evaluate(self.f.args(checks=self.f.checks({"a": "success"}, sha="1" * 40)))
        self.assertEqual("CHECK_SKIPPED_OR_UNOBSERVED", pred(out, "ALL_JOBS_RAN_AND_PASSED")["failure_code"])

    def test_no_expectation_or_no_document_fails_closed_with_lane_a_code(self) -> None:
        out = ap.evaluate(self.f.args(expect=()))
        p = pred(out, "ALL_JOBS_RAN_AND_PASSED")
        self.assertEqual("EXPECTED_JOBS_NOT_DECLARED", p["failure_code"])
        self.assertEqual("FAIL_CLOSED", p["disposition"])
        self.assertTrue(SIX <= p.keys())
        bad = self.f.td / "bad.json"
        bad.write_text("not json")
        out = ap.evaluate(self.f.args(checks=str(bad)))
        self.assertEqual("CHECK_RUNS_DOCUMENT_MALFORMED", pred(out, "ALL_JOBS_RAN_AND_PASSED")["failure_code"])

    def test_null_head_sha_run_no_longer_counts_for_head(self) -> None:
        path = self.f.td / "nullhead.json"
        path.write_text(json.dumps({"check_runs": [
            {"name": "a", "status": "completed", "conclusion": "success", "head_sha": None}]}))
        out = ap.evaluate(self.f.args(checks=str(path)))
        p = pred(out, "ALL_JOBS_RAN_AND_PASSED")
        self.assertEqual("CHECK_SKIPPED_OR_UNOBSERVED", p["failure_code"])
        self.assertEqual("UNKNOWN_NOT_AUTHENTICALLY_OBSERVED", out["job_observation"]["jobs"][0]["state"])
        self.assertEqual(1, out["job_observation"]["runs_not_evidence_for_head"])
        path.write_text(json.dumps({"check_runs": [{"name": "a", "status": "completed", "conclusion": "success"}]}))
        self.assertEqual("CHECK_SKIPPED_OR_UNOBSERVED",
                         pred(ap.evaluate(self.f.args(checks=str(path))), "ALL_JOBS_RAN_AND_PASSED")["failure_code"])

    def test_lane_a_record_is_sealed_and_bound(self) -> None:
        out = ap.evaluate(self.f.args())
        rec = out["job_observation"]
        self.assertTrue(ap.seal_verifies(rec))
        self.assertEqual(out["change_digest"], rec["change_digest"])
        self.assertEqual(1000, rec["hb_epoch"])
        self.assertEqual("StegVerse-org/.github#166", rec["owning_existing_goal"])

    def test_pin_is_lane_a_78ea9128(self) -> None:
        pin = json.loads(ap.LANE_A_PIN.read_text())
        self.assertEqual("78ea91280f04cebed02d95a9714670540f30b112", pin["producer"]["head"])
        self.assertEqual("4edc240aa9447b27adfb4a7443dfcf7bb7d9a665", pin["producer"]["git_blob_sha"])
        self.assertEqual("0e962613328ef4acd09973062844d2bf5d46230714abd2b35b110342d6660a0d", pin["sha256"])
        self.assertEqual("stegverse.admission-job-observation/v2", pin["result_schema"])

    def test_lane_a_pin_verified_and_tamper_fails_closed(self) -> None:
        mod, ref, why = ap.load_job_observation_reference()
        self.assertIsNotNone(mod, why)
        self.assertEqual(ref["pinned_sha256"], ref["vendored_sha256"])
        self.assertEqual(ref["pinned_git_blob_sha"], ref["vendored_git_blob_sha"])
        root = Path(self._td.name) / "repo"
        (root / "config" / "admission-predicate").mkdir(parents=True)
        (root / "vendor" / "lane_a").mkdir(parents=True)
        pin = json.loads(ap.LANE_A_PIN.read_text())
        (root / "config" / "admission-predicate" / "p.json").write_text(json.dumps(pin))
        src = (ap.LANE_A_PIN.resolve().parents[2] / pin["vendored_path"]).read_bytes()
        (root / pin["vendored_path"]).write_bytes(src + b"# tampered\n")
        mod, ref, why = ap.load_job_observation_reference(root / "config" / "admission-predicate" / "p.json")
        self.assertIsNone(mod)
        self.assertIn("do not equal the pin", why)
        saved = ap.LANE_A_PIN
        try:
            ap.LANE_A_PIN = root / "config" / "admission-predicate" / "p.json"
            out = ap.evaluate(self.f.args())
        finally:
            ap.LANE_A_PIN = saved
        p = pred(out, "ALL_JOBS_RAN_AND_PASSED")
        self.assertEqual("JOB_OBSERVATION_REFERENCE_UNAVAILABLE", p["failure_code"])
        self.assertIsNone(out["job_observation"])

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
        self.assertTrue(all(e["writer_session"] == {"session": None, "evidence_class": ap.UNKNOWN} for e in out["content"]))

    def test_server_push_without_local_push_fails_closed(self) -> None:
        act = self.f.td / "act.json"
        act.write_text(json.dumps([{"activity_type": "force_push", "after": "f" * 40, "timestamp": "t", "actor": {"login": "x"}}]))
        out = ap.evaluate(self.f.args("--activity", str(act)))
        self.assertEqual("BRANCH_HAS_FOREIGN_WRITER", pred(out, "BRANCH_WRITER_IS_BRANCH_OWNER")["failure_code"])

    def test_base_stale_from_supplied_inputs_only(self) -> None:
        later = self.f.base_time + 10 * 86400
        out = ap.evaluate(self.f.args("--stale-days", "7", current=("9" * 40, later)))
        p = pred(out, "HEAD_CURRENT_WITH_BASE")
        self.assertEqual("BASE_STALE", p["failure_code"])
        self.assertEqual("DENY", p["disposition"])
        self.assertEqual({"sha", "age_days"}, set(p["moved"]))
        # the current base sha need not exist in the clone: staleness reads no git
        self.assertTrue(pred(ap.evaluate(self.f.args()), "HEAD_CURRENT_WITH_BASE")["holds"])

    def test_registry_generation_and_ledger_head_compared_when_supplied(self) -> None:
        out = ap.evaluate(self.f.args("--base-registry-generation", "319", "--current-registry-generation", "320",
                                      "--base-ledger-head", "L1", "--current-ledger-head", "L1"))
        p = pred(out, "HEAD_CURRENT_WITH_BASE")
        self.assertEqual("BASE_STALE", p["failure_code"])
        self.assertEqual({"registry_generation"}, set(p["moved"]))

    def test_one_sided_registry_generation_fails_closed(self) -> None:
        for extra in (("--base-registry-generation", "319"), ("--current-registry-generation", "319")):
            with self.subTest(extra):
                p = pred(ap.evaluate(self.f.args(*extra)), "HEAD_CURRENT_WITH_BASE")
                self.assertEqual("BASE_STATE_NOT_OBSERVED", p["failure_code"])
                self.assertEqual("FAIL_CLOSED", p["disposition"])
                self.assertTrue(SIX <= p.keys())

    def test_one_sided_ledger_head_fails_closed(self) -> None:
        for extra in (("--base-ledger-head", "a" * 40), ("--current-ledger-head", "a" * 40)):
            with self.subTest(extra):
                p = pred(ap.evaluate(self.f.args(*extra)), "HEAD_CURRENT_WITH_BASE")
                self.assertEqual("BASE_STATE_NOT_OBSERVED", p["failure_code"])
                self.assertEqual("FAIL_CLOSED", p["disposition"])

    def test_base_state_not_observed(self) -> None:
        a = self.f.args()
        a.current_base_sha = None
        self.assertEqual("BASE_STATE_NOT_OBSERVED", pred(ap.evaluate(a), "HEAD_CURRENT_WITH_BASE")["failure_code"])
        out = ap.evaluate(self.f.args("--stale-days", "7"))
        self.assertTrue(pred(out, "HEAD_CURRENT_WITH_BASE")["holds"])

    def test_staleness_makes_no_git_call(self) -> None:
        import subprocess as sp
        calls = []
        real = sp.run
        def spy(cmd, *a, **k):
            calls.append(cmd)
            return real(cmd, *a, **k)
        ap.subprocess.run = spy
        try:
            ap.p_base(self.f.args("--stale-days", "7"))
        finally:
            ap.subprocess.run = real
        self.assertEqual([], calls)

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


# Known-answer vectors for change_digest (TVC rule, D7 writer_session shape).
# Source 1-2: StegVerse-Labs/TVC@735c9548c4746dfa28a8b26b8992f3f29a27b7a8
#   tests/fixtures/admission-scenarios/scenarios.jsonl (git blob 1e207c2773ececf7da0730bdb2f8c00c793c709c),
#   sv_change.content and sv_change.head.change_digest of the named scenarios, copied verbatim.
# Source 3: TVC@735c9548 tvc_request_digest.digest (blob ac242efac0c3f2020f95fc47b9690938e3b044e6) applied as
#   sv_change_admission.change_digest (blob 76003e3c56f423e554c71cae9fabfb4a81400b40) to the input below,
#   run on the box; covers a deleted entry and an UNKNOWN writer_session.
WS_A = {"evidence_class": "DECLARED", "session": "b699e0c0-3b4e-4a24-945f-6f521c282268"}
KAT = [
    ("SCN-LABS-3246-POSITIVE-CONTROL", [
        {"blob_digest": "sha256:85caa915309ffc2e6c4b3f84eb21b436b977660d0001d48b883cfdba7b0f0007", "deleted": False,
         "path": "scripts/consume_sdk_evaluator_governance_posture_request.py",
         "writer_session": {"evidence_class": "DECLARED", "session": "6329a668"}},
        {"blob_digest": "sha256:0489e69eb154e5a8c04afb400ac44860f22cf9361825db8bca30c430cfe8bee3", "deleted": False,
         "path": "tests/test_sdk_evaluator_governance_posture_resident.py",
         "writer_session": {"evidence_class": "DECLARED", "session": "6329a668"}}],
     "sha256:9cfbc87b37b3ca5d2abd91e3948e2af057fb070eef15f4ae5e2a7c638e6b064f"),
    ("SCN-LABS-3241-SKIPPED-TRANSITION", [
        {"blob_digest": "sha256:c0c27c3e8e879e757195152e8806edc15986bb13eebb513bf2de8f2a48f0099d", "deleted": False,
         "path": ".github/workflows/organization-claim-allocator-transition.yml", "writer_session": WS_A},
        {"blob_digest": "sha256:6d27fddf4d9c3fdfa4355c67cc8c1b242ae0cebe4cf862e38298fb241caedd5b", "deleted": False,
         "path": "control/workflow-surface-registry.json",
         "writer_session": {"evidence_class": "OBSERVED_COMMIT_TRAILER", "session": "session_013aXjQ22ZG7VKiewGKyCd4T"}},
        {"blob_digest": "sha256:1f31062afcd948b407e49d336b47a55275da3e7b3b60092ee9885c84d99e4eb1", "deleted": False,
         "path": "docs/RESIDENT_ORG_CLAIM_ALLOCATOR_MIRROR_HANDOFF.md",
         "writer_session": {"evidence_class": "OBSERVED_COMMIT_TRAILER", "session": "session_01QryfB2bHgHftfiBdLzx5cG"}},
        {"blob_digest": "sha256:d152791869a4a77ca3c9d176d4f23be6d294eb0a2012c95ad473f13df0d5322a", "deleted": False,
         "path": "receipts/sovereign-host/resident-request-dispatch.latest.json",
         "writer_session": {"evidence_class": "OBSERVED_COMMIT_TRAILER", "session": "session_01QryfB2bHgHftfiBdLzx5cG"}},
        {"blob_digest": "sha256:43764f3d60a85c225a53bdc93c02bbbb06c18f8764cae6c92ae7165256fa40eb", "deleted": False,
         "path": "scripts/consume_org_claim_allocator_request.py", "writer_session": WS_A},
        {"blob_digest": "sha256:0d5b6576f0a899eeb8b74e7bdfe5fc49f4a2ac86ebe6bdfa7aef15a66be1b95a", "deleted": False,
         "path": "tests/test_org_claim_custody.py", "writer_session": WS_A},
        {"blob_digest": "sha256:f8f6856ff2da446dc5ee07f52c172cebe3ebbb27b4a3a13a32d80c6b35eb0266", "deleted": False,
         "path": "tests/test_resident_org_claim_allocator.py", "writer_session": WS_A}],
     "sha256:2bf1f7b83c5ae879f389aa69833c1fb9aea90f006c229f93d684725105856c50"),
    ("TVC-IMPL-735c9548-DELETED-AND-UNKNOWN", [
        {"path": "b/old.txt", "blob_digest": None, "deleted": True,
         "writer_session": {"session": "grok:p4-maintenance-lane/a65c67bf", "evidence_class": "DECLARED"}},
        {"path": "a/new.txt", "blob_digest": "sha256:" + "ab" * 32, "deleted": False,
         "writer_session": {"session": None, "evidence_class": "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"}}],
     "sha256:76a4f1116df7d6cc12b629c00de13c50a85c11a5e2f4e4ba574407f212fa0c09"),
]


class ChangeDigestKnownAnswerTest(unittest.TestCase):
    def test_change_digest_equals_tvc_byte_for_byte(self) -> None:
        for name, content, expected in KAT:
            with self.subTest(name):
                self.assertEqual(expected, ap.change_digest(content))

    def test_writer_session_shape_is_tvc_d7(self) -> None:
        self.assertEqual({"session": SESSION, "evidence_class": "DECLARED"}, ap.writer_session(SESSION))
        self.assertEqual({"session": None, "evidence_class": "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"}, ap.writer_session(None))
        for ws in (ap.writer_session(SESSION), ap.writer_session(None)):
            self.assertEqual({"session", "evidence_class"}, set(ws))
            self.assertIn(ws["evidence_class"], ap.WRITER_EVIDENCE_CLASSES)


if __name__ == "__main__":
    unittest.main()
