#!/usr/bin/env python3
"""Read the organization ledger back and verify it, independently of the writer.

A transition is on the ledger only once a read of the ledger itself holds it.
This opens the location it is given (for the designated ref, a fresh fetch of
``refs/stegverse/organization-ledger``). It walks the chain from HEAD and
checks, for every receipt:

- its ``receipt_sha256`` is the digest of its own body;
- ``previous_receipt_sha256`` names the receipt before it, ending at genesis
  (null), so the chain has no gaps and no forks;
- the source receipt it consumed is retained under ``source-receipts/`` and
  verifies against its own body.

Given a closure result (``--closure-result``), it also checks that the
result's organization and repository receipts are in their chains and that
both carry the closure's ``communication_id``.

The repository chain is the subtree named by ``--repository-namespace``. That
walk reads repository receipts only.

Every refusal carries the six fields of a non-ALLOW. Authority and time are
constraint variables. The disposition is transition evidence only. Stdlib and
``git`` only.
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
GOAL = "StegVerse-org/.github#162 (intr-ingress-ledger/v1 organization ledger ref)"


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


def _chain(store):
    head = store.get(HEAD_KEY)
    if head is None:
        raise ReadbackRefused("ORGANIZATION_LEDGER_HEAD_PRESENT", "no HEAD")
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
    return head, chain


def readback(location, closure_result=None):
    store = open_store(parse_locator(location))
    try:
        head, chain = _chain(store)
    except ReadbackRefused as exc:
        if exc.failed_predicate == "ORGANIZATION_LEDGER_HEAD_PRESENT":
            raise ReadbackRefused(exc.failed_predicate, "no HEAD at " + str(location)) from None
        raise
    result = {
        "schema": "stegverse.organization-ledger-readback/v1",
        "location": str(location),
        "disposition": "ALLOW",
        "head_receipt_sha256": head["receipt_sha256"],
        "chain_length": len(chain),
        "genesis_receipt_sha256": chain[0]["receipt_sha256"],
        "chain": [{"receipt_sha256": receipt["receipt_sha256"],
                   "previous_receipt_sha256": receipt.get("previous_receipt_sha256"),
                   "source_transition_id": receipt.get("source_transition_id"),
                   "communication_id": (receipt.get("boundary_evidence") or {}).get("communication_id"),
                   "predecessor_org_state_sha256": receipt.get("predecessor_org_state_sha256"),
                   "successor_org_state_sha256": receipt.get("successor_org_state_sha256")}
                  for receipt in chain],
        "every_receipt_verifies_against_its_body": True,
        "every_source_receipt_retained_and_verifies": True,
        "authority_effect": "NONE_READBACK_ONLY",
        "routing_authority_constraint": "CONSTRAINT_VARIABLE",
        "admission_authority_constraint": "CONSTRAINT_VARIABLE",
        "execution_authority_constraint": "CONSTRAINT_VARIABLE",
        "time_constraint": "CONSTRAINT_VARIABLE",
        "disposition_role": "TRANSITION_EVIDENCE_ONLY",
    }
    if closure_result is not None:
        digest = closure_result.get("organization_receipt_sha256")
        receipt = next((item for item in chain if item["receipt_sha256"] == digest), None)
        if receipt is None:
            raise ReadbackRefused("CLOSURE_RECEIPT_IS_IN_THE_ORGANIZATION_LEDGER", str(digest))
        communication_id = closure_result.get("communication_id")
        evidence = receipt.get("boundary_evidence") if isinstance(receipt.get("boundary_evidence"), dict) else {}
        if not isinstance(communication_id, str) or not communication_id or evidence.get("communication_id") != communication_id:
            raise ReadbackRefused("CLOSURE_RECEIPT_CARRIES_THE_COMMUNICATION_ID", str(communication_id))
        result.update({
            "closure_disposition": closure_result.get("disposition"),
            "closure_organization_receipt_sha256": digest,
            "closure_receipt_in_chain": True,
            "closure_communication_id": communication_id,
            "closure_receipt_carries_communication_id": True,
            "master_records_awaited": False,
        })
    return result


def repository_readback(location, namespace, organization_result, closure_result=None):
    """Read the repository chain kept in ``namespace`` of the same ref.

    The walk reads repository receipts only. Each one must also be retained
    by the organization ledger that consumed it. Given a closure result, the
    repository receipt it names must be in this chain, be the source the
    organization receipt consumed, and carry the same ``communication_id``.
    """
    locator = parse_locator(location)
    repository_location = str(locator) + ":" + namespace
    store = open_store(repository_location)
    organization_store = open_store(locator)
    head = store.get(HEAD_KEY)
    if head is None:
        raise ReadbackRefused("REPOSITORY_LEDGER_HEAD_PRESENT", "no HEAD at " + repository_location)
    chain, cursor, seen = [], head.get("receipt_sha256"), set()
    while cursor is not None:
        if cursor in seen:
            raise ReadbackRefused("REPOSITORY_CHAIN_IS_ACYCLIC", cursor)
        seen.add(cursor)
        receipt = store.get(receipt_key(cursor))
        if receipt is None or receipt.get("receipt_sha256") != cursor or not self_verifies(receipt):
            raise ReadbackRefused("REPOSITORY_CHAIN_VERIFIES", str(cursor))
        if receipt.get("schema") != "stegverse.repo-transition-receipt/v1":
            raise ReadbackRefused("REPOSITORY_CHAIN_READS_REPOSITORY_RECEIPTS", str(cursor))
        retained = organization_store.get(source_key(receipt["receipt_sha256"]))
        if retained != receipt:
            raise ReadbackRefused("REPOSITORY_RECEIPT_RETAINED_IN_ORGANIZATION_LEDGER",
                                  receipt["receipt_sha256"])
        chain.append(receipt)
        cursor = receipt.get("previous_receipt_sha256")
    chain.reverse()
    result = {
        "location": repository_location,
        "namespace": namespace,
        "head_receipt_sha256": head["receipt_sha256"],
        "chain_length": len(chain),
        "genesis_receipt_sha256": chain[0]["receipt_sha256"],
        "chain": [{"receipt_sha256": receipt["receipt_sha256"],
                   "previous_receipt_sha256": receipt.get("previous_receipt_sha256"),
                   "transition_id": receipt.get("transition_id"),
                   "transition_class": receipt.get("transition_class"),
                   "communication_id": (receipt.get("evidence") or {}).get("communication_id")}
                  for receipt in chain],
        "every_receipt_verifies_against_its_body": True,
        "every_receipt_retained_in_organization_ledger": True,
        "replay_read_organization_receipts": False,
    }
    if closure_result is not None:
        digest = closure_result.get("repository_receipt_sha256")
        organization_digest = organization_result["closure_organization_receipt_sha256"]
        consumed = organization_store.get(receipt_key(organization_digest)) or {}
        if not any(receipt["receipt_sha256"] == digest for receipt in chain):
            raise ReadbackRefused("CLOSURE_REPOSITORY_RECEIPT_IS_IN_THE_REPOSITORY_LEDGER", str(digest))
        if consumed.get("source_transition_sha256") != digest and consumed.get("repo_receipt_sha256") != digest:
            raise ReadbackRefused("ORGANIZATION_RECEIPT_CONSUMES_THE_REPOSITORY_RECEIPT", str(digest))
        communication_id = closure_result.get("communication_id")
        matched = next(receipt for receipt in chain if receipt["receipt_sha256"] == digest)
        evidence = matched.get("evidence") if isinstance(matched.get("evidence"), dict) else {}
        if evidence.get("communication_id") != communication_id:
            raise ReadbackRefused("REPOSITORY_RECEIPT_CARRIES_THE_COMMUNICATION_ID", str(communication_id))
        result.update({"closure_repository_receipt_sha256": digest,
                       "closure_repository_receipt_in_chain": True,
                       "closure_repository_receipt_carries_communication_id": True,
                       "consumed_by_organization_receipt_sha256": organization_digest})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--location", required=True, help="ledger locator, e.g. git+<repo>#<ref>")
    parser.add_argument("--closure-result", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--repository-namespace", default=None,
                        help="also read back the repository chain kept in this subtree of the same ref")
    args = parser.parse_args()
    closure = json.loads(args.closure_result.read_text()) if args.closure_result else None
    try:
        result, code = readback(args.location, closure), 0
        if args.repository_namespace:
            result["repository_ledger"] = repository_readback(
                args.location, args.repository_namespace, result, closure)
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
