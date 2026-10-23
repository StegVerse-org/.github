"""MERGE_ADMISSION_RECORD: the TVC ALLOW record on the organization ledger, found by the B2 checkpoint.

Temp ledgers are the merge-transfer fixtures' pinned ledger tip (tests/test_merge_transfer.Ledger), never the
published ref. The record is TVC sv_merge_admission's own output on a synthetic observation (see
tests/fixtures/merge-admission-record/README.md): not an admission of the fixture PR.
"""
from __future__ import annotations

import base64
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = load("test_merge_transfer_for_admission_record", "tests/test_merge_transfer.py")
b2 = load("merge_transfer_admission_for_record_test", "resident-runtime/merge_transfer_admission.py")
ar = load("merge_admission_record_append_under_test", "resident-runtime/merge_admission_record_append.py")
mt = ar.mt
Ledger, FIXTURES = base.Ledger, base.FIXTURES
RECORD = json.loads((ROOT / "tests/fixtures/merge-admission-record/tvc-record-synthetic-pr200.json").read_text())
SIX = ar.SIX_FIELDS


def fixture() -> dict:
    return json.loads(FIXTURES[0].read_text())


def reseal(rec: dict) -> dict:
    body = {k: v for k, v in rec.items() if k != "record_sha256"}
    return {**body, "record_sha256": mt.sha(body)}


class Base(unittest.TestCase):
    def setUp(self):
        self.f = fixture()
        self.ledger = Ledger(self.f)
        self.addCleanup(self.ledger.close)

    def assert_refused(self, out, code, disposition="FAIL_CLOSED"):
        self.assertEqual((out["disposition"], out["failure_code"]), (disposition, code), out)
        for k in SIX:
            self.assertTrue(out.get(k), k)
        self.assertIs(out["consequence_committed"], False)
        self.assertEqual(out["lowest_supported_mode"], "E0")


class AppendAndCheckpoint(Base):
    def test_the_fixture_is_the_contracted_record_for_the_fixture_merge(self):
        self.assertTrue(ar.sealed_record(RECORD))
        self.assertEqual(sorted(RECORD), sorted(ar.contract()["record_fields"]))
        self.assertEqual((RECORD["repository"], RECORD["head_sha"]), (self.f["repository"], self.f["commit"]["parents"][-1]))

    def test_append_then_the_b2_checkpoint_finds_it_at_the_merged_head(self):
        before = self.ledger.files()
        out = ar.append_admission_record(RECORD)
        self.assertEqual((out["disposition"], out["appended"]), ("ALLOW", True), out)
        key = mt.store_module().receipt_key
        org = self.ledger.read(key(out["organization_receipt_sha256"]))
        rep = self.ledger.read(key(out["repository_receipt_sha256"]), repo=True)
        self.assertTrue(mt.sealed(org) and mt.sealed(rep))
        b = mt._boundary(org)
        self.assertEqual((b["operation"], b["admission_record"], b["record_sha256"]), ("MERGE_ADMISSION_RECORD", RECORD, RECORD["record_sha256"]))
        self.assertEqual(rep["evidence"]["admission_record"], RECORD)
        for name, data in before.items():
            if not name.endswith("HEAD.json"):
                self.assertEqual(self.ledger.files()[name], data, name)
        self.assertEqual(ar.verify_admission_record(RECORD["record_sha256"])["disposition"], "ALLOW")
        cp = b2.admission_checkpoint(self.f["repository"], self.f["commit"], mt.org_store())
        self.assertEqual((cp["disposition"], cp["admission_record_ref"]), ("ALLOW", RECORD["record_sha256"]), cp)

    def test_the_merge_transfer_receipt_then_carries_allow(self):
        ar.append_admission_record(RECORD)
        result = b2.append(self.f["commit"])
        self.assertEqual(result["disposition"], "ALLOW", result)
        self.assertEqual(result["admission_checkpoint"]["disposition"], "ALLOW")
        org = self.ledger.read(mt.store_module().receipt_key(result["organization_receipt_sha256"]))
        self.assertEqual(mt._boundary(org)["admission_record_ref"], RECORD["record_sha256"])
        self.assertEqual(b2.recorded_checkpoint(self.f["repository"], self.f["commit"]["merge_commit"])["disposition"], "ALLOW")

    def test_replay_answers_from_the_ledger(self):
        first = ar.append_admission_record(RECORD)
        after = self.ledger.files()
        again = ar.append_admission_record(copy.deepcopy(RECORD))
        self.assertEqual((again["disposition"], again["replayed"], again["appended"]), ("ALLOW", True, False))
        self.assertEqual(again["organization_receipt_sha256"], first["organization_receipt_sha256"])
        self.assertEqual(self.ledger.files(), after)


class Refusals(Base):
    def unchanged(self, out, code, disposition="FAIL_CLOSED"):
        before = self.ledger.files()
        self.assert_refused(out, code, disposition)
        self.assertEqual(self.ledger.files(), before)

    def test_not_delivered(self):
        self.unchanged(ar.append_admission_record(None), "ADMISSION_RECORD_NOT_DELIVERED")
        self.unchanged(ar.deliver(None), "ADMISSION_RECORD_NOT_DELIVERED")
        self.assertEqual(ar.main(["append"]), 1)

    def test_tampered_or_wrong_schema(self):
        self.unchanged(ar.append_admission_record({**RECORD, "head_sha": "a" * 40}), "ADMISSION_RECORD_SEAL_INVALID", "DENY")
        self.unchanged(ar.append_admission_record(reseal({**RECORD, "schema": "stegverse.merge-admission-record/v9"})),
                       "ADMISSION_RECORD_SEAL_INVALID", "DENY")

    def test_fields_not_the_contract(self):
        rec = dict(RECORD); rec.pop("change_digest")
        self.unchanged(ar.append_admission_record(reseal(rec)), "ADMISSION_RECORD_INVALID")

    def test_not_allow(self):
        rec = copy.deepcopy(RECORD); rec["predicates"][3]["disposition"] = "DENY"
        self.unchanged(ar.append_admission_record(reseal(rec)), "ADMISSION_RECORD_NOT_ALLOW", "DENY")
        self.unchanged(ar.append_admission_record(reseal({**RECORD, "predicates": []})), "ADMISSION_RECORD_NOT_ALLOW", "DENY")

    def test_other_repository(self):
        self.unchanged(ar.append_admission_record(reseal({**RECORD, "repository": "SV-011/.github"})),
                       "ADMISSION_RECORD_REPOSITORY_MISMATCH", "DENY")

    def test_unpinned_manifest(self):
        self.unchanged(ar.append_admission_record(reseal({**RECORD, "manifest_sha256": "sha256:" + "1" * 64})),
                       "ADMISSION_MANIFEST_NOT_PINNED")

    def test_epoch_not_the_ledger_head(self):
        rec = copy.deepcopy(RECORD); rec["hb_epoch"] = rec["ledger_head"]["hb_epoch"] = "32"
        self.unchanged(ar.append_admission_record(reseal(rec)), "ADMISSION_RECORD_EPOCH_NOT_LEDGER_HEAD")
        rec = copy.deepcopy(RECORD); rec["ledger_head"]["hb_epoch"] = "32"
        self.unchanged(ar.append_admission_record(reseal(rec)), "ADMISSION_RECORD_EPOCH_NOT_LEDGER_HEAD")

    def test_unledgered_verify(self):
        out = ar.verify_admission_record(RECORD["record_sha256"])
        self.assert_refused(out, "ADMISSION_RECORD_NOT_LEDGERED")

    def test_without_the_record_b2_stays_fail_closed(self):
        cp = b2.admission_checkpoint(self.f["repository"], self.f["commit"], mt.org_store())
        self.assertEqual((cp["disposition"], cp["failure_code"]), ("FAIL_CLOSED", b2.NOT_ADMITTED))


class EphemeralSigner:
    """A throwaway ed25519 key made in a temp dir for this test run (never committed, not a credential)."""
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(t / "k.pem")], check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-in", str(t / "k.pem"), "-pubout", "-out", str(t / "p.pem")], check=True, capture_output=True)
        self.pem = (t / "p.pem").read_text()
        self.delivery = {"signer_public_key_pem": self.pem, "signer_key_id": "test-ephemeral"}

    def sign(self, payload: dict) -> str:
        t = Path(self.tmp.name)
        (t / "m").write_bytes(ar.canonical(payload))
        subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", str(t / "k.pem"), "-rawin", "-in", str(t / "m"), "-out", str(t / "s")],
                       check=True, capture_output=True)
        return base64.b64encode((t / "s").read_bytes()).decode()

    def envelope(self, record: dict, **over) -> dict:
        payload = ar.signed_payload(record)
        env = {"schema": ar.DELIVERY_SCHEMA, "record": record, "signed_payload": payload, "signer_key_id": "test-ephemeral",
               "signature": self.sign(payload)}
        env.update(over)
        return env


class Delivery(Base):
    """A2: the TVC-signed delivery envelope, verified against the pinned public key before the record path."""
    @classmethod
    def setUpClass(cls):
        cls.signer = EphemeralSigner()

    @classmethod
    def tearDownClass(cls):
        cls.signer.tmp.cleanup()

    def unchanged(self, out, code, disposition="FAIL_CLOSED"):
        before = self.ledger.files()
        self.assert_refused(out, code, disposition)
        self.assertEqual(self.ledger.files(), before)

    def test_signed_delivery_appends_and_b2_finds_it(self):
        out = ar.deliver(self.signer.envelope(RECORD), delivery=self.signer.delivery)
        self.assertEqual((out["disposition"], out["appended"]), ("ALLOW", True), out)
        cp = b2.admission_checkpoint(self.f["repository"], self.f["commit"], mt.org_store())
        self.assertEqual((cp["disposition"], cp["admission_record_ref"]), ("ALLOW", RECORD["record_sha256"]), cp)

    def test_the_committed_contract_pins_no_key_so_delivery_is_fail_closed(self):
        d = ar.contract()["delivery"]
        self.assertIsNone(d["signer_public_key_pem"]); self.assertIsNone(d["signer_key_id"])
        out = ar.deliver(self.signer.envelope(RECORD))
        self.unchanged(out, "ADMISSION_RECORD_SIGNER_KEY_NOT_PINNED")
        self.assertIn("issuance receipt", out["required_evidence_or_repair"])
        self.assertNotIn("PRIVATE KEY", json.dumps(ar.contract()))

    def test_wrong_key_tampered_payload_or_signature_is_deny(self):
        other = EphemeralSigner(); self.addCleanup(other.tmp.cleanup)
        self.unchanged(ar.deliver(other.envelope(RECORD), delivery=self.signer.delivery), "ADMISSION_RECORD_DELIVERY_SIGNATURE_INVALID", "DENY")
        env = self.signer.envelope(RECORD); env["record"] = reseal({**RECORD, "pull_number": 201})
        self.unchanged(ar.deliver(env, delivery=self.signer.delivery), "ADMISSION_RECORD_DELIVERY_SIGNATURE_INVALID", "DENY")
        env = self.signer.envelope(RECORD, signature=base64.b64encode(b"\0" * 64).decode())
        self.unchanged(ar.deliver(env, delivery=self.signer.delivery), "ADMISSION_RECORD_DELIVERY_SIGNATURE_INVALID", "DENY")
        env = self.signer.envelope(RECORD, signer_key_id="someone-else")
        self.unchanged(ar.deliver(env, delivery=self.signer.delivery), "ADMISSION_RECORD_DELIVERY_SIGNATURE_INVALID", "DENY")

    def test_malformed_envelope(self):
        self.unchanged(ar.deliver(RECORD, delivery=self.signer.delivery), "ADMISSION_RECORD_DELIVERY_ENVELOPE_INVALID")
        self.unchanged(ar.deliver(self.signer.envelope(RECORD, schema="x"), delivery=self.signer.delivery),
                       "ADMISSION_RECORD_DELIVERY_ENVELOPE_INVALID")

    def test_signed_but_record_refused_is_still_refused(self):
        env = self.signer.envelope(reseal({**RECORD, "manifest_sha256": "sha256:" + "1" * 64}))
        self.unchanged(ar.deliver(env, delivery=self.signer.delivery), "ADMISSION_MANIFEST_NOT_PINNED")


class Contract(unittest.TestCase):
    def test_every_predicate_declares_its_ladder(self):
        for pid, p in ar.PREDICATES.items():
            self.assertEqual(p["lowest_supported_mode"], "E0", pid)
            for rung in ("E3", "E2", "E1", "E0", "llm_inputs"):
                self.assertTrue(p.get(rung), (pid, rung))

    def test_the_consumer_reads_this_operation(self):
        self.assertEqual(ar.OPERATION, b2.ADMISSION_RECORD_OPERATION)
        self.assertTrue(ar.contract()["record_schema"].startswith(b2.ADMISSION_RECORD_SCHEMA_PREFIX))

    def test_no_writer_workflow_until_delivery_exists(self):
        for wf in (ROOT / ".github/workflows").glob("*.yml"):
            text = wf.read_text()
            self.assertNotIn("merge_admission_record_append.py append", text, wf.name)

    def test_the_contract_pins_the_v2_2_manifest(self):
        self.assertEqual(ar.contract()["admitted_manifest_sha256"],
                         "sha256:9f0e58ec71438b65fae7a739530ce11fd59eeca04a3e56b8243432fb24bb7217")
        self.assertEqual(RECORD["manifest_sha256"], ar.contract()["admitted_manifest_sha256"])


if __name__ == "__main__":
    unittest.main()
