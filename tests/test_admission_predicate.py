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
from typing import Any

SCRIPT = Path(__file__).resolve().parents[1] / "resident-runtime" / "admission_predicate.py"
spec = importlib.util.spec_from_file_location("admission_predicate", SCRIPT)
ap = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ap
spec.loader.exec_module(ap)

SIX = set(ap.SIX_FIELDS)
SESSION = "grok:p4-maintenance-lane/a65c67bf"
LEDGER = "a5bb54d81893b392a3ce28182986fc39857807e1"


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

    def args(self, *extra: str, checks: str | None = None, epoch: Any = "auto", session: str = SESSION,
             current: tuple | None = None, expect: tuple = ("a",), identity: bool = True, receipt: Any = "default"):
        """By default a sealed #3266-shape base-state receipt for the base commit carries hb_epoch 1000 (the source).
        epoch="auto" supplies --hb-epoch equal to the receipt's hb_epoch (omitted when it has none); None omits the flag."""
        if epoch == "auto":
            epoch = "1000" if receipt == "default" else (receipt or {}).get("hb_epoch")
        c = current or (self.base, self.base_time)
        rec = []
        if receipt is not None:
            path = self.td / "base-state.json"
            path.write_text(json.dumps(readback_receipt(self.base, epoch="1000") if receipt == "default" else receipt))
            rec = ["--base-state-receipt", str(path)]
        ep = ["--hb-epoch", epoch] if epoch is not None else []
        exp = [x for e in expect for x in ("--expect", e)]
        ident = ["--repository", "Example/lane", "--base-registry-generation", "319", "--base-ledger-head", LEDGER,
                 "--current-registry-generation", "319", "--current-ledger-head", LEDGER] if identity else []
        return ap.parse(["--clone", str(self.clone), "--branch", "lane/x", "--session-id", session,
                         *rec, *ep, "--check-runs", checks or self.checks({"a": "success"}), *exp,
                         "--base-sha", self.base, "--base-commit-time", str(self.base_time),
                         "--current-base-sha", c[0], "--current-base-commit-time", str(c[1]), *ident, *extra])


def base_row(a) -> dict:
    """HEAD_CURRENT_WITH_BASE on supplied inputs alone (pure; no receipt filling)."""
    return ap.p_base(a)


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
        # P1 rule: sha256 over the change_id canonical bytes of {target_repository, base_ref, content-identity}
        ident = {"target_repository": "Example/lane",
                 "base_ref": {"registry_generation": 319, "ledger_head": LEDGER},
                 "content": sorted(({"path": e["path"], "blob_digest": e["blob_digest"], "deleted": e["deleted"]}
                                    for e in out["content"]), key=lambda e: e["path"])}
        raw = json.dumps(ident, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        self.assertEqual("sha256:" + hashlib.sha256(raw).hexdigest(), out["change_digest"])
        self.assertEqual(out["change_digest"][7:], out["change_id"][4:])
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

    def test_hb_epoch_source_unobserved_fails_closed(self) -> None:
        for receipt in (None, readback_receipt(self.f.base, epoch=None)):
            out = ap.evaluate(self.f.args(receipt=receipt))
            self.assertEqual("FAIL_CLOSED", out["disposition"])
            self.assertEqual("HB_EPOCH_SOURCE_UNOBSERVED", out["failure_code"])
            self.assertIn(ap.HB_EPOCH_INVARIANT, out["required_evidence_or_repair"])
            self.assertIsNone(out["hb_epoch"])
            self.assertTrue(ap.seal_verifies(out))
        # a flag is never the source
        self.assertEqual("HB_EPOCH_SOURCE_UNOBSERVED", ap.evaluate(self.f.args(receipt=None, epoch="1000"))["failure_code"])

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
        p = base_row(self.f.args("--base-registry-generation", "319", "--current-registry-generation", "320",
                                 "--base-ledger-head", "L1", "--current-ledger-head", "L1", identity=False))
        self.assertEqual("BASE_STALE", p["failure_code"])
        self.assertEqual({"registry_generation"}, set(p["moved"]))

    def test_one_sided_registry_generation_fails_closed(self) -> None:
        for extra in (("--base-registry-generation", "319"), ("--current-registry-generation", "319")):
            with self.subTest(extra):
                p = base_row(self.f.args(*extra, identity=False))
                self.assertEqual("BASE_STATE_NOT_OBSERVED", p["failure_code"])
                self.assertEqual("FAIL_CLOSED", p["disposition"])
                self.assertTrue(SIX <= p.keys())

    def test_one_sided_ledger_head_fails_closed(self) -> None:
        for extra in (("--base-ledger-head", "a" * 40), ("--current-ledger-head", "a" * 40)):
            with self.subTest(extra):
                p = base_row(self.f.args(*extra, identity=False))
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


# Known-answer vector for change_id / change_digest (P1 rule), copied verbatim from
# StegVerse-Labs/.github#3264 @725d0f65cd5e7b81684c045c6f5d047f95fa946b
#   tests/test_sv_record_modes.py (git blob 6dd5aa84cdc2d6ab0d4a4f72655ce2b3a6cb00f9) KAT_RECORD / KAT_BYTES / KAT_CHANGE_ID,
#   test ChangeIdCanonicalTests.test_change_id_known_answer and test_change_digest_equals_change_id_hex;
#   rule in resident-runtime/sv_work_items.py (git blob 4c6f3e75c636e19404667a7c32c22ae8dac652d4).
# The earlier TVC content-list vectors were dropped: no field uses the content-list digest any more.
KAT_RECORD = {
    "target_repository": "StegVerse-Labs/.github",
    "base_ref": {"registry_generation": 319, "ledger_head": "a5bb54d81893b392a3ce28182986fc39857807e1"},
    "content": [
        {"path": "schemas/\u00e9.json", "blob_digest": "sha256:" + "b" * 64,
         "writer_session": {"session": "P1", "evidence_class": "DECLARED"}},
        {"path": "docs/old.md", "blob_digest": None, "deleted": True,
         "writer_session": {"session": None, "evidence_class": "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"}},
    ],
}
KAT_BYTES = ('{"base_ref":{"ledger_head":"a5bb54d81893b392a3ce28182986fc39857807e1","registry_generation":319},'
             '"content":[{"blob_digest":null,"deleted":true,"path":"docs/old.md"},'
             '{"blob_digest":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","deleted":false,"path":"schemas/\u00e9.json"}],'
             '"target_repository":"StegVerse-Labs/.github"}').encode("utf-8")
KAT_CHANGE_ID = "svc:b1f56ebe998a4a0896e8f3f18ef76abe65f6f6bd0c613fa04e50291025300239"
KAT_CHANGE_DIGEST = "sha256:b1f56ebe998a4a0896e8f3f18ef76abe65f6f6bd0c613fa04e50291025300239"


class ChangeDigestKnownAnswerTest(unittest.TestCase):
    def test_canonical_bytes_equal_p1_byte_for_byte(self) -> None:
        produced = ap.change_identity_canonical_bytes(ap.change_identity_input(KAT_RECORD))
        self.assertEqual(KAT_BYTES, produced)
        self.assertEqual(342, len(produced))
        self.assertFalse(produced.endswith(b"\n"))

    def test_change_id_and_change_digest_equal_p1(self) -> None:
        self.assertEqual(KAT_CHANGE_ID, ap.change_id(KAT_RECORD))
        self.assertEqual(KAT_CHANGE_DIGEST, ap.change_digest(KAT_RECORD))
        self.assertEqual("sha256:" + hashlib.sha256(KAT_BYTES).hexdigest(), ap.change_digest(KAT_RECORD))

    def test_writer_session_is_not_identity(self) -> None:
        import copy
        other = copy.deepcopy(KAT_RECORD)
        other["content"][0]["writer_session"] = {"session": None, "evidence_class": "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"}
        self.assertEqual(KAT_CHANGE_DIGEST, ap.change_digest(other))

    def test_writer_session_shape_is_tvc_d7(self) -> None:
        self.assertEqual({"session": SESSION, "evidence_class": "DECLARED"}, ap.writer_session(SESSION))
        self.assertEqual({"session": None, "evidence_class": "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"}, ap.writer_session(None))


class ChangeIdentityInputTest(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.f = Fixture(Path(self._td.name))

    def tearDown(self) -> None:
        self._td.cleanup()

    CONTENT = [{"path": "a.txt", "blob_digest": "sha256:" + "a" * 64, "deleted": False}]

    def test_missing_registry_generation_or_ledger_head_fails_closed(self) -> None:
        for extra in ((), ("--base-registry-generation", "319", "--base-ledger-head", "XYZ")):
            p, ident = ap.p_identity(self.f.args("--repository", "Example/lane", *extra, identity=False), self.CONTENT)
            self.assertEqual("SV_CHANGE_BASE_UNBOUND", p["failure_code"])
            self.assertEqual("FAIL_CLOSED", p["disposition"])
            self.assertTrue(SIX <= p.keys())
            self.assertIsNone(ident)

    def test_missing_repository_fails_closed(self) -> None:
        p, _ = ap.p_identity(self.f.args("--base-registry-generation", "319", "--base-ledger-head", LEDGER, identity=False),
                             self.CONTENT)
        self.assertEqual("TARGET_REPOSITORY_NOT_SUPPLIED", p["failure_code"])


BASE_STATE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "admission-predicate" / "base-state-readback" / "labs-main-978b8880.json"
OTHER_LEDGER = "b" * 40


HEAD_RECEIPT_KEY = "receipts/" + "3" * 64 + ".json"


def readback_receipt(bound: str, generation: int = 319, ledger: str = LEDGER, epoch: str | None = None,
                     legacy: bool = False) -> dict:
    """A receipt in the pinned #3266 producer's shape for the fixture's base commit, sealed with the same rule: an observed
    epoch is sealed with hb_epoch_source {ledger_head, receipt, field} and the head receipt is in sources.
    legacy=True gives the pre-641f4b03 shape (caller-supplied epoch, no hb_epoch_source)."""
    body = {"schema": ap.BASE_STATE_SCHEMA, "component_id": ap.BASE_STATE_COMPONENT, "disposition": "ALLOW",
            "authority_effect": "NONE_READBACK_ONLY", "readback_writes": False, "main_ref": "refs/heads/main",
            "main_tip": bound, "bound_main_commit": bound, "hb_epoch": epoch,
            "base_ref": {"registry_generation": generation, "ledger_head": ledger},
            "sources": [{"file": "data/canonical-task-registry.json", "blob_sha": "1" * 40},
                        {"file": "refs/stegverse/organization-ledger:HEAD.json", "blob_sha": "2" * 40}]}
    if legacy:
        if epoch is None:
            body["open_questions"] = [{"id": "JD-P4-3", "slot": "hb_epoch", "status": "OPEN"}]
        return ap.seal(body)
    body["hb_epoch_source"] = None
    if epoch is not None:
        body["sources"].append({"file": "refs/stegverse/organization-ledger:" + HEAD_RECEIPT_KEY, "blob_sha": "4" * 40})
        body["hb_epoch_source"] = {"ledger_head": ledger, "receipt": HEAD_RECEIPT_KEY, "field": "$.hb_reference.epoch"}
    return ap.seal(body)


class BaseStateReceiptTest(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.f = Fixture(Path(self._td.name))

    def tearDown(self) -> None:
        self._td.cleanup()

    def write(self, receipt: dict, name: str = "receipt.json") -> str:
        path = self.f.td / name
        path.write_text(json.dumps(receipt), encoding="utf-8")
        return str(path)

    def evaluate(self, receipt: dict, *extra: str, epoch: Any = "auto") -> dict:
        return ap.evaluate(self.f.args("--repository", "Example/lane", *extra, epoch=epoch, identity=False, receipt=receipt))

    def test_tvc_fixture_receipt_verifies_as_tvc_binds_it(self) -> None:
        receipt = json.loads(BASE_STATE_FIXTURE.read_text(encoding="utf-8"))
        state, code, _ = ap.base_state_from_readback(receipt)
        self.assertIsNone(code)
        self.assertEqual({"registry_generation": 319, "ledger_head": LEDGER,
                          "bound_main_commit": "978b8880d238dc3e3a8b690c0675d8bb0e9d6985",
                          "result_sha256": "sha256:04ae0f6e40cacf885bb9bce0b466e5cc3dfd4a48783596188eefa7bfbd516a20",
                          "hb_epoch": None, "hb_epoch_open": True,
                          "registry_blob_sha": "8d3ff1902412ab85c0fafcdb4c2f11cc0b0afbef",
                          "repository": None, "registry_file": "data/canonical-task-registry.json",
                          "hb_epoch_source": None, "hb_epoch_source_receipt_blob": None,
                          "readback_disposition": "ALLOW", "fixture_only": False}, state)
        pin = json.loads(ap.BASE_STATE_PIN.read_text(encoding="utf-8"))
        self.assertEqual("2ba0e329c224c94863dac15de3f8011f777cb34f", pin["producer"]["ref"])
        self.assertEqual("2c730142254b78a5b9e1c05566fe6f5111b7d571", pin["producer"]["git_blob_sha"])
        self.assertEqual(["641f4b03e612d07047e15f2384d24780e2af86c0", "78a0c78e1f1313bd11ff916b26a3ab467f2f54e2", "c431bfb038f064b29b6b8ba7c68409f0057ea9e7"],
                         [x["ref"] for x in pin["superseded"]])
        self.assertEqual(ap.BASE_STATE_SCHEMA, pin["result_schema"])
        self.assertEqual(ap.BASE_STATE_REGISTRY_PATHS, pin["registry_paths"])
        root = Path(__file__).resolve().parents[1]
        for fx in pin["fixtures"]:
            data = (root / fx["path"]).read_bytes()
            self.assertEqual(hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest(), fx["git_blob_sha"])
        labs = json.loads((BASE_STATE_FIXTURE.parent / "labs-main-978b8880-producer-78a0c78e.json").read_text(encoding="utf-8"))
        state, code, _ = ap.base_state_from_readback(labs)
        self.assertIsNone(code)
        self.assertEqual(("StegVerse-Labs/.github", "data/canonical-task-registry.json", 319),
                         (state["repository"], state["registry_file"], state["registry_generation"]))
        unmapped = ap.seal(dict(labs, repository="Other/repo"))
        self.assertEqual("BASE_STATE_RECEIPT_MALFORMED", ap.base_state_from_readback(unmapped)[1])

    def test_org_registry_without_generation_names_the_joint_item(self) -> None:
        receipt = json.loads((BASE_STATE_FIXTURE.parent / "org-main-40a5d235-producer-78a0c78e.json").read_text(encoding="utf-8"))
        self.assertEqual("REGISTRY_GENERATION_NOT_DECLARED", receipt["failure_code"])
        receipt = ap.seal(dict(receipt, bound_main_commit=self.f.base))
        out = self.evaluate(receipt)
        p = pred(out, "BASE_STATE_RECEIPT_BOUND")
        self.assertEqual(("FAIL_CLOSED", "BASE_STATE_NOT_OBSERVED", "REGISTRY_GENERATION_NOT_DECLARED"),
                         (p["disposition"], p["failure_code"], p["receipt_failure_code"]))
        self.assertTrue(SIX <= p.keys())
        self.assertIn("Q-ORG-REGISTRY-GENERATION", p["required_evidence_or_repair"])
        self.assertIn("Q-ORG-REGISTRY-GENERATION", p["next_attempt"])

    def test_valid_receipt_binds_identity_and_base(self) -> None:
        out = self.evaluate(readback_receipt(self.f.base, epoch="1000"))
        self.assertEqual("admission-input-ready", out["admission_input"], out["fail_closed"])
        self.assertTrue(pred(out, "BASE_STATE_RECEIPT_BOUND")["holds"])
        self.assertEqual({"sha": self.f.base, "commit_time": self.f.base_time, "registry_generation": 319, "ledger_head": LEDGER},
                         out["base_ref"])
        self.assertEqual(319, out["current_base"]["registry_generation"])
        self.assertIsNotNone(out["change_digest"])
        flags = ap.evaluate(self.f.args("--repository", "Example/lane"))
        self.assertEqual(flags["change_digest"], out["change_digest"])  # same identity as the explicit flags
        agreeing = self.evaluate(readback_receipt(self.f.base, epoch="1000"), "--base-registry-generation", "319", "--base-ledger-head", LEDGER)
        self.assertEqual("ALLOW", agreeing["disposition"])

    def test_tampered_seal_fails_closed(self) -> None:
        receipt = readback_receipt(self.f.base, epoch="1000")
        receipt["base_ref"] = {"registry_generation": 320, "ledger_head": LEDGER}
        out = self.evaluate(receipt)
        p = pred(out, "BASE_STATE_RECEIPT_BOUND")
        self.assertEqual("BASE_STATE_RECEIPT_SEAL_INVALID", p["failure_code"])
        self.assertEqual("FAIL_CLOSED", out["disposition"])
        self.assertTrue(SIX <= out.keys() and SIX <= p.keys())
        self.assertIsNone(out["change_digest"])
        wrong = dict(readback_receipt(self.f.base, epoch="1000"), schema="other/v1")
        self.assertEqual("BASE_STATE_RECEIPT_SCHEMA_MISMATCH", self.evaluate(ap.seal(wrong))["failure_code"])
        refused = ap.seal(dict(readback_receipt(self.f.base, epoch="1000"), disposition="FAIL_CLOSED", failure_code="REGISTRY_GENERATION_UNREADABLE"))
        out = self.evaluate(refused)
        self.assertEqual("BASE_STATE_NOT_OBSERVED", out["failure_code"])
        self.assertEqual("REGISTRY_GENERATION_UNREADABLE", pred(out, "BASE_STATE_RECEIPT_BOUND")["receipt_failure_code"])

    def test_mismatch_with_flags_or_bound_commit_fails_closed(self) -> None:
        for extra in (("--base-registry-generation", "318"), ("--base-ledger-head", OTHER_LEDGER),
                      ("--current-ledger-head", OTHER_LEDGER)):
            with self.subTest(extra=extra):
                out = self.evaluate(readback_receipt(self.f.base, epoch="1000"), *extra)
                p = pred(out, "BASE_STATE_RECEIPT_BOUND")
                self.assertEqual("BASE_STATE_RECEIPT_FLAG_MISMATCH", p["failure_code"])
                self.assertEqual("FAIL_CLOSED", out["disposition"])
                self.assertTrue(SIX <= out.keys())
        out = self.evaluate(readback_receipt("c" * 40, epoch="1000"))
        self.assertEqual("BASE_STATE_RECEIPT_COMMIT_MISMATCH", out["failure_code"])
        self.assertTrue(SIX <= out.keys())

    def test_epoch_from_valid_receipt_binds(self) -> None:
        out = self.evaluate(readback_receipt(self.f.base, epoch="4242"))
        self.assertEqual("ALLOW", out["disposition"], out["fail_closed"])
        self.assertEqual(4242, out["hb_epoch"])
        hb = pred(out, "HB_EPOCH_SUPPLIED")
        self.assertEqual(("4242", ap.HB_EPOCH_INVARIANT), (hb["receipt_hb_epoch"], hb["invariant"]))
        self.assertEqual(4242, out["job_observation"]["hb_epoch"])  # the receipt epoch reaches Lane A
        self.assertEqual(["BASE_STATE_RECEIPT_BOUND", "HB_EPOCH_SUPPLIED"], [p["predicate"] for p in out["predicates"][:2]])
        self.assertEqual("ALLOW", self.evaluate(readback_receipt(self.f.base, epoch="4242"), epoch="4242")["disposition"])

    def test_null_receipt_epoch_is_source_unobserved(self) -> None:
        for receipt in (readback_receipt(self.f.base, epoch=None), readback_receipt(self.f.base, epoch=None, legacy=True),
                        readback_receipt(self.f.base, epoch="4242", legacy=True)):  # a caller-supplied epoch is not observed
          for epoch in (None, "4242"):
            out = self.evaluate(receipt, epoch=epoch)
            self.assertEqual(("FAIL_CLOSED", "HB_EPOCH_SOURCE_UNOBSERVED"), (out["disposition"], out["failure_code"]))
            self.assertTrue(pred(out, "BASE_STATE_RECEIPT_BOUND")["holds"])
            self.assertEqual(["BASE_STATE_RECEIPT_BOUND", "HB_EPOCH_SUPPLIED"], [p["predicate"] for p in out["predicates"]])
            self.assertIsNone(out["hb_epoch"])
            self.assertTrue(SIX <= out.keys())

    def test_flag_mismatch_is_deny_hb_epoch_mismatch(self) -> None:
        """Ruling 15:41Z (P1, #3266 @641f4b03, Lane B #46): a contradicting --hb-epoch is DENY HB_EPOCH_MISMATCH."""
        for flag in ("4243", "32", "04241"):
            with self.subTest(flag=flag):
                out = self.evaluate(readback_receipt(self.f.base, epoch="4242"), epoch=flag)
                self.assertEqual(("DENY", "HB_EPOCH_MISMATCH"), (out["disposition"], out["failure_code"]))
                self.assertEqual("HB_EPOCH_SUPPLIED", out["failed_predicate"])
                hb = pred(out, "HB_EPOCH_SUPPLIED")
                self.assertEqual((LEDGER, "4242", flag), (hb["ledger_head"], hb["expected"], hb["hb_epoch"]))
                self.assertNotIn("supplied_epoch_rule", hb)  # well formed, only differs
                self.assertNotIn("cross_checked", hb)  # P1's DENY carries no cross_checked
                self.assertTrue(SIX <= out.keys() and all(out[f] for f in SIX))
                self.assertEqual(2, len(out["predicates"]))
                self.assertIsNone(out["hb_epoch"])
                self.assertTrue(ap.seal_verifies(out))
        self.assertEqual("ALLOW", self.evaluate(readback_receipt(self.f.base, epoch="4242"), epoch="04242")["disposition"])

    def test_invalid_supplied_epoch_is_deny_hb_epoch_mismatch(self) -> None:
        """A malformed --hb-epoch other than absent/null/sentinel fails kernel supplied_epoch_failure (726248a5) and is
        DENY HB_EPOCH_MISMATCH with P1's detail {ledger_head, expected, hb_epoch, supplied_epoch_rule}."""
        for flag in ("12", "31", "0", "x", "+33", " 33", "3_3", "33.0", "-40", "\uff14\uff12", "4242\n", "unknown", "NULL", "None"):
            with self.subTest(flag=flag):
                out = self.evaluate(readback_receipt(self.f.base, epoch="4242"), epoch=flag)
                hb = pred(out, "HB_EPOCH_SUPPLIED")
                self.assertEqual(("DENY", "HB_EPOCH_MISMATCH"), (out["disposition"], out["failure_code"]))
                self.assertTrue(SIX <= hb.keys() and all(hb[f] for f in SIX))
                self.assertEqual((LEDGER, "4242", flag), (hb["ledger_head"], hb["expected"], hb["hb_epoch"]))
                self.assertTrue(hb["supplied_epoch_rule"].startswith("HB_EPOCH_INVALID: "))
                self.assertNotIn("HB_EPOCH_FLAG_MISMATCH", [p.get("failure_code") for p in out["predicates"]])
                self.assertTrue(ap.seal_verifies(out))

    def test_explicit_null_or_sentinel_flag_fails_closed(self) -> None:
        """Ruling 16:03Z: an explicit '', 'null' or UNKNOWN_NOT_AUTHENTICALLY_OBSERVED --hb-epoch is FAIL_CLOSED
        HB_EPOCH_SOURCE_UNOBSERVED, even when the sealed source is observed."""
        for flag in ("", "null", "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"):
            with self.subTest(flag=flag):
                out = self.evaluate(readback_receipt(self.f.base, epoch="4242"), epoch=flag)
                hb = pred(out, "HB_EPOCH_SUPPLIED")
                self.assertEqual(("FAIL_CLOSED", "HB_EPOCH_SOURCE_UNOBSERVED"), (out["disposition"], out["failure_code"]))
                self.assertEqual("HB_EPOCH_SUPPLIED", out["failed_predicate"])
                self.assertTrue(SIX <= hb.keys() and all(hb[f] for f in SIX))
                self.assertNotIn("supplied_epoch_rule", hb)
                self.assertIn("checked before 726248a5", hb["detail"])
                self.assertEqual(LEDGER, hb["ledger_head"])
                self.assertIsNone(out["hb_epoch"])
                self.assertEqual(2, len(out["predicates"]))

    def test_omitted_flag_runs_no_cross_check_and_reaches_allow(self) -> None:
        """P1 @ae8b105d: --hb-epoch omitted is HB_EPOCH_NOT_CROSS_CHECKED -> ALLOW {hb_epoch, ledger_head, cross_checked: false},
        on the sealed epoch of the real 2ba0e329 ALLOW receipt; a held cross-check is ALLOW with cross_checked true."""
        allow = json.loads((BASE_STATE_FIXTURE.parent / "labs-main-978b8880-producer-2ba0e329.json").read_text(encoding="utf-8"))
        receipt = ap.seal(dict({k: v for k, v in allow.items() if k != "result_sha256"}, bound_main_commit=self.f.base))
        out = self.evaluate(receipt, epoch=None)
        hb = pred(out, "HB_EPOCH_SUPPLIED")
        self.assertEqual(("ALLOW", "469411750", "a5bb54d81893b392a3ce28182986fc39857807e1", False, "HB_EPOCH_NOT_CROSS_CHECKED"),
                         (hb["disposition"], hb["hb_epoch"], hb["ledger_head"], hb["cross_checked"], hb["detail"]))
        self.assertNotIn("cross_check", hb)
        self.assertEqual("ALLOW", out["disposition"], out["fail_closed"])
        self.assertEqual("admission-input-ready", out["admission_input"])
        self.assertEqual(469411750, out["hb_epoch"])
        self.assertEqual(469411750, out["job_observation"]["hb_epoch"])
        self.assertTrue(ap.seal_verifies(out))
        checked = self.evaluate(receipt, epoch="469411750")
        self.assertEqual(("ALLOW", True), (checked["disposition"], pred(checked, "HB_EPOCH_SUPPLIED")["cross_checked"]))
        self.assertNotIn("detail", pred(checked, "HB_EPOCH_SUPPLIED"))
        self.assertEqual(("DENY", "HB_EPOCH_MISMATCH"), tuple(self.evaluate(receipt, epoch="469411751")[k] for k in ("disposition", "failure_code")))
        self.assertEqual("ALLOW", self.evaluate(readback_receipt(self.f.base, epoch="4242"), epoch=None)["disposition"])

    def test_source_is_checked_before_the_supplied_value(self) -> None:
        """P1 order: an unobserved sealed source is FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED whatever was supplied."""
        for flag in ("x", "12", "4243", "4242", None, "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"):
            for receipt in (readback_receipt(self.f.base, epoch=None), None):
                with self.subTest(flag=flag, receipt=bool(receipt)):
                    out = ap.evaluate(self.f.args(epoch=flag, receipt=receipt))
                    self.assertEqual(("FAIL_CLOSED", "HB_EPOCH_SOURCE_UNOBSERVED"),
                                     (pred(out, "HB_EPOCH_SUPPLIED")["disposition"], pred(out, "HB_EPOCH_SUPPLIED")["failure_code"]))

    def test_receipt_deny_hb_epoch_mismatch_still_binds_the_observed_epoch(self) -> None:
        """P1 @ae8b105d: a #3266 DENY HB_EPOCH_MISMATCH readback observed the epoch (only the producer's own cross-check
        disagreed); it binds like ALLOW and the admission's own --hb-epoch decides."""
        body = {k: v for k, v in readback_receipt(self.f.base, epoch="4242").items() if k != "result_sha256"}
        body.update(disposition="DENY", failure_code="HB_EPOCH_MISMATCH", failed_predicate=ap.HB_EPOCH_INVARIANT,
                    required_evidence_or_repair="r", retry_entrypoint="e", owning_existing_goal="StegVerse-org/.github#164",
                    next_attempt="n", expected_hb_epoch="4243", flag_failure_code="HB_EPOCH_FLAG_MISMATCH")
        receipt = ap.seal(body)
        self.assertEqual("DENY", ap.base_state_from_readback(receipt)[0]["readback_disposition"])
        for flag, want in ((None, ("ALLOW", None)), ("4242", ("ALLOW", None)), ("4243", ("DENY", "HB_EPOCH_MISMATCH"))):
            with self.subTest(flag=flag):
                out = self.evaluate(receipt, epoch=flag)
                self.assertTrue(pred(out, "BASE_STATE_RECEIPT_BOUND")["holds"])
                hb = pred(out, "HB_EPOCH_SUPPLIED")
                self.assertEqual(want, (hb["disposition"], hb.get("failure_code")))
        other = ap.seal(dict(body, failure_code="REGISTRY_GENERATION_NOT_DECLARED"))
        self.assertEqual("BASE_STATE_NOT_OBSERVED", ap.base_state_from_readback(other)[1])

    def test_real_2ba0e329_receipts_bind_the_kat_epoch(self) -> None:
        """Receipts produced by the pinned producer @2ba0e329 at the Labs ledger head a5bb54d8 (its KAT): both the ALLOW
        receipt and the --hb-epoch 469411751 DENY receipt seal hb_epoch 469411750 with hb_epoch_source and bind it."""
        allow = json.loads((BASE_STATE_FIXTURE.parent / "labs-main-978b8880-producer-2ba0e329.json").read_text(encoding="utf-8"))
        state, code, why = ap.base_state_from_readback(allow)
        self.assertIsNone(code, why)
        self.assertEqual(("469411750", "a5bb54d81893b392a3ce28182986fc39857807e1", 319),
                         (state["hb_epoch"], state["ledger_head"], state["registry_generation"]))
        self.assertEqual({"ledger_head": "a5bb54d81893b392a3ce28182986fc39857807e1",
                          "receipt": "receipts/35810b6598e99cef32d9a0f1f97d07394d9f21c540ed7d3a395d9d78b753db3d.json",
                          "field": "$.hb_reference.epoch"}, state["hb_epoch_source"])
        out = self.evaluate(ap.seal(dict({k: v for k, v in allow.items() if k != "result_sha256"}, bound_main_commit=self.f.base)))
        self.assertEqual("ALLOW", pred(out, "HB_EPOCH_SUPPLIED")["disposition"], out["fail_closed"])
        self.assertEqual(469411750, out["hb_epoch"])
        deny = json.loads((BASE_STATE_FIXTURE.parent / "labs-main-978b8880-producer-2ba0e329-hb-epoch-469411751-deny.json").read_text(encoding="utf-8"))
        state, code, why = ap.base_state_from_readback(deny)
        self.assertIsNone(code, why)
        self.assertEqual(("DENY", "469411750"), (state["readback_disposition"], state["hb_epoch"]))
        resealed = ap.seal(dict({k: v for k, v in deny.items() if k != "result_sha256"}, bound_main_commit=self.f.base))
        self.assertEqual(("ALLOW", False), (lambda h: (h["disposition"], h["cross_checked"]))(pred(self.evaluate(resealed, epoch=None), "HB_EPOCH_SUPPLIED")))
        out = self.evaluate(resealed, epoch="469411751")
        self.assertEqual(("DENY", "HB_EPOCH_MISMATCH"), (out["disposition"], out["failure_code"]))

    def test_2ba0e329_receipt_seals_and_sentinel(self) -> None:
        """Re-minted at #3266 @2ba0e329: the omitted --hb-epoch ALLOW seal is 084f638e and carries cross_checked false +
        hb_epoch_cross_check HB_EPOCH_NOT_CROSS_CHECKED; --hb-epoch UNKNOWN_NOT_AUTHENTICALLY_OBSERVED is a sealed FAIL_CLOSED
        HB_EPOCH_SOURCE_UNOBSERVED receipt with hb_epoch and hb_epoch_source null, which binds nothing here."""
        d = BASE_STATE_FIXTURE.parent
        allow = json.loads((d / "labs-main-978b8880-producer-2ba0e329.json").read_text(encoding="utf-8"))
        self.assertEqual("sha256:084f638e3663a3f25f789aa3c7a4118d33911dcf27c93379bf384113afb35d6a", allow["result_sha256"])
        self.assertTrue(ap.seal_verifies(allow))
        self.assertEqual((False, "HB_EPOCH_NOT_CROSS_CHECKED"), (allow["cross_checked"], allow["hb_epoch_cross_check"]))
        sentinel = json.loads((d / "labs-main-978b8880-producer-2ba0e329-hb-epoch-unknown-fail-closed.json").read_text(encoding="utf-8"))
        self.assertTrue(ap.seal_verifies(sentinel))
        self.assertEqual(("FAIL_CLOSED", "HB_EPOCH_SOURCE_UNOBSERVED", None, None),
                         (sentinel["disposition"], sentinel["failure_code"], sentinel["hb_epoch"], sentinel["hb_epoch_source"]))
        self.assertEqual("BASE_STATE_NOT_OBSERVED", ap.base_state_from_readback(sentinel)[1])
        out = self.evaluate(ap.seal(dict({k: v for k, v in sentinel.items() if k != "result_sha256"}, bound_main_commit=self.f.base)), epoch=None)
        self.assertEqual("HB_EPOCH_SOURCE_UNOBSERVED", pred(out, "BASE_STATE_RECEIPT_BOUND")["receipt_failure_code"])
        self.assertEqual(("FAIL_CLOSED", "HB_EPOCH_SOURCE_UNOBSERVED"),
                         (pred(out, "HB_EPOCH_SUPPLIED")["disposition"], pred(out, "HB_EPOCH_SUPPLIED")["failure_code"]))

    def test_row_text_cites_only_the_current_3266_head(self) -> None:
        pin = json.loads(ap.BASE_STATE_PIN.read_text(encoding="utf-8"))
        self.assertEqual("StegVerse-Labs/.github#3266 @" + pin["producer"]["ref"][:8], ap.BASE_STATE_PRODUCER)
        stale = [x["ref"][:8] for x in pin["superseded"]]
        for receipt, flag in ((readback_receipt(self.f.base, epoch="4242"), None), (readback_receipt(self.f.base, epoch=None), None),
                              (readback_receipt(self.f.base, epoch="4242"), "x"), (None, None)):
            text = json.dumps(self.evaluate(receipt, epoch=flag))
            self.assertIn(ap.BASE_STATE_PRODUCER, text)
            for ref in stale:
                self.assertNotIn(ref, text)
        src = Path(ap.__file__).read_text(encoding="utf-8")
        for ref in stale:
            self.assertNotIn(ref, src)

    def test_bad_hb_epoch_source_is_source_unobserved(self) -> None:
        """P1 @ae8b105d: an hb_epoch_source not naming $.hb_reference.epoch at base_ref.ledger_head, a receipt that is not
        receipts/<hex>.json (P4: or not in sources), a fixture_only readback, or a sealed epoch failing 726248a5 against
        that source (derived_from_clock not false) is FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED."""
        good = readback_receipt(self.f.base, epoch="4242")
        self.assertEqual({"ledger_head": LEDGER, "receipt": HEAD_RECEIPT_KEY, "field": "$.hb_reference.epoch"},
                         pred(self.evaluate(good), "HB_EPOCH_SUPPLIED")["receipt_hb_epoch_source"])
        body = {k: v for k, v in good.items() if k != "result_sha256"}
        src = good["hb_epoch_source"]
        bad = [dict(body, hb_epoch_source=dict(src, ledger_head=OTHER_LEDGER)), dict(body, hb_epoch_source=dict(src, field="$.epoch")),
               dict(body, hb_epoch_source=dict(src, receipt="receipts/x.json")),
               dict(body, hb_epoch_source=dict(src, receipt="receipts/" + "5" * 64 + ".json")),
               dict(body, hb_epoch_source="x"), dict(body, hb_epoch_source=None), dict(body, fixture_only=True),
               dict(body, hb_epoch_source=dict(src, derived_from_clock=True))]
        for rec in bad:
            with self.subTest(rec=rec.get("hb_epoch_source"), fixture_only=rec.get("fixture_only")):
                for flag in (None, "4242"):
                    out = self.evaluate(ap.seal(rec), epoch=flag)
                    self.assertTrue(pred(out, "BASE_STATE_RECEIPT_BOUND")["holds"])
                    self.assertEqual(("FAIL_CLOSED", "HB_EPOCH_SOURCE_UNOBSERVED", "HB_EPOCH_SUPPLIED"),
                                     (out["disposition"], out["failure_code"], out["failed_predicate"]))
                    self.assertTrue(pred(out, "HB_EPOCH_SUPPLIED")["detail"])

    def test_failed_receipt_leaves_epoch_unobserved(self) -> None:
        receipt = readback_receipt(self.f.base, epoch="4242")
        receipt["base_ref"] = {"registry_generation": 320, "ledger_head": LEDGER}  # seal no longer verifies
        out = self.evaluate(receipt)
        self.assertEqual("BASE_STATE_RECEIPT_SEAL_INVALID", out["failure_code"])
        self.assertEqual("HB_EPOCH_SOURCE_UNOBSERVED", pred(out, "HB_EPOCH_SUPPLIED")["failure_code"])
        self.assertEqual(2, len(out["predicates"]))

if __name__ == "__main__":
    unittest.main()
