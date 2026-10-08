#!/usr/bin/env python3
"""Propagate repository transition receipts into the organization ledger.

`organization_scope_rule` is that every state transition occurring within the
organization emits an organization receipt. Repositories in this organization
append their own transitions to their own ledgers -- the LLM-adapter records a
node's arrival at its ingress boundary -- and nothing carried those receipts up,
so the organization's record began at its own boundary and the whole front half
of the path was absent from it.

Nothing about this is a crossing. The adapter and this repository are both in
`StegVerse-org`, so there is no organization boundary between them and no
Interlock/InTr involved; InTr is the inter-organization transport, and the hop
that needs it is organization to `master-records/.github`. A repository ledger
is addressed, not located: `ledger_store` exists so the chain is reachable by
key on whatever substrate holds it, and on one node the repository and
organization ledgers are sibling addresses under one state home.

The organization ledger already admitted these receipts. `verify_source` takes
any `repository` inside this organization and binds the receipt by its own
digest, and `aggregate_repo_transition` already exposed `--repo-receipt`. What
was missing was the step that walks a repository's chain and hands the receipts
over, in order, exactly once.

Order and exactly-once are the whole job. Receipts are propagated in repository
chain order, so the organization's record of a repository cannot imply a
sequence the repository never had. Each is verified against its own body before
it is propagated, because propagating an unverified receipt would put
unverified evidence on the organization chain. And a receipt already propagated
is skipped by reading what the organization chain already carries, so a second
run is a no-op rather than a duplicate-recovery failure.

Nothing here grants authority, performs a transition, or claims custody. It
records, at the organization level, transitions that already occurred.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ledger_store import HEAD_KEY, RECEIPT_PREFIX, PosixLedgerStore  # noqa: E402

REGISTRY = ROOT / "org-boundary/registry/services.json"
REPOSITORY_RECEIPT_SCHEMA = "stegverse.repo-transition-receipt/v1"
ORGANIZATION_RECEIPT_SCHEMA = "stegverse.organization-transition-receipt/v1"
ORG_TRANSITION_CLASS = "REPO_STATE_PROPAGATION"
RESULT_SCHEMA = "stegverse.organization-repository-propagation/v1"

#: Where repository ledgers live, as a tree of addresses. This is the layout
#: both repository emitters derive by default; redirecting the home redirects
#: the whole tree. `STEGVERSE_REPO_LEDGER_ROOT` is a different knob -- it points
#: one emitter at one ledger -- and is deliberately not consulted here, because
#: a single root cannot name the ledgers of several repositories at once.
LEDGER_HOME_VARIABLE = "STEGVERSE_REPO_LEDGER_HOME"


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


organization_ledger = _module("aggregate_repo_transition",
                              "resident-runtime/aggregate_repo_transition.py")


def repository_ledger_home() -> Path:
    override = os.getenv(LEDGER_HOME_VARIABLE)
    if override:
        return Path(override).expanduser().resolve()
    raise organization_ledger.LedgerLocationRequired(LEDGER_HOME_VARIABLE)


def declared_repositories() -> list[str]:
    """The repositories this organization declares, read off the service registry.

    The registry is the organization's own statement of what belongs to it. A
    repository list written here instead would be a second answer to a question
    the registry already answers.
    """
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    organization = registry["organization"]
    return sorted({
        str(service["repository"]) for service in registry.get("services", [])
        if str(service.get("repository", "")).startswith(organization + "/")
    })


def repository_chain(root: Path) -> list[dict[str, Any]]:
    """A repository's receipts in chain order, genesis first, each verified.

    The chain is walked from the published head backwards and reversed, so the
    order is the repository's own. A receipt whose claimed digest is not the
    digest of its body stops the walk: an unverifiable receipt must not reach
    the organization chain, and the ones before it in the chain are not made
    trustworthy by it.
    """
    store = PosixLedgerStore(root)
    head = store.get(HEAD_KEY)
    if head is None:
        return []
    chain: list[dict[str, Any]] = []
    cursor = head.get("receipt_sha256")
    seen: set[str] = set()
    while cursor:
        if cursor in seen:
            raise SystemExit("REPOSITORY_LEDGER_CHAIN_CYCLE:" + cursor)
        seen.add(cursor)
        receipt = store.get(RECEIPT_PREFIX + cursor.split(":", 1)[1] + ".json")
        if receipt is None:
            raise SystemExit("REPOSITORY_LEDGER_RECEIPT_MISSING:" + cursor)
        if receipt.get("schema") != REPOSITORY_RECEIPT_SCHEMA:
            raise SystemExit("REPOSITORY_LEDGER_RECEIPT_SCHEMA_MISMATCH:" + cursor)
        body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        if receipt.get("receipt_sha256") != organization_ledger.sha(body):
            raise SystemExit("REPOSITORY_LEDGER_RECEIPT_HASH_MISMATCH:" + cursor)
        chain.append(receipt)
        cursor = receipt.get("previous_receipt_sha256")
    chain.reverse()
    return chain


def already_propagated(organization_root: Path) -> set[str]:
    """The repository receipts the organization chain already carries."""
    store = PosixLedgerStore(organization_root)
    carried: set[str] = set()
    for key in store.list_prefix(RECEIPT_PREFIX):
        receipt = store.get(key) or {}
        if receipt.get("schema") != ORGANIZATION_RECEIPT_SCHEMA:
            continue
        digest = receipt.get("repo_receipt_sha256")
        if isinstance(digest, str) and digest:
            carried.add(digest)
    return carried


def _no_prior_repository_receipt(repository: str) -> str:
    """The organization's state before it carried anything from this repository.

    `require_state_digest` wants a digest in every state field, and a genesis
    receipt has no predecessor to name. This is that absence, stated and
    reproducible, rather than a zero digest that reads like a real state.
    """
    return organization_ledger.sha({"repository": repository,
                                    "state": "NO_PRIOR_REPOSITORY_RECEIPT"})


def propagate(repository: str, *, repository_root: Path | None = None,
              hb_epoch: int | None = None) -> dict[str, Any]:
    """Record this repository's unpropagated transitions on the organization chain."""
    root = Path(repository_root) if repository_root else repository_ledger_home() / repository
    organization_root = organization_ledger.ledger_root()
    if not (root / HEAD_KEY).is_file():
        # The capability holding that ledger did not materialize on this node.
        # Nothing is missing; there is nothing of it here to carry.
        return {"schema": RESULT_SCHEMA, "repository": repository,
                "repository_ledger_present": False, "propagated": [], "skipped": [],
                "authority_effect": "NONE_PROPAGATION_ONLY"}

    chain = repository_chain(root)
    carried = already_propagated(organization_root)
    propagated: list[dict[str, Any]] = []
    skipped: list[str] = []
    for receipt in chain:
        digest = receipt["receipt_sha256"]
        if digest in carried:
            skipped.append(digest)
            continue
        predecessor = receipt.get("previous_receipt_sha256") or _no_prior_repository_receipt(repository)
        organization_receipt = organization_ledger.append(
            receipt, ORG_TRANSITION_CLASS, predecessor, digest,
            {"propagated_by": "resident-runtime/propagate_repository_receipts.py",
             "repository_ledger_address": str(root),
             "repository_transition_class": receipt.get("transition_class"),
             "crossed_an_organization_boundary": False,
             "interlock_intr_involved": False},
            "NONE", hb_epoch=hb_epoch)
        propagated.append({
            "repository_receipt_sha256": digest,
            "repository_transition_id": receipt.get("transition_id"),
            "repository_transition_class": receipt.get("transition_class"),
            "organization_receipt_sha256": organization_receipt["receipt_sha256"],
        })
        carried.add(digest)
    return {
        "schema": RESULT_SCHEMA,
        "repository": repository,
        "repository_ledger_present": True,
        "repository_ledger_address": str(root),
        "repository_chain_length": len(chain),
        "propagated": propagated,
        "skipped": skipped,
        "propagation_order": "REPOSITORY_CHAIN_ORDER",
        "every_receipt_verified_against_its_own_body": True,
        "crossed_an_organization_boundary": False,
        "interlock_intr_involved": False,
        "authority_effect": "NONE_PROPAGATION_ONLY",
    }


def propagate_all(*, hb_epoch: int | None = None) -> dict[str, Any]:
    """Propagate every declared repository whose ledger is present on this node."""
    results = [propagate(repository, hb_epoch=hb_epoch)
               for repository in declared_repositories()]
    return {
        "schema": RESULT_SCHEMA + "-sweep",
        "organization": json.loads(REGISTRY.read_text(encoding="utf-8"))["organization"],
        "repositories_declared": len(results),
        "repositories_present": sum(1 for r in results if r["repository_ledger_present"]),
        "receipts_propagated": sum(len(r["propagated"]) for r in results),
        "receipts_already_carried": sum(len(r["skipped"]) for r in results),
        "repositories": results,
        "authority_effect": "NONE_PROPAGATION_ONLY",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Carry repository transition receipts onto the organization chain.")
    parser.add_argument("--repository", default=None,
                        help="one declared repository; omit to sweep every declared repository")
    parser.add_argument("--repository-ledger-root", type=Path, default=None,
                        help="address of that repository's ledger; derived from the ledger home when absent")
    parser.add_argument("--hb-epoch", type=int, default=None,
                        help="heartbeat epoch; derived from the host clock, and marked as derived, when absent")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if args.repository:
        result = propagate(args.repository, repository_root=args.repository_ledger_root,
                           hb_epoch=args.hb_epoch)
    else:
        if args.repository_ledger_root is not None:
            raise SystemExit("--repository-ledger-root names one repository's ledger; pass --repository")
        result = propagate_all(hb_epoch=args.hb_epoch)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered)
    print(json.dumps({key: value for key, value in result.items()
                      if key != "repositories"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
