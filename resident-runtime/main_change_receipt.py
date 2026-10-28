"""Main-change receipt writer (StegVerse-org/.github#160 issuecomment-6353130407 section 1.3 B1; correction
issuecomment-6354202109: every merge or main push is receipted and surfaced).

Lowest supported operating mode: E0 (ecosystem only, no LLM; #160 issuecomment-6354238464). Stdlib only; reads
git objects of the repository it runs in; no clock, no network, no secret. Every repository in the federation
calls it through the reusable workflow ``.github/workflows/main-change-receipt.yml`` pinned to a commit of
StegVerse-org/.github, from its own ``on: push: branches: [main]``.

One receipt per commit a push to main introduces (first-parent ``before..after``), whatever produced it: a PR
merge, a squash, a direct push or a bot commit. Recording is not admission: the receipt is always written, and
what it could not establish is carried as six-field items (the first non-ALLOW item is ``disposition``):

  MAIN_HISTORY_REWRITTEN                 the push's before is not an ancestor of after (forced update of main)
  ADMISSION_CHECKPOINT_NOT_INSTALLED     no admission record is bound at the merged head (B2 is Lane C's step)
  HB_EPOCH_SOURCE_UNOBSERVED             no supplied epoch: the repository carries no organization ledger head
  ORGANIZATION_LEDGER_APPEND_NOT_AVAILABLE  the receipt is ledgered on this repository's own receipt ref, not on
                                         the organization ledger (that append needs a credential E0 does not hold)

The receipts are appended, fast-forward only, to ``refs/stegverse/main-change-receipts`` in the same repository
(one tree, ``receipts/<commit>.json``), then verified from a fresh fetch of the published ref.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "stegverse.main-change-receipt/v1"
LOWEST_SUPPORTED_MODE = "E0"
RECEIPT_REF = "refs/stegverse/main-change-receipts"
ORG_LEDGER_REF = "refs/stegverse/organization-ledger"
MAIN_REF = "refs/heads/main"
ZERO = "0" * 40
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SUPPLIED_EPOCH = re.compile(r"^(?:3[2-9]|[4-9][0-9]|[1-9][0-9]{2,})$")  # org-kernel supplied_epoch_failure
MERGE_SUBJECT = re.compile(r"^Merge pull request #([0-9]+) from \S+")
SQUASH_SUBJECT = re.compile(r"\(#([0-9]+)\)$")
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
ENTRYPOINT = ".github/workflows/main-change-receipt.yml (the repository's next push to main)"
COORDINATION_GOAL = "STEGVERSE-CANONICAL-WORK-COORDINATION-001 (StegVerse-org/.github#160)"
BROKER_GOAL = "TVC-GITHUB-REPOSITORY-OPERATION-BROKER-001"
IDENTITY = ("stegverse-main-change-receipt", "main-change-receipt@stegverse.invalid")


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def seal(body: Mapping[str, Any], field: str = "receipt_sha256") -> dict[str, Any]:
    clean = {k: v for k, v in body.items() if k != field}
    return {**clean, field: "sha256:" + hashlib.sha256(canon(clean)).hexdigest()}


def seal_verifies(record: Any, field: str = "receipt_sha256") -> bool:
    return isinstance(record, Mapping) and isinstance(record.get(field), str) and seal(record, field)[field] == record[field]


def item(code: str, predicate: str, repair: str, goal: str, next_attempt: str, retry: str = ENTRYPOINT) -> dict[str, str]:
    return {"disposition": "FAIL_CLOSED", "failure_code": code, "failed_predicate": predicate,
            "required_evidence_or_repair": repair, "retry_entrypoint": retry, "owning_existing_goal": goal,
            "next_attempt": next_attempt}


# -- git ----------------------------------------------------------------------------------------------------

def _git(root: Path | str, *args: str, env: Mapping[str, str] | None = None, input_: bytes | None = None) -> str:
    full_env = None if env is None else {**os.environ, **env}
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=full_env,
                          input=input_).stdout.decode("utf-8").strip()


def _ok(root: Path | str, *args: str) -> bool:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True).returncode == 0


def commit_facts(root: Path | str, commit: str) -> dict[str, Any]:
    raw = _git(root, "cat-file", "commit", commit)
    header, _, message = raw.partition("\n\n")
    tree, parents, committer_time = None, [], None
    for line in header.splitlines():
        key, _, value = line.partition(" ")
        if key == "tree":
            tree = value
        elif key == "parent":
            parents.append(value)
        elif key == "committer":
            committer_time = " ".join(value.rsplit(" ", 2)[-2:])  # "<unix> <tz>" as recorded in the object
    return {"commit": _git(root, "rev-parse", "--verify", commit + "^{commit}"), "tree": tree, "parents": parents,
            "subject": message.splitlines()[0] if message else "", "committer_time_recorded": committer_time}


def pushed_commits(root: Path | str, before: str, after: str) -> tuple[list[str], bool]:
    """(first-parent commits before..after oldest first, history_rewritten)."""
    if not before or before == ZERO or not _ok(root, "cat-file", "-e", before + "^{commit}"):
        return [after], False
    if before == after:
        return [], False
    rewritten = not _ok(root, "merge-base", "--is-ancestor", before, after)
    if rewritten:
        return [after], True
    out = _git(root, "rev-list", "--first-parent", "--reverse", f"{before}..{after}")
    return [c for c in out.splitlines() if c], False


def merge_kind(facts: Mapping[str, Any], push_commit_count: int) -> tuple[str, int | None, str | None]:
    m = MERGE_SUBJECT.match(facts["subject"]) if len(facts["parents"]) == 2 else None
    if m:
        return "MERGE_COMMIT", int(m.group(1)), "MERGE_COMMIT_SUBJECT"
    s = SQUASH_SUBJECT.search(facts["subject"]) if len(facts["parents"]) == 1 else None
    if s and push_commit_count == 1:
        return "SQUASH_OR_REBASE_MERGE", int(s.group(1)), "COMMIT_SUBJECT"
    return "DIRECT_PUSH", None, None


def ledger_epoch(root: Path | str, ref: str = ORG_LEDGER_REF) -> tuple[str | None, str | None]:
    """(supplied epoch, head receipt sha256) carried by the organization ledger head: HEAD.json names the head
    receipt, whose hb_reference.epoch is the epoch. (None, None) when unreadable; never a clock."""
    if not _ok(root, "rev-parse", "--verify", "--quiet", ref):
        return None, None
    try:
        head = json.loads(_git(root, "show", f"{ref}:HEAD.json"))
        digest = head["receipt_sha256"]
        hexd = digest.split(":", 1)[1]
        doc = json.loads(_git(root, "show", f"{ref}:receipts/{hexd}.json"))
    except (subprocess.CalledProcessError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        return None, None
    if not isinstance(doc, Mapping) or doc.get("receipt_sha256") != digest:
        return None, None
    hb = doc.get("hb_reference")
    epoch = hb.get("epoch") if isinstance(hb, Mapping) else None
    if isinstance(epoch, int) and not isinstance(epoch, bool):
        epoch = str(epoch)
    if isinstance(epoch, str) and SUPPLIED_EPOCH.match(epoch):
        return epoch, digest
    return None, None


# -- receipts -----------------------------------------------------------------------------------------------

def observe(root: Path | str, *, repository: str, before: str, after: str, writer: Mapping[str, str],
            organization_ledger_writer_installed: bool = False) -> list[dict[str, Any]]:
    commits, rewritten = pushed_commits(root, before, after)
    epoch, epoch_head = ledger_epoch(root)
    receipts = []
    for c in commits:
        facts = commit_facts(root, c)
        kind, pr, pr_source = merge_kind(facts, len(commits))
        items = []
        if rewritten:
            items.append(item("MAIN_HISTORY_REWRITTEN", "MAIN_ADVANCES_BY_FAST_FORWARD",
                              "the push replaced main history; restore the replaced commits through a successor change",
                              COORDINATION_GOAL, "the next main-change receipt"))
        items.append(item("ADMISSION_CHECKPOINT_NOT_INSTALLED", "MAIN_CHANGE_HAS_ADMISSION_RECORD_AT_MERGED_HEAD",
                          "the B2 admission checkpoint binds admission_record_ref (a successor PR reverts or re-admits "
                          "the change through the broker; a retroactive ALLOW is never issued)",
                          BROKER_GOAL, "the next main-change receipt", retry="TVC broker admission"))
        if epoch is None:
            items.append(item("HB_EPOCH_SOURCE_UNOBSERVED", "EPOCH_IS_SUPPLIED_NEVER_READ_FROM_A_CLOCK",
                              f"this repository carries no {ORG_LEDGER_REF} head with a supplied epoch",
                              COORDINATION_GOAL, "the next main-change receipt after the organization ledger is readable"))
        if not organization_ledger_writer_installed:
            items.append(item("ORGANIZATION_LEDGER_APPEND_NOT_AVAILABLE", "REPO_MAIN_PUSH_EMITS_ORGANIZATION_MAIN_MERGE_TRANSFER",
                              f"the receipt is on this repository's {RECEIPT_REF}; the organization ledger append needs "
                              "a per-transition credential issued by the organization (not held in E0)",
                              COORDINATION_GOAL, "the census receipt flips to ALLOW"))
        body = {"schema": SCHEMA, "lowest_supported_mode": LOWEST_SUPPORTED_MODE, "repository": repository,
                "ref": MAIN_REF, "commit": facts["commit"], "tree": facts["tree"], "parents": facts["parents"],
                "subject": facts["subject"], "committer_time_recorded": facts["committer_time_recorded"],
                "merge_kind": kind, "pull_request": pr, "pull_request_source": pr_source,
                "push": {"before": before or ZERO, "after": after, "commits": len(commits), "history_rewritten": rewritten},
                "hb_epoch": epoch, "hb_epoch_source": {"ref": ORG_LEDGER_REF, "head_receipt_sha256": epoch_head} if epoch else None,
                "admission_record_ref": None, "writer": dict(writer),
                "items": items, "disposition": items[0]["disposition"] if items else "ALLOW",
                "authority_effect": "NONE"}
        if items:
            body["first_item"] = {k: items[0][k] for k in SIX_FIELDS}
        receipts.append(seal(body))
    return receipts


def receipt_path(commit: str) -> str:
    return f"receipts/{commit}.json"


def append(root: Path | str, receipts: list[Mapping[str, Any]], ref: str = RECEIPT_REF) -> dict[str, Any]:
    """Append the receipts to ``ref`` as one commit (idempotent: a receipt already there is answered from the ref)."""
    tip = _git(root, "rev-parse", "--verify", "--quiet", ref) if _ok(root, "rev-parse", "--verify", "--quiet", ref) else None
    new = [r for r in receipts if not (tip and _ok(root, "cat-file", "-e", f"{tip}:{receipt_path(r['commit'])}"))]
    if not new:
        return {"ref": ref, "tip": tip, "appended": [], "already_ledgered": [r["commit"] for r in receipts]}
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        if tip:
            _git(root, "read-tree", tip, env=env)
        else:
            _git(root, "read-tree", "--empty", env=env)
        for r in new:
            blob = _git(root, "hash-object", "-w", "--stdin", input_=json.dumps(r, indent=2, sort_keys=True).encode() + b"\n")
            _git(root, "update-index", "--add", "--cacheinfo", f"100644,{blob},{receipt_path(r['commit'])}", env=env)
        tree = _git(root, "write-tree", env=env)
    last = new[-1]["committer_time_recorded"] or "0 +0000"
    ident = {"GIT_AUTHOR_NAME": IDENTITY[0], "GIT_AUTHOR_EMAIL": IDENTITY[1], "GIT_AUTHOR_DATE": last,
             "GIT_COMMITTER_NAME": IDENTITY[0], "GIT_COMMITTER_EMAIL": IDENTITY[1], "GIT_COMMITTER_DATE": last}
    args = ["commit-tree", tree, "-m", "main-change receipts: " + " ".join(r["commit"][:12] for r in new)]
    if tip:
        args[2:2] = ["-p", tip]
    commit = _git(root, *args, env=ident)
    if tip:
        _git(root, "update-ref", ref, commit, tip)
    else:
        _git(root, "update-ref", ref, commit, ZERO)
    return {"ref": ref, "tip": commit, "previous_tip": tip, "appended": [r["commit"] for r in new],
            "already_ledgered": [r["commit"] for r in receipts if r not in new]}


def verify(root: Path | str, commits: list[str], ref: str = RECEIPT_REF) -> dict[str, Any]:
    """Every commit has a sealed receipt at the tip of ``ref`` (read from a fresh fetch by the caller)."""
    problems = []
    if not _ok(root, "rev-parse", "--verify", "--quiet", ref):
        problems.append({"ref": ref, "problem": "ref absent"})
    else:
        for c in commits:
            try:
                doc = json.loads(_git(root, "show", f"{ref}:{receipt_path(c)}"))
            except (subprocess.CalledProcessError, ValueError):
                problems.append({"commit": c, "problem": "no receipt"})
                continue
            if not seal_verifies(doc) or doc.get("commit") != c or doc.get("schema") != SCHEMA:
                problems.append({"commit": c, "problem": "receipt does not verify"})
    if problems:
        out = item("MAIN_CHANGE_RECEIPT_NOT_LEDGERED", "EVERY_MAIN_CHANGE_HAS_A_LEDGERED_RECEIPT",
                   "re-run the writer; a receipt already ledgered is answered from the ref", COORDINATION_GOAL,
                   "the next push to main")
        return {**out, "problems": problems}
    return {"disposition": "ALLOW", "verified": commits, "ref": ref}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="main-change receipt writer (E0)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("observe")
    o.add_argument("--root", default=".")
    o.add_argument("--repository", required=True)
    o.add_argument("--before", default="")
    o.add_argument("--after", required=True)
    o.add_argument("--writer-ref", required=True)
    o.add_argument("--writer-sha256", required=True)
    o.add_argument("--organization-ledger-writer-installed", action="store_true")
    o.add_argument("--out", required=True)
    a_ = sub.add_parser("append")
    a_.add_argument("--root", default=".")
    a_.add_argument("--receipts", required=True)
    a_.add_argument("--out", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--root", required=True)
    v.add_argument("--receipts", required=True)
    v.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "observe":
        writer = {"repository": "StegVerse-org/.github", "path": "resident-runtime/main_change_receipt.py",
                  "ref": a.writer_ref, "sha256": a.writer_sha256}
        result: Any = observe(a.root, repository=a.repository, before=a.before, after=a.after, writer=writer,
                              organization_ledger_writer_installed=a.organization_ledger_writer_installed)
    elif a.cmd == "append":
        result = append(a.root, json.loads(Path(a.receipts).read_text()))
    else:
        result = verify(a.root, [r["commit"] for r in json.loads(Path(a.receipts).read_text())])
    Path(a.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if isinstance(result, Mapping) and result.get("disposition") == "FAIL_CLOSED" else 0


if __name__ == "__main__":
    sys.exit(main())
