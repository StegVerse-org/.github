"""sv_push_receipt: the org-ledger writer appends one sv-push-receipt.v1 per push range.

Port of StegVerse-Labs/.github tests/test_sv_push_receipt_append.py (#3424) to this organization's writer
(StegVerse-org/.github#167; owner P1 #163).

Temporary repositories and ledgers only (each ledger is the pinned published ledger tip, rebuilt in a temp bare
repository by tests/test_merge_transfer_gitstore.py::TempLedger): receipts here are exercise evidence on those, not records of the published
organization ledger. Clock-free and network-free: epochs are supplied constants and the pushes in the one producer
round-trip are local to a temporary bare repository.

  * accept: the receipt is the repository receipt's $.evidence, aggregated into an organization receipt, read back from a
    fresh fetch, with a supplied (not clock-derived) epoch; a producer-emitted receipt is accepted as emitted;
  * duplicate: a second receipt for the same (repository, ref, old_sha, new_sha) is refused with the six fields and appends
    nothing, identical or not; another range is appended beside it;
  * malformed: every shape or seal break and every epoch break is a six-field refusal before any write;
  * routing: the ingest request names the operation; the manifest declares it; the writer runs it on push only.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
       "owning_existing_goal", "next_attempt")
WRITER = ROOT / ".github" / "workflows" / "organization-ledger-writer.yml"
CATALOG = ROOT / "tools" / "tasks" / "task_catalog.json"
OPERATIONS = ROOT / ".stegverse" / "organization-ledger-ingest" / "operations.json"
WORKFLOW_FILES = ("organization-egress-boundary-validation.yml", "organization-ledger-writer.yml", "validation-dispatcher.yml")
REPOSITORY = "StegVerse-org/StegVerse-SDK"
BRANCH = "refs/heads/laneb/example"


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pa = _load("sv_push_receipt_append_test", ROOT / "resident-runtime" / "sv_push_receipt_append.py")
producer = pa.producer
ing = _load("organization_ledger_ingest_for_push", ROOT / "resident-runtime" / "organization_ledger_ingest.py")
from tests import test_merge_transfer_gitstore as mtg  # noqa: E402  the pinned published ledger tip, rebuilt in a temp repository

TempLedger = mtg.TempLedger

ledger_store = pa.ingress.repository_ledger.ledger_store
readback = ing._module("organization_ledger_readback_for_push", "resident-runtime/organization_ledger_readback.py")
REF = mtg.PIN["ledger_ref"]
NAMESPACE = mtg.PIN["repository_ledger_namespace"]


def _git(git_dir, *args):
    return subprocess.run(["git", "--git-dir", str(git_dir), *args], check=True, capture_output=True).stdout


def oid(n: int) -> str:
    return f"{n:040x}"


def push_receipt(old=1, new=3, **override):
    """A sealed sv-push-receipt.v1 built through the producer's own seal; commits old+1..new."""
    body = {"schema": "stegverse.sv_push_receipt.v1", "repository": REPOSITORY, "ref": BRANCH, "old_sha": oid(old),
            "new_sha": oid(new), "pusher_session": "p1-sandbox-and-hcb-20261024", "pushed_commits": [oid(n) for n in range(old + 1, new + 1)],
            "hb_epoch": "1024"}
    body.update(override)
    body = {k: v for k, v in body.items() if v is not None}
    body.pop("result_sha256", None)
    return producer.seal(body)


class AppendBase(unittest.TestCase):
    def setUp(self):
        self.ledger = TempLedger()
        self.addCleanup(self.ledger.close)
        self._work = tempfile.TemporaryDirectory()
        self.addCleanup(self._work.cleanup)
        self.work = Path(self._work.name)
        self.bare = self.ledger.git_dir
        self.seed = self.ledger.tip()

    def tip(self):
        return self.ledger.tip()

    def assert_refused(self, result, code, disposition="FAIL_CLOSED"):
        self.assertEqual(result["disposition"], disposition, result)
        self.assertEqual(result["failure_code"], code, result)
        for field in SIX:
            self.assertTrue(isinstance(result[field], str) and result[field], field)
        self.assertIs(result["consequence_committed"], False)
        self.assertEqual(self.tip(), self.seed, "a refusal appends nothing")

    def chain_for(self, location=None):
        store = ledger_store.open_store(location or f"git+{self.bare}#{REF}:{NAMESPACE}")
        rl = pa.ingress.repository_ledger
        return [r for r in rl.chain(store, store.get(ledger_store.HEAD_KEY)) if r["transition_class"] == pa.TRANSITION_CLASS]


class Accept(AppendBase):
    def test_append_round_trips_with_a_supplied_epoch_and_keeps_history(self):
        receipt = push_receipt()
        result = pa.append_push_receipt(receipt, hb_epoch=1024)
        self.assertEqual(result["disposition"], "ALLOW", result)
        self.assertIs(result["appended"], True)
        self.assertEqual(result["transition_class"], "SV_PUSH_RECEIPT_APPEND")
        self.assertEqual(result["range"], {"repository": REPOSITORY, "ref": BRANCH, "old_sha": oid(1), "new_sha": oid(3)})
        self.assertIs(result["organization_receipt_preserves_repository_receipt"], True)
        self.assertEqual(_git(self.bare, "merge-base", "--is-ancestor", self.seed, REF), b"")
        self.assertEqual(_git(self.bare, "rev-parse", f"{REF}:HEAD.json") != b"", True)

        store = ledger_store.open_store(f"git+{self.bare}#{REF}")
        org = store.get(result["organization_receipt_key"])
        repo = store.get(result["repository_receipt_source_key"])
        self.assertEqual(repo["repository"], "StegVerse-org/.github")  # the ledger's own repository; the pushed one is in evidence
        self.assertEqual(repo["evidence"], receipt)  # the complete receipt, self-identified by $.evidence.schema
        self.assertEqual(repo["transition_class"], "SV_PUSH_RECEIPT_APPEND")
        self.assertEqual(org["boundary_evidence"]["operation"], "sv_push_receipt")
        self.assertEqual(org["repo_receipt_sha256"], repo["receipt_sha256"])
        for row in (org, repo):
            self.assertIs(row["hb_reference"]["derived_from_clock"], False)
            self.assertEqual(row["hb_reference"]["epoch"], 1024)
            self.assertTrue(pa._self_verifies(row))
            self.assertTrue(readback.self_verifies(row))

        reader = self.work / "reader.git"
        subprocess.run(["git", "init", "--bare", "-q", str(reader)], check=True)
        subprocess.run(["git", "--git-dir", str(reader), "fetch", "-q", str(self.bare), f"+{REF}:{REF}"], check=True)
        bound = pa.bind_push_receipt(f"git+{reader}#{REF}", result)
        self.assertEqual(bound["disposition"], "ALLOW", bound)
        self.assertEqual(readback.readback(f"git+{reader}#{REF}")["disposition"], "ALLOW")
        self.assertEqual(ing.main(["read", "--request", str(ROOT / ing.REQUEST_PATH)]), 0)
        self.assertEqual(len(self.chain_for()), 1)

    def test_a_receipt_the_producer_emitted_is_accepted_as_emitted(self):
        base = self.work / "emit"
        remote = self.work / "emit-remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(base)], check=True)

        def git(*args):
            env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
            env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
            return subprocess.run(["git", "-C", str(base), *args], env=env, capture_output=True, text=True, check=True).stdout.strip()
        git("remote", "add", "origin", str(remote))
        (base / "a").write_text("a\n")
        git("add", "a")
        git("commit", "-q", "-m", "a")
        git("push", "-q", "origin", "main")
        old = git("rev-parse", "HEAD")
        (base / "b").write_text("b\n")
        git("add", "b")
        git("commit", "-q", "-m", "b")
        git("push", "-q", "origin", "main")
        out = self.work / "emitted.json"
        emitted = producer.emit(base, repository_name=REPOSITORY, ref="refs/heads/main", old_sha=old,
                                pusher_session="p1-sandbox-and-hcb-20261024", after_ref="refs/remotes/origin/main", hb_epoch="1024", out=out)
        self.assertEqual(emitted["schema"], "stegverse.sv_push_receipt.v1", emitted)
        result = pa.append_push_receipt(json.loads(out.read_text(encoding="utf-8")), hb_epoch=1024)
        self.assertEqual(result["disposition"], "ALLOW", result)
        self.assertEqual(result["push_result_sha256"], emitted["result_sha256"])

    def test_a_different_range_is_appended_beside_the_first_and_the_chain_stays_whole(self):
        first = pa.append_push_receipt(push_receipt(1, 3), hb_epoch=1024)
        second = pa.append_push_receipt(push_receipt(3, 4), hb_epoch=1024)  # the next push on the same ref
        other_ref = pa.append_push_receipt(push_receipt(1, 3, ref="refs/heads/laneb/other"), hb_epoch=1024)
        other_repo = pa.append_push_receipt(push_receipt(1, 3, repository="StegVerse-org/Other-Repo"), hb_epoch=1024)
        for result in (first, second, other_ref, other_repo):
            self.assertEqual(result["disposition"], "ALLOW", result)
        self.assertEqual(len({r["range_id"] for r in (first, second, other_ref, other_repo)}), 4)
        self.assertEqual(len(self.chain_for()), 4)  # chain() verifies every node it walks

    def test_transition_id_names_the_range_alone(self):
        a = push_receipt(1, 3, pusher_session="one", hb_epoch="1024")
        b = push_receipt(1, 3, pusher_session="two", hb_epoch="2048")
        self.assertNotEqual(a["result_sha256"], b["result_sha256"])
        self.assertEqual(pa.transition_id(a), pa.transition_id(b))
        self.assertTrue(pa.transition_id(a).startswith("SV_PUSH_RECEIPT_APPEND:"))


class DuplicateRange(AppendBase):
    def test_a_second_receipt_for_the_same_range_is_refused_and_appends_nothing(self):
        first = pa.append_push_receipt(push_receipt(), hb_epoch=1024)
        self.assertEqual(first["disposition"], "ALLOW", first)
        tip = self.tip()
        again = pa.append_push_receipt(push_receipt(), hb_epoch=1024)
        self.assertEqual(again["disposition"], "FAIL_CLOSED", again)
        self.assertEqual(again["failure_code"], "SV_PUSH_RECEIPT_RANGE_ALREADY_RECORDED")
        self.assertEqual(again["failed_predicate"], "ONE_PUSH_RECEIPT_PER_REPOSITORY_REF_OLD_NEW_RANGE")
        for field in SIX:
            self.assertTrue(isinstance(again[field], str) and again[field], field)
        self.assertIs(again["appended"], False)
        self.assertIs(again["consequence_committed"], False)
        self.assertIs(again["byte_identical_to_recorded"], True)
        self.assertEqual(again["recorded_repository_receipt_sha256"], first["repository_receipt_sha256"])
        self.assertEqual(self.tip(), tip, "the ledger did not move")
        self.assertEqual(len(self.chain_for()), 1)

    def test_a_receipt_for_the_same_range_that_differs_in_any_field_is_also_a_duplicate(self):
        first = pa.append_push_receipt(push_receipt(), hb_epoch=1024)
        tip = self.tip()
        for variant, epoch in ((push_receipt(pusher_session="another-session"), 1024),
                               (push_receipt(hb_epoch="2048"), 2048),
                               (push_receipt(pushed_commits=[oid(3)]), 1024),
                               (push_receipt(change_id="svc:" + "a" * 64), 1024)):
            self.assertNotEqual(variant["result_sha256"], push_receipt()["result_sha256"])
            result = pa.append_push_receipt(variant, hb_epoch=epoch)
            self.assertEqual(result["failure_code"], "SV_PUSH_RECEIPT_RANGE_ALREADY_RECORDED", result)
            self.assertIs(result["appended"], False)
            self.assertIs(result["byte_identical_to_recorded"], False)
            self.assertEqual(result["recorded_repository_receipt_sha256"], first["repository_receipt_sha256"])
            self.assertEqual(self.tip(), tip)
        self.assertEqual(len(self.chain_for()), 1)

    def test_the_duplicate_is_refused_through_the_command_line_with_a_nonzero_exit(self):
        receipt_file = self.work / "push-receipt.json"
        receipt_file.write_text(json.dumps(push_receipt()), encoding="utf-8")
        env = dict(os.environ)  # TempLedger binds STEGVERSE_ORG_LEDGER_ROOT and STEGVERSE_REPO_LEDGER_ROOT
        argv = [sys.executable, str(ROOT / "resident-runtime" / "sv_push_receipt_append.py"), "append",
                "--push-receipt", str(receipt_file), "--hb-epoch", "1024"]
        ok = subprocess.run(argv, env=env, capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        tip = self.tip()
        dup = subprocess.run(argv, env=env, capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(dup.returncode, 1, dup.stdout + dup.stderr)
        self.assertEqual(json.loads(dup.stdout)["failure_code"], "SV_PUSH_RECEIPT_RANGE_ALREADY_RECORDED")
        self.assertEqual(self.tip(), tip)


class MalformedEvidence(AppendBase):
    def test_non_push_evidence_is_refused_before_any_write(self):
        for bad in (None, ["not", "an", "object"], "text", {"communication_id": "x"},
                    push_receipt(schema="stegverse.sv_push_receipt.v0"),
                    {"schema": "stegverse.sv_check_receipt.v1", "check_id": "x"}):
            self.assert_refused(pa.append_push_receipt(bad, hb_epoch=1024), "LEDGER_EVIDENCE_NOT_A_PUSH_RECEIPT")

    def test_a_shape_or_seal_break_is_refused_before_any_write(self):
        good = push_receipt()
        broken = {
            "extra field": producer.seal({**{k: v for k, v in good.items() if k != "result_sha256"}, "kind": "sv_push_receipt"}),
            "missing field": {k: v for k, v in good.items() if k != "pusher_session"},
            "short old_sha": push_receipt(old_sha="abc"),
            "uppercase new_sha": push_receipt(new_sha="A" * 40, pushed_commits=["A" * 40]),
            "pushed_commits not ending at new_sha": push_receipt(pushed_commits=[oid(3), oid(2)]),
            "empty pushed_commits": push_receipt(pushed_commits=[]),
            "repeated commit": push_receipt(pushed_commits=[oid(3), oid(3)]),
            "blank pusher_session": push_receipt(pusher_session="  "),
            "tag ref": push_receipt(ref="refs/tags/v1"),
            "bad repository": push_receipt(repository="no-owner"),
            "bad change_id": push_receipt(change_id="svc:short"),
            "epoch under 32": push_receipt(hb_epoch="31"),
            "epoch not text": push_receipt(hb_epoch=1024),
            "tampered after sealing": {**good, "pusher_session": "someone-else"},
            "seal removed": {k: v for k, v in good.items() if k != "result_sha256"},
            "seal replaced": {**good, "result_sha256": "sha256:" + "0" * 64},
        }
        for name, bad in broken.items():
            result = pa.append_push_receipt(bad, hb_epoch=1024)
            self.assertEqual(result["disposition"], "FAIL_CLOSED", name)
            self.assertEqual(result["failure_code"], "SV_PUSH_RECEIPT_MALFORMED", name)
            for field in SIX:
                self.assertTrue(isinstance(result[field], str) and result[field], name + " " + field)
            self.assertEqual(self.tip(), self.seed, name)
            self.assertIs(result["consequence_committed"], False, name)
            self.assertTrue(result["problem"], name)

    def test_an_absent_null_or_sentinel_epoch_is_unobserved_on_either_side(self):
        for bad in (None, "", "null", "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"):
            result = pa.append_push_receipt(push_receipt(), hb_epoch=bad)
            self.assert_refused(result, "HB_EPOCH_SOURCE_UNOBSERVED")
            self.assertEqual(result["shared_rule_sha256"], pa.SHARED_RULE_SHA256)

    def test_a_malformed_or_unequal_epoch_is_a_mismatch_and_no_clock_is_read(self):
        for bad in (True, False, 31, 0, -40, "1024", 1024.0, "unknown"):
            result = pa.append_push_receipt(push_receipt(), hb_epoch=bad)
            self.assert_refused(result, "HB_EPOCH_MISMATCH", disposition="DENY")
            self.assertEqual(result["failed_predicate"], "PUSH_RECEIPT_HB_EPOCH_EQUALS_APPEND_HB_EPOCH")
        result = pa.append_push_receipt(push_receipt(hb_epoch="2048"), hb_epoch=1024)
        self.assert_refused(result, "HB_EPOCH_MISMATCH", disposition="DENY")
        self.assertEqual(self.tip(), self.seed)

    def test_the_verifier_reads_no_clock_and_no_network(self):
        text = (ROOT / "resident-runtime" / "sv_push_receipt_append.py").read_text(encoding="utf-8")
        for token in ("import time", "from time", "datetime", "import socket", "urllib", "requests", "http.client", "subprocess",
                      "time.time", "utcnow"):
            self.assertNotIn(token, text, token)


class Routing(unittest.TestCase):
    def test_the_ingest_request_names_the_operation_and_materializes_the_receipt(self):
        receipt = push_receipt()
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / "request.json"
            request.write_text(json.dumps({"schema": ing.SCHEMA, "operation": "sv_push_receipt", "push_receipt": receipt,
                                           "hb_epoch": 1024}), encoding="utf-8")
            read = ing.read_request(request)
            self.assertEqual(read["disposition"], "ALLOW", read)
            self.assertEqual((read["operation"], read["push_receipt"], read["hb_epoch"]), ("sv_push_receipt", receipt, 1024))
            env_file, out = Path(tmp) / "env", Path(tmp) / "parts"
            self.assertEqual(ing.main(["read", "--request", str(request), "--materialize", str(out), "--github-env", str(env_file)]), 0)
            self.assertEqual(json.loads((out / "push-receipt.json").read_text(encoding="utf-8")), receipt)
            self.assertEqual(env_file.read_text(encoding="utf-8").split(), ["INGEST_OPERATION=sv_push_receipt", "HB_EPOCH=1024"])
            for bad, code in (({"push_receipt": "text"}, "LEDGER_EVIDENCE_NOT_A_PUSH_RECEIPT"),
                              ({"push_receipt": [receipt]}, "LEDGER_EVIDENCE_NOT_A_PUSH_RECEIPT"),
                              ({"hb_epoch": "1024"}, "SV_PUSH_RECEIPT_HB_EPOCH_INVALID"),
                              ({"hb_epoch": True}, "SV_PUSH_RECEIPT_HB_EPOCH_INVALID"),
                              ({"hb_epoch": -1}, "SV_PUSH_RECEIPT_HB_EPOCH_INVALID"),
                              ({"check_receipt": {}}, "INGEST_REQUEST_SCHEMA_MISMATCH")):
                request.write_text(json.dumps({"schema": ing.SCHEMA, "operation": "sv_push_receipt", "push_receipt": receipt,
                                               "hb_epoch": 1024} | bad), encoding="utf-8")
                refused = ing.read_request(request)
                self.assertEqual(refused["failure_code"], code, refused)
                for field in SIX:
                    self.assertTrue(refused[field], field)

    def test_the_operation_is_declared_with_its_class_schema_and_one_receipt_per_range(self):
        declared = json.loads(OPERATIONS.read_text(encoding="utf-8"))["organization_ledger_writer_operations"]
        entry, = [e for e in declared if e["operation"] == pa.OPERATION_ID]
        self.assertEqual(entry["operation_module"], "resident-runtime/sv_push_receipt_append.py")
        self.assertEqual(entry["transition_class"], pa.TRANSITION_CLASS)
        self.assertEqual(entry["evidence_schema"], pa.PUSH_RECEIPT_SCHEMA_ID)
        self.assertEqual(entry["organization_receipt_boundary_operation"], "sv_push_receipt")
        self.assertIs(entry["ingress_capability"], False)
        self.assertIs(entry["addressable_from_the_service_registry"], False)
        self.assertIn("SV_PUSH_RECEIPT_RANGE_ALREADY_RECORDED", entry["one_receipt_per_range"])
        self.assertIn("no dispatch input, no schedule", entry["invoked_by"])
        self.assertEqual(entry["epoch_rule_sha256"], pa.SHARED_RULE_SHA256)
        self.assertEqual(pa.KERNEL_RULE_SHA256, pa.SHARED_RULE_SHA256, "the writer's epoch rule is the pinned shared rule")
        sealed, = [e for e in declared if e["operation"] == ing.SEALED]
        self.assertEqual(sealed["entrypoint"], "resident-runtime/organization_ledger_ingest.py::append_sealed")
        schema = json.loads((ROOT / "schemas" / "sv-push-receipt.v1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema"]["const"], pa.PUSH_RECEIPT_SCHEMA_ID)

    def test_the_epoch_rule_is_the_egress_boundarys_byte_identical_copy(self):
        egress = ing._module("organization_egress_boundary_for_push", "resident-runtime/organization_egress_boundary.py")
        self.assertEqual(inspect.getsource(egress.supplied_epoch_failure), inspect.getsource(pa.epoch_rule))

    def test_a_pushed_ingest_request_selects_the_ledger_ingest_writer_job_only(self):
        writer_plan = _load("writer_plan_for_push", ROOT / "tools" / "tasks" / "writer_plan.py")  # the writer's plan job
        jobs = json.loads((ROOT / "control/workflow-surface-registry.json").read_text())["writer_jobs"]
        for name in ("request.json", "operations.json"):
            got = writer_plan.select([".stegverse/organization-ledger-ingest/" + name], jobs)
            self.assertEqual(got, {"ledger-transition": False, "governance-return": False, "ledger-ingest": True}, name)

    def test_the_writer_runs_it_on_push_only_under_the_shared_lock_and_the_pr_check_appends_nothing(self):
        text = WRITER.read_text(encoding="utf-8")
        head, jobs = text.split("\njobs:\n", 1)
        job = jobs[jobs.index("\n  ledger-ingest:\n"):]
        self.assertIn("env.INGEST_OPERATION == 'sv_push_receipt'", job)
        self.assertIn("resident-runtime/sv_push_receipt_append.py append", job)
        self.assertIn("resident-runtime/sv_push_receipt_append.py readback", job)
        self.assertIn("resident-runtime/sv_push_receipt_append.py", job.split("py_compile", 1)[1].split("\n\n", 1)[0])
        self.assertIn("concurrency:\n  group: organization-ledger\n  cancel-in-progress: false\n", text)
        on = head.split("\non:\n", 1)[1].split("\n\n", 1)[0]
        for token in ("workflow_dispatch", "schedule", "cron", "pull_request"):
            self.assertNotIn(token, on, token)
        self.assertNotIn("--force", text)
        self.assertNotIn("update-ref", job)
        self.assertEqual(job.count('git push origin "$LEDGER_REF:$LEDGER_REF"'), 1, "one fast-forward publish for either operation")
        self.assertEqual(sorted(p.name for p in (ROOT / ".github" / "workflows").glob("*.yml")), list(WORKFLOW_FILES),
                         "no workflow was added (G17)")
        group, = [g for g in json.loads(CATALOG.read_text(encoding="utf-8"))["groups"]
                  if g["id"] == "organization-ledger-ingest-validation.unit"]
        steps = "\n".join((ROOT / step["run_file"]).read_text(encoding="utf-8") for step in group["steps"])
        self.assertIn("tests.test_sv_push_receipt_append", steps)
        self.assertIn("tests.test_sv_push_receipt", steps)
        self.assertNotIn("sv_push_receipt_append.py append", steps)

    def test_files_touched_do_not_use_the_forbidden_word(self):
        token = "g" + "rant"
        for path in (ROOT / "resident-runtime" / "sv_push_receipt_append.py", Path(__file__)):
            self.assertNotIn(token, path.read_text(encoding="utf-8").lower(), path.name)


if __name__ == "__main__":
    unittest.main()
