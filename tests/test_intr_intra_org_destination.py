"""InTr mesh destination inside the organization: StegVerse-org/.github -> StegVerse-org/LLM-adapter.

Temp ledgers are the tree of the pinned ledger tip (git archive), never the
published ref. Receipts written here are NOT LEDGERED and NOT AUTHENTIC.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

import importlib.util
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = json.loads((ROOT / "tests/fixtures/intr-path-transfer/expected-real-state.json").read_text())
NAMESPACE = json.loads((ROOT / ".stegverse/transition-ledger/contract.json").read_text())[
    "repository_ledger_location"]["namespace"]
TRANSFER = EXPECTED["verified_transfer_commit"]   # main-merge transfer VERIFIED at the pinned tip
UNLEDGERED = EXPECTED["unledgered_commit"]        # no main-merge transfer receipt at the pinned tip


def _load(name, relative):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pt = _load("intr_path_transfer_under_intra_org_test", "resident-runtime/intr_path_transfer.py")


class Ledger:
    """A temporary copy of the pinned append-base tree (git archive); never the published ref.

    append_base_tip is the fixture's documented base for fresh appends: at ledger_tip (21648778) the
    fixture's unledgered_commit already carries a main-merge transfer receipt."""

    def __init__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name) / "ledger"
        self.root.mkdir()
        subprocess.run("git -C '%s' archive %s | tar -x -C '%s'" % (ROOT, EXPECTED["append_base_tip"], self.root),
                       shell=True, check=True)
        self.saved = {k: os.environ.get(k) for k in ("STEGVERSE_ORG_LEDGER_ROOT", "STEGVERSE_REPO_LEDGER_ROOT")}
        os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = str(self.root)
        os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = str(self.root / NAMESPACE)
        for commit in EXPECTED.get("temp_merge_transfers") or []:   # temp copies only; not ledgered
            result = pt.mt.append_merge_transfer(pt.mt.commit_facts(commit))
            assert result["disposition"] == "ALLOW", result

    def files(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def close(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.dir.cleanup()


io_ = pt._intra_org()
DEST = "StegVerse-org/LLM-adapter"
PID = "StegVerse-org/.github->StegVerse-org/LLM-adapter:intr-destination"
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
       "owning_existing_goal", "next_attempt")


def path():
    return {p["path_id"]: p for p in io_.declared_paths()}[PID]


def cid():
    return {r["path_id"]: r["communication_id"] for r in io_.load_declaration()}[PID]


class IntraOrgDestination(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger()

    def tearDown(self):
        self.ledger.close()

    def six(self, result, disposition, code):
        self.assertEqual(result["disposition"], disposition, result)
        self.assertEqual(result["failure_code"], code, result)
        for field in SIX:
            self.assertTrue(result.get(field), field)

    def test_declared_path_is_code_defined_and_inside_the_organization(self):
        self.assertEqual(io_.INTRA_ORG_DESTINATIONS, (DEST,))
        p = path()
        self.assertEqual(p["destination_location"],
                         "refs/stegverse/organization-ledger:repository-ledger/" + DEST)
        self.assertEqual([r["path_id"] for r in io_.load_declaration()], [PID])

    def test_real_state_at_the_pinned_tip_is_not_registered(self):
        state = io_.real_state()
        self.assertEqual(state["counts"], {"ALLOW": 0, "DENY": 0, "FAIL_CLOSED": 1})
        self.six(state["paths"][0], "FAIL_CLOSED", io_.NOT_REGISTERED)

    def test_append_reaches_layer_one_allow_and_both_chains_record_it(self):
        [result] = io_.append_transfers(TRANSFER)
        self.assertEqual(result["disposition"], "ALLOW", result)
        self.assertEqual((result["layer"], result["path"], result["replayed"]), (1, "VERIFIED", False))
        self.assertEqual(result["halves"], {"registration": "ALLOW", "source": "ALLOW", "destination": "ALLOW"})
        sub = self.ledger.root / "repository-ledger" / DEST
        receipts = [json.loads(p.read_text()) for p in sorted((sub / "receipts").glob("*.json"))]
        self.assertEqual(len(receipts), 2)
        genesis = next(r for r in receipts if r["previous_receipt_sha256"] is None)
        ingress = next(r for r in receipts if r["previous_receipt_sha256"] is not None)
        self.assertEqual((genesis["repository"], genesis["transition_class"]), (DEST, io_.GENESIS_CLASS))
        self.assertEqual(ingress["previous_receipt_sha256"], genesis["receipt_sha256"])
        self.assertEqual(ingress["evidence"]["source_organization_receipt_sha256"],
                         result["source"]["organization_receipt_sha256"])
        self.assertEqual(json.loads((sub / "HEAD.json").read_text())["receipt_sha256"], ingress["receipt_sha256"])
        self.assertEqual(io_.real_state()["counts"], {"ALLOW": 1, "DENY": 0, "FAIL_CLOSED": 0})
        self.assertEqual(io_.verify_path(path(), cid())["result_sha256"], result["result_sha256"])

    def test_replay_is_answered_from_the_ledger(self):
        io_.append_transfers(TRANSFER)
        before = self.ledger.files()
        [again] = io_.append_transfers(TRANSFER)
        self.assertEqual((again["disposition"], again["replayed"]), ("ALLOW", True))
        self.assertEqual(self.ledger.files(), before)

    def test_unledgered_transfer_commit_writes_nothing(self):
        before = self.ledger.files()
        [result] = io_.append_transfers(UNLEDGERED)
        self.six(result, "FAIL_CLOSED", io_.TRANSFER_NOT_LEDGERED)
        self.assertEqual(self.ledger.files(), before)

    def test_undeclared_destination_writes_nothing(self):
        before = self.ledger.files()
        verified = pt.mt.verify_merge_transfer(io_.repository(), TRANSFER)
        epoch, _ = pt.mt.head_epoch(io_.org_store())
        result = io_.append_row({"path_id": "StegVerse-org/.github->StegVerse-org/SV-LLM:intr-destination",
                                 "communication_id": "x"}, TRANSFER, verified, epoch)
        self.six(result, "FAIL_CLOSED", io_.UNDECLARED)
        self.assertEqual(self.ledger.files(), before)

    def test_edited_destination_receipt_is_deny(self):
        io_.append_transfers(TRANSFER)
        sub = self.ledger.root / "repository-ledger" / DEST / "receipts"
        for p in sub.glob("*.json"):
            r = json.loads(p.read_text())
            if r["previous_receipt_sha256"] is not None:
                r["evidence"]["message_sha256"] = "sha256:" + "0" * 64
                p.write_text(json.dumps(r))
        result = io_.verify_path(path(), cid())
        self.assertEqual(result["disposition"], "DENY", result)
        self.assertIn("DENY", result["halves"].values())
        self.assertNotIn("ALLOW", (result["halves"]["destination"],))
        before = self.ledger.files()
        [again] = io_.append_transfers(TRANSFER)
        self.assertEqual(again["disposition"], "DENY")
        self.assertEqual(self.ledger.files(), before)

    def test_writer_cli_appends_and_verify_expects_the_crossing(self):
        out = self.ledger.root.parent / "append.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pt.main(["verify", "--expect-source", "ALLOW"]), 1)
            self.assertEqual(pt.main(["append", "--transfer-commit", TRANSFER, "--out", str(out)]), 0)
            self.assertEqual(pt.main(["verify", "--expect-source", "ALLOW"]), 0)
        appended = json.loads(out.read_text())
        self.assertEqual([r["disposition"] for r in appended], ["ALLOW"] * len(appended))
        self.assertEqual(appended[-1]["path_id"], PID)


if __name__ == "__main__":
    unittest.main()
