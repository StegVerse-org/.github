"""B3 main-change digest: resident-runtime/merge_digest.py and its workflow_run consumer."""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSUMER = ROOT / ".github/workflows/organization-ledger-merge-digest.yml"
VALIDATION = ROOT / ".github/workflows/organization-ledger-merge-digest-validation.yml"
WRITER = ROOT / ".github/workflows/organization-ledger-merge-transfer.yml"
REF = "refs/stegverse/organization-ledger"
REPO = "Example-Org/.github"
A, B = "a" * 40, "b" * 40


def load():
    spec = importlib.util.spec_from_file_location("merge_digest_under_test", ROOT / "resident-runtime/merge_digest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


md = load()


def seal(body: dict) -> dict:
    return {**body, "receipt_sha256": md.sha(body)}


class Ledger:
    """A bare git dir holding receipts/<hex>.json on REF."""

    def __init__(self, receipts: list[dict]):
        self.tmp = tempfile.TemporaryDirectory()
        self.git_dir = Path(self.tmp.name) / "ledger.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.git_dir)], check=True)
        env_index = Path(self.tmp.name) / "index"
        env = {"GIT_DIR": str(self.git_dir), "GIT_INDEX_FILE": str(env_index), "GIT_AUTHOR_NAME": "t",
               "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
               "PATH": "/usr/bin:/bin:/usr/local/bin"}
        for receipt in receipts:
            blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], input=json.dumps(receipt).encode(),
                                  env=env, check=True, capture_output=True).stdout.decode().strip()
            name = "receipts/" + receipt["receipt_sha256"][7:] + ".json"
            subprocess.run(["git", "update-index", "--add", "--cacheinfo", "100644," + blob + "," + name], env=env, check=True)
        tree = subprocess.run(["git", "write-tree"], env=env, check=True, capture_output=True).stdout.decode().strip()
        commit = subprocess.run(["git", "commit-tree", tree, "-m", "t"], env=env, check=True,
                                capture_output=True).stdout.decode().strip()
        subprocess.run(["git", "update-ref", REF, commit], env=env, check=True)


def receipt(commit: str, **boundary) -> dict:
    return seal({"schema": "stegverse.organization-transition-receipt/v1", "organization": "Example-Org",
                 "hb_reference": {"epoch": 7, "derived_from_clock": False},
                 "boundary_evidence": {"operation": "ORGANIZATION_MAIN_MERGE_TRANSFER", "merge_commit": commit,
                                       "disposition": "ALLOW", **boundary}})


def allow(commit: str, org: dict) -> dict:
    return {"disposition": "ALLOW", "merge_commit": commit, "hb_epoch": 7, "transfer": "VERIFIED",
            "organization_receipt_sha256": org["receipt_sha256"], "repository_receipt_sha256": "sha256:" + "c" * 64}


def build(results, ledger=None, pulls=None, commits=(A,), **kw):
    return md.build(repository=REPO, head_sha=commits[-1], run_id="42", run_url="https://example/run/42",
                    run_conclusion="success", commits=list(commits), selection="WRITER_SELECTION", results=results,
                    git_dir=ledger.git_dir if ledger else None, ref=REF, pulls=pulls or {}, parents={},
                    default_goal_issue=REPO + "#160", **kw)


class Selection(unittest.TestCase):
    def test_the_writer_selection_is_used_and_malformed_lines_are_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "commits.txt").write_text(A + "\nnot-a-sha\n" + B + "\n" + A + "\n")
            self.assertEqual(md.selected_commits(Path(tmp), B), ([A, B], "WRITER_SELECTION"))

    def test_absent_writer_evidence_projects_the_head_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(md.selected_commits(Path(tmp), B), ([B], "WRITER_EVIDENCE_ABSENT_HEAD_ONLY"))
        self.assertEqual(md.selected_commits(None, B)[0], [B])
        with self.assertRaises(ValueError):
            md.selected_commits(None, "HEAD")


class Digest(unittest.TestCase):
    def test_an_allowed_merge_is_projected_with_its_read_back_receipt(self):
        org = receipt(A)
        ledger = Ledger([org])
        digest = build([allow(A, org)], ledger, pulls={A: [12]})
        entry = digest["entries"][0]
        self.assertEqual(entry["disposition"], "ALLOW")
        self.assertTrue(entry["receipt_read_back"])
        self.assertIs(entry["epoch_derived_from_clock"], False)
        self.assertEqual((entry["merge_kind"], entry["pull_requests"]), ("PULL_REQUEST", [12]))
        self.assertEqual((entry["goal_issue"], entry["goal_binding"]), (REPO + "#160", "DEFAULT_GOAL_ISSUE"))
        self.assertEqual(digest["lowest_supported_mode"], "E0")
        self.assertIs(digest["clock_read"], False)
        goal, kv = digest["projections"]
        self.assertEqual((goal["projection"], goal["disposition"]), ("GOAL_ISSUE_COMMENT", "ALLOW"))
        self.assertEqual((kv["projection"], kv["disposition"], kv["class"]), ("KV_COORDINATION_FOLDER", "FAIL_CLOSED", "C"))
        for field in md.SIX_FIELDS:
            self.assertTrue(kv[field], field)
        text = md.markdown(digest)
        self.assertTrue(text.startswith(digest["marker"]))
        self.assertIn("| PR #12 | `" + A[:12] + "`", text)
        self.assertIn("KV_DIGEST_CUSTODY_PATH_NOT_SETTLED", text)

    def test_a_refused_merge_carries_the_verifiers_six_fields(self):
        refusal = {"disposition": "FAIL_CLOSED", "merge_commit": A, "failure_code": "MERGE_TRANSFER_RECEIPT_NOT_LEDGERED",
                   "failed_predicate": "P", "required_evidence_or_repair": "R", "retry_entrypoint": "E",
                   "owning_existing_goal": "G", "next_attempt": "N"}
        entry = build([refusal], pulls={A: []})["entries"][0]
        self.assertEqual(entry["merge_kind"], "DIRECT_PUSH")
        self.assertEqual([entry[f] for f in md.SIX_FIELDS], ["MERGE_TRANSFER_RECEIPT_NOT_LEDGERED", "P", "R", "E", "G", "N"])
        self.assertIn("FAIL_CLOSED: MERGE_TRANSFER_RECEIPT_NOT_LEDGERED / P / R / E / G / N", md.markdown(build([refusal])))

    def test_a_merge_with_no_verifier_result_is_never_silent(self):
        digest = build(None, commits=(A, B))
        self.assertEqual([e["failure_code"] for e in digest["entries"]], ["MAIN_CHANGE_RECEIPT_NOT_VERIFIED"] * 2)
        self.assertEqual(digest["entries"][0]["merge_kind"], "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED")

    def test_an_unsealed_receipt_is_refused(self):
        org = receipt(A)
        tampered = {**org, "organization": "Other"}
        ledger = Ledger([tampered])
        entry = build([allow(A, org)], ledger)["entries"][0]
        self.assertEqual(entry["failure_code"], "MAIN_CHANGE_RECEIPT_NOT_SEALED")

    def test_a_task_binding_in_another_repository_is_a_credential_transition_not_a_stop(self):
        org = receipt(A, goal_issue="Other-Org/.github#5")
        ledger = Ledger([org])
        digest = build([allow(A, org)], ledger)
        entry = digest["entries"][0]
        self.assertEqual((entry["goal_issue"], entry["goal_binding"]), ("Other-Org/.github#5", "RECEIPT_TASK_BINDING"))
        goal = digest["projections"][0]
        self.assertEqual((goal["disposition"], goal["failure_code"], goal["class"]),
                         ("FAIL_CLOSED", "GOAL_ISSUE_CROSS_REPOSITORY_WRITE_CREDENTIAL_NOT_ISSUED", "B"))
        self.assertIn("TV/TVC", goal["required_evidence_or_repair"])
        self.assertNotIn("owner", json.dumps(digest).lower())

    def test_the_digest_id_is_deterministic_per_batch(self):
        org = receipt(A)
        ledger = Ledger([org])
        self.assertEqual(build([allow(A, org)], ledger)["digest_id"], build([allow(A, org)], ledger)["digest_id"])
        self.assertNotEqual(build([allow(A, org)], ledger)["digest_id"], build(None)["digest_id"])

    def test_no_clock_is_read(self):
        source = (ROOT / "resident-runtime/merge_digest.py").read_text()
        self.assertIsNone(re.search(r"^\s*(import|from)\s+(time|datetime)\b", source, re.M))


def _strip(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


class WorkflowShape(unittest.TestCase):
    def test_the_consumer_runs_only_on_completion_of_the_writer(self):
        text = _strip(CONSUMER.read_text())
        writer_name = re.search(r"^name:\s*(.+)$", WRITER.read_text(), re.M).group(1).strip()
        on = text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(re.findall(r"^  (\w+):", on, re.M), ["workflow_run"])
        self.assertIn("workflows: [" + writer_name + "]", on)
        self.assertIn("types: [completed]", on)
        for forbidden in ("workflow_dispatch", "schedule", "pull_request_target", "pull_request:", "cron"):
            self.assertNotIn(forbidden, text)

    def test_the_consumer_holds_least_privilege_and_writes_no_ledger(self):
        text = _strip(CONSUMER.read_text())
        self.assertIn("\npermissions: {}\n", text)
        job_perms = re.search(r"\n    permissions:\n((?:      .+\n)+)", text).group(1)
        self.assertEqual(sorted(l.strip() for l in job_perms.splitlines()),
                         ["actions: read", "contents: read", "issues: write", "pull-requests: read"])
        self.assertNotRegex(text, r"\n    if:")
        self.assertNotIn("git push", text)
        self.assertNotIn("update-ref", text)
        self.assertNotIn("append", text.replace("--commits-file", ""))

    def test_the_validation_is_read_only_on_pull_request(self):
        text = _strip(VALIDATION.read_text())
        on = text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(re.findall(r"^  (\w+):", on, re.M), ["pull_request"])
        self.assertIn("\npermissions:\n  contents: read\n", text)
        self.assertNotIn(": write", text)
        self.assertNotRegex(text, r"\n    if:")


if __name__ == "__main__":
    unittest.main()
