"""InTr protocol v1: the main-merge transfer predicate for StegVerse-Labs and GCAT-BCAT-Engine.

Those two organizations are pinned to Lane D's git-store verifier
(resident-runtime/merge_transfer_gitstore.py, sha256 bf9f1c15...; the same bytes at
StegVerse-org/.github#211, StegVerse-Labs/.github#3292 and
GCAT-BCAT-Engine/.github#16), mode dual. Every other organization stays on
merge_transfer.py (single read).

The side-by-side tests run that verifier from a byte copy pinned by sha256
(tests/fixtures/intr-protocol/merge-transfer-gitstore/merge_transfer_gitstore.py).
They lay each readback out in a temporary directory in the ledger layout the
verifier reads (HEAD.json, receipts/, source-receipts/, repository-ledger/<repo>/receipts/)
and require the same disposition, failure_code and failed_predicate from both.

expected-receipts.json was appended by that verifier to temporary bare copies of
the published ledger tips. It is labelled NOT_LEDGERED_NOT_AUTHENTIC: the published
ledgers hold no main-merge transfer receipt at those tips (manifest.json).
No ledger, clock, network or git is read here.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "intr-protocol" / "merge-transfer-gitstore"
VENDORED = FIXTURES / "merge_transfer_gitstore.py"
LANDED = ROOT / "resident-runtime" / "merge_transfer_gitstore.py"
EXPECTED = FIXTURES / "expected-receipts.json"
MANIFEST = FIXTURES / "manifest.json"
PIN = "sha256:bf9f1c15420b1c9c8e21655fe176d6b009e190357e09e433bac170bf09247176"
GITSTORE_ORGS = ("StegVerse-Labs", "GCAT-BCAT-Engine")
HEADS = {"StegVerse-org/.github": ("StegVerse-org/.github#211", "5f5f3669ebd9cffdbb68c57d941bc966dba22708"),
         "StegVerse-Labs/.github": ("StegVerse-Labs/.github#3292", "e3a0f5062fa5470f33e28ea57965e09f8b61b3f0"),
         "GCAT-BCAT-Engine/.github": ("GCAT-BCAT-Engine/.github#16", "f0d55e81391d840d0826e32bc6067ac7ce0f45bb")}
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair",
       "retry_entrypoint", "owning_existing_goal", "next_attempt")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


intr = _load("intr_protocol_mt_gitstore", ROOT / "org-runtime" / "intr_protocol.py")
gs = _load("merge_transfer_gitstore_vendored", VENDORED)


def reseal(receipt):
    body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    return {**body, "receipt_sha256": intr.digest(body)}


def rows():
    return json.loads(EXPECTED.read_text())["receipts"]


def readback(index=0, **overrides):
    row = rows()[index]
    value = {"schema": "stegverse.intr-main-merge-transfer-readback/v1",
             "repository": row["repository"], "merge_commit": row["merge_commit"], "ledger_tip": row["ledger_tip"],
             "organization_receipt": copy.deepcopy(row["organization_receipt"]),
             "repository_receipt": copy.deepcopy(row["repository_receipt"]),
             "retained_repository_receipt": copy.deepcopy(row["retained_repository_receipt"])}
    value.update(overrides)
    return value


def without_gitstore_pins():
    contract = copy.deepcopy(intr.load_contract())
    contract["main_merge_transfer"].pop("verifiers_by_organization")
    return contract


def gitstore_verdict(value, mode):
    """Lay the readback out in the ledger layout and run the pinned verifier over it."""
    org_receipt = value.get("organization_receipt")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo_ns = root / "repository-ledger" / value["repository"]
        (root / "receipts").mkdir(parents=True)
        (root / "source-receipts").mkdir()
        (repo_ns / "receipts").mkdir(parents=True)

        def put(path, document):
            if document is not None:
                path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")

        if isinstance(org_receipt, dict):
            digest = org_receipt["receipt_sha256"]
            put(root / "HEAD.json", {"receipt_sha256": digest})
            put(root / gs.receipt_key(digest), org_receipt)
            linked = org_receipt.get("repo_receipt_sha256")
            if isinstance(linked, str) and ":" in linked:
                put(repo_ns / gs.receipt_key(linked), value.get("repository_receipt"))
                put(root / gs.source_key(linked), value.get("retained_repository_receipt"))
        organization = gs.DirReader(root)
        return gs.verify_merge_transfer(value["repository"], value["merge_commit"], organization,
                                        organization.at("repository-ledger/" + value["repository"]), mode=mode)


class Contract(unittest.TestCase):
    def test_vendored_verifier_is_the_pinned_bytes(self):
        self.assertEqual("sha256:" + hashlib.sha256(VENDORED.read_bytes()).hexdigest(), PIN)
        if LANDED.is_file():  # once StegVerse-org/.github#211 lands, the landed file must be these bytes
            self.assertEqual(LANDED.read_bytes(), VENDORED.read_bytes())

    def test_labs_and_gcat_are_pinned_to_the_gitstore_verifier(self):
        mt = intr.load_contract()["main_merge_transfer"]
        pins = mt["verifiers_by_organization"]
        self.assertEqual(set(pins), set(GITSTORE_ORGS))
        for org in GITSTORE_ORGS:
            pin = pins[org]
            self.assertEqual(pin["sha256"], PIN)
            self.assertEqual(pin["path"], "resident-runtime/merge_transfer_gitstore.py")
            self.assertEqual(pin["checked_by"], "resident-runtime/merge_transfer_gitstore.py verify")
            self.assertEqual(pin["mode"], "dual")
            self.assertIs(pin["landed"], False)
            self.assertEqual({h["repository"]: (h["pull_request"], h["head"]) for h in pin["heads"]}, HEADS)
            self.assertTrue(all(h["sha256"] == PIN for h in pin["heads"]))
            self.assertEqual(intr.merge_transfer_verifier(org)["mode"], "dual")
        self.assertIn("observed_at", pins["StegVerse-Labs"]["store_note"])
        self.assertIn("#3263", pins["StegVerse-Labs"]["store_note"])
        self.assertEqual(pins["StegVerse-Labs"]["writer_surface"], "AGGREGATE_TRANSITION")
        self.assertEqual(pins["GCAT-BCAT-Engine"]["writer_surface"], "DUAL_LEDGER")
        for org in ("StegVerse-org", "SV-011", "StegGhost", "SV-LLM"):
            self.assertEqual(intr.merge_transfer_verifier(org),
                             {"path": "resident-runtime/merge_transfer.py",
                              "checked_by": "resident-runtime/merge_transfer.py verify", "mode": "single",
                              "sha256": mt["verifier"]["sha256"]})

    def test_divergence_is_in_the_predicate_fail_closed_set(self):
        mt = intr.load_contract()["main_merge_transfer"]
        predicate = mt["destination_predicates"][0]
        self.assertEqual(predicate["fail_closed_failure_codes"],
                         ["MERGE_TRANSFER_RECEIPT_NOT_LEDGERED", "MERGE_TRANSFER_DUAL_LEDGER_DIVERGENCE"])
        self.assertEqual(predicate["checked_by_organization"],
                         {o: "resident-runtime/merge_transfer_gitstore.py verify" for o in GITSTORE_ORGS})
        evidence = {p["id"]: p for p in mt["evidence_predicates"]}
        dual = evidence[intr.DUAL_PREDICATE]
        self.assertEqual((dual["disposition"], dual["failure_code"]), ("FAIL_CLOSED", intr.DUAL_DIVERGENCE))

    def test_names_agree_with_the_gitstore_verifier(self):
        text = VENDORED.read_text(encoding="utf-8")
        mt = intr.load_contract()["main_merge_transfer"]
        self.assertEqual((gs.NOT_LEDGERED, gs.LINK_UNVERIFIED, gs.DUAL_DIVERGENCE),
                         (intr.NOT_LEDGERED, intr.LINK_UNVERIFIED, intr.DUAL_DIVERGENCE))
        self.assertEqual((gs.OPERATION, gs.EVIDENCE_SCHEMA, gs.PROFILE_ID, gs.MAIN_REF),
                         (mt["operation"], mt["schema_ref"], mt["profile_id"], mt["ref"]))
        for predicate in (intr.LEDGERED_PREDICATE, intr.LINK_PREDICATE, intr.DUAL_PREDICATE):
            self.assertIn('"' + predicate + '"', text)


class Allow(unittest.TestCase):
    def test_temp_appended_receipts_verify_as_the_gitstore_verifier_verified_them(self):
        self.assertEqual({r["organization"] for r in rows()}, set(GITSTORE_ORGS))
        self.assertIs(json.loads(EXPECTED.read_text())["authentic_receipt"], False)
        for index, row in enumerate(rows()):
            with self.subTest(org=row["organization"]):
                result = intr.verify_merge_transfer_evidence(readback(index))
                self.assertEqual(result["disposition"], "ALLOW", result)
                self.assertEqual((result["verifier"], result["verifier_mode"]),
                                 ("resident-runtime/merge_transfer_gitstore.py verify", "dual"))
                for mode in ("dual", "single"):
                    want = row["verified_by_merge_transfer_gitstore_py"][mode]
                    self.assertEqual(want["disposition"], "ALLOW")
                    for key in ("organization_receipt_sha256", "repository_receipt_sha256", "pull_request", "hb_epoch"):
                        self.assertEqual(result[key], want[key], key)
                    live = gitstore_verdict(readback(index), mode)
                    self.assertEqual(live["disposition"], "ALLOW", live)
                    self.assertEqual(live["organization_receipt_sha256"], want["organization_receipt_sha256"])

    def test_labs_receipt_carries_the_clock_observed_at_the_verifier_ignores(self):
        # StegVerse-Labs' organization writer stamps observed_at from the clock
        # (aggregate_repo_transition.py:1083; StegVerse-Labs/.github#3263, #3290).
        # The verdict does not read it: changing it and resealing still verifies.
        labs = next(i for i, r in enumerate(rows()) if r["organization"] == "StegVerse-Labs")
        value = readback(labs)
        self.assertIn("observed_at", value["organization_receipt"])
        value["organization_receipt"]["observed_at"] = "1970-01-01T00:00:00+00:00"
        value["organization_receipt"] = reseal(value["organization_receipt"])
        self.assertEqual(intr.verify_merge_transfer_evidence(value)["disposition"], "ALLOW")
        self.assertEqual(gitstore_verdict(value, "dual")["disposition"], "ALLOW")


class RealState(unittest.TestCase):
    def test_published_ledgers_hold_no_transfer_receipt_for_the_current_main_merge(self):
        dimension = intr.merge_transfer_dimension(MANIFEST)
        self.assertEqual(dimension["counts"], {"ALLOW": 0, "DENY": 0, "FAIL_CLOSED": 2})
        pins = intr.load_contract()["main_merge_transfer"]["verifiers_by_organization"]
        for result in dimension["results"]:
            org = result["subject"]["repository"].split("/")[0]
            self.assertEqual((result["failure_code"], result["failed_predicate"]),
                             ("MERGE_TRANSFER_RECEIPT_NOT_LEDGERED", "MAIN_MERGE_HAS_AN_ORGANIZATION_LEDGER_RECEIPT"))
            self.assertEqual(result["subject"]["ledger_tip"], pins[org]["ledger_tip_observed"])
            for field in SIX:
                self.assertTrue(result.get(field), field)
        for row in json.loads(MANIFEST.read_text())["readbacks"]:
            for mode in ("dual", "single"):
                self.assertEqual(gitstore_verdict(row, mode)["failure_code"], "MERGE_TRANSFER_RECEIPT_NOT_LEDGERED")


class SideBySide(unittest.TestCase):
    """The offline check and the pinned verifier give one verdict on the same receipts."""

    def relinked(self, edit, index=0):
        value = readback(index)
        edit(value["repository_receipt"]["evidence"])
        value["repository_receipt"]["evidence"]["payload_sha256"] = intr._evidence_payload_digest(
            value["repository_receipt"]["evidence"])
        value["repository_receipt"] = reseal(value["repository_receipt"])
        value["retained_repository_receipt"] = copy.deepcopy(value["repository_receipt"])
        value["organization_receipt"]["repo_receipt_sha256"] = value["repository_receipt"]["receipt_sha256"]
        value["organization_receipt"] = reseal(value["organization_receipt"])
        return value

    def cases(self, index):
        other = 1 - index
        out = {"verified": readback(index),
               "organization receipt absent": readback(index, organization_receipt=None),
               "repository receipt absent": readback(index, repository_receipt=None)}
        value = readback(index)
        value["organization_receipt"]["hb_reference"]["epoch"] += 1
        out["organization receipt unsealed"] = value
        value = readback(index)
        value["repository_receipt"]["evidence"]["tree"] = "0" * 40
        out["repository receipt unsealed"] = value
        out["retained copy absent"] = readback(index, retained_repository_receipt=None)
        value = readback(index)
        value["retained_repository_receipt"]["hb_reference"]["epoch"] += 1
        out["retained copy differs"] = value
        value = readback(index)
        value["organization_receipt"]["boundary_evidence"]["operation"] = "DIAGNOSTIC_CROSSING"
        value["organization_receipt"] = reseal(value["organization_receipt"])
        out["not this merge's transfer"] = value
        value = readback(index)
        value["organization_receipt"]["source_repository"] = rows()[other]["repository"]
        value["organization_receipt"] = reseal(value["organization_receipt"])
        out["organization receipt names another repository"] = value
        foreign = copy.deepcopy(rows()[other]["repository_receipt"])
        out["link to a different repository receipt"] = readback(
            index, repository_receipt=foreign, retained_repository_receipt=copy.deepcopy(foreign))
        for field, edit in {"merge_commit": lambda e: e.update(merge_commit=rows()[other]["merge_commit"]),
                            "repository": lambda e: e.update(repository=rows()[other]["repository"]),
                            "ref": lambda e: e.update(ref="refs/heads/laneb/other"),
                            "schema": lambda e: e.update(schema="stegverse.main-merge-transfer-evidence/v2")}.items():
            out["evidence " + field + " contradicts"] = self.relinked(edit, index)
        value = self.relinked(lambda e: None, index)
        value["repository_receipt"]["evidence"]["pull_request"] = 999
        value["repository_receipt"] = reseal(value["repository_receipt"])
        value["retained_repository_receipt"] = copy.deepcopy(value["repository_receipt"])
        value["organization_receipt"]["repo_receipt_sha256"] = value["repository_receipt"]["receipt_sha256"]
        value["organization_receipt"] = reseal(value["organization_receipt"])
        out["evidence digest mismatch"] = value
        return out

    def test_dual_mode_verdicts_match_for_labs_and_gcat(self):
        seen = set()
        for index in range(len(rows())):
            for name, value in self.cases(index).items():
                with self.subTest(org=rows()[index]["organization"], case=name):
                    ours = intr.verify_merge_transfer_evidence(value)
                    theirs = gitstore_verdict(value, "dual")
                    self.assertEqual((ours["disposition"], ours.get("failure_code"), ours.get("failed_predicate")),
                                     (theirs["disposition"], theirs.get("failure_code"), theirs.get("failed_predicate")),
                                     (ours, theirs))
                    if ours["disposition"] != "ALLOW":
                        for field in SIX:
                            self.assertTrue(ours.get(field), field)
                    seen.add((ours["disposition"], ours.get("failure_code")))
        self.assertEqual(seen, {("ALLOW", None), ("FAIL_CLOSED", intr.NOT_LEDGERED),
                                ("FAIL_CLOSED", intr.DUAL_DIVERGENCE), ("DENY", intr.LINK_UNVERIFIED)})

    def test_single_mode_verdicts_match_without_the_gitstore_pin(self):
        contract = without_gitstore_pins()
        for index in range(len(rows())):
            for name, value in self.cases(index).items():
                with self.subTest(org=rows()[index]["organization"], case=name):
                    ours = intr.verify_merge_transfer_evidence(value, contract)
                    theirs = gitstore_verdict(value, "single")
                    self.assertEqual((ours["disposition"], ours.get("failure_code"), ours.get("failed_predicate")),
                                     (theirs["disposition"], theirs.get("failure_code"), theirs.get("failed_predicate")))
                    self.assertNotEqual(ours.get("failure_code"), intr.DUAL_DIVERGENCE)

    def test_merge_transfer_py_organizations_are_not_held_to_the_retained_copy(self):
        # SV-011's published ledger retains no source-receipts/ copy; its pin is merge_transfer.py (single).
        manifest = json.loads((ROOT / "tests/fixtures/intr-protocol/merge-transfer/manifest.json").read_text())
        for row in manifest["readbacks"]:
            self.assertNotIn("retained_repository_receipt", row)
        dimension = intr.merge_transfer_dimension(ROOT / "tests/fixtures/intr-protocol/merge-transfer/manifest.json")
        self.assertEqual(dimension["counts"], {"ALLOW": 4, "DENY": 0, "FAIL_CLOSED": 1})


if __name__ == "__main__":
    unittest.main()
