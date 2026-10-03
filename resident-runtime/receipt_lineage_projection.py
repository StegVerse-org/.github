#!/usr/bin/env python3
"""Project a receipt chain into the lineage record shape, deriving what it needs.

`Admissible-Existence/RE`'s lineage contract asks each record for `receipt_id`,
`event_type`, `predecessor_id`, `payload_hash` and `sequence`. A StegVerse
receipt carries the first, third and fourth under different names and neither of
the other two, so a real chain fed to RE's `validate_re_lineage.evaluate`
returns `FAIL_CLOSED` as stored.

Both missing fields are derivable, so nothing is stored and no repository that
writes receipts changes:

    ORIGINAL     the receipt with no predecessor -- the first receipt of the
                 chain, which is what RE requires a new process to mark
    SUPPLEMENT   an ordinary append: it adds to the chain without superseding
                 anything, which is every transition this ecosystem currently
                 emits
    CORRECTION   the receipt names a prior receipt it corrects
    INVALIDATION the receipt names a prior receipt it voids

`sequence` is chain position. All of it comes from `previous_receipt_sha256`,
which every receipt already carries, plus two optional evidence fields that
appear only on a transition that actually supersedes or voids one.

A projection, not a migration. The ledger is untouched and read-only here. A
receipt is committed evidence and the shape it was minted in is part of what it
is, so the lineage shape is computed on read -- the same reason
`tools/check_re_obligation_evidence.py` normalises RE's own receipts for
comparison rather than rewriting them.

RE judges, this does not. The rules about what makes a lineage reconstructable
-- that corrections must not erase predecessors, that invalidations must
reference existing receipts, that reordered history fails closed -- live in
RE's contract and its validator enforces them. Restating them here would be a
second authority on that shape, and the stale one, so this module produces the
records faithfully and lets RE's own evaluator decide. CI pins RE and runs it.

What *is* checked here is this ecosystem's own integrity rule, because a
projection built on a receipt whose digest does not recompute would be
presenting a lineage that does not hold: every receipt is verified against its
own body before it is projected.

Nothing here grants authority. RE's contract says so itself --
`lineage_reconstruction_creates_authority: false` -- and a projection of a chain
is not a transition on it.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]

PROJECTION_SCHEMA = "stegverse.receipt-lineage-projection/v1"
#: The contract this projection targets, by reference rather than by copy.
LINEAGE_CONTRACT = "Admissible-Existence/RE:data/re-lineage-contract.json"
LINEAGE_VALIDATOR = "Admissible-Existence/RE:validators/validate_re_lineage.py"

#: The shape this projection produces. Declared here as this module's own
#: output contract, which is a different thing from restating RE's rules about
#: what makes a lineage reconstructable -- those stay in RE, and RE's validator
#: enforces them. `Admissible-Existence/RE` is private, so a cross-organization
#: checkout would need a credential secret and `github_token_runtime_authority`
#: is NONE; each repository therefore asserts what it owns. This repository's CI
#: holds the projection to this shape; RE's CI holds a projected chain to its
#: own validator.
PROJECTED_FIELDS = ("receipt_id", "event_type", "predecessor_id",
                    "payload_hash", "sequence")

ORIGINAL = "ORIGINAL"
CORRECTION = "CORRECTION"
INVALIDATION = "INVALIDATION"
SUPPLEMENT = "SUPPLEMENT"

#: The two evidence fields that carry information the chain does not already
#: hold. Additive and optional: they appear only on a transition that supersedes
#: or voids a prior receipt, and nothing in this ecosystem writes them yet.
CORRECTS_FIELD = "corrects_receipt_sha256"
INVALIDATES_FIELD = "invalidates_receipt_sha256"

REPOSITORY = "REPOSITORY"
ORGANIZATION = "ORGANIZATION"


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


repository_ledger = _module("repo_transition_emit", ".stegverse/transition-ledger/emit.py")
organization_ledger = _module("aggregate_repo_transition",
                              "resident-runtime/aggregate_repo_transition.py")
ledger_store = _module("ledger_store", "resident-runtime/ledger_store.py")


class LineageRefused(Exception):
    """A chain this projection will not present, carrying why."""


def _verified(receipt: Mapping[str, Any], digest: str, sha) -> dict[str, Any]:
    """A receipt that recomputes to the digest it is reached by, or a refusal."""
    body = dict(receipt)
    body.pop("receipt_sha256", None)
    if receipt.get("receipt_sha256") != digest or sha(body) != digest:
        raise LineageRefused("RECEIPT_DOES_NOT_VERIFY_AGAINST_ITS_OWN_BODY:" + digest)
    return dict(receipt)


def _walk(root: Path, sha) -> list[dict[str, Any]]:
    """The chain from HEAD backwards, reversed, each receipt verified.

    Walking from HEAD is what makes the order the chain's own rather than a
    directory listing's: a glob would present receipts in whatever order the
    filesystem offers, and `orphaned_or_reordered_history_fails_closed`.
    """
    store = ledger_store.PosixLedgerStore(root)
    head = store.get(ledger_store.HEAD_KEY)
    cursor = (head or {}).get("receipt_sha256")
    chain, seen = [], set()
    while cursor:
        if cursor in seen:
            raise LineageRefused("PREDECESSOR_CYCLE:" + cursor)
        seen.add(cursor)
        receipt = store.get(ledger_store.receipt_key(cursor))
        if receipt is None:
            raise LineageRefused("PREDECESSOR_MISSING:" + cursor)
        chain.append(_verified(receipt, cursor, sha))
        cursor = receipt.get("previous_receipt_sha256")
    chain.reverse()
    return chain


def repository_chain(root: Path | None = None) -> list[dict[str, Any]]:
    """This repository's own transition chain."""
    return _walk(Path(root) if root else repository_ledger.lr(), repository_ledger.sha)


def organization_chain(root: Path | None = None) -> list[dict[str, Any]]:
    """This organization's chain, which consumes the repository receipts."""
    return _walk(Path(root) if root else organization_ledger.ledger_root(),
                 organization_ledger.sha)


def _superseded(receipt: Mapping[str, Any], field: str) -> Any:
    """What this receipt names as superseded, from wherever its level puts it."""
    evidence = receipt.get("evidence")
    if isinstance(evidence, Mapping) and evidence.get(field):
        return evidence[field]
    return receipt.get(field)


def event_type(receipt: Mapping[str, Any]) -> str:
    """Which lineage event this receipt is, derived rather than read.

    Order matters. A receipt with no predecessor is the chain's ORIGINAL
    whatever else it says, because RE's lineage requires the first record to be
    one and there is nothing earlier for it to correct.
    """
    if receipt.get("previous_receipt_sha256") is None:
        return ORIGINAL
    # A repository receipt carries its detail under `evidence`; an organization
    # receipt carries it at the top level. A supersession field is read from
    # wherever the level puts it rather than from one assumed place.
    if _superseded(receipt, INVALIDATES_FIELD):
        return INVALIDATION
    if _superseded(receipt, CORRECTS_FIELD):
        return CORRECTION
    return SUPPLEMENT


#: The successor state digest, under each name a ledger gives it. The two levels
#: genuinely differ -- a repository receipt carries `successor_state_sha256`
#: while an organization receipt carries `successor_org_state_sha256` -- and
#: projecting only the first silently produced a null `payload_hash`, which RE
#: fails closed on. Read the field the level actually uses rather than assuming
#: one spelling.
SUCCESSOR_FIELDS = ("successor_state_sha256", "successor_org_state_sha256")


def successor_state(receipt: Mapping[str, Any]) -> Any:
    for field in SUCCESSOR_FIELDS:
        value = receipt.get(field)
        if value:
            return value
    return None


def lineage_record(receipt: Mapping[str, Any], sequence: int) -> dict[str, Any]:
    """One receipt as a lineage record.

    `payload_hash` is the successor state, because that is what this transition
    produced and what a reader reconstructing forward would recompute. The
    receipt's own digest is its identity, not its payload.
    """
    record = {
        "receipt_id": receipt["receipt_sha256"],
        "event_type": event_type(receipt),
        "predecessor_id": receipt.get("previous_receipt_sha256"),
        "payload_hash": successor_state(receipt),
        "sequence": sequence,
    }
    # Carried through only when the receipt actually names what it supersedes,
    # so an ordinary append projects without fields it does not have.
    for field in (CORRECTS_FIELD, INVALIDATES_FIELD):
        superseded = _superseded(receipt, field)
        if superseded:
            record[field] = superseded
    return record


def project(chain: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The chain as lineage records, in the chain's own order."""
    return [lineage_record(receipt, index + 1) for index, receipt in enumerate(chain)]


def projection(level: str = REPOSITORY, *, root: Path | None = None) -> dict[str, Any]:
    """Project a chain and report what was derived, without judging it.

    The verdict is RE's to give. This reports the records and what they were
    derived from, so RE's own validator can be run against them.
    """
    if level not in (REPOSITORY, ORGANIZATION):
        raise LineageRefused("UNKNOWN_LEDGER_LEVEL:" + str(level))
    chain = repository_chain(root) if level == REPOSITORY else organization_chain(root)
    records = project(chain)
    counts: dict[str, int] = {}
    for record in records:
        counts[record["event_type"]] = counts.get(record["event_type"], 0) + 1
    return {
        "schema": PROJECTION_SCHEMA,
        "level": level,
        "lineage_contract": LINEAGE_CONTRACT,
        "lineage_validator": LINEAGE_VALIDATOR,
        "verdict_is_res_to_give_not_this_projections": True,
        "records": records,
        "record_count": len(records),
        "event_type_counts": counts,
        "derived_not_stored": [
            "event_type derived from previous_receipt_sha256 and the two "
            "optional supersession fields",
            "sequence derived from chain position",
        ],
        "projected_fields": list(PROJECTED_FIELDS),
        "every_receipt_verified_against_its_own_body": True,
        "order_is_the_chains_own_from_head_backwards": True,
        "ledger_unchanged_by_this_projection": True,
        "lineage_reconstruction_creates_authority": False,
        "authority_effect": "NONE_PROJECTION_ONLY",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--level", choices=[REPOSITORY, ORGANIZATION], default=REPOSITORY)
    parser.add_argument("--ledger-root", default=None,
                        help="project this ledger instead of the resolved one")
    parser.add_argument("--records-only", action="store_true",
                        help="emit just the records, for a validator to read")
    parser.add_argument("--out")
    args = parser.parse_args()
    try:
        report = projection(args.level, root=args.ledger_root)
    except LineageRefused as refused:
        print(json.dumps({"schema": PROJECTION_SCHEMA, "level": args.level,
                          "refused": str(refused),
                          "authority_effect": "NONE_PROJECTION_ONLY"},
                         indent=2, sort_keys=True))
        return 1
    rendered = json.dumps(report["records"] if args.records_only else report,
                          indent=2, sort_keys=True)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
