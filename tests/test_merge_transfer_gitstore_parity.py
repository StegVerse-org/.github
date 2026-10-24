"""Parity: merge_transfer_gitstore gives resident-runtime/merge_transfer.py's verdict on the same receipts.

merge_transfer.py (sha256 032ed727..., pinned in data/intr-protocol/v1/protocol.json)
is read, never changed. Both verifiers read the same temp git ledger (the
pinned published tip, rebuilt from the snapshot): merge_transfer.py through
ledger_store's git locators, the variant through git cat-file. Single mode
must equal it result for result; dual mode must equal it wherever the two
ledgers hold one receipt, and differs only by FAIL_CLOSED
MERGE_TRANSFER_DUAL_LEDGER_DIVERGENCE where they do not. The append parity
case holds the two writers to byte-identical receipts.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINNED_SHA256 = "032ed727358d56f33369b35e6cc50d65f6af5dc0035f0b69fe7cddb3f4f4e20e"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = _load("test_merge_transfer_gitstore_for_parity", ROOT / "tests/test_merge_transfer_gitstore.py")
g = base.g
mt = _load("merge_transfer_for_parity", ROOT / "resident-runtime/merge_transfer.py")
TempLedger, SYNTHETIC, PIN, reseal, doc, repo_key = (base.TempLedger, base.SYNTHETIC, base.PIN, base.reseal,
                                                     base.doc, base.repo_key)


def both(ledger, repo=None, merge=None):
    repo, merge = repo or PIN["repository"], merge or SYNTHETIC["merge_commit"]
    return (mt.verify_merge_transfer(repo, merge), ledger.verify(repo, merge, "single"),
            ledger.verify(repo, merge, "dual"))


class Pinned(unittest.TestCase):
    def test_the_existing_verifier_is_the_pinned_file_unchanged(self):
        digest = hashlib.sha256((ROOT / "resident-runtime/merge_transfer.py").read_bytes()).hexdigest()
        self.assertEqual(digest, PINNED_SHA256)
        protocol = json.loads((ROOT / "data/intr-protocol/v1/protocol.json").read_text())
        self.assertEqual(protocol["main_merge_transfer"]["verifier"]["sha256"], "sha256:" + PINNED_SHA256)

    def test_the_codes_and_texts_are_the_existing_verifier_s(self):
        for name in ("OPERATION", "PROFILE_ID", "EVIDENCE_SCHEMA", "RESULT_SCHEMA", "PENDING_SCHEMA", "MAIN_REF",
                     "GOAL", "ENTRYPOINT", "SIX_FIELDS", "NOT_LEDGERED", "LINK_UNVERIFIED", "EPOCH_UNOBSERVED",
                     "FACTS_INVALID", "COLLISION", "WRITER_REFUSED"):
            self.assertEqual(getattr(g, name), getattr(mt, name), name)
        self.assertEqual(g.merge_evidence(PIN["repository"], SYNTHETIC), mt.merge_evidence(PIN["repository"], SYNTHETIC))


class RealReceipts(unittest.TestCase):
    def test_every_ledgered_merge_on_the_pinned_tip_verifies_the_same(self):
        with TempLedger() as ledger:
            merges = []
            for _digest, receipt in g.org_chain(ledger.readers()[0]):
                boundary = g._boundary(receipt)
                if boundary.get("operation") == g.OPERATION:
                    merges.append((boundary["repository"], boundary["merge_commit"]))
            self.assertTrue(merges)
            for repo, merge in merges + [(PIN["repository"], "1" * 40)]:
                old, single, dual = both(ledger, repo, merge)
                self.assertEqual(single, old, merge)
                self.assertEqual(dual, old, merge)
            self.assertEqual(both(ledger, *merges[0])[0]["disposition"], "ALLOW")


class Scenarios(unittest.TestCase):
    def _case(self, mutate=None, repo=None, merge=None, *, diverges=False):
        with TempLedger() as ledger:
            result = mt.append_merge_transfer(SYNTHETIC)
            self.assertEqual(result["disposition"], "ALLOW", result)
            if mutate:
                mutate(ledger, result)
            old, single, dual = both(ledger, repo, merge)
            self.assertEqual(single, old)
            if diverges:
                self.assertEqual(dual["failure_code"], g.DUAL_DIVERGENCE)
            else:
                self.assertEqual(dual, old)
            return old

    def test_allow(self):
        self.assertEqual(self._case()["disposition"], "ALLOW")

    def test_not_ledgered(self):
        self.assertEqual(self._case(merge="1" * 40)["failure_code"], mt.NOT_LEDGERED)
        self.assertEqual(self._case(repo="SV-000/.github")["failure_code"], mt.NOT_LEDGERED)

        def drop(ledger, result):
            digest = result["repository_receipt_sha256"]
            ledger.write({repo_key(digest): None, g.source_key(digest): None})
        self.assertEqual(self._case(drop)["failure_code"], mt.NOT_LEDGERED)

        def unseal_org(ledger, result):
            key = g.receipt_key(result["organization_receipt_sha256"])
            org = ledger.read(key)
            org["hb_reference"]["epoch"] += 1
            ledger.put(key, org)
        self.assertEqual(self._case(unseal_org)["failure_code"], mt.NOT_LEDGERED)

    def test_deny(self):
        for field, value in (("merge_commit", "0" * 40), ("ref", "refs/heads/feature"), ("tree", "f" * 40)):
            def contradict(ledger, result, field=field, value=value):
                digest = result["repository_receipt_sha256"]
                rep = ledger.read(repo_key(digest))
                rep["evidence"][field] = value
                ledger.write({repo_key(digest): doc(reseal(rep)), g.source_key(digest): doc(reseal(rep))})
            old = self._case(contradict)
            self.assertEqual((old["disposition"], old["failure_code"]), ("DENY", mt.LINK_UNVERIFIED))

    def test_dual_divergence_is_the_only_difference(self):
        def diverge(ledger, result):
            digest = result["repository_receipt_sha256"]
            rep = ledger.read(repo_key(digest))
            rep["authority_effect"] = "OTHER"
            ledger.put(g.source_key(digest), reseal(rep))
        self.assertEqual(self._case(diverge, diverges=True)["disposition"], "ALLOW")


class AppendParity(unittest.TestCase):
    def test_the_two_writers_append_byte_identical_receipts(self):
        outcomes = []
        for writer in (mt.append_merge_transfer, g.append_merge_transfer):
            with TempLedger() as ledger:
                result = writer(SYNTHETIC)
                self.assertEqual(result["disposition"], "ALLOW", result)
                files = ledger.files()
                outcomes.append((result["organization_receipt_sha256"], result["repository_receipt_sha256"],
                                 files[g.receipt_key(result["organization_receipt_sha256"])],
                                 files[repo_key(result["repository_receipt_sha256"])]))
        self.assertEqual(outcomes[0], outcomes[1])


if __name__ == "__main__":
    unittest.main()
