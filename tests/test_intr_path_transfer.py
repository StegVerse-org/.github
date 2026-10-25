"""InTr mesh path transfer: declared paths, the path-receipt append, and the two-half verifier.

Temp ledgers are the tree of the pinned ledger tip (git archive), never the
published ref; this workflow has contents: read and pushes nothing. Receipts
written here are NOT LEDGERED and NOT AUTHENTIC: they exist only in a temporary
directory for the duration of a test. Path receipts appear on the real ledger
only once the transfer declaration lands on main and
.github/workflows/intr-path-transfer.yml appends it.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "intr-path-transfer"
EXPECTED = json.loads((FIXTURES / "expected-real-state.json").read_text())
LEDGER_TIP = EXPECTED["ledger_tip"]
NAMESPACE = json.loads((ROOT / ".stegverse/transition-ledger/contract.json").read_text())[
    "repository_ledger_location"]["namespace"]
TRANSFER = EXPECTED["verified_transfer_commit"]   # main-merge transfer VERIFIED at the pinned tip
UNLEDGERED = EXPECTED["unledgered_commit"]        # no main-merge transfer receipt at the pinned tip
APPEND_BASE = EXPECTED["append_base_tip"]          # last tip before the path receipts: fresh appends are tested here
LEDGERED_TRANSFER = EXPECTED["ledgered_transfer_commit"]   # the transfer commit of the 7 path receipts at LEDGER_TIP


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pt = load("intr_path_transfer_under_test", "resident-runtime/intr_path_transfer.py")


class Ledger:
    def __init__(self, tip=LEDGER_TIP):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        subprocess.run("git -C '%s' archive %s | tar -x -C '%s'" % (ROOT, tip, self.root), shell=True, check=True)
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


def reseal(receipt):
    body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    return {**body, "receipt_sha256": pt.sha(body)}


def mine():
    return [p for p in pt.declared_paths() if p["source"] == pt.organization()]


def cid(path):
    rows = {r["path_id"]: r["communication_id"] for r in pt.load_declaration()}
    return rows[path["path_id"]]


class DeclaredPaths(unittest.TestCase):
    def test_paths_are_ordered_pairs_of_conformant_organizations(self):
        paths = pt.declared_paths()
        orgs = sorted({p["source"] for p in paths})
        self.assertEqual(len(orgs), 13)
        self.assertEqual(len(paths), len(orgs) * (len(orgs) - 1))
        self.assertEqual(len({p["path_id"] for p in paths}), len(paths))
        for p in paths:
            self.assertNotEqual(p["source"], p["destination"])
            self.assertEqual(p["capability"], "intr-destination")
            self.assertTrue(p["destination_address"].endswith(".intr-destination"))

    def test_declaration_covers_every_path_from_this_organization_once(self):
        rows = pt.load_declaration()
        self.assertEqual(sorted(r["path_id"] for r in rows), sorted(p["path_id"] for p in mine()))
        self.assertEqual(len({r["communication_id"] for r in rows}), len(rows))

    def test_messages_conform_to_the_protocol(self):
        for p in mine():
            m = pt.message(p, cid(p), TRANSFER)
            self.assertEqual(pt.intr.conform_message(m, p["destination"])["disposition"], "ALLOW")


class RealState(unittest.TestCase):
    def test_every_path_is_fail_closed_at_the_pinned_tip(self):
        ledger = Ledger()
        try:
            state = pt.real_state()
        finally:
            ledger.close()
        self.assertEqual(state["counts"], {"ALLOW": 0, "DENY": 0, "FAIL_CLOSED": 156})
        self.assertEqual(state["paths"], EXPECTED["paths"])
        self.assertEqual(state["counts"], EXPECTED["counts"])

    def test_paths_sourced_here_are_answered_from_the_ledger_at_the_pinned_tip(self):
        ledger = Ledger()
        try:
            before = ledger.files()
            ledgered = set(EXPECTED["ledgered_path_ids"])
            results = pt.append_transfers(TRANSFER)
            got = {r["path_id"]: (r["disposition"], bool(r.get("replayed"))) for r in results}
            # the 7 paths ledgered at the pinned tip are answered from the ledger; a row added after it appends
            # fresh on this temporary copy (NOT LEDGERED, NOT AUTHENTIC), and no pre-existing file changes
            self.assertEqual(got, {p["path_id"]: ("ALLOW", p["path_id"] in ledgered) for p in mine()}, results)
            self.assertEqual(len(ledgered), 7)
            after = ledger.files()
            for name, data in before.items():
                if not name.endswith("HEAD.json"):
                    self.assertEqual(after[name], data, name)
            for p in mine():
                source = pt.verify_source(p, cid(p))
                self.assertEqual((source["disposition"], source["transfer_commit"]),
                                 ("ALLOW", LEDGERED_TRANSFER if p["path_id"] in ledgered else TRANSFER))
                whole = pt.verify_path(p, cid(p))
                self.assertEqual(whole["halves"], {"source": "ALLOW", "destination": "FAIL_CLOSED"})
                for field in pt.SIX_FIELDS:
                    self.assertTrue(whole[field], field)
        finally:
            ledger.close()


class Append(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger(APPEND_BASE)

    def tearDown(self):
        self.ledger.close()

    def test_append_links_the_transfer_and_the_source_half_verifies(self):
        before = self.ledger.files()
        results = pt.append_transfers(TRANSFER)
        self.assertEqual([r["disposition"] for r in results], ["ALLOW"] * len(mine()), results)
        after = self.ledger.files()
        for name, data in before.items():
            if not name.endswith("HEAD.json"):
                self.assertEqual(after[name], data, name)
        for p in mine():
            source = pt.verify_source(p, cid(p))
            self.assertEqual(source["disposition"], "ALLOW", source)
            self.assertEqual(source["transfer_commit"], TRANSFER)
            whole = pt.verify_path(p, cid(p))
            self.assertEqual((whole["disposition"], whole["failure_code"]),
                             ("FAIL_CLOSED", "INTR_PATH_CROSS_ORG_READ_CREDENTIAL_NOT_ISSUED"))
            self.assertEqual(whole["halves"], {"source": "ALLOW", "destination": "FAIL_CLOSED"})
            self.assertIn("StegVerse-Labs/TVC", whole["retry_entrypoint"])
            self.assertEqual(whole["classification"], "A")
            self.assertIn("TVC-PRIVATE-SOURCE-READ-001", whole["owning_existing_goal"])
            self.assertNotIn("#162", whole["owning_existing_goal"])
            for field in pt.SIX_FIELDS:
                self.assertTrue(whole[field], field)
        replay = pt.append_transfers(TRANSFER)
        self.assertTrue(all(r.get("replayed") for r in replay))
        self.assertEqual(self.ledger.files(), after)

    def test_a_ledgered_path_is_answered_from_the_ledger_on_a_later_push(self):
        pt.append_transfers(TRANSFER)
        after = self.ledger.files()
        later = pt.append_transfers(EXPECTED["later_verified_transfer_commit"])
        self.assertTrue(all(r.get("replayed") for r in later))
        self.assertEqual(self.ledger.files(), after)

    def test_a_transfer_without_a_ledgered_main_merge_writes_nothing(self):
        before = self.ledger.files()
        (result,) = pt.append_transfers(UNLEDGERED)
        self.assertEqual((result["disposition"], result["failure_code"]),
                         ("FAIL_CLOSED", "INTR_PATH_TRANSFER_COMMIT_NOT_LEDGERED"))
        for field in pt.SIX_FIELDS:
            self.assertTrue(result[field], field)
        self.assertEqual(self.ledger.files(), before)

    def stores_with(self, edit):
        """Append, then rewrite the first path's repository receipt evidence, reseal it and relink the org receipt."""
        pt.append_transfers(TRANSFER)
        org, rep = pt.mt.org_store(), pt.mt.repo_store()
        key = pt.mt.store_module().receipt_key
        p = mine()[0]
        found = pt.verify_source(p, cid(p))
        org_r = org.get(key(found["organization_receipt_sha256"]))
        rep_r = rep.get(key(found["repository_receipt_sha256"]))
        evidence = copy.deepcopy(rep_r["evidence"])
        edit(evidence)
        evidence["payload_sha256"] = pt.sha({k: v for k, v in evidence.items()
                                             if k not in ("payload_sha256", "disposition", "communication_id")})
        new_rep = reseal({**rep_r, "evidence": evidence})
        new_org = reseal({**org_r, "repo_receipt_sha256": new_rep["receipt_sha256"]})

        class Store(dict):
            def get(self, k):
                if k not in self:
                    raise KeyError(k)
                return dict.__getitem__(self, k)
        chain = pt._chain(org)
        o = Store()
        receipts = {d: r for d, r in chain}
        # the edited receipt sits in its own position on the chain: rebuild links above it
        order = [d for d, _ in chain]
        i = order.index(found["organization_receipt_sha256"])
        receipts[order[i]] = new_org
        prev = new_org["receipt_sha256"]
        for d in reversed(order[:i]):
            r = reseal({**receipts[d], "previous_receipt_sha256": prev})
            receipts[d] = r
            prev = r["receipt_sha256"]
        for r in receipts.values():
            o[key(r["receipt_sha256"])] = r
        o[pt.mt.store_module().HEAD_KEY] = {"receipt_sha256": prev}
        rs = Store({key(new_rep["receipt_sha256"]): new_rep})
        return p, o, rs

    def test_contradicted_path_receipts_are_denied(self):
        cases = {
            "path": lambda e: e.update(destination_organization="Infrastructure-Continuity-Ventures"),
            "address": lambda e: e.update(destination_address="infrastructure-continuity-ventures.intr-destination"),
            "transfer": lambda e: e.update(transfer_commit=UNLEDGERED),
            "message": lambda e: e["message"].update(communication_id="other"),
        }
        for name, edit in cases.items():
            with self.subTest(name=name):
                ledger = Ledger()
                try:
                    p, o, rs = self.stores_with(edit)
                    result = pt.verify_source(p, cid(p), o, rs)
                finally:
                    ledger.close()
                self.assertEqual((result["disposition"], result["failure_code"]),
                                 ("DENY", "INTR_PATH_RECEIPT_LINK_UNVERIFIED"), result)
                for field in pt.SIX_FIELDS:
                    self.assertTrue(result[field], field)


class DestinationHalf(unittest.TestCase):
    """Destination receipts here are SYNTHETIC (built and sealed in this test), not read from any ledger."""

    def readback(self, p, source, communication_id, link=None):
        link = link or source
        evidence_core = {"schema": "stegverse.intr-path-ingress-evidence/v1", "path_id": p["path_id"],
                         "source_organization_receipt_sha256": link["organization_receipt_sha256"],
                         "source_repository_receipt_sha256": link["repository_receipt_sha256"]}
        evidence = {**evidence_core, "payload_sha256": pt.sha(evidence_core), "disposition": "ALLOW",
                    "communication_id": communication_id}
        repo = reseal({"schema": "stegverse.repo-transition-receipt/v1", "repository": p["destination"] + "/.github",
                       "evidence": evidence, "synthetic": "NOT_LEDGERED_NOT_AUTHENTIC"})
        org = reseal({"schema": "stegverse.organization-transition-receipt/v1",
                      "source_repository": p["destination"] + "/.github", "repo_receipt_sha256": repo["receipt_sha256"],
                      "previous_receipt_sha256": None, "synthetic": "NOT_LEDGERED_NOT_AUTHENTIC",
                      "boundary_evidence": {"operation": "ORGANIZATION_INTR_DESTINATION_INGRESS", "path_id": p["path_id"],
                                            "communication_id": communication_id,
                                            "source_organization_receipt_sha256": link["organization_receipt_sha256"],
                                            "source_repository_receipt_sha256": link["repository_receipt_sha256"]}})
        return {"schema": "stegverse.intr-path-ledger-readback/v1", "repository": p["destination"] + "/.github",
                "head_receipt_sha256": org["receipt_sha256"], "chain": [org], "organization_receipt": org,
                "repository_receipt": repo}

    def test_both_halves_verify_only_with_a_destination_readback(self):
        ledger = Ledger()
        try:
            pt.append_transfers(TRANSFER)
            p = mine()[0]
            source = pt.verify_source(p, cid(p))
            whole = pt.verify_path(p, cid(p), destination_readback=self.readback(p, source, cid(p)))
            other = dict(source, repository_receipt_sha256="sha256:" + "0" * 64)
            denied = pt.verify_path(p, cid(p), destination_readback=self.readback(p, source, cid(p), link=other))
        finally:
            ledger.close()
        self.assertEqual((whole["disposition"], whole["path"]), ("ALLOW", "VERIFIED"), whole)
        self.assertEqual((denied["disposition"], denied["failure_code"]),
                         ("DENY", "INTR_PATH_DESTINATION_RECEIPT_LINK_UNVERIFIED"))

    def test_destination_refusals(self):
        p = mine()[0]
        absent = pt.verify_destination(p, cid(p))
        self.assertEqual((absent["disposition"], absent["failure_code"], absent["classification"]),
                         ("FAIL_CLOSED", "INTR_PATH_CROSS_ORG_READ_CREDENTIAL_NOT_ISSUED", "A"))
        for field in pt.SIX_FIELDS:
            self.assertTrue(absent[field], field)


class DocumentedDefaults(unittest.TestCase):
    """Main's default, pinned (StegVerse-org/.github#162, Lane B). No definition is changed here.

    Lines quoted at main 907f4305.
    - data/intr-protocol/v1/protocol.json:172 "declared_paths": "every ordered pair of distinct organizations ..."
      and resident-runtime/federation_cycle.py:14-15 "It is intra-organization: no boundary is crossed and no InTr is
      involved.": a row naming a repository of this organization as the destination is undeclared and writes nothing.
    - docs/INTR_PATH_TRANSFER_V1.md:42 "carried pair's inclusion in the source ledger | FAIL_CLOSED
      INTR_PATH_CROSS_ORG_READ_CREDENTIAL_NOT_ISSUED": with no TVC read receipt, the production writer's consume
      (.github/workflows/organization-ledger-writer.yml path-ingress, which neither fetches an anonymous copy nor sets
      STEGVERSE_INTR_PUBLIC_LEDGERS) stays FAIL_CLOSED; the public-ledger route is reached only through its explicit
      flag (--public-ledgers / STEGVERSE_INTR_PUBLIC_LEDGERS) and stays a proposal.
    """

    def test_an_intra_organization_repository_destination_is_undeclared_and_writes_nothing(self):
        org = pt.organization()
        pid = org + "/.github->" + org + "/LLM-adapter:intr-destination"
        self.assertNotIn(pid, {p["path_id"] for p in pt.declared_paths()})
        for p in pt.declared_paths():
            self.assertNotIn("/", p["source"] + p["destination"], p["path_id"])
        ledger = Ledger()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                declaration = Path(tmp) / "transfers.json"
                declaration.write_text(json.dumps({
                    "schema": pt.DECLARATION_SCHEMA, "source_repository": pt.repository(),
                    "transfers": [{"path_id": pid, "communication_id": "intr-path-v1:" + pid.split(":")[0]}]}))
                before = ledger.files()
                (result,) = pt.append_transfers(TRANSFER, declaration=declaration)
                self.assertEqual(ledger.files(), before)
        finally:
            ledger.close()
        self.assertEqual((result["disposition"], result["failure_code"], result["failed_predicate"]),
                         ("FAIL_CLOSED", "INTR_PATH_UNDECLARED", "TRANSFER_NAMES_A_DECLARED_PATH_FROM_THIS_ORGANIZATION"))
        for field in pt.SIX_FIELDS:
            self.assertTrue(result[field], field)

    def test_the_production_writer_does_not_opt_into_the_anonymous_read(self):
        # Re-purposed (base id kept) under Rigel's standing invariant, 2026-10-25: every organization's .github is
        # public, so the writer's path-ingress job observes source inclusion through the anonymous read, exactly
        # once, before consume, with no token. The writer's other jobs still do not opt in.
        writer = (ROOT / ".github" / "workflows" / "organization-ledger-writer.yml").read_text(encoding="utf-8")
        start = writer.index("\n  # Folded from .github/workflows/intr-path-ingress.yml")
        end = writer.index("\n  # Folded from", start + 1)
        job, rest = writer[start:end], writer[:start] + writer[end:]
        for opt_in in ("STEGVERSE_INTR_PUBLIC_LEDGERS", "intr_public_ledgers", "--public-ledgers"):
            self.assertNotIn(opt_in, rest, opt_in)
        self.assertEqual(job.count('bash tools/tasks/intr_public_ledgers.sh "$RUNNER_TEMP/public-ledgers"'), 1)
        self.assertEqual(job.count('export STEGVERSE_INTR_PUBLIC_LEDGERS="$RUNNER_TEMP/public-ledgers"'), 1)
        self.assertLess(job.index("intr_public_ledgers.sh"), job.index("intr_path_ingress.py consume"))
        self.assertLess(job.index("STEGVERSE_INTR_PUBLIC_LEDGERS"), job.index("intr_path_ingress.py consume"))
        for token in ("secrets.", "FEDERATION_HOP_TOKEN", "FEDERATION_READ_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
            self.assertNotIn(token, job, token)
        reader = (ROOT / "tools" / "tasks" / "intr_public_ledgers.sh").read_text(encoding="utf-8")
        self.assertIn("-c credential.helper= -c http.https://github.com/.extraheader=", reader)

    def test_source_inclusion_without_the_flag_is_fail_closed_credential_not_issued(self):
        pi = load("intr_path_ingress_documented_default", "resident-runtime/intr_path_ingress.py")
        row = json.loads((ROOT / ".stegverse/intr-path-transfer/inbound.json").read_text(encoding="utf-8"))["transfers"][0]
        carried = row["carried"]
        checked = {"path_id": row["path_id"], "communication_id": row["communication_id"],
                   "source_repository": carried["source_organization_receipt"]["source_repository"],
                   "source_organization_receipt_sha256": carried["source_organization_receipt"]["receipt_sha256"],
                   "source_repository_receipt_sha256": carried["source_repository_receipt"]["receipt_sha256"]}
        saved = os.environ.pop(pi.PUBLIC_LEDGERS_ENV, None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / (checked["source_repository"].split("/")[0] + ".git")).mkdir()   # a copy no flag names
                self.assertIsNone(pi.public_ledger_dir(checked["source_repository"]))
                got = pi.source_inclusion(checked, Path(tmp) / "no-tvc-read-receipts")
        finally:
            if saved is not None:
                os.environ[pi.PUBLIC_LEDGERS_ENV] = saved
        self.assertEqual((got["disposition"], got["failure_code"], got["failed_predicate"]),
                         ("FAIL_CLOSED", "INTR_PATH_CROSS_ORG_READ_CREDENTIAL_NOT_ISSUED",
                          "OTHER_ORGANIZATION_LEDGER_IS_READ_THROUGH_TV_TVC"))
        self.assertIn("StegVerse-Labs/TVC", got["retry_entrypoint"])
        for field in pt.SIX_FIELDS:
            self.assertTrue(got[field], field)


if __name__ == "__main__":
    unittest.main()
