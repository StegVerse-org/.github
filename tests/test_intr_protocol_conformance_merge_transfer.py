"""InTr protocol v1: MAIN_MERGE_TRANSFER_RECEIPT_LEDGERED, the main-merge transfer dimension.

The offline check in org-runtime/intr_protocol.py is the contract of
resident-runtime/merge_transfer.py verify (StegVerse-org/.github#202,
SV-011/.github#15), pinned by sha256 in data/intr-protocol/v1/protocol.json.
It reads supplied readbacks only: no ledger, git, clock or network.

The expected receipts are the ones #202 and SV-011#15 computed in a temporary
copy of each ledger tip. readbacks-before-append.json is the state before the
first append (both merges FAIL_CLOSED); manifest.json is read back from the
ledger refs after it (four merges VERIFIED, f40ad7dd not ledgered).
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
BEFORE_APPEND = FIXTURES / "readbacks-before-append.json"
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
        landed = {row["repository"]: row for row in mt["verifier"]["landed_at"]}
        self.assertEqual(set(landed), {"StegVerse-org/.github", "SV-011/.github"})
        self.assertEqual(landed["StegVerse-org/.github"]["merge_commit"], "41035e9e4bca6d4114f2f6a181b03dda2de85481")
        self.assertEqual(landed["SV-011/.github"]["merge_commit"], "a636fafca237a0f928fa0eccfe4585866bfecf9d")
        # One digest today: the file landed byte-identical in both organizations.
        for row in landed.values():
            self.assertEqual(row["sha256"], mt["verifier"]["sha256"])

    def test_contract_agrees_with_the_landed_verifier(self):
        """merge_transfer.py is on main (#202); its names must agree and its digest must equal this org's pin."""
        mt = intr.load_contract()["main_merge_transfer"]
        self.assertTrue(VERIFIER.is_file(), "resident-runtime/merge_transfer.py landed with #202")
        text = VERIFIER.read_text(encoding="utf-8")
        constant = lambda name: re.search(r'^%s = "([^"]+)"' % name, text, re.M).group(1)
        self.assertEqual(constant("OPERATION"), mt["operation"])
        self.assertEqual(constant("EVIDENCE_SCHEMA"), mt["schema_ref"])
        self.assertEqual(constant("PROFILE_ID"), mt["profile_id"])
        self.assertEqual(constant("MAIN_REF"), mt["ref"])
        self.assertEqual(constant("NOT_LEDGERED"), intr.NOT_LEDGERED)
        self.assertEqual(constant("LINK_UNVERIFIED"), intr.LINK_UNVERIFIED)
        self.assertNotIn("ORGANIZATION_LEDGER_RECEIPT_UNSEALED", text)
        self.assertIn('"' + intr.LEDGERED_PREDICATE + '"', text)
        self.assertIn('"' + intr.LINK_PREDICATE + '"', text)
        digest = "sha256:" + hashlib.sha256(VERIFIER.read_bytes()).hexdigest()
        pin = next(r["sha256"] for r in mt["verifier"]["landed_at"] if r["repository"] == "StegVerse-org/.github")
        if digest != pin:
            self.fail("resident-runtime/merge_transfer.py is " + digest + "; re-pin main_merge_transfer.verifier")


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
    def assertSix(self, result):
        for field in SIX:
            self.assertTrue(result.get(field), field)
        self.assertEqual(result["retry_entrypoint"],
                         ".github/workflows/organization-ledger-merge-transfer.yml (push to main)")
        self.assertEqual(result["owning_existing_goal"], "StegVerse-org/.github#162")

    def test_before_the_first_append_both_merges_were_not_ledgered(self):
        dimension = intr.merge_transfer_dimension(BEFORE_APPEND)
        got = {r["subject"]["merge_commit"]: (r["disposition"], r["failure_code"], r["failed_predicate"])
               for r in dimension["results"]}
        self.assertEqual(got, {
            ORG_MERGE: ("FAIL_CLOSED", "MERGE_TRANSFER_RECEIPT_NOT_LEDGERED", "MAIN_MERGE_HAS_AN_ORGANIZATION_LEDGER_RECEIPT"),
            SV011_MERGE: ("FAIL_CLOSED", "MERGE_TRANSFER_RECEIPT_NOT_LEDGERED", "MAIN_MERGE_HAS_AN_ORGANIZATION_LEDGER_RECEIPT")})
        for result in dimension["results"]:
            self.assertEqual(result["transfer"], "UNVERIFIED")
            self.assertEqual(result["detail"], "no organization receipt names ORGANIZATION_MAIN_MERGE_TRANSFER for "
                             + result["subject"]["repository"] + "@" + result["subject"]["merge_commit"])
            self.assertSix(result)

    def test_after_the_first_append_four_merges_verify_and_203_is_not_ledgered(self):
        dimension = intr.merge_transfer_dimension(MANIFEST)
        got = {(r["subject"]["repository"], r["subject"]["merge_commit"][:8]): (r["disposition"], r.get("failure_code"))
               for r in dimension["results"]}
        self.assertEqual(got, {
            ("StegVerse-org/.github", "f160ac7d"): ("ALLOW", None),
            ("StegVerse-org/.github", "41035e9e"): ("ALLOW", None),
            ("StegVerse-org/.github", "f40ad7dd"): ("FAIL_CLOSED", "MERGE_TRANSFER_RECEIPT_NOT_LEDGERED"),
            ("SV-011/.github", "d7beaf59"): ("ALLOW", None),
            ("SV-011/.github", "a636fafc"): ("ALLOW", None)})
        self.assertEqual(dimension["counts"], {"ALLOW": 4, "DENY": 0, "FAIL_CLOSED": 1})
        tips = {r["subject"]["repository"]: r["subject"]["ledger_tip"] for r in dimension["results"]}
        self.assertEqual(tips, {"StegVerse-org/.github": "824e0b76d470081bcabceb096c59e0695361e6d4",
                                "SV-011/.github": "6594bafc85d47c041424e6b3f72cfa028a87f5a5"})
        for result in dimension["results"]:
            if result["disposition"] == "ALLOW":
                self.assertEqual(result["transfer"], "VERIFIED")
            else:
                self.assertSix(result)

    def test_the_backfilled_receipts_are_the_ones_the_append_predicted(self):
        live = {r["merge_commit"]: r for r in json.loads(MANIFEST.read_text())["readbacks"]}
        for row in json.loads(EXPECTED.read_text())["receipts"]:
            self.assertEqual(live[row["merge_commit"]]["organization_receipt"], row["organization_receipt"])
            self.assertEqual(live[row["merge_commit"]]["repository_receipt"], row["repository_receipt"])

    def test_mesh_conformance_stays_thirteen_allow_with_the_separate_dimension(self):
        # The test id is required verification at base and keeps its name; the pinned count is now all sixteen
        # organizations ALLOW (StegVerse-org/.github#162), the thirteen of the earlier mesh plus the three new ones.
        report = intr.conform_mesh(DESTINATIONS, merge_transfer_manifest=MANIFEST)
        self.assertEqual(report["counts"], {"ALLOW": 16, "DENY": 0, "FAIL_CLOSED": 0})
        self.assertEqual(report["merge_transfer"]["counts"], {"ALLOW": 4, "DENY": 0, "FAIL_CLOSED": 1})
        plain = intr.conform_mesh(DESTINATIONS)
        self.assertNotIn("merge_transfer", plain)
        self.assertEqual(plain["results"], report["results"])


class Refusals(unittest.TestCase):
    def check(self, value, disposition, code, predicate):
        result = intr.verify_merge_transfer_evidence(value)
        self.assertEqual((result["disposition"], result["failure_code"], result["failed_predicate"]),
                         (disposition, code, predicate), result)
        self.assertEqual(result["transfer"], "UNVERIFIED")
        self.assertEqual(result["destination_predicate"], "MAIN_MERGE_TRANSFER_RECEIPT_LEDGERED")
        for field in SIX:
            self.assertTrue(result.get(field), field)
        return result

    def not_ledgered(self, value):
        return self.check(value, "FAIL_CLOSED", "MERGE_TRANSFER_RECEIPT_NOT_LEDGERED",
                          "MAIN_MERGE_HAS_AN_ORGANIZATION_LEDGER_RECEIPT")

    def contradicted(self, value):
        return self.check(value, "DENY", "MERGE_TRANSFER_RECEIPT_LINK_UNVERIFIED",
                          "ORGANIZATION_RECEIPT_LINKS_TO_THE_MERGE_COMMIT")

    def relinked(self, edit):
        """Edit the repository receipt evidence, reseal it, and re-link a resealed organization receipt to it."""
        value = readback()
        edit(value["repository_receipt"]["evidence"])
        value["repository_receipt"] = reseal(value["repository_receipt"])
        value["organization_receipt"]["repo_receipt_sha256"] = value["repository_receipt"]["receipt_sha256"]
        value["organization_receipt"] = reseal(value["organization_receipt"])
        return value

    def test_unnamed_subject_fails_closed(self):
        self.check(None, "FAIL_CLOSED", "MERGE_TRANSFER_SUBJECT_UNOBSERVED", "READBACK_NAMES_THE_MERGE")
        self.check(readback(merge_commit="f160ac7d"), "FAIL_CLOSED",
                   "MERGE_TRANSFER_SUBJECT_UNOBSERVED", "READBACK_NAMES_THE_MERGE")

    def test_absent_receipts_fail_closed_not_ledgered(self):
        self.not_ledgered(readback(organization_receipt=None))
        self.not_ledgered(readback(repository_receipt=None))

    def test_unsealed_receipts_fail_closed_not_ledgered(self):
        value = readback()
        value["organization_receipt"]["hb_reference"]["epoch"] += 1
        self.not_ledgered(value)
        value = readback()
        value["repository_receipt"]["evidence"]["tree"] = "0" * 40
        self.not_ledgered(value)

    def test_a_receipt_that_is_not_this_merges_transfer_fails_closed(self):
        # merge_transfer.py skips these on the chain; they are not this merge's transfer receipt.
        value = readback()
        value["organization_receipt"]["boundary_evidence"]["operation"] = "DIAGNOSTIC_CROSSING"
        value["organization_receipt"] = reseal(value["organization_receipt"])
        self.not_ledgered(value)
        self.not_ledgered(readback(merge_commit=SV011_MERGE))
        self.not_ledgered(readback(repository="SV-011/.github"))

    def test_organization_receipt_naming_another_repository_is_denied(self):
        value = readback()
        value["organization_receipt"]["source_repository"] = "SV-011/.github"
        value["organization_receipt"] = reseal(value["organization_receipt"])
        self.assertIn("organization receipt names repository", self.contradicted(value)["detail"])

    def test_link_to_a_different_repository_receipt_is_denied(self):
        other = readback(1)["repository_receipt"]
        result = self.contradicted(readback(repository_receipt=other))
        self.assertIn("is sealed as", result["detail"])

    def test_evidence_contradicting_the_merge_is_denied(self):
        cases = {
            "merge_commit": lambda e: e.update(merge_commit=SV011_MERGE),
            "repository": lambda e: e.update(repository="SV-011/.github"),
            "ref": lambda e: e.update(ref="refs/heads/laneb/other"),
            "schema": lambda e: e.update(schema="stegverse.main-merge-transfer-evidence/v2"),
        }
        for field, edit in cases.items():
            with self.subTest(field=field):
                def apply(evidence, edit=edit):
                    edit(evidence)
                    evidence["payload_sha256"] = intr._evidence_payload_digest(evidence)
                result = self.contradicted(self.relinked(apply))
                self.assertIn("evidence " + field + " is", result["detail"])

    def test_evidence_digest_mismatch_is_denied(self):
        value = self.relinked(lambda e: e.update(pull_request=999))
        result = self.contradicted(value)
        self.assertIn("does not carry the digest it claims", result["detail"])


if __name__ == "__main__":
    unittest.main()
