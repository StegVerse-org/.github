"""B2: the admission checkpoint in the main-merge transfer writer step.

Same temp ledgers as tests/test_merge_transfer.py (the pinned ledger tip). Every
merge still gets its receipts; the organization receipt's boundary also
carries admission_record_ref, merge_kind and admission_checkpoint, which is
ALLOW only when a sealed merge-admission record names the merged head.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

from tests.workflow_surface import catalog_groups, step_bodies, writer_job

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = load("test_merge_transfer_for_admission", "tests/test_merge_transfer.py")
b2 = load("merge_transfer_admission_under_test", "resident-runtime/merge_transfer_admission.py")
mt = b2.mt
Ledger, FIXTURES = base.Ledger, base.FIXTURES
# G17: the writer is job merge-transfer of organization-ledger-writer.yml and the
# validation workflow's jobs are catalog groups run by validation-dispatcher.yml.
VALIDATION = "organization-ledger-merge-transfer-validation.yml"


def fixture() -> dict:
    return json.loads(FIXTURES[0].read_text())


def record(f: dict, head: str | None = None, pull: int | None = None) -> dict:
    body = {"schema": "stegverse.merge-admission-record/v2.1", "repository": f["repository"],
            "pull_number": pull if pull is not None else int(mt.PR_SUBJECT.fullmatch(f["commit"]["subject"]).group(1)),
            "head_sha": head or f["commit"]["parents"][-1], "disposition": "ALLOW"}
    return {**body, "record_sha256": mt.sha(body)}


class MemoryOrg:
    """An organization chain in memory: HEAD -> receipts linked by previous_receipt_sha256."""

    def __init__(self, records: list[dict], seal: bool = True):
        self.data, previous = {}, None
        for rec in records:
            body = {"previous_receipt_sha256": previous,
                    "boundary_evidence": {"operation": b2.ADMISSION_RECORD_OPERATION, "admission_record": rec}}
            receipt = {**body, "receipt_sha256": mt.sha(body) if seal else "sha256:" + "0" * 64}
            self.data[mt.store_module().receipt_key(receipt["receipt_sha256"])] = receipt
            previous = receipt["receipt_sha256"]
        self.data[mt.store_module().HEAD_KEY] = {"receipt_sha256": previous}

    def get(self, key):
        return self.data[key]


class Checkpoint(unittest.TestCase):
    def setUp(self):
        self.f = fixture()

    def check(self, org, facts=None):
        return b2.admission_checkpoint(self.f["repository"], facts or self.f["commit"], org)

    def assert_fail_closed(self, cp):
        self.assertEqual(cp["disposition"], "FAIL_CLOSED")
        self.assertEqual(cp["failure_code"], "MERGED_HEAD_IS_NOT_THE_ADMITTED_HEAD")
        for field in mt.SIX_FIELDS:
            self.assertTrue(cp[field], field)
        self.assertIsNone(cp["admission_record_ref"])

    def test_a_sealed_record_at_the_merged_head_is_allow(self):
        rec = record(self.f)
        cp = self.check(MemoryOrg([rec]))
        self.assertEqual((cp["disposition"], cp["admission_record_ref"], cp["merge_kind"]),
                         ("ALLOW", rec["record_sha256"], "MERGE_COMMIT"))
        self.assertEqual(cp["merged_head"], self.f["commit"]["parents"][-1])

    def test_no_record_is_fail_closed_with_six_fields(self):
        self.assert_fail_closed(self.check(MemoryOrg([])))

    def test_a_record_at_another_head_is_fail_closed_and_names_it(self):
        cp = self.check(MemoryOrg([record(self.f, head="a" * 40)]))
        self.assert_fail_closed(cp)
        self.assertIn("a" * 40, cp["detail"])

    def test_a_record_for_another_pr_or_unsealed_does_not_count(self):
        self.assert_fail_closed(self.check(MemoryOrg([record(self.f, pull=999999)])))
        forged = record(self.f)
        forged["head_sha"] = "b" * 40  # record_sha256 no longer matches
        self.assert_fail_closed(self.check(MemoryOrg([forged])))
        self.assert_fail_closed(self.check(MemoryOrg([record(self.f)], seal=False)))

    def test_a_direct_push_carries_no_admitted_head(self):
        facts = {**self.f["commit"], "parents": self.f["commit"]["parents"][:1], "subject": "direct push"}
        cp = self.check(MemoryOrg([record(self.f)]), facts)
        self.assert_fail_closed(cp)
        self.assertEqual((cp["merge_kind"], cp["merged_head"]), ("DIRECT_PUSH", facts["merge_commit"]))


class AppendWithCheckpoint(unittest.TestCase):
    def test_every_merge_gets_its_receipts_and_the_boundary_carries_the_checkpoint(self):
        for path in FIXTURES:
            f = json.loads(path.read_text())
            ledger = Ledger(f)
            try:
                before = ledger.files()
                result = b2.append(f["commit"])
                self.assertEqual(result["disposition"], "ALLOW", result)  # the transfer is recorded
                cp = result["admission_checkpoint"]
                self.assertEqual(cp["disposition"], "FAIL_CLOSED")  # no admission record is ledgered at the tip
                self.assertEqual(cp["failure_code"], b2.NOT_ADMITTED)
                key = mt.store_module().receipt_key
                org = ledger.read(key(result["organization_receipt_sha256"]))
                rep = ledger.read(key(result["repository_receipt_sha256"]), repo=True)
                self.assertTrue(mt.sealed(org) and mt.sealed(rep))
                self.assertEqual(rep, f["expected_repository_receipt"])  # the evidence is merge_transfer's, unchanged
                boundary = mt._boundary(org)
                self.assertEqual(boundary["merge_commit"], f["commit"]["merge_commit"])
                self.assertIsNone(boundary["admission_record_ref"])
                self.assertEqual(boundary["merge_kind"], "MERGE_COMMIT")
                self.assertEqual(boundary["admission_checkpoint"]["disposition"], "FAIL_CLOSED")
                for field in mt.SIX_FIELDS:
                    self.assertEqual(boundary["admission_checkpoint"][field], cp[field])
                after = ledger.files()
                for name, data in before.items():
                    if not name.endswith("HEAD.json"):
                        self.assertEqual(after[name], data, name)
                verified = mt.verify_merge_transfer(f["repository"], f["commit"]["merge_commit"])
                self.assertEqual((verified["disposition"], verified["transfer"]), ("ALLOW", "VERIFIED"))
                readback = b2.recorded_checkpoint(f["repository"], f["commit"]["merge_commit"])
                self.assertEqual(readback["source"], "ORGANIZATION_RECEIPT")
                self.assertEqual(readback["failure_code"], b2.NOT_ADMITTED)
                replay = b2.append(f["commit"])
                self.assertTrue(replay["replayed"])
                self.assertEqual(replay["organization_receipt_sha256"], result["organization_receipt_sha256"])
                self.assertEqual(ledger.files(), after)
            finally:
                ledger.close()

    def test_a_merge_ledgered_before_b2_replays_without_collision(self):
        f = fixture()
        ledger = Ledger(f)
        try:
            old = mt.append_merge_transfer(f["commit"])
            self.assertEqual(old, f["append_result"])
            after = ledger.files()
            replay = b2.append(f["commit"])
            self.assertTrue(replay["replayed"])
            self.assertEqual(replay["organization_receipt_sha256"], old["organization_receipt_sha256"])
            self.assertEqual(replay["admission_checkpoint"]["source"], "RECOMPUTED_RECEIPT_PREDATES_B2")
            self.assertEqual(replay["admission_checkpoint"]["disposition"], "FAIL_CLOSED")
            self.assertEqual(ledger.files(), after)
        finally:
            ledger.close()

    def test_invalid_facts_are_refused_before_any_read(self):
        bad = {**fixture()["commit"], "parents": []}
        self.assertEqual(b2.append(bad)["failure_code"], mt.FACTS_INVALID)

    def test_the_checkpoint_cli_fails_on_fail_closed(self):
        f = fixture()
        ledger = Ledger(f)
        try:
            b2.append(f["commit"])
            self.assertEqual(b2.main(["checkpoint", "--commit", f["commit"]["merge_commit"]]), 1)
        finally:
            ledger.close()


class Pins(unittest.TestCase):
    def test_merge_transfer_py_is_unchanged(self):
        digest = hashlib.sha256((ROOT / "resident-runtime/merge_transfer.py").read_bytes()).hexdigest()
        self.assertEqual(digest, "032ed727358d56f33369b35e6cc50d65f6af5dc0035f0b69fe7cddb3f4f4e20e")

    def test_the_writer_appends_through_b2_and_checks_after_publish(self):
        """G17: the writer is job merge-transfer of organization-ledger-writer.yml; same assertions on that job."""
        text = writer_job("merge-transfer")
        self.assertIn("merge_transfer_admission.py append", text)
        self.assertNotIn("merge_transfer.py append", text)
        self.assertLess(text.index("git push origin"), text.index("merge_transfer_admission.py checkpoint"))
        self.assertLess(text.index("merge_transfer.py verify"), text.index("merge_transfer_admission.py checkpoint"))
        on = text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(on.strip(), "push:\n    branches: [main]")
        self.assertNotIn("secrets.", text)

    def test_the_validation_workflow_runs_b2(self):
        """G17: the validation workflow's jobs are catalog groups; B2 runs in their step bodies."""
        text = "\n".join(step_bodies(g) for g in catalog_groups(VALIDATION))
        self.assertIn("resident-runtime/merge_transfer_admission.py", text)
        self.assertIn("tests.test_merge_transfer_admission", text)


if __name__ == "__main__":
    unittest.main()
