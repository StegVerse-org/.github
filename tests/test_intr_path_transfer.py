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


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pt = load("intr_path_transfer_under_test", "resident-runtime/intr_path_transfer.py")


class Ledger:
    def __init__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        subprocess.run("git -C '%s' archive %s | tar -x -C '%s'" % (ROOT, LEDGER_TIP, self.root), shell=True, check=True)
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
        self.assertEqual(len(orgs), 8)
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
        self.assertEqual(state["counts"], {"ALLOW": 0, "DENY": 0, "FAIL_CLOSED": 56})
        self.assertEqual(state["paths"], EXPECTED["paths"])
        self.assertEqual(state["counts"], EXPECTED["counts"])


class Append(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger()

    def tearDown(self):
        self.ledger.close()

    def test_append_links_the_transfer_and_the_source_half_verifies(self):
        before = self.ledger.files()
        results = pt.append_transfers(TRANSFER)
        self.assertEqual([r["disposition"] for r in results], ["ALLOW"] * 7, results)
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
            "path": lambda e: e.update(destination_organization="AaCT-E"),
            "address": lambda e: e.update(destination_address="aact-e.intr-destination"),
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



# -- INTR-PATH-TRANSFER-TYPED-BODY-001 (StegVerse-org/.github#162, Lane B) --------------------------------

MAIN = "907f4305"   # current main when the typed body was built; the golden is that commit's output
GOLDEN = FIXTURES / "untyped-golden.json"
TYPED = FIXTURES / "typed-genesis-observed.json"
TYPED_SHA256 = "a4f3f951e874f9b0ad37a7cf88234d9f067c68b43455da07e975ccf1749e2022"   # = LLM-adapter#431's copy
LLM_ADAPTER = "StegVerse-org/LLM-adapter"
LLM_NS = "repository-ledger/StegVerse-org/LLM-adapter"
MT = "sha256:" + "7" * 64
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
       "owning_existing_goal", "next_attempt")


def dumps(value):
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def untyped_output():
    """Every observable output of the untyped path for the existing fixtures (the golden's generator)."""
    import hashlib
    out = {"schema": "stegverse.intr-path-transfer-untyped-golden/v1",
           "note": "Output of current main for the existing fixtures (declaration, pinned snapshot, pinned ledger "
                   "tip). Typed bodies must leave every value here byte-identical. Temp-ledger receipts are NOT "
                   "LEDGERED.",
           "paths": pt.declared_paths(), "declaration": pt.load_declaration()}
    out["messages"] = [pt.message(p, cid(p), TRANSFER) for p in mine()]
    out["path_evidence"] = [pt.path_evidence(p, cid(p), TRANSFER, MT) for p in mine()]
    ledger = Ledger()
    try:
        before = ledger.files()
        out["real_state_before"] = pt.real_state()
        out["append"] = pt.append_transfers(TRANSFER)
        after = ledger.files()

        def digest(k, v):   # HEAD.json names the temp directory in receipt_path; bind its receipt digest instead
            return json.loads(v)["receipt_sha256"] if k.endswith("HEAD.json") else hashlib.sha256(v).hexdigest()
        out["ledger_files_written_sha256"] = {k: digest(k, v) for k, v in sorted(after.items()) if before.get(k) != v}
        out["verify_source"] = [pt.verify_source(p, cid(p)) for p in mine()]
        out["real_state_after"] = pt.real_state()
        out["replay"] = pt.append_transfers(TRANSFER)
        out["unledgered"] = pt.append_transfers(UNLEDGERED)
    finally:
        ledger.close()
    return out


GENESIS_EPOCH = 446655631


def synthetic_genesis():
    """Byte-deterministic: emit.py's receipt body at a supplied epoch, no clock (StegVerse-Labs/.github#3263/#3290;
    StegVerse-org/.github#167 comment 6372442705). Equals LLM-adapter#431's precomputed expected genesis for these
    inputs (scripts/llm_adapter_repository_ledger_genesis_pin.py precompute --hb-epoch 446655631)."""
    body = {"schema": "stegverse.repo-transition-receipt/v1", "repository": LLM_ADAPTER,
            "transition_id": "REPOSITORY_LEDGER_INITIALIZATION:" + LLM_ADAPTER,
            "transition_class": "REPOSITORY_LEDGER_INITIALIZATION",
            "predecessor_state_sha256": "sha256:" + "0" * 64, "successor_state_sha256": "sha256:" + "1" * 64,
            "evidence": {"namespace": LLM_NS}, "authority_effect": "NONE",
            "hb_reference": {"epoch": GENESIS_EPOCH, "heartbeat_id": "HB:%d" % GENESIS_EPOCH, "frequency_hz": 100,
                             "period_ms": 10, "progression_dependency": "OSCILLATOR_ONLY",
                             "derived_from_clock": False, "authority_effect": "NONE"},
            "ordering": "OSCILLATOR_HEARTBEAT_EPOCH_ONLY", "observed_at": "SUPPLIED_HB_EPOCH:%d" % GENESIS_EPOCH,
            "observed_at_is_descriptive_not_ordering": True, "previous_receipt_sha256": None}
    return {**body, "receipt_sha256": pt.sha(body)}


def destination_record(source, epoch=GENESIS_EPOCH + 2, **edit):
    """The destination's own ingress record of a crossing: the intr_transport_carrier destination_evidence shape
    (LLM-adapter#431/#432/#433), pointing at the egress record by digest, with a supplied epoch. Synthetic."""
    ev = source["evidence"]
    core = {"schema": "stegverse.intr-path-ingress-evidence/v1", "repository": LLM_ADAPTER, "path_id": ev["path_id"],
            "source_repository": source["repository"], "source_repository_receipt_sha256": source["receipt_sha256"],
            "message": ev["message"], "message_sha256": ev["message_sha256"],
            "addressed_location": ev["destination_location"], "endpoint_kind": ev["endpoint_kind"],
            "source_inclusion": "READ_BACK_FROM_THE_ENDPOINT_LEDGER_AND_RETAINED"}
    evidence = {**core, "payload_sha256": pt.sha(core), "disposition": "ALLOW", "communication_id": ev["communication_id"],
                "boundary_evidence": {"operation": "ORGANIZATION_INTR_DESTINATION_INGRESS", "path_id": ev["path_id"],
                                      "communication_id": ev["communication_id"],
                                      "source_repository_receipt_sha256": source["receipt_sha256"]}}
    body = {"schema": "stegverse.repo-transition-receipt/v1", "repository": LLM_ADAPTER,
            "transition_id": "INTR_MESH_PATH_INGRESS:" + ev["communication_id"],
            "transition_class": "INTR_MESH_PATH_INGRESS", "predecessor_state_sha256": "sha256:" + "1" * 64,
            "successor_state_sha256": source["receipt_sha256"], "evidence": evidence, "authority_effect": "NONE",
            "hb_reference": {**synthetic_genesis()["hb_reference"], "epoch": epoch, "heartbeat_id": "HB:%d" % epoch},
            "observed_at": "SUPPLIED_HB_EPOCH:%d" % epoch, "previous_receipt_sha256": synthetic_genesis()["receipt_sha256"]}
    body.update(edit)
    return {**body, "receipt_sha256": pt.sha(body)}


def declaration_with(*rows):
    document = json.loads(pt.DECLARATION.read_text())
    document["transfers"] = document["transfers"] + list(rows)
    d = tempfile.TemporaryDirectory()
    path = Path(d.name) / "transfers.json"
    path.write_text(json.dumps(document))
    return d, path


class UntypedTransfersAreByteIdentical(unittest.TestCase):
    def test_golden_is_main_output_and_untyped_output_is_byte_identical(self):
        golden = GOLDEN.read_text()
        recorded = json.loads(golden)["generated_from"]
        blob = subprocess.run(["git", "-C", str(ROOT), "show", MAIN + ":resident-runtime/intr_path_transfer.py"],
                              check=True, capture_output=True).stdout
        import hashlib
        self.assertEqual(recorded, {"commit": MAIN, "file": "resident-runtime/intr_path_transfer.py",
                                    "sha256": hashlib.sha256(blob).hexdigest()})
        out = untyped_output()
        out["generated_from"] = recorded
        self.assertEqual(dumps(out), golden)

    def test_a_typed_row_alongside_leaves_untyped_rows_byte_identical(self):
        golden = json.loads(GOLDEN.read_text())
        row = pt.genesis_observed_row(LLM_ADAPTER, synthetic_genesis()["receipt_sha256"])
        holder, decl = declaration_with(row)
        ledger = Ledger()
        try:
            state = pt.real_state(declaration=decl)
            results = pt.append_transfers(TRANSFER, declaration=decl)
        finally:
            ledger.close()
            holder.cleanup()
        self.assertEqual(dumps(results[:-1]), dumps(golden["append"]))
        self.assertEqual(dumps(state["paths"]), dumps(golden["real_state_before"]["paths"]))
        self.assertEqual(state["counts"], golden["real_state_before"]["counts"])
        self.assertEqual(results[-1]["disposition"], "ALLOW")
        self.assertTrue(results[-1]["typed"])
        self.assertNotIn("typed_transfers", golden["real_state_before"])
        self.assertEqual([t["disposition"] for t in state["typed_transfers"]], ["FAIL_CLOSED"])


class TypedBody(unittest.TestCase):
    def setUp(self):
        self.genesis = synthetic_genesis()
        self.row = pt.genesis_observed_row(LLM_ADAPTER, self.genesis["receipt_sha256"])

    def assert_six(self, result, disposition, code):
        self.assertEqual((result["disposition"], result["failure_code"]), (disposition, code), result)
        for field in SIX:
            self.assertIsInstance(result[field], str, field)
            self.assertTrue(result[field], field)
        self.assertEqual(result["owning_existing_goal"], "StegVerse-org/.github#162")
        for word in ("grant", "approved", "authorized", "merge-ready"):
            self.assertNotIn(word, json.dumps(result).lower())

    def refused_append(self, row):
        """Append a declaration whose only addition is ``row``; the row's result, and that nothing was written for it."""
        holder, decl = declaration_with(row)
        ledger = Ledger()
        try:
            baseline = pt.append_transfers(TRANSFER)
            before = ledger.files()
            results = pt.append_transfers(TRANSFER, declaration=decl)
            self.assertEqual(ledger.files(), before)
            self.assertTrue(all(r.get("replayed") for r in results[:-1]), baseline)
        finally:
            ledger.close()
            holder.cleanup()
        return results[-1]

    def test_the_genesis_observed_row_is_allowlisted_sealed_and_typed(self):
        self.assertEqual(sorted(pt.TYPED_BODY_SCHEMAS), ["stegverse.repository-ledger-genesis-pointer/v1"])
        self.assertIsNone(pt.typed_refusal(self.row))
        self.assertEqual(self.row["typed_body_sha256"], pt.sha(self.row["typed_body"]))
        ev = pt.typed_path_evidence(self.row, TRANSFER, MT)
        self.assertEqual(ev["destination_location"],
                         "refs/stegverse/organization-ledger:repository-ledger/StegVerse-org/LLM-adapter")
        self.assertEqual(ev["endpoint_kind"], "ORG")
        self.assertIn(ev["endpoint_kind"], pt.ENDPOINT_KINDS)
        self.assertEqual(ev["typed_body_sha256"], pt.sha(ev["message"]["body"]))
        self.assertEqual(ev["message_sha256"], pt.sha(ev["message"]))
        core = {k: v for k, v in ev.items()
                if k not in ("payload_sha256", "disposition", "communication_id", "boundary_evidence")}
        self.assertEqual(ev["payload_sha256"], pt.sha(core))
        # the untyped evidence gains nothing
        p = mine()[0]
        self.assertNotIn("destination_location", pt.path_evidence(p, cid(p), TRANSFER, MT))
        self.assertNotIn("endpoint_kind", pt.path_evidence(p, cid(p), TRANSFER, MT))

    def test_endpoint_kinds_are_432s_endpoint_kind_v1_enum(self):
        # StegVerse-org/LLM-adapter#432 schemas/endpoint-kind.v1.json $defs.endpoint_kind.enum
        self.assertEqual(pt.ENDPOINT_KINDS, ("EPHEMERAL", "PERMANENT", "GATEWAY", "KV", "SKAP_VAULT", "ORG"))

    def test_typed_append_emits_the_cross_repo_fixture_byte_identically(self):
        import hashlib
        text = TYPED.read_text()
        self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), TYPED_SHA256)
        fixture = json.loads(text)
        self.assertEqual(fixture["genesis_receipt"], self.genesis)
        self.assertEqual(fixture["declaration_row"], self.row)
        holder, decl = declaration_with(self.row)
        ledger = Ledger()
        try:
            results = pt.append_transfers(TRANSFER, declaration=decl)
            typed = results[-1]
            source = pt.mt._receipt(pt.mt.repo_store(), typed["repository_receipt_sha256"])
            verified = pt.verify_typed_source(self.row)
            after = ledger.files()
            replay = pt.append_transfers(TRANSFER, declaration=decl)
            self.assertEqual(ledger.files(), after)
            state = pt.real_state(declaration=decl)
        finally:
            ledger.close()
            holder.cleanup()
        self.assertEqual(dumps(typed), dumps(fixture["append_result"]))
        self.assertEqual(dumps(source), dumps(fixture["source_receipt"]))
        self.assertEqual(verified["disposition"], "ALLOW", verified)
        self.assertEqual(verified["repository_receipt_sha256"], source["receipt_sha256"])
        self.assertTrue(replay[-1]["replayed"])
        self.assertEqual(state["typed_transfers"][0]["disposition"], "ALLOW")

    def test_the_emitted_source_half_has_the_receivers_carrier_shape(self):
        """intr_transport_carrier.verify's source-half predicates (LLM-adapter#431/#432/#433, sha256 9f460c07...)."""
        fixture = json.loads(TYPED.read_text())
        source, signal = fixture["source_receipt"], fixture["declaration_row"]["typed_body"]
        body = {k: v for k, v in source.items() if k != "receipt_sha256"}
        self.assertEqual(source["receipt_sha256"], pt.sha(body))
        self.assertEqual((source["schema"], source["transition_class"]),
                         ("stegverse.repo-transition-receipt/v1", "INTR_MESH_PATH_TRANSFER"))
        ev = source["evidence"]
        self.assertEqual(ev["schema"], "stegverse.intr-path-transfer-evidence/v1")
        core = {k: v for k, v in ev.items()
                if k not in ("payload_sha256", "disposition", "communication_id", "boundary_evidence")}
        self.assertEqual(ev["payload_sha256"], pt.sha(core))
        self.assertEqual(ev["destination_location"],
                         "refs/stegverse/organization-ledger:repository-ledger/StegVerse-org/LLM-adapter")
        self.assertEqual(ev["destination_organization"], "StegVerse-org")
        self.assertEqual(ev["boundary_evidence"]["operation"], "INTR_MESH_PATH_TRANSFER")
        self.assertEqual(ev["message"]["message_class"], "ecosystem.communication")
        self.assertEqual(ev["message_sha256"], pt.sha(ev["message"]))
        self.assertEqual(pt.sha(ev["message"]["body"]), pt.sha(signal))
        self.assertEqual(ev["path_id"], "StegVerse-org/.github->StegVerse-org:intr-destination")
        # the body is exactly #431's genesis_signal(genesis, contract): a pointer, never a copied record
        self.assertEqual(signal, {"schema": "stegverse.repository-ledger-genesis-pointer/v1",
                                  "ledger_location": "StegVerse-org/.github#refs/stegverse/organization-ledger:"
                                                     + LLM_NS,
                                  "genesis_receipt_sha256": fixture["genesis_receipt"]["receipt_sha256"],
                                  # originated by the org's own path, never an endpoint (#160 comment 6372871021)
                                  "node_ref": "StegVerse-org/.github"})
        # the egress record carries a supplied epoch; the synthetic genesis is clock-free
        self.assertIs(source["hb_reference"]["derived_from_clock"], False)
        self.assertEqual(fixture["genesis_receipt"]["observed_at"], "SUPPLIED_HB_EPOCH:446655631")
        self.assertIsNone(pt.record_epoch_failure(fixture["genesis_receipt"]))

    def test_any_other_typed_schema_is_refused_with_six_fields(self):
        other = {**self.row["typed_body"], "schema": "stegverse.node-ingress-signal/v1"}
        row = {**self.row, "typed_body": other, "typed_body_sha256": pt.sha(other)}
        self.assert_six(pt.typed_refusal(row), "FAIL_CLOSED", "INTR_PATH_TYPED_BODY_SCHEMA_NOT_ALLOWLISTED")
        self.assert_six(self.refused_append(row), "FAIL_CLOSED", "INTR_PATH_TYPED_BODY_SCHEMA_NOT_ALLOWLISTED")
        for body in ({"schema": None}, "not an object", {}):
            r = {**self.row, "typed_body": body, "typed_body_sha256": pt.sha(body)}
            self.assert_six(pt.typed_refusal(r), "FAIL_CLOSED", "INTR_PATH_TYPED_BODY_SCHEMA_NOT_ALLOWLISTED")

    def test_unsealed_or_nonconformant_typed_rows_are_refused(self):
        unsealed = {**self.row, "typed_body_sha256": "sha256:" + "b" * 64}
        self.assert_six(self.refused_append(unsealed), "DENY", "INTR_PATH_TYPED_BODY_UNSEALED")
        body = self.row["typed_body"]
        cases = {
            "extra body key": {**body, "extra": 1},
            "other signal class": {**body, "signal_class": "NODE_INGRESS_SIGNAL"},
            "foreign repository": {**body, "repository": "StegVerse-Labs/LLM-adapter"},
            "self": {**body, "repository": "StegVerse-org/.github"},
            "other node_ref": {**body, "node_ref": "n-1"},
            "bad genesis": {**body, "genesis_receipt_sha256": "abc"},
            "other ledger location": {**body, "ledger_location": "StegVerse-org/.github#refs/heads/main:x"},
        }
        for name, b in cases.items():
            with self.subTest(name=name):
                self.assert_six(pt.typed_refusal({**self.row, "typed_body": b, "typed_body_sha256": pt.sha(b)}),
                                "FAIL_CLOSED", "INTR_PATH_TYPED_BODY_NONCONFORMANT")
        for name, row in {"path": {**self.row, "path_id": "StegVerse-org->SV-011:intr-destination"},
                          "location": {**self.row, "destination_location":
                                       "refs/stegverse/organization-ledger:repository-ledger/StegVerse-org/Other"},
                          "extra row key": {**self.row, "note": "x"},
                          "missing row key": {k: v for k, v in self.row.items() if k != "typed_body_sha256"}}.items():
            with self.subTest(name=name):
                self.assert_six(pt.typed_refusal(row), "FAIL_CLOSED", "INTR_PATH_TYPED_BODY_NONCONFORMANT")
        for kind in ("NODE_INGRESS_SIGNAL", None, "org"):
            self.assert_six(pt.typed_refusal({**self.row, "endpoint_kind": kind}), "FAIL_CLOSED",
                            "INTR_PATH_ENDPOINT_KIND_UNDECLARED")
        bad_cid = {**self.row, "communication_id": "has space"}
        self.assert_six(pt.typed_refusal(bad_cid), "FAIL_CLOSED", "INTR_PATH_MESSAGE_NONCONFORMANT")

    def test_a_gateway_endpoint_never_carries_an_external_ledger_ref(self):
        gw = {**self.row, "endpoint_kind": "GATEWAY"}
        body = self.row["typed_body"]
        cases = {
            "row ledger_root": {**gw, "ledger_root": "/srv/node-ledger"},
            "row external_ledger_ref": {**gw, "external_ledger_ref": "StegVerse-Labs/x#refs/stegverse/ledger"},
            "body ledger_root": {**gw, "typed_body": {**body, "ledger_root": "/x"},
                                 "typed_body_sha256": pt.sha({**body, "ledger_root": "/x"})},
            "foreign location": {**gw, "destination_location": "StegVerse-Labs/.github#refs/stegverse/organization-ledger:x"},
            "url location": {**gw, "destination_location": "https://example.invalid/ledger"},
            "other ref": {**gw, "destination_location": "refs/heads/ledger:node-ledger/StegVerse-org/n-1"},
            "escaping location": {**gw, "destination_location": "refs/stegverse/organization-ledger:../../x"},
        }
        for name, row in cases.items():
            with self.subTest(name=name):
                self.assert_six(pt.typed_refusal(row), "DENY", "INTR_PATH_GATEWAY_CARRIES_EXTERNAL_LEDGER_REF")
        self.assert_six(self.refused_append(cases["row ledger_root"]), "DENY",
                        "INTR_PATH_GATEWAY_CARRIES_EXTERNAL_LEDGER_REF")
        # a GATEWAY row with no external ref is still an endpoint, never a source of org-ledger records
        self.assert_six(pt.typed_refusal(gw), "FAIL_CLOSED", "ENDPOINT_NOT_AN_ORG_LEDGER_SOURCE")

    def test_no_endpoint_is_a_source_of_org_ledger_records(self):
        """Rigel (#160 comment 6372871021): no endpoint, externally or ecosystem maintained, is an Organization
        member or a source of org-ledger records; only ORG rows land on the org ledger, and nothing is written."""
        head = "sha256:" + "ab" * 32
        for kind in ("EPHEMERAL", "PERMANENT", "GATEWAY", "KV", "SKAP_VAULT"):
            with self.subTest(kind=kind):
                row = {**self.row, "endpoint_kind": kind, "endpoint_head_sha256": head}
                refused = pt.typed_refusal(row)
                self.assert_six(refused, "FAIL_CLOSED", "ENDPOINT_NOT_AN_ORG_LEDGER_SOURCE")
                self.assertEqual(refused["failed_predicate"],
                                 "INTR_PATH_TYPED_ROW_LANDS_ONLY_THE_ORGS_OWN_RECORD_NO_ENDPOINT_IS_A_SOURCE_OF_ORG_LEDGER_RECORDS")
        self.assert_six(self.refused_append({**self.row, "endpoint_kind": "PERMANENT"}), "FAIL_CLOSED",
                        "ENDPOINT_NOT_AN_ORG_LEDGER_SOURCE")
        self.assertIsNone(pt.typed_refusal(self.row))

    def test_kv_and_skap_rows_must_record_the_endpoint_head_digest(self):
        # Lane D condition 2 (StegVerse-org/.github#160 comment 6372216673): the Org-side linked receipt records the
        # independent endpoint's head digest; required for KV and SKAP_VAULT, a digest only
        head = "sha256:" + "ab" * 32
        for kind in ("KV", "SKAP_VAULT"):
            with self.subTest(kind=kind):
                self.assert_six(pt.typed_refusal({**self.row, "endpoint_kind": kind}), "FAIL_CLOSED",
                                "INTR_PATH_ENDPOINT_HEAD_DIGEST_MISSING")
                # with the digest the row passes this check and is still not an admitted path or schema kind
                later = pt.typed_refusal({**self.row, "endpoint_kind": kind, "endpoint_head_sha256": head})
                self.assertNotIn(later["failure_code"], ("INTR_PATH_ENDPOINT_HEAD_DIGEST_MISSING",
                                                         "INTR_PATH_ENDPOINT_HEAD_NOT_A_DIGEST"))
                self.assertEqual(later["disposition"], "FAIL_CLOSED")
        for bad in ("refs/stegverse/kv-ledger:01_KV_Ledger", "gdrive://folder/HEAD", "sha256:" + "AB" * 32,
                    "sha256:" + "ab" * 31, None, 7):
            with self.subTest(bad=bad):
                self.assert_six(pt.typed_refusal({**self.row, "endpoint_kind": "KV", "endpoint_head_sha256": bad}),
                                "DENY", "INTR_PATH_ENDPOINT_HEAD_NOT_A_DIGEST")
        self.assert_six(self.refused_append({**self.row, "endpoint_kind": "KV"}), "FAIL_CLOSED",
                        "INTR_PATH_ENDPOINT_HEAD_DIGEST_MISSING")

    def test_the_endpoint_head_digest_is_optional_and_rides_in_boundary_evidence(self):
        """Reuse boundary_evidence (#167 comment 6372442705, ruling 2): a row without the field is byte-identical."""
        head = "sha256:" + "cd" * 32
        plain = pt.typed_path_evidence(self.row, TRANSFER, MT)
        self.assertNotIn("endpoint_head_sha256", plain)
        self.assertNotIn("endpoint_head_sha256", plain["boundary_evidence"])
        row = {**self.row, "endpoint_head_sha256": head}
        self.assertIsNone(pt.typed_refusal(row))
        ev = pt.typed_path_evidence(row, TRANSFER, MT)
        self.assertNotIn("endpoint_head_sha256", ev)
        self.assertEqual(ev["boundary_evidence"]["endpoint_head_sha256"], head)
        self.assertEqual({k: v for k, v in ev.items() if k != "boundary_evidence"},
                         {k: v for k, v in plain.items() if k != "boundary_evidence"})
        self.assertEqual({k: v for k, v in ev["boundary_evidence"].items() if k != "endpoint_head_sha256"},
                         plain["boundary_evidence"])
        source = Path(pt.__file__).read_text()
        self.assertIn("**({ENDPOINT_HEAD_KEY: row[ENDPOINT_HEAD_KEY]}", source)   # and on the Org receipt boundary

    def test_a_crossing_is_recorded_by_both_sides(self):
        """Rigel, StegVerse-org/.github#162 comment 6372641743: egress on the source side, ingress on the destination
        side, each pointing at the other by digest, each with a supplied epoch. One-sided: six fields."""
        source = json.loads(TYPED.read_text())["source_receipt"]
        dest = destination_record(source)
        self.assertIsNone(pt.typed_crossing_failure(source, dest))
        self.assertNotIn("receipt_sha256", dest["evidence"])     # a pointer to the egress, not its body
        for side, (s, d) in {"SOURCE_ONLY": (source, None), "DESTINATION_ONLY": (None, dest),
                             "NEITHER": (None, None)}.items():
            with self.subTest(side=side):
                got = pt.typed_crossing_failure(s, d)
                self.assert_six(got, "FAIL_CLOSED", "INTR_CROSSING_NOT_RECORDED_BY_BOTH_SIDES")
                self.assertEqual((got["one_sided"], got["failed_predicate"]),
                                 (side, "EACH_CROSSING_RECORDED_BY_BOTH_ENDPOINTS"))
        other = dict(dest)
        other["evidence"] = {**dest["evidence"], "source_repository_receipt_sha256": "sha256:" + "e" * 64}
        other = destination_record(source, evidence=other["evidence"])
        self.assert_six(pt.typed_crossing_failure(source, other), "DENY", "INTR_CROSSING_NOT_RECORDED_BY_BOTH_SIDES")
        unsealed = {**dest, "transition_class": "INTR_MESH_PATH_INGRESS", "authority_effect": "X"}
        self.assert_six(pt.typed_crossing_failure(source, unsealed), "FAIL_CLOSED",
                        "INTR_CROSSING_NOT_RECORDED_BY_BOTH_SIDES")

    def test_a_valid_both_sides_crossing_fires_neither_endpoint_code(self):
        """Coordination (#167, provisional): an endpoint's own side of a crossing is in its own chain and the Org
        records only its own digest-only side; that is not a ledger source, so neither ENDPOINT_NOT_AN_ORG_LEDGER_SOURCE
        nor ENDPOINT_ORG_MEMBERSHIP_REFUSED fires on a valid both-sides crossing."""
        holder, decl = declaration_with(self.row)
        ledger = Ledger()
        try:
            self.assertIsNone(pt.typed_refusal(self.row))
            results = pt.append_transfers(TRANSFER, declaration=decl)
            source = pt.mt._receipt(pt.mt.repo_store(), results[-1]["repository_receipt_sha256"])
            dest = destination_record(source)
            self.assertIsNone(pt.typed_crossing_failure(source, dest))
            both = pt.verify_typed_crossing(self.row, dest)
            self.assertEqual((both["disposition"], both["recorded_by_both_sides"]), ("ALLOW", True), both)
            seen = json.dumps([results, source, dest, both])
            for code in ("ENDPOINT_NOT_AN_ORG_LEDGER_SOURCE", "ENDPOINT_ORG_MEMBERSHIP_REFUSED"):
                self.assertNotIn(code, seen)
        finally:
            ledger.close()
            holder.cleanup()
        self.assertEqual(pt.ENDPOINT_NOT_ORG_SOURCE, "ENDPOINT_NOT_AN_ORG_LEDGER_SOURCE")
        self.assertNotIn("INTR_PATH_ENDPOINT_NOT_AN_ORG_LEDGER_SOURCE", Path(pt.__file__).read_text().replace(
            "Renamed from INTR_PATH_ENDPOINT_NOT_AN_ORG_LEDGER_SOURCE", ""))

    def test_a_crossing_record_without_a_supplied_epoch_is_refused(self):
        source = json.loads(TYPED.read_text())["source_receipt"]
        hb = synthetic_genesis()["hb_reference"]
        cases = {"clock-derived ingress": (destination_record(source, hb_reference={**hb, "derived_from_clock": True}),
                                           "HB_EPOCH_INVALID"),
                 "no hb_reference": (destination_record(source, hb_reference=None), "HB_EPOCH_NOT_SUPPLIED"),
                 "epoch below HB32": (destination_record(source, hb_reference={**hb, "epoch": 7}), "HB_EPOCH_INVALID"),
                 "clock observed_at": (destination_record(source, observed_at="2026-10-23T19:00:00+00:00"),
                                       "HB_EPOCH_INVALID")}
        for name, (dest, code) in cases.items():
            with self.subTest(name=name):
                got = pt.typed_crossing_failure(source, dest)
                self.assert_six(got, "FAIL_CLOSED", code)
                self.assertEqual(got["failed_predicate"], "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH")
        clocked = {k: v for k, v in source.items() if k != "receipt_sha256"}
        clocked["hb_reference"] = {**clocked["hb_reference"], "derived_from_clock": True}
        clocked = {**clocked, "receipt_sha256": pt.sha(clocked)}
        self.assert_six(pt.typed_crossing_failure(clocked, destination_record(clocked)), "FAIL_CLOSED",
                        "HB_EPOCH_INVALID")

    def test_verify_typed_crossing_reads_the_source_half_off_the_ledger(self):
        holder, decl = declaration_with(self.row)
        ledger = Ledger()
        try:
            self.assert_six(pt.verify_typed_crossing(self.row, None), "FAIL_CLOSED", "INTR_PATH_RECEIPT_NOT_LEDGERED")
            fixture_source = json.loads(TYPED.read_text())["source_receipt"]
            got = pt.verify_typed_crossing(self.row, destination_record(fixture_source))
            self.assert_six(got, "FAIL_CLOSED", "INTR_CROSSING_NOT_RECORDED_BY_BOTH_SIDES")
            self.assertEqual(got["one_sided"], "DESTINATION_ONLY")
            typed = pt.append_transfers(TRANSFER, declaration=decl)[-1]
            source = pt.mt._receipt(pt.mt.repo_store(), typed["repository_receipt_sha256"])
            got = pt.verify_typed_crossing(self.row, None)
            self.assert_six(got, "FAIL_CLOSED", "INTR_CROSSING_NOT_RECORDED_BY_BOTH_SIDES")
            self.assertEqual(got["one_sided"], "SOURCE_ONLY")
            both = pt.verify_typed_crossing(self.row, destination_record(source))
            self.assertEqual((both["disposition"], both["recorded_by_both_sides"]), ("ALLOW", True), both)
        finally:
            ledger.close()
            holder.cleanup()

    def test_endpoint_paths_are_a_data_row_list_with_no_row_yet(self):
        mesh = pt.intr.load_contract()["mesh_path_transfer"]
        self.assertEqual(mesh["endpoint_paths"], [])
        self.assertIn("6372216673", mesh["endpoint_paths_note"])
        self.assertEqual(pt.endpoint_paths(), [])
        self.assertIsNone(pt.endpoint_path("01_KV_Ledger->StegVerse-org:intr-destination"))

    def test_the_intra_org_path_is_a_data_row_of_the_existing_path_schema(self):
        rows = pt.intra_org_paths()
        self.assertEqual([r["path_id"] for r in rows], [pt.typed_path_id()])
        row = rows[0]
        mesh = pt.declared_paths()[0]
        for key in ("path_id", "source", "destination", "capability"):   # the declared_paths row keys, reused
            self.assertIn(key, mesh)
            self.assertIsInstance(row[key], str)
        self.assertEqual((row["source"], row["destination"], row["capability"]),
                         (pt.repository(), pt.organization(), pt.CAPABILITY))
        self.assertEqual(row["endpoint_kinds"], ["ORG"])
        self.assertEqual(row["typed_body_schemas"], sorted(pt.TYPED_BODY_SCHEMAS))
        self.assertTrue(self.row["destination_location"].startswith(row["destination_location_prefix"]))
        self.assertEqual(pt.intra_org_path(self.row["path_id"]), row)
        # not a mesh path: the untyped declared paths are unchanged
        self.assertNotIn(pt.typed_path_id(), [m["path_id"] for m in pt.declared_paths()])

    def test_a_typed_row_on_an_undeclared_intra_org_path_is_refused(self):
        from unittest import mock
        with mock.patch.object(pt, "intra_org_paths", return_value=[]):
            self.assert_six(pt.typed_refusal(self.row), "FAIL_CLOSED", "INTR_PATH_INTRA_ORG_PATH_UNDECLARED")
        narrowed = [{**pt.intra_org_paths()[0], "endpoint_kinds": ["PERMANENT"]}]
        with mock.patch.object(pt, "intra_org_paths", return_value=narrowed):
            self.assert_six(pt.typed_refusal(self.row), "FAIL_CLOSED", "INTR_PATH_INTRA_ORG_PATH_UNDECLARED")
        self.assertIsNone(pt.typed_refusal(self.row))

    def readback(self, **block):
        g = self.genesis["receipt_sha256"]
        base = {"namespace": "repository-ledger/" + LLM_ADAPTER, "genesis_receipt_sha256": g,
                "head_receipt_sha256": g, "chain_length": 1,
                "chain": [{"receipt_sha256": g, "previous_receipt_sha256": None,
                           "transition_id": "REPOSITORY_LEDGER_INITIALIZATION:" + LLM_ADAPTER,
                           "transition_class": "REPOSITORY_LEDGER_INITIALIZATION"}],
                "every_receipt_verifies_against_its_body": True,
                "every_receipt_retained_in_organization_ledger": True, "replay_read_organization_receipts": False}
        return {"schema": "stegverse.organization-ledger-readback/v1", "repository_ledger": {**base, **block}}

    def test_the_genesis_append_read_back_emits_the_typed_row(self):
        """Reuse-first trigger: the genesis append's own read-back yields exactly the typed row; landing it in
        transfers.json is the existing path-transfer transition."""
        self.assertEqual(pt.genesis_observed_row_from_readback(self.readback()), self.row)
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "readback.json"
            f.write_text(json.dumps(self.readback()))
            out = subprocess.run([sys.executable, str(ROOT / "resident-runtime/intr_path_transfer.py"), "typed-row",
                                  "--from-readback", str(f)], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(json.loads(out.stdout), self.row)

    def test_a_read_back_without_a_genesis_emits_nothing(self):
        g = self.genesis["receipt_sha256"]
        for bad in (self.readback(chain=[]),
                    self.readback(chain=[{"receipt_sha256": g, "previous_receipt_sha256": None,
                                          "transition_class": "INTR_MESH_PATH_TRANSFER"}]),
                    self.readback(genesis_receipt_sha256="sha256:" + "0" * 64),
                    self.readback(every_receipt_retained_in_organization_ledger=False),
                    self.readback(namespace="somewhere-else"),
                    {**self.readback(), "disposition": "FAIL_CLOSED"}, {}, None):
            with self.subTest(bad=bad):
                self.assert_six(pt.genesis_observed_row_from_readback(bad), "FAIL_CLOSED",
                                "INTR_PATH_GENESIS_NOT_READ_BACK")

    def test_no_new_workflow_and_the_path_workflows_are_unchanged(self):
        for name in ("intr-path-transfer.yml", "intr-path-ingress.yml", "intr-path-transfer-validation.yml",
                     "organization-ledger-transition.yml"):
            path = ".github/workflows/" + name
            blob = subprocess.run(["git", "-C", str(ROOT), "show", MAIN + ":" + path], check=True,
                                  capture_output=True).stdout
            self.assertEqual((ROOT / path).read_bytes(), blob, path)
        source = (ROOT / "resident-runtime/intr_path_transfer.py").read_text()
        import ast
        names = set()
        for n in ast.walk(ast.parse(source)):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                names.add((n.module or "").split(".")[0])
        self.assertEqual(names, {"__future__", "argparse", "importlib", "json", "sys", "pathlib", "typing"})


if __name__ == "__main__":
    unittest.main()
