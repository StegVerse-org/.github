#!/usr/bin/env python3
"""B2: the admission checkpoint inside the main-merge transfer writer step.

StegVerse-org/.github#160 issuecomment-6353130407 section 1.3 (B2). Recording
is not admission: every merge on main still gets its repository and
organization receipts, and the organization receipt's boundary also carries

  - ``admission_record_ref``: the record_sha256 of the sealed merge-admission
    record (StegVerse-Labs/TVC sv_merge_admission, schema
    stegverse.merge-admission-record/*) ledgered for the merged head, or null;
  - ``merge_kind``: MERGE_COMMIT (two parents, "Merge pull request #n" subject)
    or DIRECT_PUSH (anything else: a squash, a rebase or a push cannot carry an
    admitted head);
  - ``admission_checkpoint``: ALLOW, or FAIL_CLOSED
    MERGED_HEAD_IS_NOT_THE_ADMITTED_HEAD with the six fields. A retroactive
    ALLOW is never issued; the repair is a successor PR that reverts or
    re-admits the change through the TVC broker.

resident-runtime/merge_transfer.py (sha256 032ed727..., pinned in
data/intr-protocol/v1/protocol.json and byte-pinned by the gitstore variant)
is unchanged and is only called, as merge_transfer_range.py does: the
repository receipt's evidence is merge_transfer.merge_evidence, byte for byte.
A merge already ledgered is answered from the ledger (verify first) and never
re-appended with a new boundary, so pending merges recorded before B2 replay
without a collision; their checkpoint is recomputed and marked as such.

An admission record is found on this organization's chain as a sealed
organization receipt whose boundary_evidence.operation is
MERGE_ADMISSION_RECORD and whose boundary_evidence.admission_record is a
sealed record (record_sha256) naming this repository, this PR and, as head_sha,
the merge commit's last parent. Nothing appends such receipts yet (the
ledgered admission-record append is a missing capability, class B), so until
it exists every merge's checkpoint is FAIL_CLOSED: observed, never silent.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("merge_transfer_for_admission", ROOT / "resident-runtime/merge_transfer.py")
mt = importlib.util.module_from_spec(_spec)
sys.modules["merge_transfer_for_admission"] = mt
_spec.loader.exec_module(mt)

CHECKPOINT_SCHEMA = "stegverse.main-merge-admission-checkpoint/v1"
ADMISSION_RECORD_OPERATION = "MERGE_ADMISSION_RECORD"
ADMISSION_RECORD_SCHEMA_PREFIX = "stegverse.merge-admission-record/"
NOT_ADMITTED = "MERGED_HEAD_IS_NOT_THE_ADMITTED_HEAD"
NOT_ADMITTED_PREDICATE = "MAIN_CHANGE_HAS_ADMISSION_RECORD_AT_MERGED_HEAD"
ADMISSION_GOAL = "TVC-GITHUB-REPOSITORY-OPERATION-BROKER-001"
ADMISSION_RETRY = ("TVC broker admission: StegVerse-Labs/TVC sv_merge_admission.evaluate on a successor PR, whose "
                   "ALLOW record drives MERGE_ADMITTED_PULL_REQUEST")
NEXT_ATTEMPT = "the next main-change receipt"
ALLOW, DENY, FAIL_CLOSED = mt.ALLOW, mt.DENY, mt.FAIL_CLOSED


def merge_kind(facts: Mapping[str, Any]) -> str:
    return "MERGE_COMMIT" if len(facts["parents"]) == 2 and mt.PR_SUBJECT.fullmatch(facts["subject"]) else "DIRECT_PUSH"


def admission_records(repo: str, organization: Any) -> list[Mapping[str, Any]]:
    """Sealed merge-admission records ledgered for ``repo`` on this organization's chain, newest first."""
    out = []
    for digest, receipt in mt.org_chain(organization):
        if not mt.sealed(receipt) or receipt["receipt_sha256"] != digest:
            break
        boundary = mt._boundary(receipt)
        record = boundary.get("admission_record")
        if boundary.get("operation") != ADMISSION_RECORD_OPERATION or not isinstance(record, Mapping):
            continue
        body = {k: v for k, v in record.items() if k != "record_sha256"}
        if str(record.get("schema", "")).startswith(ADMISSION_RECORD_SCHEMA_PREFIX) and record.get("record_sha256") == mt.sha(body) \
                and record.get("repository") == repo:
            out.append(record)
    return out


def admission_checkpoint(repo: str, facts: Mapping[str, Any], organization: Any = None) -> dict[str, Any]:
    """ALLOW only when a sealed admission record names this repository, this PR and the merged head."""
    organization = organization if organization is not None else mt.org_store()
    kind = merge_kind(facts)
    match = mt.PR_SUBJECT.fullmatch(facts["subject"]) if kind == "MERGE_COMMIT" else None
    pull = int(match.group(1)) if match else None
    merged_head = facts["parents"][-1] if kind == "MERGE_COMMIT" else facts["merge_commit"]
    records = admission_records(repo, organization) if pull is not None else []
    found = next((r for r in records if r.get("pull_number") == pull and r.get("head_sha") == merged_head), None)
    out = {"schema": CHECKPOINT_SCHEMA, "repository": repo, "merge_commit": facts["merge_commit"], "merge_kind": kind,
           "pull_request": pull, "merged_head": merged_head, "admission_record_ref": found["record_sha256"] if found else None}
    if found:
        return {**out, "disposition": ALLOW}
    heads = sorted({str(r.get("head_sha")) for r in records if r.get("pull_number") == pull})
    detail = ("a direct push or non-merge commit carries no admitted head" if kind == "DIRECT_PUSH"
              else "the ledgered admission record for this PR names head " + ", ".join(heads) if heads
              else "no sealed merge-admission record for this PR is on the organization ledger")
    return {**out, "disposition": FAIL_CLOSED, "failure_code": NOT_ADMITTED, "failed_predicate": NOT_ADMITTED_PREDICATE,
            "required_evidence_or_repair": "a successor PR that reverts this change or re-admits it through the TVC broker; "
                                           "a retroactive ALLOW is never issued",
            "retry_entrypoint": ADMISSION_RETRY, "owning_existing_goal": ADMISSION_GOAL, "next_attempt": NEXT_ATTEMPT,
            "detail": detail}


def boundary_extra(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    keep = ("disposition", "merged_head") + mt.SIX_FIELDS
    return {"admission_record_ref": checkpoint["admission_record_ref"], "merge_kind": checkpoint["merge_kind"],
            "admission_checkpoint": {k: checkpoint[k] for k in keep if k in checkpoint}}


def recorded_checkpoint(repo: str, merge_commit: str, organization: Any = None, repository_store: Any = None) -> dict[str, Any] | None:
    """The checkpoint the transfer's organization receipt recorded, read back from the ledger (None: none recorded)."""
    organization = organization if organization is not None else mt.org_store()
    verified = mt.verify_merge_transfer(repo, merge_commit, organization, repository_store)
    if verified["disposition"] != ALLOW:
        return None
    receipt = mt._receipt(organization, verified["organization_receipt_sha256"])
    boundary = mt._boundary(receipt) if isinstance(receipt, Mapping) else {}
    cp = boundary.get("admission_checkpoint")
    if not isinstance(cp, Mapping):
        return None
    return {"schema": CHECKPOINT_SCHEMA, "repository": repo, "merge_commit": merge_commit, "merge_kind": boundary.get("merge_kind"),
            "admission_record_ref": boundary.get("admission_record_ref"), **cp, "source": "ORGANIZATION_RECEIPT",
            "organization_receipt_sha256": verified["organization_receipt_sha256"]}


def append(facts: Mapping[str, Any]) -> dict[str, Any]:
    """merge_transfer.append_merge_transfer plus the B2 boundary; verify first; never a partial write."""
    repo = mt.repository()
    bad = mt.facts_failure(facts)
    if bad is not None:
        return mt.refusal(mt.FACTS_INVALID, "MERGE_COMMIT_FACTS_ARE_READ_FROM_THE_COMMIT_OBJECT",
                          "pass the commit's tree, parents and subject as git cat-file reads them",
                          "re-run on the pushed commit; nothing was written", repository=repo, detail=bad)
    organization, repository_store = mt.org_store(), mt.repo_store()
    known = mt.verify_merge_transfer(repo, facts["merge_commit"], organization, repository_store)
    if known["disposition"] == DENY:
        return known  # nothing is appended over a contradiction
    if known["disposition"] == ALLOW:  # already ledgered: answered from the ledger
        cp = recorded_checkpoint(repo, facts["merge_commit"], organization, repository_store) or \
            {**admission_checkpoint(repo, facts, organization), "source": "RECOMPUTED_RECEIPT_PREDATES_B2"}
        return {**known, "operation": mt.OPERATION, "replayed": True, "admission_checkpoint": cp}
    epoch, failed = mt.head_epoch(organization)
    if failed is not None:
        return {**failed, "repository": repo, "merge_commit": facts["merge_commit"]}
    evidence = mt.merge_evidence(repo, facts)
    checkpoint = admission_checkpoint(repo, facts, organization)
    try:
        appended, replayed = mt.ingress._append(
            mt.TRANSITION_CLASS, facts["merge_commit"], evidence, epoch, operation=mt.OPERATION, profile_id=mt.PROFILE_ID,
            boundary_extra={"repository": repo, "merge_commit": facts["merge_commit"], **boundary_extra(checkpoint)})
    except ValueError as exc:
        code = mt.COLLISION if str(exc) == "ledger_receipt_collision" else mt.WRITER_REFUSED
        return mt.refusal(code, "ONE_MERGE_COMMIT_BINDS_ONE_TRANSFER_RECEIPT",
                          "the ledger already binds this merge commit to different evidence, or the writer refused: " + str(exc),
                          "inspect the recorded receipt; nothing was written", repository=repo,
                          merge_commit=facts["merge_commit"], detail=str(exc))
    except SystemExit as exc:
        found = mt.ingress.ledger_writer_refusal(exc, mt.ENTRYPOINT, mt.GOAL) if hasattr(mt.ingress, "ledger_writer_refusal") else None
        if found is None and not isinstance(exc.code, str):
            raise
        record = found[0] if found else mt.refusal(mt.WRITER_REFUSED, "LEDGER_WRITER_ADMITS_THE_APPEND",
                                                   "repair what the ledger writer refused (" + str(exc.code) + ")",
                                                   "re-run once repaired; nothing was written")
        return {**record, "schema": mt.RESULT_SCHEMA, "repository": repo, "merge_commit": facts["merge_commit"]}
    return {"schema": mt.RESULT_SCHEMA, "disposition": ALLOW, "operation": mt.OPERATION, "repository": repo,
            "merge_commit": facts["merge_commit"], "pull_request": evidence["pull_request"], "hb_epoch": epoch,
            "replayed": replayed,
            "repository_receipt_sha256": appended["repository_receipt"]["receipt_sha256"],
            "organization_receipt_sha256": appended["organization_receipt"]["receipt_sha256"],
            "admission_checkpoint": {**checkpoint, "source": "ORGANIZATION_RECEIPT"}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("append", "checkpoint"):
        p = sub.add_parser(name)
        p.add_argument("--commit", action="append", default=[])
        p.add_argument("--commits-file")
        p.add_argument("--out")
    args = parser.parse_args(argv)
    commits = list(args.commit)
    if args.commits_file:
        commits += Path(args.commits_file).read_text(encoding="utf-8").split()
    if not commits:
        print(json.dumps(mt.refusal(mt.FACTS_INVALID, "A_PUSH_NAMES_ITS_COMMITS", "name at least one commit",
                                    "re-run with --commit or --commits-file; nothing was done"), indent=2))
        return 1
    results = []
    for commit in commits:
        facts = mt.commit_facts(commit)
        if args.command == "append":
            results.append(append(facts))
        else:  # read back from the (fresh) ledger; a receipt from before B2 is recomputed and marked
            results.append(recorded_checkpoint(mt.repository(), facts["merge_commit"])
                           or {**admission_checkpoint(mt.repository(), facts), "source": "RECOMPUTED_RECEIPT_PREDATES_B2"})
    text = json.dumps(results, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.command == "append":  # the transfer itself: every merge gets its receipt
        return 0 if all(r["disposition"] == ALLOW for r in results) else 1
    # B2: the step fails, with six fields, when any merged head is not an admitted head (receipts are already published)
    return 0 if all(r["disposition"] == ALLOW for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
