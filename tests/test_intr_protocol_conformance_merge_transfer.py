"""InTr protocol v1: MAIN_MERGE_TRANSFER_RECEIPT_LEDGERED, the main-merge transfer dimension.

The offline check in org-runtime/intr_protocol.py is the contract of
resident-runtime/merge_transfer.py verify (StegVerse-org/.github#202,
SV-011/.github#15), pinned by sha256 in data/intr-protocol/v1/protocol.json.
It reads supplied readbacks only: no ledger, git, clock or network.

The expected receipts are the ones #202 and SV-011#15 compute in a temporary
copy of each ledger tip; they are not ledgered and are not authentic receipts.
The real state (manifest.json) is FAIL_CLOSED for both merges.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATIONS = ROOT / "tests" / "fixtures" / "intr-protocol" / "destinations" / "manifest.json"
FIXTURES = ROOT / "tests" / "fixtures" / "intr-protocol" / "merge-transfer"
MANIFEST = FIXTURES / "manifest.json"
EXPECTED = FIXTURES / "expected-receipts.json"
VERIFIER = ROOT / "resident-runtime" / "merge_transfer.py"
spec = importlib.util.spec_from_file_location("intr_protocol_mt", ROOT / "org-runtime" / "intr_protocol.py")
intr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(intr)

SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair",
       "retry_entrypoint", "owning_existing_goal", "next_attempt")
SV011_MERGE = "d7beaf593a15c8e170540cbbf9ee3273003e645a"
ORG_MERGE = "f160ac7d61891ee8b187368fbf05372eacc8064c"


def reseal(receipt):
    body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    return {**body, "receipt_sha256": intr.digest(body)}


def readback(index=0, **overrides):
    row = json.loads(EXPECTED.read_text())["receipts"][index]
    value = {"schema": "stegverse.intr-main-merge-transfer-readback/v1",
             "repository": row["repository"], "merge_commit": row["merge_commit"],
             "ledger_tip": row["ledger_tip"],
             "organization_receipt": copy.deepcopy(row["organization_receipt"]),
             "repository_receipt": copy.deepcopy(row["repository_receipt"])}
    value.update(overrides)
    return value


class Contract(unittest.TestCase):
    def test_predicate_operation_and_evidence_are_declared(self):
        mt = intr.load_contract()["main_merge_transfer"]
        predicate = next(p for p in mt["destination_predicates"] if p["id"] == "MAIN_MERGE_TRANSFER_RECEIPT_LEDGERED")
        self.assertEqual(predicate["operation"], "ORGANIZATION_MAIN_MERGE_TRANSFER")
        self.assertEqual(predicate["evidence_schema"], "stegverse.main-merge-transfer-evidence/v1")
        self.assertEqual(predicate["checked_by"], "resident-runtime/merge_transfer.py verify")
        self.assertEqual(predicate["unobserved_failure_code"], intr.NOT_LEDGERED)
        self.assertEqual((predicate["unobserved"], predicate["contradicted"]), ("FAIL_CLOSED", "DENY"))
        self.assertEqual(mt["schema_ref"], predicate["evidence_schema"])
        self.assertEqual(mt["operation"], predicate["operation"])
        self.assertRegex(mt["verifier"]["sha256"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual({p["pull_request"] for p in mt["verifier"]["pinned_at"]},
                         {"StegVerse-org/.github#202", "SV-011/.github#15"})

    def test_contract_agrees_with_the_verifier_when_it_is_present(self):
        """Before #202 lands the contract must declare that dependency; after, the names must agree."""
        mt = intr.load_contract()["main_merge_transfer"]
        if not VERIFIER.is_file():
            self.assertIn("StegVerse-org/.github#202", mt["verifier"]["admission_depends_on"])
            return
        text = VERIFIER.read_text(encoding="utf-8")
        constant = lambda name: re.search(r'^%s = "([^"]+)"' % name, text, re.M).group(1)
        self.assertEqual(constant("OPERATION"), mt["operation"])
        self.assertEqual(constant("EVIDENCE_SCHEMA"), mt["schema_ref"])
        self.assertEqual(constant("PROFILE_ID"), mt["profile_id"])
        self.assertEqual(constant("MAIN_REF"), mt["ref"])
        self.assertEqual(constant("NOT_LEDGERED"), intr.NOT_LEDGERED)
        self.assertEqual(constant("LINK_UNVERIFIED"), intr.LINK_UNVERIFIED)
        self.assertEqual(constant("RECEIPT_UNSEALED"), intr.RECEIPT_UNSEALED)
        digest = "sha256:" + hashlib.sha256(VERIFIER.read_bytes()).hexdigest()
        if digest != mt["verifier"]["sha256"]:
            self.fail("resident-runtime/merge_transfer.py is " + digest + "; re-pin main_merge_transfer.verifier.sha256")


class Allow(unittest.TestCase):
    def test_sealed_linked_receipts_verify_for_both_organizations(self):
        rows = json.loads(EXPECTED.read_text())["receipts"]
        self.assertEqual({r["merge_commit"] for r in rows}, {ORG_MERGE, SV011_MERGE})
        for index, row in enumerate(rows):
            result = intr.verify_merge_transfer_evidence(readback(index))
            self.assertEqual(result["disposition"], "ALLOW", result)
            self.assertEqual(result["transfer"], "VERIFIED")
            want = row["verified_by_merge_transfer_py"]
            for key in ("organization_receipt_sha256", "repository_receipt_sha256", "pull_request", "hb_epoch"):
                self.assertEqual(result[key], want[key], key)
            self.assertEqual(result["authority_effect"], "NONE_CONFORMANCE_EVIDENCE_ONLY")

    def test_result_is_deterministic(self):
        self.assertEqual(intr.canon(intr.verify_merge_transfer_evidence(readback())),
                         intr.canon(intr.verify_merge_transfer_evidence(readback())))


class RealState(unittest.TestCase):
    def test_current_mains_are_fail_closed_not_ledgered(self):
        dimension = intr.merge_transfer_dimension(MANIFEST)
        got = {r["subject"]["merge_commit"]: (r["disposition"], r["failure_code"], r["failed_predicate"])
               for r in dimension["results"]}
        self.assertEqual(got, {
            ORG_MERGE: ("FAIL_CLOSED", "MERGE_TRANSFER_RECEIPT_NOT_LEDGERED", "MAIN_MERGE_TRANSFER_RECEIPT_LEDGERED"),
            SV011_MERGE: ("FAIL_CLOSED", "MERGE_TRANSFER_RECEIPT_NOT_LEDGERED", "MAIN_MERGE_TRANSFER_RECEIPT_LEDGERED")})
        self.assertEqual(dimension["counts"], {"ALLOW": 0, "DENY": 0, "FAIL_CLOSED": 2})
        for result in dimension["results"]:
            self.assertEqual(result["transfer"], "UNVERIFIED")
            for field in SIX:
                self.assertTrue(result.get(field), field)
            self.assertEqual(result["retry_entrypoint"],
                             ".github/workflows/organization-ledger-merge-transfer.yml (push to main)")
            self.assertEqual(result["owning_existing_goal"], "StegVerse-org/.github#162")

    def test_mesh_conformance_stays_eight_allow_with_the_separate_dimension(self):
        report = intr.conform_mesh(DESTINATIONS, merge_transfer_manifest=MANIFEST)
        self.assertEqual(report["counts"], {"ALLOW": 8, "DENY": 0, "FAIL_CLOSED": 0})
        self.assertEqual(report["merge_transfer"]["counts"], {"ALLOW": 0, "DENY": 0, "FAIL_CLOSED": 2})
        plain = intr.conform_mesh(DESTINATIONS)
        self.assertNotIn("merge_transfer", plain)
        self.assertEqual(plain["results"], report["results"])


class Refusals(unittest.TestCase):
    def check(self, value, disposition, code, predicate):
        result = intr.verify_merge_transfer_evidence(value)
        self.assertEqual((result["disposition"], result["failure_code"], result["failed_predicate"]),
                         (disposition, code, predicate), result)
        self.assertEqual(result["transfer"], "UNVERIFIED")
        for field in SIX:
            self.assertTrue(result.get(field), field)

    def test_absent_or_unobserved_evidence_fails_closed(self):
        self.check(None, "FAIL_CLOSED", "MERGE_TRANSFER_SUBJECT_UNOBSERVED", "READBACK_NAMES_THE_MERGE")
        self.check(readback(merge_commit="f160ac7d"), "FAIL_CLOSED",
                   "MERGE_TRANSFER_SUBJECT_UNOBSERVED", "READBACK_NAMES_THE_MERGE")
        self.check(readback(organization_receipt=None), "FAIL_CLOSED",
                   "MERGE_TRANSFER_RECEIPT_NOT_LEDGERED", "MAIN_MERGE_TRANSFER_RECEIPT_LEDGERED")
        self.check(readback(repository_receipt=None), "FAIL_CLOSED",
                   "MERGE_TRANSFER_RECEIPT_LINK_UNVERIFIED", "REPOSITORY_RECEIPT_IS_SEALED")

    def test_another_operations_receipt_is_not_a_transfer(self):
        value = readback()
        value["organization_receipt"]["boundary_evidence"]["operation"] = "DIAGNOSTIC_CROSSING"
        value["organization_receipt"] = reseal(value["organization_receipt"])
        self.check(value, "FAIL_CLOSED", "MERGE_TRANSFER_RECEIPT_NOT_LEDGERED", "MAIN_MERGE_TRANSFER_RECEIPT_LEDGERED")

    def test_unsealed_receipts_fail_closed(self):
        value = readback()
        value["organization_receipt"]["hb_reference"]["epoch"] += 1
        self.check(value, "FAIL_CLOSED", "ORGANIZATION_LEDGER_RECEIPT_UNSEALED", "ORGANIZATION_RECEIPT_IS_SEALED")
        value = readback()
        value["repository_receipt"]["evidence"]["tree"] = "0" * 40
        self.check(value, "FAIL_CLOSED", "MERGE_TRANSFER_RECEIPT_LINK_UNVERIFIED", "REPOSITORY_RECEIPT_IS_SEALED")

    def test_unknown_evidence_version_fails_closed(self):
        value = readback()
        value["repository_receipt"]["evidence"]["schema"] = "stegverse.main-merge-transfer-evidence/v2"
        value["repository_receipt"] = reseal(value["repository_receipt"])
        value["organization_receipt"]["repo_receipt_sha256"] = value["repository_receipt"]["receipt_sha256"]
        value["organization_receipt"] = reseal(value["organization_receipt"])
        self.check(value, "FAIL_CLOSED", "MERGE_TRANSFER_EVIDENCE_VERSION_UNKNOWN",
                   "REPOSITORY_RECEIPT_EVIDENCE_SCHEMA_IS_V1")

    def test_receipt_for_another_merge_is_denied(self):
        # The organization receipt is sealed and real-shaped but names SV-011's merge.
        self.check(readback(merge_commit=SV011_MERGE), "DENY",
                   "MERGE_TRANSFER_RECEIPT_LINK_UNVERIFIED", "ORGANIZATION_RECEIPT_NAMES_THE_MERGE")
        self.check(readback(repository="SV-011/.github"), "DENY",
                   "MERGE_TRANSFER_RECEIPT_LINK_UNVERIFIED", "ORGANIZATION_RECEIPT_NAMES_THE_MERGE")

    def test_link_to_a_different_repository_receipt_is_denied(self):
        other = readback(1)["repository_receipt"]
        self.check(readback(repository_receipt=other), "DENY",
                   "MERGE_TRANSFER_RECEIPT_LINK_UNVERIFIED", "ORGANIZATION_RECEIPT_LINKS_THE_REPOSITORY_RECEIPT")

    def test_repository_receipt_carrying_another_merge_is_denied(self):
        value = readback()
        evidence = value["repository_receipt"]["evidence"]
        evidence["merge_commit"] = SV011_MERGE
        evidence["payload_sha256"] = intr._evidence_payload_digest(evidence)
        value["repository_receipt"] = reseal(value["repository_receipt"])
        value["organization_receipt"]["repo_receipt_sha256"] = value["repository_receipt"]["receipt_sha256"]
        value["organization_receipt"] = reseal(value["organization_receipt"])
        self.check(value, "DENY", "MERGE_TRANSFER_RECEIPT_LINK_UNVERIFIED", "REPOSITORY_RECEIPT_CARRIES_THE_MERGE")
        value = readback()
        value["repository_receipt"]["evidence"]["pull_request"] = 999
        value["repository_receipt"] = reseal(value["repository_receipt"])
        value["organization_receipt"]["repo_receipt_sha256"] = value["repository_receipt"]["receipt_sha256"]
        value["organization_receipt"] = reseal(value["organization_receipt"])
        self.check(value, "DENY", "MERGE_TRANSFER_RECEIPT_LINK_UNVERIFIED", "REPOSITORY_RECEIPT_CARRIES_THE_MERGE")


if __name__ == "__main__":
    unittest.main()
