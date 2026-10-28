"""Push-receipt session binder (B1b; StegVerse-org/.github#160 issuecomment-6353130407 rank 3 "org#192 binder",
correction issuecomment-6354202109 "merge-admission v2 genesis with the session derived from push receipts").

Lowest supported operating mode: E0 (no LLM, stdlib only, no clock, no network). It replaces the merge-admission
predicate PR_AUTHOR_SESSION_DECLARED (TVC config/sv-merge-admission/manifest.json reads it from
pull_request.body_first_line, a value an LLM types) with an authoring session DERIVED from the ledgered
sv-push-receipt.v1 chain covering the PR's base..head:

  derived authoring_session = the pusher_session of the first push receipt of the chain;
  every later push in the chain is by that session or by a session holding a sealed co-author grant from it
  for the same change_id.

The receipt checks are a line-for-line port of TVC sv_change_admission.py (TVC main c4845bea, blob 81d81c03):
``push_receipt_problem`` (closed key set plus result_sha256 seal) and ``_push_receipt_chain`` (first old_sha ==
base_sha, contiguous, last new_sha == head_sha, one repository, one ref, change_id when present). The schema and
producer are pinned, never vendored:

  schema   StegVerse-Labs/.github schemas/sv-push-receipt.v1.schema.json  git blob 67b9f7d3 sha256 5892048a...
  producer StegVerse-Labs/.github resident-runtime/sv_push_receipt.py     git blob 0ea4ff4c sha256 67e9d037...

Dispositions (six fields each; the first non-ALLOW decides):
  BRANCH_WRITER_UNOBSERVED   (detail WRITER_EVIDENCE_GAP) the chain does not cover base..head
  PUSH_RECEIPT_NOT_LEDGERED  a receipt was supplied but not read back from a ledger ref
  BRANCH_HAS_FOREIGN_WRITER  a push in the chain is by another session without a receipted co-author grant

Stated limit: the producer records pusher_session as the pushing session declares it at push time. The binder
removes the LLM-typed PR-body declaration, and binds the session to the git range through sealed, ledgered push
receipts; it does not authenticate the session name beyond what the ledgered receipt carries.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "stegverse.push-receipt-session-binding/v1"
LOWEST_SUPPORTED_MODE = "E0"
REPLACES_PREDICATE = "PR_AUTHOR_SESSION_DECLARED"
SESSION_SOURCE = "PUSH_RECEIPT_CHAIN"
PUSH_RECEIPT_SCHEMA = "stegverse.sv_push_receipt.v1"
CO_AUTHOR_GRANT_SCHEMA = "stegverse.sv-change-co-author-grant/v0.1"
PINS = {
    "consumer": {"repository": "StegVerse-Labs/TVC", "ref": "c4845bea704949c46658042963e8c532c9559939",
                 "file": "sv_change_admission.py", "git_blob_sha": "81d81c038671ce95061b404622f250b457f34cee",
                 "functions": ["push_receipt_problem", "_push_receipt_chain"]},
    "schema": {"repository": "StegVerse-Labs/.github", "file": "schemas/sv-push-receipt.v1.schema.json",
               "git_blob_sha": "67b9f7d3b3536dd686f7703dff609283c6035af7",
               "sha256": "5892048af26a166f3b53cfec6bbed7f8cb45f26c604fbe9b1dd1049c39d5cfea"},
    "producer": {"repository": "StegVerse-Labs/.github", "file": "resident-runtime/sv_push_receipt.py",
                 "git_blob_sha": "0ea4ff4cafd127bbd18b2ee62d51cd344a1488ef",
                 "sha256": "67e9d037a63fe46079c1fa59a7c2935a69946ded3e3945dbd58800de1f88993a"},
}
GOAL = "TVC-GITHUB-REPOSITORY-OPERATION-BROKER-001 (StegVerse-org/.github#160 rank 3)"
RETRY = "resident-runtime/push_receipt_session_binder.py::bind (merge-admission v2 genesis evaluation)"
WRITER_EVIDENCE_GAP = "WRITER_EVIDENCE_GAP"
UNKNOWN = "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
              "owning_existing_goal", "next_attempt")

_PUSH_RECEIPT_KEYS = frozenset({"schema", "repository", "ref", "old_sha", "new_sha", "pusher_session", "change_id",
                                "pushed_commits", "hb_epoch", "result_sha256"})
_PUSH_REF = re.compile(r"^refs/heads/\S+$")
_REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_CHANGE_ID = re.compile(r"^svc:[0-9a-f]{64}$")
_SUPPLIED_EPOCH = re.compile(r"^(?:3[2-9]|[4-9][0-9]|[1-9][0-9]{2,})$")


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def seal(body: Mapping[str, Any], field: str = "result_sha256") -> dict[str, Any]:
    clean = {k: v for k, v in body.items() if k != field}
    return {**clean, field: "sha256:" + hashlib.sha256(canon(clean)).hexdigest()}


def seal_verifies(r: Any, field: str = "result_sha256") -> bool:
    return isinstance(r, Mapping) and isinstance(r.get(field), str) and seal(r, field)[field] == r[field]


def is_unknown(v: Any) -> bool:
    return v is None or v == UNKNOWN


def push_receipt_problem(r: Any) -> str | None:
    """sv-push-receipt.v1 (closed; additionalProperties false) plus its result_sha256 seal. None when it holds."""
    if not isinstance(r, Mapping) or r.get("schema") != PUSH_RECEIPT_SCHEMA:
        return "schema"
    if set(r) - _PUSH_RECEIPT_KEYS or (_PUSH_RECEIPT_KEYS - {"change_id"}) - set(r):
        return "fields"
    if not (isinstance(r["repository"], str) and _REPO_NAME.match(r["repository"]) and isinstance(r["ref"], str) and _PUSH_REF.match(r["ref"])):
        return "repository_or_ref"
    if not all(isinstance(r[k], str) and _GIT_SHA.match(r[k]) for k in ("old_sha", "new_sha")):
        return "old_or_new_sha"
    c = r["pushed_commits"]
    if not isinstance(c, list) or not c or any(not (isinstance(x, str) and _GIT_SHA.match(x)) for x in c) or len(set(c)) != len(c) \
            or c[-1] != r["new_sha"]:
        return "pushed_commits"
    if not (isinstance(r["pusher_session"], str) and r["pusher_session"].strip()):
        return "pusher_session"
    if "change_id" in r and not (isinstance(r["change_id"], str) and _CHANGE_ID.match(r["change_id"])):
        return "change_id"
    if not (isinstance(r["hb_epoch"], str) and _SUPPLIED_EPOCH.match(r["hb_epoch"])):
        return "hb_epoch"
    if not seal_verifies(r, "result_sha256"):
        return "seal"
    return None


def _result(disposition: str, body: Mapping[str, Any]) -> dict[str, Any]:
    return seal({"schema": SCHEMA, "lowest_supported_mode": LOWEST_SUPPORTED_MODE, "replaces": REPLACES_PREDICATE,
                 "session_source": SESSION_SOURCE, "pins": PINS, "disposition": disposition, "authority_effect": "NONE",
                 **body})


def _fail(code: str, predicate: str, repair: str, next_attempt: str, **detail: Any) -> dict[str, Any]:
    return _result("FAIL_CLOSED", {"failure_code": code, "failed_predicate": predicate,
                                   "required_evidence_or_repair": repair, "retry_entrypoint": RETRY,
                                   "owning_existing_goal": GOAL, "next_attempt": next_attempt,
                                   "authoring_session": UNKNOWN, "detail": detail})


def _writer_gap(gap: str, **d: Any) -> dict[str, Any]:
    return _fail("BRANCH_WRITER_UNOBSERVED", "BRANCH_WRITER_IS_BRANCH_OWNER",
                 "a contiguous chain of sealed, ledgered sv-push-receipt.v1 receipts whose first old_sha is base_sha and whose "
                 "last new_sha is head_sha; a range with no receipt stays UNKNOWN (never reconstructed), so supersede the change",
                 "the next push to the branch emits its receipt (resident-runtime/sv_push_receipt.py) and the binder re-runs",
                 writer_evidence=WRITER_EVIDENCE_GAP, gap=gap, **d)


def _granted_sessions(derived: str, change_id: str | None, grants: Any) -> set[str]:
    out = set()
    for r in grants if isinstance(grants, list) else []:
        if (isinstance(r, Mapping) and r.get("schema") == CO_AUTHOR_GRANT_SCHEMA and seal_verifies(r, "receipt_sha256")
                and r.get("granted_by_session") == derived and isinstance(r.get("co_author_session"), str)
                and change_id is not None and r.get("change_id") == change_id):
            out.add(r["co_author_session"])
    return out


def bind(*, target_repository: str, base_sha: Any, head_sha: Any, receipts: Any, ledgered: bool,
         change_id: str | None = None, co_author_grant_receipts: Any = None, ledger: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Derive the authoring session of base_sha..head_sha from the push-receipt chain (port of TVC _push_receipt_chain)."""
    if not (isinstance(base_sha, str) and _GIT_SHA.match(base_sha) and isinstance(head_sha, str) and _GIT_SHA.match(head_sha)):
        return _writer_gap("projection.github.{base_sha, head_sha} not bound", base_sha=base_sha, head_sha=head_sha)
    if not isinstance(receipts, list) or not receipts:
        return _writer_gap("no push receipts", base_sha=base_sha, head_sha=head_sha)
    bad = [{"index": i, "problem": p} for i, p in enumerate(map(push_receipt_problem, receipts)) if p]
    if bad:
        return _writer_gap("push receipt not a sealed sv-push-receipt.v1", invalid=bad)
    other = [i for i, r in enumerate(receipts) if r["repository"] != target_repository
             or (change_id is not None and r.get("change_id", change_id) != change_id)]
    refs = sorted({r["ref"] for r in receipts})
    if other or len(refs) != 1:
        return _writer_gap("push receipts for another repository, change_id or ref", indexes=other, refs=refs)
    by_old: dict[str, list[Mapping[str, Any]]] = {}
    for r in receipts:
        by_old.setdefault(r["old_sha"], []).append(r)
    chain, at, seen = [], base_sha, set()
    while at != head_sha:
        nxt = by_old.get(at) or []
        if len(nxt) != 1 or at in seen:
            return _writer_gap("no unique push receipt continues the chain" if len(nxt) != 1 else "chain loops",
                               at=at, base_sha=base_sha, head_sha=head_sha, candidates=len(nxt))
        seen.add(at)
        chain.append(nxt[0])
        at = nxt[0]["new_sha"]
    if len(chain) != len(receipts):
        return _writer_gap("push receipts outside the base..head chain", chained=len(chain), supplied=len(receipts))
    if not ledgered:
        return _fail("PUSH_RECEIPT_NOT_LEDGERED", "PUSH_RECEIPTS_ARE_READ_BACK_FROM_A_LEDGER_REF",
                     "append each sv-push-receipt to refs/stegverse/organization-ledger (the org-ledger writer's transition, "
                     "StegVerse-Labs/.github#3255) and bind from that readback, never from a supplied file",
                     "the binder re-runs over the ledger readback", receipts=[r["result_sha256"] for r in chain])
    derived = chain[0]["pusher_session"]
    allowed = {derived} | _granted_sessions(derived, change_id, co_author_grant_receipts)
    foreign = [{"pusher_session": r["pusher_session"], "old_sha": r["old_sha"], "new_sha": r["new_sha"]}
               for r in chain if r["pusher_session"] not in allowed or is_unknown(r["pusher_session"])]
    if foreign:  # FAIL_CLOSED (matching P1 and TVC), not DENY
        return _fail("BRANCH_HAS_FOREIGN_WRITER", "BRANCH_WRITER_IS_BRANCH_OWNER",
                     "every push in the chain is by the derived session or by a session holding a receipted co-author grant from it; "
                     "a superseding change by the derived session carries the foreign content openly under such a grant",
                     "the successor change's chain is bound", derived_session=derived, foreign_pushes=foreign)
    return _result("ALLOW", {"repository": target_repository, "ref": refs[0], "base_sha": base_sha, "head_sha": head_sha,
                             "change_id": change_id, "authoring_session": derived,
                             "co_authors": sorted({r["pusher_session"] for r in chain} - {derived}),
                             "push_receipts": [r["result_sha256"] for r in chain], "ledger": dict(ledger or {}),
                             "pusher_session_evidence_class": "DECLARED_AT_PUSH_TIME_SEALED_AND_LEDGERED"})


def receipts_from_ledger(git_dir: str | Path, ref: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every sealed sv-push-receipt.v1 in the tree at ``ref`` (a ledger readback, never a supplied file)."""
    def git(*a: str) -> str:
        return subprocess.run(["git", "-C", str(git_dir), *a], check=True, capture_output=True).stdout.decode()
    tip = git("rev-parse", "--verify", ref + "^{commit}").strip()
    out = []
    for path in git("ls-tree", "-r", "--name-only", tip).splitlines():
        if not path.endswith(".json"):
            continue
        try:
            doc = json.loads(git("show", f"{tip}:{path}"))
        except (subprocess.CalledProcessError, ValueError):
            continue
        if isinstance(doc, Mapping) and doc.get("schema") == PUSH_RECEIPT_SCHEMA:
            out.append(dict(doc))
    return out, {"ref": ref, "tip": tip}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="derive the authoring session from ledgered push receipts (E0)")
    ap.add_argument("--repository", required=True)
    ap.add_argument("--base-sha", required=True)
    ap.add_argument("--head-sha", required=True)
    ap.add_argument("--branch", required=True, help="refs/heads/<branch> of the PR head")
    ap.add_argument("--change-id")
    ap.add_argument("--ledger-git-dir", required=True)
    ap.add_argument("--ledger-ref", default="refs/stegverse/organization-ledger")
    ap.add_argument("--co-author-grants", help="JSON list of sealed co-author grant receipts")
    a = ap.parse_args(argv)
    receipts, ledger = receipts_from_ledger(a.ledger_git_dir, a.ledger_ref)
    receipts = [r for r in receipts if r.get("repository") == a.repository and r.get("ref") == a.branch]
    # the receipts of this range: those on the walk from base_sha (earlier pushes to the branch are not this PR's)
    by_old: dict[str, list[dict[str, Any]]] = {}
    for r in receipts:
        by_old.setdefault(r.get("old_sha"), []).append(r)
    walk, at, seen = [], a.base_sha, set()
    while at in by_old and at not in seen and at != a.head_sha:
        seen.add(at)
        walk.extend(by_old[at])
        at = by_old[at][0].get("new_sha")
    receipts = walk
    grants = json.loads(Path(a.co_author_grants).read_text()) if a.co_author_grants else None
    result = bind(target_repository=a.repository, base_sha=a.base_sha, head_sha=a.head_sha, receipts=receipts,
                  ledgered=True, change_id=a.change_id, co_author_grant_receipts=grants, ledger=ledger)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["disposition"] == "ALLOW" else 1


if __name__ == "__main__":
    sys.exit(main())
