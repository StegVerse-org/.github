#!/usr/bin/env python3
"""Read the organization ledger back and verify it, independently of the writer.

A transition is runtime reality only once the organization ledger holds it, so
the evidence of an append is a readback from the ledger itself, not the
writer's own report. This opens the ledger at the location it is given (for the
designated ref, a fresh fetch of `refs/stegverse/organization-ledger`). It walks
the chain from HEAD and checks, for every receipt:

- its `receipt_sha256` is the digest of its own body;
- `previous_receipt_sha256` names the receipt before it, ending at genesis
  (null), so the chain has no gaps and no forks;
- the source receipt it consumed is retained under `source-receipts/` and
  verifies against its own body.

Given an ingress result (`--ingress-result`), it also checks that the result's
organization receipt is in the chain, and that it is bound to the submitted
manifest: its predecessor state is the canonical manifest digest.

Every refusal carries the six fields of a non-ALLOW. Stdlib and `git` only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ledger_store import HEAD_KEY, open_store, parse_locator, receipt_key, source_key  # noqa: E402

RETRY = "resident-runtime/organization_ledger_readback.py::main"
GOAL = "LLMA-DECLARED-PATH-CONFORMANCE-368"


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(value):
    return "sha256:" + hashlib.sha256(canon(value)).hexdigest()


class ReadbackRefused(Exception):
    def __init__(self, failed_predicate, detail):
        super().__init__(failed_predicate + ": " + detail)
        self.failed_predicate = failed_predicate
        self.detail = detail


def self_verifies(document):
    body = {key: value for key, value in document.items() if key != "receipt_sha256"}
    return document.get("receipt_sha256") == sha(body)


def readback(location, ingress_result=None, manifest=None):
    store = open_store(parse_locator(location))
    head = store.get(HEAD_KEY)
    if head is None:
        raise ReadbackRefused("ORGANIZATION_LEDGER_HEAD_PRESENT", "no HEAD at " + location)
    chain, cursor, seen = [], head.get("receipt_sha256"), set()
    while cursor is not None:
        if cursor in seen:
            raise ReadbackRefused("ORGANIZATION_LEDGER_CHAIN_IS_ACYCLIC", cursor)
        seen.add(cursor)
        receipt = store.get(receipt_key(cursor))
        if receipt is None:
            raise ReadbackRefused("ORGANIZATION_LEDGER_CHAIN_IS_COMPLETE", "missing " + cursor)
        if receipt.get("receipt_sha256") != cursor or not self_verifies(receipt):
            raise ReadbackRefused("ORGANIZATION_RECEIPT_VERIFIES_AGAINST_ITS_BODY", cursor)
        source_digest = receipt.get("source_transition_sha256")
        source = store.get(source_key(source_digest)) if source_digest else None
        if source is None or source.get("receipt_sha256") != source_digest or not self_verifies(source):
            raise ReadbackRefused("SOURCE_RECEIPT_RETAINED_AND_VERIFIES", str(source_digest))
        chain.append(receipt)
        cursor = receipt.get("previous_receipt_sha256")
    chain.reverse()
    result = {
        "schema": "stegverse.organization-ledger-readback/v1",
        "location": location,
        "disposition": "ALLOW",
        "head_receipt_sha256": head["receipt_sha256"],
        "chain_length": len(chain),
        "genesis_receipt_sha256": chain[0]["receipt_sha256"],
        "chain": [{"receipt_sha256": r["receipt_sha256"],
                   "previous_receipt_sha256": r.get("previous_receipt_sha256"),
                   "source_transition_id": r.get("source_transition_id"),
                   "predecessor_org_state_sha256": r.get("predecessor_org_state_sha256"),
                   "successor_org_state_sha256": r.get("successor_org_state_sha256")} for r in chain],
        "every_receipt_verifies_against_its_body": True,
        "every_source_receipt_retained_and_verifies": True,
        "authority_effect": "NONE_READBACK_ONLY",
    }
    if ingress_result is not None:
        # A refusal is recorded too, under its own name, and is bound to the
        # submitted manifest's digest rather than the canonical one.
        refused = ingress_result.get("refusal_organization_receipt_sha256") is not None
        digest = ingress_result.get("refusal_organization_receipt_sha256" if refused
                                    else "organization_receipt_sha256")
        receipt = next((r for r in chain if r["receipt_sha256"] == digest), None)
        if receipt is None:
            raise ReadbackRefused("INGRESS_RECEIPT_IS_IN_THE_ORGANIZATION_LEDGER", str(digest))
        if refused:
            manifest_state = sha(manifest) if manifest is not None else None
        else:
            manifest_state = "sha256:" + str(ingress_result.get("canonical_manifest_sha256"))
        if not manifest_state or receipt.get("predecessor_org_state_sha256") != manifest_state:
            raise ReadbackRefused("RECEIPT_IS_BOUND_TO_THE_SUBMITTED_MANIFEST", str(manifest_state))
        result.update({
            "ingress_disposition": ingress_result.get("disposition"),
            "ingress_refused": refused,
            "ingress_organization_receipt_sha256": digest,
            "ingress_receipt_in_chain": True,
            "ingress_receipt_bound_to_manifest": True,
            "canonical_manifest_sha256": ingress_result.get("canonical_manifest_sha256"),
            "organization_transition_id": ingress_result.get("organization_transition_id"),
            "master_records_awaited": False,
        })
    return result


def _repository_emitter():
    """The repository ledger's own chain walker, so the readback verifies nodes the way the writer does."""
    import importlib.util
    emit = Path(__file__).resolve().parents[1] / ".stegverse/transition-ledger/emit.py"
    spec = importlib.util.spec_from_file_location("repository_ledger_readback_emit", emit)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def repository_readback(location, namespace, organization_result, ingress_result=None):
    """Read the repository chain kept in `namespace` of the same ref back and verify it.

    The repository ledger is durable only if its chain survives the run that
    wrote it, so this walks `repository-ledger/<repository>/HEAD.json` back
    through repository receipts alone -- never an organization receipt, as the
    repository replay rule requires -- and checks every node the way the
    emitter does. Each repository receipt in the chain must also be retained
    byte-for-byte by the organization ledger it was consumed into. Given an
    ingress result, the repository receipt it names must be in this chain and
    be the source the ingress's organization receipt consumed.
    """
    emitter = _repository_emitter()
    locator = parse_locator(location)
    repository_location = str(locator) + ":" + namespace
    store = open_store(repository_location)
    organization_store = open_store(locator)
    head = store.get(HEAD_KEY)
    if head is None:
        raise ReadbackRefused("REPOSITORY_LEDGER_HEAD_PRESENT", "no HEAD at " + repository_location)
    try:
        chain = list(emitter.chain(store, head))
    except emitter.RepoLedgerChainBreak as exc:
        raise ReadbackRefused("REPOSITORY_CHAIN_VERIFIES", str(exc)) from None
    chain.reverse()
    for receipt in chain:
        retained = organization_store.get(source_key(receipt["receipt_sha256"]))
        if retained != receipt:
            raise ReadbackRefused("REPOSITORY_RECEIPT_RETAINED_IN_ORGANIZATION_LEDGER",
                                  receipt["receipt_sha256"])
    result = {
        "location": repository_location,
        "namespace": namespace,
        "head_receipt_sha256": head["receipt_sha256"],
        "chain_length": len(chain),
        "genesis_receipt_sha256": chain[0]["receipt_sha256"],
        "chain": [{"receipt_sha256": r["receipt_sha256"],
                   "previous_receipt_sha256": r.get("previous_receipt_sha256"),
                   "transition_id": r.get("transition_id"),
                   "transition_class": r.get("transition_class")} for r in chain],
        "every_receipt_verifies_against_its_body": True,
        "every_receipt_retained_in_organization_ledger": True,
        "replay_read_organization_receipts": False,
    }
    if ingress_result is not None:
        refused = ingress_result.get("refusal_organization_receipt_sha256") is not None
        digest = ingress_result.get("refusal_repository_receipt_sha256" if refused
                                    else "repository_receipt_sha256")
        if not any(r["receipt_sha256"] == digest for r in chain):
            raise ReadbackRefused("INGRESS_REPOSITORY_RECEIPT_IS_IN_THE_REPOSITORY_LEDGER", str(digest))
        organization_digest = organization_result["ingress_organization_receipt_sha256"]
        consumed = organization_store.get(receipt_key(organization_digest)) or {}
        if consumed.get("source_transition_sha256") != digest:
            raise ReadbackRefused("ORGANIZATION_RECEIPT_CONSUMES_THE_REPOSITORY_RECEIPT", str(digest))
        result.update({"ingress_repository_receipt_sha256": digest,
                       "ingress_repository_receipt_in_chain": True,
                       "consumed_by_organization_receipt_sha256": organization_digest})
    return result


def recorded_for(location, canonical_manifest_sha256):
    """The verified receipt already binding this manifest, or None.

    One manifest is one transition. A request submitted again is answered from
    the ledger rather than appended a second time.
    """
    try:
        verified = readback(location)
    except ReadbackRefused as exc:
        if exc.failed_predicate == "ORGANIZATION_LEDGER_HEAD_PRESENT":
            return None
        raise
    state = "sha256:" + canonical_manifest_sha256
    return next((r["receipt_sha256"] for r in verified["chain"]
                 if r["predecessor_org_state_sha256"] == state), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--location", required=True, help="ledger locator, e.g. git+<repo>#<ref>")
    parser.add_argument("--ingress-result", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None,
                        help="the submitted manifest; binds a recorded refusal to it")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--recorded-for", metavar="CANONICAL_MANIFEST_SHA256", default=None,
                        help="print the receipt already binding this manifest, or nothing")
    parser.add_argument("--repository-namespace", default=None,
                        help="also read back the repository chain kept in this subtree of the same ref")
    args = parser.parse_args()
    if args.recorded_for:
        print(recorded_for(args.location, args.recorded_for) or "")
        return 0
    ingress = json.loads(args.ingress_result.read_text()) if args.ingress_result else None
    manifest = json.loads(args.manifest.read_text()) if args.manifest else None
    try:
        result, code = readback(args.location, ingress, manifest), 0
        if args.repository_namespace:
            result["repository_ledger"] = repository_readback(
                args.location, args.repository_namespace, result, ingress)
    except (ReadbackRefused, ValueError, RuntimeError, FileNotFoundError) as exc:
        result, code = {
            "schema": "stegverse.organization-ledger-readback/v1",
            "location": args.location,
            "disposition": "FAIL_CLOSED",
            "failure_code": "ORGANIZATION_LEDGER_READBACK_FAILED",
            "failed_predicate": getattr(exc, "failed_predicate", "ORGANIZATION_LEDGER_READS_BACK"),
            "required_evidence_or_repair": getattr(exc, "detail", str(exc)),
            "retry_entrypoint": RETRY,
            "owning_existing_goal": GOAL,
            "next_attempt": "fetch the ledger ref again and rerun the readback; nothing is written by it",
            "authority_effect": "NONE_READBACK_ONLY",
        }, 1
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
