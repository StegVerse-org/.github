"""The path transfer's ledger binding (resident-runtime/intr_path_ledger.py): per-organization selection, and the
git-store backend driven end to end over this organization's own ledger.

Selection follows data/intr-protocol/v1/protocol.json main_merge_transfer.verifiers_by_organization:
StegVerse-Labs and GCAT-BCAT-Engine bind merge_transfer_gitstore.py at its pinned digest; every other
organization binds merge_transfer.py, unchanged.

The git-store tests here use a contract whose pin also names this organization, and Lane D's modules as pinned
byte copies in a checkout layout (tests/fixtures/intr-path-ledger/gitstore-checkout/resident-runtime/:
ledger_gitstore.py sha256 3c3ec97d..., merge_transfer_gitstore.py sha256 bf9f1c15...), so the real
ledger_gitstore.append runs on this organization's own writer surface over temporary ledgers at the pinned tip.
Every receipt written is NOT LEDGERED and NOT AUTHENTIC.
"""
from __future__ import annotations

import copy
import tempfile
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from intr_path_temp_ledger import TempLedger  # noqa: E402

CHECKOUT = ROOT / "tests/fixtures/intr-path-ledger/gitstore-checkout"
EXPECTED = json.loads((ROOT / "tests/fixtures/intr-path-transfer/expected-real-state.json").read_text())
NAMESPACE = json.loads((ROOT / ".stegverse/transition-ledger/contract.json").read_text())[
    "repository_ledger_location"]["namespace"]
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair",
       "retry_entrypoint", "owning_existing_goal", "next_attempt")


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pt = load("intr_path_transfer_ledger_test", "resident-runtime/intr_path_transfer.py")
pl = pt.path_ledger   # one module, so one Refused class, for every path module
pi = load("intr_path_ingress_ledger_test", "resident-runtime/intr_path_ingress.py")
ORG = pt.organization()


def contract_pinning_this_organization():
    contract = copy.deepcopy(pl.load_contract())
    pins = contract["main_merge_transfer"]["verifiers_by_organization"]
    pins[ORG] = copy.deepcopy(pins["StegVerse-Labs"])
    return contract


def gitstore(module_root=CHECKOUT):
    return pl.binding(ROOT, contract=contract_pinning_this_organization(), organization=ORG, module_root=module_root)


def verifier_only(tmp):
    """A checkout that carries merge_transfer_gitstore.py but not yet ledger_gitstore.py."""
    target = Path(tmp) / "resident-runtime"
    target.mkdir(parents=True)
    (target / "merge_transfer_gitstore.py").write_bytes((CHECKOUT / "resident-runtime/merge_transfer_gitstore.py").read_bytes())
    return Path(tmp)


class Bound:
    """Install one binding in both path modules (and the ingress module the transfer loads) for a test."""

    def __init__(self, binding):
        self.binding = binding
        for module in (pt, pi, pt.path_ingress()):
            module.bind(binding)

    def close(self):
        for module in (pt, pi, pt.path_ingress()):
            module.bind()


def mine():
    return [p for p in pt.declared_paths() if p["source"] == ORG]


def cid(path):
    return {r["path_id"]: r["communication_id"] for r in pt.load_declaration()}[path["path_id"]]


class Selection(unittest.TestCase):
    def test_merge_transfer_py_organizations_are_unchanged(self):
        self.assertEqual(pt.ledger.kind, "MERGE_TRANSFER_PY")
        self.assertEqual(pi.ledger.kind, "MERGE_TRANSFER_PY")
        for org in ("StegVerse-org", "SV-011", "StegGhost", "SV-LLM"):
            self.assertIsNone(pl.pin_for(org))

    def test_labs_and_gcat_select_the_pinned_gitstore_verifier(self):
        for org in ("StegVerse-Labs", "GCAT-BCAT-Engine"):
            pin = pl.pin_for(org)
            self.assertEqual((pin["path"], pin["mode"]), ("resident-runtime/merge_transfer_gitstore.py", "dual"))
            self.assertEqual(pin["ledger_module"]["path"], "resident-runtime/ledger_gitstore.py")
            self.assertEqual(pin["ledger_module"]["sha256"],
                             "sha256:3c3ec97dcc10aa17afb8858b03d5ac7261290e84efb52576fbabc1370d8d917c")
            chosen = pl.binding(ROOT, organization=org, module_root=CHECKOUT)
            self.assertEqual((chosen.kind, chosen.mode, chosen.verifier, chosen.writer_module),
                             ("MERGE_TRANSFER_GITSTORE", "dual", "resident-runtime/merge_transfer_gitstore.py verify",
                              "resident-runtime/ledger_gitstore.py"))

    def test_a_file_that_is_not_the_pinned_bytes_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            forged = verifier_only(tmp)
            (forged / "resident-runtime/ledger_gitstore.py").write_text("# not the pinned bytes\n")
            with self.assertRaises(pl.Refused) as raised:
                pl.binding(ROOT, organization="StegVerse-Labs", module_root=forged)
        result = raised.exception.result
        self.assertEqual(result["failure_code"], "INTR_PATH_LEDGER_VERIFIER_DIGEST_UNPINNED")
        for field in SIX:
            self.assertTrue(result[field], field)
        unbound = pl.bound(ROOT, organization="StegVerse-Labs")   # this checkout carries no gitstore file
        self.assertEqual(unbound.kind, "UNBOUND")
        bound = Bound(unbound)
        try:
            results = pt.append_transfers(EXPECTED["verified_transfer_commit"])
        finally:
            bound.close()
        self.assertEqual([(r["disposition"], r["failure_code"]) for r in results],
                         [("FAIL_CLOSED", "INTR_PATH_LEDGER_VERIFIER_DIGEST_UNPINNED")])


class GitstoreBackend(unittest.TestCase):
    def run_both(self, check):
        for git in (False, True):
            with self.subTest(store="git" if git else "posix"):
                ledger = TempLedger(ROOT, EXPECTED["ledger_tip"], NAMESPACE, git=git)
                try:
                    check(ledger)
                finally:
                    ledger.close()

    def test_readers_find_the_verified_transfer_and_the_real_state_is_unchanged(self):
        def check(ledger):
            bound = Bound(gitstore())
            try:
                for commit in EXPECTED.get("temp_merge_transfers") or []:   # temp copies only; not ledgered
                    self.assertEqual(pt.ledger.append_merge_transfer(commit)["disposition"], "ALLOW")
                verdict = pt.ledger.verify_transfer(EXPECTED["verified_transfer_commit"])
                missing = pt.ledger.verify_transfer(EXPECTED["unledgered_commit"])
                state = pt.real_state()
            finally:
                bound.close()
            self.assertEqual(verdict["disposition"], "ALLOW", verdict)
            self.assertEqual(missing["failure_code"], "MERGE_TRANSFER_RECEIPT_NOT_LEDGERED")
            self.assertEqual(state["paths"], EXPECTED["paths"])
        self.run_both(check)

    def test_without_the_ledger_module_every_append_fails_closed_and_writes_nothing(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = verifier_only(tmp.name)

        def check(ledger):
            bound = Bound(gitstore(root))
            try:
                for commit in EXPECTED.get("temp_merge_transfers") or []:   # temp copies only; not ledgered
                    self.assertEqual(pt.ledger.append_merge_transfer(commit)["disposition"], "ALLOW")
                before = ledger.files()
                results = pt.append_transfers(EXPECTED["verified_transfer_commit"])
            finally:
                bound.close()
            self.assertEqual(len(results), 7)
            for result in results:
                self.assertEqual((result["disposition"], result["failure_code"]),
                                 ("FAIL_CLOSED", "INTR_PATH_GITSTORE_WRITER_UNBOUND"), result)
                for field in SIX:
                    self.assertTrue(result[field], field)
                self.assertIn("ledger_gitstore.py", result["required_evidence_or_repair"])
            self.assertEqual(ledger.files(), before)
        self.run_both(check)

    def test_lane_d_append_writes_both_halves_and_they_verify_through_the_gitstore_readers(self):
        def check(ledger):
            bound = Bound(gitstore())
            try:
                for commit in EXPECTED.get("temp_merge_transfers") or []:   # temp copies only; not ledgered
                    self.assertEqual(pt.ledger.append_merge_transfer(commit)["disposition"], "ALLOW")
                transfer = pt.ledger.verify_transfer(EXPECTED["verified_transfer_commit"])
                results = pt.append_transfers(EXPECTED["verified_transfer_commit"])
                self.assertEqual([r["disposition"] for r in results], ["ALLOW"] * 7, results)
                after = ledger.files()
                organization, repository = pt.ledger.readers()
                for p in mine():
                    source = pt.verify_source(p, cid(p))
                    self.assertEqual(source["disposition"], "ALLOW", source)
                    # the link: the verified transfer's organization receipt seal is in the path evidence
                    self.assertEqual(source["merge_transfer_organization_receipt_sha256"],
                                     transfer["organization_receipt_sha256"])
                    org_r = organization.get(pt.ledger.receipt_key(source["organization_receipt_sha256"]))
                    self.assertEqual(org_r["boundary_evidence"]["operation"], "INTR_MESH_PATH_TRANSFER")
                    self.assertEqual(org_r["boundary_evidence"]["path_id"], p["path_id"])
                    retained = organization.get(pt.ledger.source_key(source["repository_receipt_sha256"]))
                    self.assertEqual(retained, repository.get(pt.ledger.receipt_key(source["repository_receipt_sha256"])))
                replay = pt.append_transfers(EXPECTED["verified_transfer_commit"])
                self.assertTrue(all(r.get("replayed") for r in replay), replay)
                self.assertEqual(ledger.files(), after)
                # destination half on the same binding: carried copies of one source pair enter ingress
                p = mine()[0]
                source = pt.verify_source(p, cid(p))
                carried = {"source_organization_receipt": organization.get(pt.ledger.receipt_key(source["organization_receipt_sha256"])),
                           "source_repository_receipt": repository.get(pt.ledger.receipt_key(source["repository_receipt_sha256"]))}
                checked = pi.check_source_pair(carried["source_organization_receipt"], carried["source_repository_receipt"],
                                               p["path_id"], cid(p), p["destination"])
                self.assertEqual(checked["disposition"], "ALLOW", checked)
            finally:
                bound.close()
        self.run_both(check)


if __name__ == "__main__":
    unittest.main()
