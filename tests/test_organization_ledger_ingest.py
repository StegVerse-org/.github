"""The committed organization ledger ingest request, appended by the governed writer on push.

resident-runtime/organization_ledger_ingest.py admits a test receipt sealed by
its producer's CI (StegVerse-Labs/TVC's conformance receipt, then StegVerse-Labs/repo-standards'
org owner-drift receipt) and appends it
through aggregate_repo_transition.append, at the epoch the ledger head carries,
retaining the receipt unchanged; the writer's ledger-ingest job runs it when
.stegverse/organization-ledger-ingest/** changes on main. These tests run
against temporary bare git repositories only: no clock, no network.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
REQUEST = ROOT / ".stegverse/organization-ledger-ingest/request.json"  # whichever request is committed now
# The sealed_test_receipt request of run 40145286437 as committed by #246 and kept here, so these tests keep pinning
# that receipt while another operation's request (sv_push_receipt) is the one committed.
SEALED_REQUEST = ROOT / "tests/fixtures/organization-ledger-ingest/sealed-request.json"
WRITER = ROOT / ".github/workflows/organization-ledger-writer.yml"
REF = "refs/stegverse/organization-ledger"
DIGEST = "sha256:6feec3f5634e2bea4a586cb427d4f1ff9c1a08f4386834e60ff0cc379bc4f60b"
TVC_DIGEST = "sha256:2c39c6088e92988d722e139e3b5085f377478b0711b0e3c2a14ce3079d23f8a6"  # appended by #246, ledger tip 9fc1406c
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
       "owning_existing_goal", "next_attempt")
EPOCH = 4400


def _load(name, relative):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ing = _load("organization_ledger_ingest", "resident-runtime/organization_ledger_ingest.py")
org = ing._module("aggregate_repo_transition", "resident-runtime/aggregate_repo_transition.py")
ledger_store = ing._module("ledger_store", "resident-runtime/ledger_store.py")
writer_plan = _load("writer_plan_for_ingest", "tools/tasks/writer_plan.py")


def committed():
    return json.loads(SEALED_REQUEST.read_text(encoding="utf-8"))


def seal(body):
    body = {k: v for k, v in body.items() if k != "receipt_sha256"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return {**body, "receipt_sha256": "sha256:" + hashlib.sha256(text).hexdigest()}


def seed_receipt():
    body = {"schema": "stegverse.repo-transition-receipt/v1", "repository": "StegVerse-org/.github",
            "transition_id": "ingest-test-genesis"}
    return {**body, "receipt_sha256": org.sha(body)}


class Admission(unittest.TestCase):
    def setUp(self):
        self.request = committed()
        self.receipt, self.provenance = self.request["receipt"], self.request["provenance"]

    def refused(self, result, code):
        self.assertEqual(result["disposition"], "FAIL_CLOSED", result)
        self.assertEqual(result["failure_code"], code, result)
        for field in SIX:
            self.assertTrue(result.get(field), field)
        self.assertIs(result["consequence_committed"], False)

    def test_the_committed_request_is_the_repo_standards_owner_drift_receipt_of_run_40145286437(self):
        read = ing.read_request(SEALED_REQUEST)
        self.assertEqual(read["disposition"], "ALLOW")
        self.assertEqual(self.receipt["receipt_sha256"], DIGEST)
        self.assertTrue(ing.seal_verifies(self.receipt))
        self.assertEqual(self.provenance["run_id"], 40145286437)
        self.assertEqual(self.receipt["receipt_kind"], "REPO_STANDARDS_ORG_OWNER_DRIFT_TEST_RECEIPT")
        self.assertEqual(self.receipt["consumed_source"]["repository"], "StegVerse-org/.github")
        self.assertEqual(self.receipt["consumed_source"]["commit"][:8], "4033813e")
        self.assertIsNone(ing.admit_sealed(self.receipt, self.provenance, ledger_repository="StegVerse-org/.github"))

    def test_another_organizations_ledger_is_refused(self):
        self.refused(ing.admit_sealed(self.receipt, self.provenance, ledger_repository="StegVerse-Labs/.github"),
                     "SEALED_RECEIPT_TARGETS_ANOTHER_LEDGER")

    def test_a_broken_seal_an_unaccepted_kind_a_skip_and_a_wrong_provenance_are_refused(self):
        tampered = {**self.receipt, "suite": "OTHER"}
        self.refused(ing.admit_sealed(tampered, self.provenance, ledger_repository="StegVerse-org/.github"),
                     "SEALED_RECEIPT_SEAL_MISMATCH")
        self.refused(ing.admit_sealed(seal(tampered), self.provenance, ledger_repository="StegVerse-org/.github"),
                     "SEALED_RECEIPT_NOT_ACCEPTED")
        skipped = seal({**self.receipt, "counts": {**self.receipt["counts"], "skipped": 1}})
        self.refused(ing.admit_sealed(skipped, self.provenance, ledger_repository="StegVerse-org/.github"),
                     "SEALED_RECEIPT_TESTS_NOT_ZERO_SKIPPED")
        denied = seal({**self.receipt, "disposition": "DENY"})
        self.refused(ing.admit_sealed(denied, self.provenance, ledger_repository="StegVerse-org/.github"),
                     "SEALED_RECEIPT_NOT_ALLOW")
        self.refused(ing.admit_sealed(self.receipt, {**self.provenance, "run_id": "40145286437"},
                                      ledger_repository="StegVerse-org/.github"), "SEALED_RECEIPT_PROVENANCE_MISMATCH")
        self.refused(ing.admit_sealed(self.receipt, self.provenance, ledger_repository="StegVerse-org/.github",
                                      accepted=ing.load_accepted(ROOT / "absent.json")),
                     "SEALED_RECEIPT_ACCEPTANCE_UNDECLARED")

    def test_malformed_requests_fail_closed(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / "request.json"
            self.refused(ing.read_request(path), "INGEST_REQUEST_ABSENT")
            path.write_text("{", encoding="utf-8")
            self.refused(ing.read_request(path), "INGEST_REQUEST_UNREADABLE")
            for bad in ({**self.request, "operation": "sv_check_receipt"}, {**self.request, "receipt": []},
                        {**self.request, "extra": 1}, {k: v for k, v in self.request.items() if k != "provenance"}):
                path.write_text(json.dumps(bad), encoding="utf-8")
                self.refused(ing.read_request(path), "INGEST_REQUEST_SCHEMA_MISMATCH")

    def test_the_ingest_writer_binds_a_sealed_receipt_by_its_own_seal(self):
        writer = ing.writer()
        for source in (ing.sealed_source(self.receipt), writer.verify_source(self.receipt)):
            self.assertEqual(source["source_transition_sha256"], DIGEST)
            self.assertIsNone(source["repo_receipt_sha256"])
        with self.assertRaisesRegex(SystemExit, "sealed test receipt hash mismatch"):
            writer.verify_source({**self.receipt, "suite": "OTHER"})
        # Other schemas still reach the contract's own gate, and the shared writer is unchanged.
        with self.assertRaisesRegex(SystemExit, "schema mismatch"):
            writer.verify_source({**self.receipt, "schema": "stegverse.other/v1"})
        with self.assertRaisesRegex(SystemExit, "schema mismatch"):
            org.verify_source(self.receipt)
        self.assertNotIn(ing.SEALED_TEST_RECEIPT_SCHEMA, org.C["consumes"])


class SealedAppend(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.repo = Path(self._dir.name) / "ledger.git"
        self.location = "git+%s#%s" % (self.repo, REF)
        env = {k: v for k, v in os.environ.items() if not k.startswith("STEGVERSE_")}
        env["STEGVERSE_ORG_LEDGER_ROOT"] = self.location
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.request = committed()

    def store(self):
        return org.open_store(org.ledger_root())

    def seed(self):
        store = self.store()
        store.initialize()
        return org.append(seed_receipt(), "REPO_STATE_PROPAGATION", org.GENESIS, "sha256:" + "b" * 64, {},
                          "NONE", hb_epoch=EPOCH, store=store)

    def append(self):
        return ing.append_sealed(self.request["receipt"], self.request["provenance"],
                                 ledger_repository="StegVerse-org/.github")

    def test_append_retains_the_exact_receipt_at_the_head_epoch_reads_back_and_a_retry_mints_nothing(self):
        genesis = self.seed()
        out = self.append()
        self.assertEqual(out["disposition"], "ALLOW", out)
        self.assertEqual((out["receipt_sha256"], out["hb_epoch"], out["transition_replayed"]), (DIGEST, EPOCH, False))
        store = self.store()
        self.assertEqual(store.get(ledger_store.source_key(DIGEST)), self.request["receipt"])
        row = store.get(ledger_store.receipt_key(out["organization_receipt_sha256"]))
        self.assertEqual(row["previous_receipt_sha256"], genesis["receipt_sha256"])
        self.assertEqual(row["org_transition_class"], ing.SEALED_CLASS)
        self.assertEqual(row["boundary_evidence"]["producer_run_id"], 40145286437)
        back = ing.readback_sealed(self.location, self.request["receipt"])
        self.assertEqual(back["disposition"], "ALLOW", back)
        self.assertEqual(back["chain_length"], 2)
        again = self.append()
        self.assertEqual((again["organization_receipt_sha256"], again["transition_replayed"]),
                         (out["organization_receipt_sha256"], True))
        self.assertEqual(ing.readback_sealed(self.location, self.request["receipt"])["chain_length"], 2)

    def test_nothing_is_written_without_a_head_epoch_or_a_supplied_ledger(self):
        self.store().initialize()
        out = self.append()
        self.assertEqual(out["disposition"], "FAIL_CLOSED", out)
        self.assertIs(out["consequence_committed"], False)
        for field in SIX:
            self.assertTrue(out.get(field), field)
        self.assertIsNone(self.store().get(ledger_store.HEAD_KEY))
        self.assertEqual(ing.readback_sealed(self.location, self.request["receipt"])["failure_code"],
                         "LEDGER_READBACK_UNAVAILABLE")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.append()["failure_code"], "ORGANIZATION_LEDGER_UNAVAILABLE")

    def test_a_refused_receipt_writes_nothing(self):
        genesis = self.seed()
        out = ing.append_sealed(self.request["receipt"], self.request["provenance"],
                                ledger_repository="StegVerse-Labs/.github")
        self.assertEqual(out["failure_code"], "SEALED_RECEIPT_TARGETS_ANOTHER_LEDGER")
        self.assertEqual(self.store().get(ledger_store.HEAD_KEY)["receipt_sha256"], genesis["receipt_sha256"])


class Trigger(unittest.TestCase):
    def test_a_pushed_ingest_request_selects_the_ledger_ingest_writer_job_only(self):
        jobs = json.loads((ROOT / "control/workflow-surface-registry.json").read_text())["writer_jobs"]
        got = writer_plan.select([".stegverse/organization-ledger-ingest/request.json"], jobs)
        self.assertEqual(got, {"ledger-transition": False, "governance-return": False, "ledger-ingest": True})

    def test_the_writer_job_appends_on_push_only_through_the_ingest_module(self):
        text = WRITER.read_text(encoding="utf-8")
        job = text[text.index("\n  ledger-ingest:\n"):]
        self.assertNotIn("\n  workflow_dispatch", text.split("\njobs:")[0])
        self.assertNotIn("workflow_dispatch", job)
        self.assertIn("needs.plan.outputs.ledger-ingest == 'true'", job)
        self.assertIn("organization_ledger_ingest.py append-sealed", job)
        self.assertIn("organization_ledger_ingest.py readback-sealed", job)
        self.assertIn('git push origin "$LEDGER_REF:$LEDGER_REF"', job)
        self.assertNotIn("update-ref", job)

    def test_the_committed_request_is_one_of_the_declared_operations(self):
        declared = {e["operation"] for e in json.loads((ROOT / ".stegverse/organization-ledger-ingest/operations.json")
                                                       .read_text(encoding="utf-8"))["organization_ledger_writer_operations"]}
        self.assertEqual(declared, {ing.SEALED, ing.SV_PUSH, ing.SV_ADMIT})
        self.assertEqual(set(ing.FIELDS), declared)
        read = ing.read_request(REQUEST)
        self.assertEqual(read["disposition"], "ALLOW", read)
        self.assertIn(read["operation"], declared)

    def test_the_sealed_commands_refuse_a_push_receipt_request(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / "request.json"
            path.write_text(json.dumps({"schema": ing.SCHEMA, "operation": ing.SV_PUSH, "push_receipt": {"schema": "x"},
                                        "hb_epoch": 1024}), encoding="utf-8")
            done = subprocess.run([sys.executable, str(ROOT / "resident-runtime/organization_ledger_ingest.py"),
                                   "admit-sealed", "--request", str(path), "--ledger-repository", "StegVerse-org/.github"],
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 1)
            self.assertEqual(json.loads(done.stdout)["failure_code"], "INGEST_OPERATION_NOT_SEALED_TEST_RECEIPT")

    def test_the_cli_admits_the_committed_request_and_refuses_another_ledger(self):
        run = lambda repo: subprocess.run([sys.executable, str(ROOT / "resident-runtime/organization_ledger_ingest.py"),
                                           "admit-sealed", "--request", str(SEALED_REQUEST), "--ledger-repository", repo],
                                          capture_output=True, text=True)
        self.assertEqual(run("StegVerse-org/.github").returncode, 0)
        self.assertEqual(run("StegVerse-Labs/.github").returncode, 1)


if __name__ == "__main__":
    unittest.main()
