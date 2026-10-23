"""DRIFT_RECEIPT_APPENDER (resident-runtime/drift_receipt_appender.py) over toy repositories: B1 writer reuse,
admission FAIL_CLOSED pending genesis with six fields, scratch-only dry-run append, refusals."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "resident-runtime"
sys.path.insert(0, str(RUNTIME))
import drift_receipt_appender as appender  # noqa: E402

WRITER = RUNTIME / "main_change_receipt.py"
MANIFEST = RUNTIME / "drift-receipt-appender.transition.json"
FIXTURES = ROOT / "tests" / "fixtures" / "drift-receipt-appender"
SIX = appender.SIX_FIELDS
ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@stegverse.invalid", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@stegverse.invalid", "GIT_AUTHOR_DATE": "1700000000 +0000",
       "GIT_COMMITTER_DATE": "1700000000 +0000"}


def git(root: Path, *args: str) -> str:
    import os
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
                          env={**os.environ, **ENV}).stdout.strip()


class AppenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.repo = self.dir / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("a\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        (self.repo / "b.txt").write_text("b\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "head")
        self.head = git(self.repo, "rev-parse", "HEAD")
        self.writer, refusal = appender.load_writer(WRITER)
        self.assertIsNone(refusal)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def payload(self, **over) -> dict:
        body = {"schema": "stegverse.test-suite-baseline-drift/v1", "repository": "Toy/.github", "head": self.head,
                "hb_epoch": "469411750", "disposition": "FAIL_CLOSED", "failure_code": "TEST_SUITE_BASELINE_DRIFT",
                "failed_predicate": "MAIN_FAILING_SET_IS_WITHIN_BASELINE", "required_evidence_or_repair": "repair",
                "retry_entrypoint": "toy.yml", "owning_existing_goal": "#166", "next_attempt": "next push",
                "verification": {"runner": "pytest", "counts": {"passed": 2}, "required_verification_skipped": 0}}
        body.update(over)
        return self.writer.seal(body)

    def write(self, name: str, doc) -> str:
        path = self.dir / name
        path.write_text(json.dumps(doc))
        return str(path)

    def run_cli(self, *args: str) -> tuple[int, dict]:
        out = self.dir / "out.json"
        code = appender.main([*args, "--writer", str(WRITER), "--writer-ref", "test", "--manifest", str(MANIFEST),
                              "--out", str(out)])
        return code, json.loads(out.read_text())

    def scratch(self, with_remote: bool = False) -> Path:
        path = self.dir / ("scratch-remote.git" if with_remote else "scratch.git")
        subprocess.run(["git", "clone", "-q", "--bare", "--no-local", str(self.repo), str(path)], check=True)
        if not with_remote:
            git(path, "remote", "remove", "origin")
        return path

    def assert_six(self, record: dict) -> None:
        self.assertEqual(record["disposition"], "FAIL_CLOSED")
        for k in SIX:
            self.assertTrue(record.get(k), k)

    def test_receipt_reuses_the_b1_writer_and_admission_stays_fail_closed_pending_genesis(self) -> None:
        payload = self.payload()
        r = appender.receipt(self.repo, payload, self.writer, "test")
        self.assertTrue(self.writer.seal_verifies(r))
        self.assertEqual(r["schema"], appender.SCHEMA)
        self.assertEqual(r["operation"], "TEST_SUITE_BASELINE_DRIFT")
        self.assertEqual(r["payload"]["receipt_sha256"], payload["receipt_sha256"])
        mc = r["main_change_receipt"]
        self.assertEqual(mc["schema"], "stegverse.main-change-receipt/v1")
        self.assertTrue(self.writer.seal_verifies(mc))
        self.assertEqual(r["main_change_receipt_sha256"], mc["receipt_sha256"])
        self.assertEqual(mc["commit"], self.head)
        self.assertEqual(r["writer"]["sha256"], appender.WRITER_SHA256)
        self.assertEqual(r["admission"]["failure_code"], "DRIFT_RECEIPT_APPENDER_ADMISSION_PENDING_GENESIS")
        self.assert_six(r["admission"])
        self.assertEqual(r["disposition"], "FAIL_CLOSED")
        self.assertEqual(r["first_item"], {k: r["admission"][k] for k in SIX})
        self.assertEqual(r["organization_ledger_effect"], "NONE")
        self.assertEqual(appender.receipt(self.repo, payload, self.writer, "test"), r)  # no clock: replayable

    def test_pr_disposition_payload_is_accepted(self) -> None:
        r = appender.receipt(self.repo, self.payload(schema="stegverse.test-suite-pr-disposition/v1",
                                                     disposition="PRE_EXISTING_BASELINE_FAILURE"), self.writer, "test")
        self.assertEqual(r["payload"]["disposition"], "PRE_EXISTING_BASELINE_FAILURE")
        self.assertEqual(r["disposition"], "FAIL_CLOSED")

    def test_dry_run_appends_to_the_scratch_copy_only_and_reads_back(self) -> None:
        scratch = self.scratch()
        fresh = self.dir / "fresh.git"
        git(self.dir, "init", "-q", "--bare", str(fresh))
        code, result = self.run_cli("dry-run", "--root", str(self.repo), "--payload", self.write("p.json", self.payload()),
                                    "--scratch", str(scratch), "--fresh", str(fresh))
        self.assertEqual(code, 0, result)
        self.assertEqual(result["append"]["appended"], [self.head])
        self.assertEqual(result["replay"]["appended"], [])
        self.assertEqual(result["verify"]["disposition"], "ALLOW")
        self.assertEqual(git(scratch, "rev-parse", appender.DRIFT_REF), result["append"]["tip"])
        self.assertEqual(git(fresh, "rev-parse", appender.DRIFT_REF), result["append"]["tip"])
        self.assertEqual(git(self.repo, "for-each-ref", "refs/stegverse"), "")

    def test_dry_run_refuses_a_repository_with_a_remote(self) -> None:
        scratch = self.scratch(with_remote=True)
        code, result = self.run_cli("dry-run", "--root", str(self.repo), "--payload", self.write("p.json", self.payload()),
                                    "--scratch", str(scratch))
        self.assertEqual(code, 1)
        self.assertEqual(result["refusal"]["failure_code"], "DRY_RUN_TARGET_NOT_SCRATCH")
        self.assert_six(result["refusal"])
        self.assertEqual(git(scratch, "for-each-ref", "refs/stegverse"), "")

    def test_payload_refusals_carry_six_fields(self) -> None:
        good = self.payload()
        cases = {
            "DRIFT_PAYLOAD_SEAL_DOES_NOT_VERIFY": {**good, "disposition": "ALLOW"},
            "DRIFT_PAYLOAD_SCHEMA_NOT_ACCEPTED": self.payload(schema="other/v1"),
            "HB_EPOCH_SOURCE_UNOBSERVED": self.payload(hb_epoch=None),
            "DRIFT_PAYLOAD_SIX_FIELDS_INCOMPLETE": self.payload(next_attempt=""),
            "DRIFT_PAYLOAD_HEAD_UNNAMED": self.payload(head="abc"),
        }
        for code_name, doc in cases.items():
            refusal = appender.check_payload(self.writer, doc)
            self.assertEqual(refusal["failure_code"], code_name)
            self.assert_six(refusal)
        missing = appender.receipt(self.repo, self.payload(head="f" * 40), self.writer, "test")
        self.assertEqual(missing["failure_code"], "DRIFT_PAYLOAD_HEAD_NOT_IN_REPOSITORY")
        code, result = self.run_cli("receipt", "--root", str(self.repo), "--payload", self.write("a.json", good),
                                    "--payload", self.write("b.json", good))
        self.assertEqual(code, 1)
        self.assertEqual(result["refusals"][0]["failure_code"], "DRIFT_PAYLOAD_HEAD_REPEATED")

    def test_writer_off_pin_is_refused(self) -> None:
        other = self.dir / "writer.py"
        other.write_text(WRITER.read_text() + "\n# drift\n")
        module, refusal = appender.load_writer(other)
        self.assertIsNone(module)
        self.assertEqual(refusal["failure_code"], "B1_WRITER_NOT_AT_PIN")
        self.assert_six(refusal)

    def test_declaration_pins_this_appender_and_the_b1_writer(self) -> None:
        doc, refusal = appender.load_manifest(MANIFEST)
        self.assertIsNone(refusal)
        self.assertEqual(doc["verifier"]["sha256"], "sha256:" + hashlib.sha256((RUNTIME / "drift_receipt_appender.py").read_bytes()).hexdigest())
        self.assertEqual(hashlib.sha256(WRITER.read_bytes()).hexdigest(), doc["writer"]["sha256"])
        self.assertEqual(doc["admission"]["disposition"], "FAIL_CLOSED")
        for k in SIX:
            self.assertEqual(doc["admission"][k], appender.ADMISSION_PENDING_GENESIS[k])
        self.assertEqual(doc["organization_ledger_effect"], "NONE")
        self.assertEqual(doc["registry_generation_effect"], "NONE")
        workflow = (ROOT / ".github" / "workflows" / "drift-receipt-appender-validation.yml").read_text()
        for word in ("workflow_dispatch", "schedule", "cron", "contents: write"):
            self.assertNotIn(word, workflow)

    def test_payload_without_verification_accounting_is_required_verification_skipped(self) -> None:
        body = self.payload()
        body.pop("verification")
        body.pop("receipt_sha256")
        r = appender.receipt(self.repo, self.writer.seal(body), self.writer, "test")
        self.assertEqual(r["first_item"]["failure_code"], "REQUIRED_VERIFICATION_SKIPPED")
        self.assertEqual(r["items"][0]["failure_code"], "REQUIRED_VERIFICATION_SKIPPED")
        self.assert_six(r["items"][0])
        self.assertEqual(r["disposition"], "FAIL_CLOSED")
        self.assertEqual(r["admission"]["failure_code"], "DRIFT_RECEIPT_APPENDER_ADMISSION_PENDING_GENESIS")

    def test_pre_existing_payload_naming_a_skip_is_never_receipted_as_pre_existing_alone(self) -> None:
        row = {"test": "tests/test_s.py::test_s", "kind": "SKIPPED", "failure_code": "REQUIRED_VERIFICATION_SKIPPED",
               "failed_predicate": "REQUIRED_TEST_IS_NOT_SKIPPED", "retry_entrypoint": "toy.yml",
               "disposition": "FAIL_CLOSED", "blocking": True}
        for over in ({"tests": [row], "verification": {"counts": {"skipped": 1}, "required_verification_skipped": 1}},
                     {"verification": {"counts": {"passed": 3, "xfailed": 1}}},
                     {"verification": {"counts": {"skipped": 2}}}):
            payload = self.payload(schema="stegverse.test-suite-pr-disposition/v1",
                                   disposition="PRE_EXISTING_BASELINE_FAILURE", **over)
            r = appender.receipt(self.repo, payload, self.writer, "test")
            first = r["items"][0]
            self.assertEqual(first["failure_code"], "REQUIRED_VERIFICATION_SKIPPED", over)
            self.assertNotEqual(r["first_item"]["failure_code"], "PRE_EXISTING_BASELINE_FAILURE")
            self.assert_six(first)
            self.assertGreaterEqual(first["skipped_or_unrun"], 1)

    def test_clean_verification_block_adds_no_item(self) -> None:
        r = appender.receipt(self.repo, self.payload(), self.writer, "test")
        self.assertEqual(r["required_verification"], {"disposition": "ALLOW"})
        self.assertNotIn("REQUIRED_VERIFICATION_SKIPPED", [i["failure_code"] for i in r["items"]])

    def test_retained_fixtures_verify_under_the_b1_seal(self) -> None:
        for path in sorted(FIXTURES.glob("*.json")):
            doc = json.loads(path.read_text())
            self.assertIsNone(appender.check_payload(self.writer, doc), path.name)


if __name__ == "__main__":
    unittest.main()
