"""sv_check_receipt: the org-ledger writer appends one NWI-S1 check receipt (StegVerse-org/.github#163/#167).

Port of the StegVerse-Labs/.github operation of the same name to this organization's own writer, so a NATIVE SV_ISSUE can be
derived from a failing check receipt on this ledger (sv_change_admit_append.py). Authoring-Session: p1-ecosystem-ai-lane.

Temporary repositories and ledgers only (each ledger is the pinned published ledger tip, rebuilt in a temp bare repository by
tests/test_merge_transfer_gitstore.py::TempLedger): receipts here are exercise evidence on those, not records of the published
organization ledger. Clock-free and network-free: epochs are supplied constants.

  * accept: the check receipt is the repository receipt's $.evidence, aggregated into an organization receipt, read back from a
    fresh fetch, at a supplied epoch; P1 derives a NATIVE issue from a failing one and none from a passing one;
  * replay: the same receipt appended again is the recorded pair, nothing new;
  * refusals: malformed receipts, an undeclared command, every epoch break and a drifted P1 pin are six-field refusals before
    any write;
  * routing: the ingest request names the operation; the manifest declares it; the writer runs it on push only, no new workflow.
"""
from __future__ import annotations

import inspect
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests import test_sv_push_receipt_append as pushtests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "resident-runtime"))
import sv_check_receipt_append as svc  # noqa: E402

ing, pa, readback, ledger_store, _git = pushtests.ing, pushtests.pa, pushtests.readback, pushtests.ledger_store, pushtests._git
REF, NAMESPACE = pushtests.REF, pushtests.NAMESPACE
SIX = svc.SIX_FIELDS
WRITER = ROOT / ".github" / "workflows" / "organization-ledger-writer.yml"
OPERATIONS = ROOT / ".stegverse" / "organization-ledger-ingest" / "operations.json"
CATALOG = ROOT / "tools" / "tasks" / "task_catalog.json"
EPOCH = 1024
HEAD = "a" * 40
CHANGE = "sha256:" + "b" * 64
wi = svc.p1_readers()


def check_receipt(**override):
    r = {"schema": "stegverse.sv_check_receipt.v1", "check_id": "workflow-surface-registered",
         "disposition": "FAIL_CLOSED", "change_digest": CHANGE, "head_sha": HEAD, "hb_epoch": str(EPOCH),
         "verifier_ref": "SV-LLM/.github#46 fixture run",
         "failure_code": "WORKFLOW_SURFACE_UNREGISTERED", "failed_predicate": "EVERY_WORKFLOW_FILE_IS_REGISTERED",
         "required_evidence_or_repair": "register .github/workflows/x.yml in control/workflow-surface-registry.json",
         "retry_entrypoint": "scripts/validate_workflow_surface_hygiene.py", "owning_existing_goal": "HYGIENE-CAUSAL-ROOTS-001",
         "next_attempt": "after the registry entry lands"}
    r.update(override)
    return {k: v for k, v in r.items() if v is not None}


def passing_receipt(**override):
    return check_receipt(disposition="ALLOW", failure_code=None, failed_predicate=None, required_evidence_or_repair=None,
                         retry_entrypoint=None, owning_existing_goal=None, next_attempt=None, **override)


class CheckBase(pushtests.AppendBase):
    def ledger_objects(self, result):
        commit = self.tip()
        keys = (result["organization_receipt_key"], result["repository_receipt_source_key"])
        return commit, {commit + ":" + k: _git(self.bare, "show", commit + ":" + k) for k in keys}

    def derive(self, result, generation=319):
        commit, objs = self.ledger_objects(result)
        ref = "%s@%s:%s" % (REF, commit, result["organization_receipt_key"])
        return wi.derive_issue_from_check_receipt(objs, ref, observed_base={"registry_generation": generation, "ledger_head": commit})


class Accept(CheckBase):
    def test_a_failing_check_receipt_round_trips_and_p1_derives_a_native_issue(self):
        receipt = check_receipt()
        result = svc.append_check_receipt(receipt, hb_epoch=EPOCH)
        self.assertEqual(result["disposition"], "ALLOW", result)
        self.assertEqual(result["transition_class"], "SV_CHECK_RECEIPT_APPEND")
        self.assertIs(result["transition_replayed"], False)
        self.assertIs(result["organization_receipt_preserves_repository_receipt"], True)
        self.assertEqual(_git(self.bare, "merge-base", "--is-ancestor", self.seed, REF), b"")
        store = ledger_store.open_store(f"git+{self.bare}#{REF}")
        org = store.get(result["organization_receipt_key"])
        repo = store.get(result["repository_receipt_source_key"])
        self.assertEqual(repo["evidence"], receipt)  # the complete receipt, self-identified by $.evidence.schema
        self.assertEqual(org["boundary_evidence"]["operation"], "sv_check_receipt")
        self.assertEqual(org["repo_receipt_sha256"], repo["receipt_sha256"])
        for row in (org, repo):
            self.assertIs(row["hb_reference"]["derived_from_clock"], False)
            self.assertEqual(row["hb_reference"]["epoch"], EPOCH)
            self.assertTrue(svc._self_verifies(row))
            self.assertTrue(readback.self_verifies(row))
        reader = self.work / "reader.git"
        subprocess.run(["git", "init", "--bare", "-q", str(reader)], check=True)
        subprocess.run(["git", "--git-dir", str(reader), "fetch", "-q", str(self.bare), f"+{REF}:{REF}"], check=True)
        bound = svc.bind_check_receipt(f"git+{reader}#{REF}", result)
        self.assertEqual(bound["disposition"], "ALLOW", bound)
        self.assertEqual(readback.readback(f"git+{reader}#{REF}")["disposition"], "ALLOW")
        issue = self.derive(result)
        self.assertEqual(issue["record_mode"], "NATIVE")
        self.assertEqual(issue["source_receipt"]["receipt_sha256"], result["organization_receipt_sha256"])
        self.assertEqual(issue["disposition"]["failure_code"], "WORKFLOW_SURFACE_UNREGISTERED")
        self.assertTrue(issue["issue_id"].startswith("svi:"))
        self.assertEqual(self.derive(result)["issue_id"], issue["issue_id"], "the issue is derived, so it re-derives identically")

    def test_a_passing_check_receipt_appends_and_derives_no_issue(self):
        result = svc.append_check_receipt(passing_receipt(), hb_epoch=EPOCH)
        self.assertEqual(result["disposition"], "ALLOW", result)
        with self.assertRaises(wi.Refusal):
            self.derive(result)

    def test_the_same_receipt_again_is_the_recorded_pair_and_appends_nothing(self):
        first = svc.append_check_receipt(check_receipt(), hb_epoch=EPOCH)
        tip = self.tip()
        again = svc.append_check_receipt(check_receipt(), hb_epoch=EPOCH)
        self.assertEqual(again["disposition"], "ALLOW", again)
        self.assertIs(again["transition_replayed"], True)
        self.assertEqual(again["organization_receipt_sha256"], first["organization_receipt_sha256"])
        self.assertEqual(self.tip(), tip, "the ledger did not move")

    def test_the_admission_check_alone_reads_no_ledger_and_writes_nothing(self):
        ok = svc.admit_check_receipt(check_receipt(), hb_epoch=EPOCH)
        self.assertEqual(ok["disposition"], "ALLOW", ok)
        self.assertIs(ok["writes"], False)
        self.assertEqual(self.tip(), self.seed)
        self.assert_refused(svc.admit_check_receipt(check_receipt(), hb_epoch=31), "HB_EPOCH_MISMATCH", disposition="DENY")


class Refusals(CheckBase):
    def test_a_receipt_that_is_not_a_valid_check_receipt_is_refused_before_any_write(self):
        for name, receipt in {"not an object": "text", "wrong schema": check_receipt(schema="stegverse.other.v1"),
                              "extra field": check_receipt(unknown_field=1),
                              "missing field": {k: v for k, v in check_receipt().items() if k != "verifier_ref"}}.items():
            result = svc.append_check_receipt(receipt, hb_epoch=EPOCH)
            self.assertEqual(result["failure_code"], "LEDGER_EVIDENCE_NOT_A_CHECK_RECEIPT", (name, result))
            self.assertEqual(self.tip(), self.seed, name)
            self.assertIs(result["consequence_committed"], False, name)
            for field in SIX:
                self.assertTrue(isinstance(result[field], str) and result[field], name + " " + field)

    def test_an_undeclared_command_is_refused_unless_it_is_the_verifiers_own_refusal(self):
        from unittest import mock
        undeclared = {"offline_command": "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED", "command_paths": []}
        with mock.patch.dict(wi.REQUIRED_CHECKS["checks"], {"workflow-surface-registered": undeclared}):
            self.assertFalse(svc.command_declared("workflow-surface-registered"))
            for receipt in (check_receipt(), passing_receipt()):
                result = svc.append_check_receipt(receipt, hb_epoch=EPOCH)
                self.assert_refused(result, "CHECK_COMMAND_UNDECLARED")
                self.assertEqual(result["failed_predicate"], "CHECK_HAS_OFFLINE_COMMAND")
            # the verifier's own FAIL_CLOSED CHECK_COMMAND_UNDECLARED receipt is the one receipt it may append (P1's rule)
            own = check_receipt(failure_code="CHECK_COMMAND_UNDECLARED", failed_predicate="CHECK_HAS_OFFLINE_COMMAND")
            self.assertEqual(svc.append_check_receipt(own, hb_epoch=EPOCH)["disposition"], "ALLOW")

    def test_an_absent_null_or_sentinel_epoch_is_unobserved(self):
        for bad in (None, "", "null", "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"):
            result = svc.append_check_receipt(check_receipt(), hb_epoch=bad)
            self.assert_refused(result, "HB_EPOCH_SOURCE_UNOBSERVED")
            self.assertEqual(result["shared_rule_sha256"], svc.SHARED_RULE_SHA256)
        for bad in (None, "", "null"):
            self.assert_refused(svc.append_check_receipt(check_receipt(hb_epoch=bad), hb_epoch=EPOCH), "HB_EPOCH_SOURCE_UNOBSERVED")

    def test_a_malformed_or_unequal_epoch_is_a_mismatch_and_no_clock_is_read(self):
        for bad in (True, False, 31, 0, -40, "1024", 1024.0, "unknown", 2048):
            self.assert_refused(svc.append_check_receipt(check_receipt(), hb_epoch=bad), "HB_EPOCH_MISMATCH", disposition="DENY")
        self.assert_refused(svc.append_check_receipt(check_receipt(hb_epoch="2048"), hb_epoch=EPOCH), "HB_EPOCH_MISMATCH", disposition="DENY")

    def test_the_vendored_p1_files_are_pinned_and_a_drifted_one_refuses_before_any_write(self):
        self.assertIsNone(svc.P1_PIN_FAILURE)
        import unittest.mock
        with unittest.mock.patch.object(svc, "P1_PIN_FAILURE", "x does not match its manifest digest"):
            self.assert_refused(svc.append_check_receipt(check_receipt(), hb_epoch=EPOCH), "P1_CONTRACT_PINS_UNVERIFIED")

    def test_the_epoch_rule_is_the_pinned_shared_rule(self):
        self.assertEqual(svc.KERNEL_RULE_SHA256, svc.SHARED_RULE_SHA256)
        self.assertEqual(svc.SHARED_RULE_SHA256, pa.SHARED_RULE_SHA256)

    def test_the_writer_reads_no_clock_and_no_network(self):
        text = (ROOT / "resident-runtime" / "sv_check_receipt_append.py").read_text(encoding="utf-8")
        for token in ("import time", "from time", "datetime", "import socket", "urllib", "requests", "http.client", "subprocess",
                      "time.time", "utcnow"):
            self.assertNotIn(token, text, token)


class Routing(unittest.TestCase):
    def test_the_ingest_request_names_the_operation_and_materializes_the_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / "request.json"
            base = {"schema": ing.SCHEMA, "operation": "sv_check_receipt", "check_receipt": check_receipt(), "hb_epoch": EPOCH}
            request.write_text(json.dumps(base), encoding="utf-8")
            read = ing.read_request(request)
            self.assertEqual(read["disposition"], "ALLOW", read)
            self.assertEqual((read["operation"], read["hb_epoch"]), ("sv_check_receipt", EPOCH))
            env_file, out = Path(tmp) / "env", Path(tmp) / "parts"
            self.assertEqual(ing.main(["read", "--request", str(request), "--materialize", str(out), "--github-env", str(env_file)]), 0)
            self.assertEqual(json.loads((out / "check-receipt.json").read_text(encoding="utf-8")), check_receipt())
            self.assertEqual(env_file.read_text(encoding="utf-8").split(), ["INGEST_OPERATION=sv_check_receipt", "HB_EPOCH=1024"])
            for bad, code in (({"check_receipt": "text"}, "LEDGER_EVIDENCE_NOT_A_CHECK_RECEIPT"),
                              ({"hb_epoch": "1024"}, "SV_CHECK_RECEIPT_HB_EPOCH_INVALID"),
                              ({"hb_epoch": True}, "SV_CHECK_RECEIPT_HB_EPOCH_INVALID"),
                              ({"hb_epoch": -1}, "SV_CHECK_RECEIPT_HB_EPOCH_INVALID"),
                              ({"push_receipt": {}}, "INGEST_REQUEST_SCHEMA_MISMATCH"),
                              ({"evaluation_subject": "text"}, "INGEST_REQUEST_SCHEMA_MISMATCH")):
                request.write_text(json.dumps(base | bad), encoding="utf-8")
                refused = ing.read_request(request)
                self.assertEqual(refused["failure_code"], code, refused)
                for field in SIX:
                    self.assertTrue(refused[field], field)

    def test_the_operation_is_declared_with_its_class_and_the_pinned_epoch_rule(self):
        declared = json.loads(OPERATIONS.read_text(encoding="utf-8"))["organization_ledger_writer_operations"]
        entry, = [e for e in declared if e["operation"] == svc.OPERATION_ID]
        self.assertEqual(entry["operation_module"], "resident-runtime/sv_check_receipt_append.py")
        self.assertEqual(entry["transition_class"], svc.TRANSITION_CLASS)
        self.assertEqual(entry["organization_receipt_boundary_operation"], "sv_check_receipt")
        self.assertEqual(entry["epoch_rule_sha256"], svc.SHARED_RULE_SHA256)
        self.assertIs(entry["ingress_capability"], False)
        self.assertIs(entry["addressable_from_the_service_registry"], False)
        self.assertIn("no dispatch input, no schedule, no new workflow", entry["invoked_by"])

    def test_the_writer_runs_it_on_push_only_under_the_shared_lock_and_the_pr_check_appends_nothing(self):
        text = WRITER.read_text(encoding="utf-8")
        head, _ = text.split("\njobs:\n", 1)
        job = text[text.index("\n  ledger-ingest:\n"):]
        self.assertIn("env.INGEST_OPERATION == 'sv_check_receipt'", job)
        self.assertIn("resident-runtime/sv_check_receipt_append.py append", job)
        self.assertIn("resident-runtime/sv_check_receipt_append.py readback", job)
        self.assertIn("resident-runtime/sv_check_receipt_append.py", job.split("py_compile", 1)[1].split("python resident", 1)[0])
        on = head.split("\non:\n", 1)[1].split("\n\n", 1)[0]
        for token in ("workflow_dispatch", "schedule", "cron", "pull_request"):
            self.assertNotIn(token, on, token)
        self.assertEqual(job.count('git push origin "$LEDGER_REF:$LEDGER_REF"'), 1, "one fast-forward publish for every operation")
        self.assertNotIn("--force", text)
        self.assertEqual(sorted(p.name for p in (ROOT / ".github" / "workflows").glob("*.yml")), list(pushtests.WORKFLOW_FILES),
                         "no workflow was added (G17)")
        group, = [g for g in json.loads(CATALOG.read_text(encoding="utf-8"))["groups"]
                  if g["id"] == "organization-ledger-ingest-validation.unit"]
        steps = "\n".join((ROOT / step["run_file"]).read_text(encoding="utf-8") for step in group["steps"])
        self.assertIn("tests.test_sv_check_receipt_append", steps)
        self.assertIn("sv_check_receipt_append.py admit", steps)
        self.assertNotIn("sv_check_receipt_append.py append", steps)

    def test_files_touched_do_not_use_the_forbidden_word(self):
        token = "g" + "rant"
        for path in (ROOT / "resident-runtime" / "sv_check_receipt_append.py", Path(__file__)):
            self.assertNotIn(token, path.read_text(encoding="utf-8").lower().replace(token + "s nothing", ""), path.name)


if __name__ == "__main__":
    unittest.main()
