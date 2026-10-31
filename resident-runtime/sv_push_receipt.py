#!/usr/bin/env python3
"""sv-push-receipt.v1 producer: branch-writer evidence taken from the push itself (no reflog).

Writer evidence must not depend on a local reflog (a lost reflog entry leaves BRANCH_WRITER_IS_BRANCH_OWNER
FAIL_CLOSED UNKNOWN_NOT_AUTHENTICALLY_OBSERVED for that range; that ruling stands and nothing here
reconstructs past ranges). At push time the pushing session:

1. ``read_ref(repository, after_ref)`` BEFORE the push -> ``old_sha`` (for a new branch: the fork base it names);
2. pushes (its own transport; this module never pushes);
3. ``emit(...)`` AFTER the push: reads ``after_ref`` again -> ``new_sha``, requires ``old_sha`` to be an ancestor
   of ``new_sha`` (a non-fast-forward push is refused, not receipted), lists ``pushed_commits`` with
   ``git rev-list --reverse --topo-order old_sha..new_sha``, seals the receipt (``result_sha256``) and, when
   ``out`` is given, writes it to that file.

``after_ref`` is the local ref the push updates (e.g. ``refs/remotes/origin/<branch>`` after ``git push``, or
the branch itself in a bare mirror). ``hb_epoch`` is supplied by the caller (ASCII digits >= 32), else
FAIL_CLOSED; there is no clock. No network. Read-only apart from writing the receipt file. Appending the
receipt to ``refs/stegverse/organization-ledger`` is the org-ledger writer's transition (StegVerse-Labs/.github#3255);
this module never appends. A refusal is a sealed six-field FAIL_CLOSED result and writes nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

RECEIPT_SCHEMA = "stegverse.sv_push_receipt.v1"
REFUSAL_SCHEMA = "stegverse.sv-push-receipt-refusal/v1"
APPENDER = "org-ledger writer (StegVerse-Labs/.github#3255)"
OWNING_EXISTING_GOAL = "StegVerse-org/.github#164"
RETRY = "resident-runtime/sv_push_receipt.py::emit"
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
              "owning_existing_goal", "next_attempt")
RECEIPT_FIELDS = frozenset({"schema", "repository", "ref", "old_sha", "new_sha", "pusher_session", "change_id",
                            "pushed_commits", "hb_epoch", "result_sha256"})
_OID = re.compile(r"[0-9a-f]{40}\Z")
_EPOCH = re.compile(r"(?:3[2-9]|[4-9][0-9]|[1-9][0-9]{2,})\Z")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_CHANGE_ID = re.compile(r"svc:[0-9a-f]{64}\Z")
_BRANCH = re.compile(r"refs/heads/\S+\Z")


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def seal(body: dict[str, Any]) -> dict[str, Any]:
    clean = {k: v for k, v in body.items() if k != "result_sha256"}
    return {**clean, "result_sha256": "sha256:" + hashlib.sha256(canon(clean)).hexdigest()}


def seal_verifies(result: Any) -> bool:
    return isinstance(result, dict) and seal(result).get("result_sha256") == result.get("result_sha256")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    return subprocess.run(["git", "-C", str(repo), *args], env=env, capture_output=True, check=False)


def _out(proc: subprocess.CompletedProcess) -> str | None:
    return proc.stdout.decode().strip() if proc.returncode == 0 else None


def read_ref(repository: Any, ref: str) -> str | None:
    """The commit ``ref`` points at now (call BEFORE the push for old_sha). Read-only; reads the ref value, not its history."""
    repo = Path(str(repository))
    sha = _out(_git(repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}"))
    return sha if sha and _OID.match(sha) else None


def _refuse(code: str, predicate: str, repair: str, next_attempt: str, **detail: Any) -> dict[str, Any]:
    return seal({"schema": REFUSAL_SCHEMA, "disposition": "FAIL_CLOSED", "failure_code": code, "failed_predicate": predicate,
                 "required_evidence_or_repair": repair, "retry_entrypoint": RETRY, "owning_existing_goal": OWNING_EXISTING_GOAL,
                 "next_attempt": next_attempt, "receipt_written": False, "detail": detail})


def emit(repository: Any, *, repository_name: Any, ref: Any, old_sha: Any, pusher_session: Any, hb_epoch: Any,
         after_ref: str | None = None, change_id: Any = None, out: Any = None) -> dict[str, Any]:
    """Emit the sv-push-receipt.v1 for a push that just happened. Never raises; refusals write nothing."""
    if hb_epoch is None:
        return _refuse("HB_EPOCH_NOT_SUPPLIED", "HB_EPOCH_SUPPLIED", "the caller supplies hb_epoch (ASCII digits >= 32); never a clock",
                       "re-run with the supplied hb_epoch")
    if isinstance(hb_epoch, int) and not isinstance(hb_epoch, bool):
        hb_epoch = str(hb_epoch)
    if not isinstance(hb_epoch, str) or not hb_epoch.isascii() or not _EPOCH.match(hb_epoch):
        return _refuse("HB_EPOCH_INVALID", "HB_EPOCH_SUPPLIED", "hb_epoch is ASCII digits with value >= 32", "re-run with a well-formed hb_epoch")
    for ok, name, want in ((isinstance(repository_name, str) and _REPO.match(repository_name), "repository_name", "owner/name"),
                           (isinstance(ref, str) and _BRANCH.match(ref), "ref", "refs/heads/<branch>"),
                           (isinstance(pusher_session, str) and pusher_session.strip(), "pusher_session", "the pushing session"),
                           (change_id is None or (isinstance(change_id, str) and _CHANGE_ID.match(change_id)), "change_id", "svc:<64 hex> or absent"),
                           (isinstance(old_sha, str) and _OID.match(old_sha), "old_sha", "the 40-hex ref value read before the push")):
        if not ok:
            return _refuse("PUSH_RECEIPT_INPUT_INVALID", "PUSH_RECEIPT_INPUTS_WELL_FORMED", f"{name}: {want}", "re-run with well-formed inputs", field=name)
    repo = Path(str(repository)) if isinstance(repository, (str, Path)) else None
    if repo is None or _out(_git(repo, "rev-parse", "--git-dir")) is None:
        return _refuse("PUSH_NOT_OBSERVED", "REPOSITORY_READABLE", "the local repository the push was made from", "re-run in that repository")
    after = after_ref or ref
    new_sha = read_ref(repo, after)
    if new_sha is None:
        return _refuse("PUSH_NOT_OBSERVED", "PUSHED_REF_READ_AFTER_PUSH", f"{after} resolves to a commit after the push", "re-run after the push completes")
    if _out(_git(repo, "cat-file", "-e", old_sha + "^{commit}")) is None:
        return _refuse("PUSH_NOT_OBSERVED", "OLD_SHA_PRESENT", f"commit {old_sha} (the ref read before the push) is present", "re-run in the pushing clone")
    if new_sha == old_sha:
        return _refuse("PUSH_NOT_OBSERVED", "PUSH_MOVED_REF", f"{after} moved from {old_sha}; it did not", "emit after a push that moved the ref",
                       old_sha=old_sha, new_sha=new_sha)
    if _git(repo, "merge-base", "--is-ancestor", old_sha, new_sha).returncode != 0:
        return _refuse("PUSH_NOT_FAST_FORWARD", "PUSH_IS_FAST_FORWARD", f"{old_sha} is an ancestor of {new_sha}; a rewrite is not receipted",
                       "a fast-forward push (no force-push)", old_sha=old_sha, new_sha=new_sha)
    listed = _out(_git(repo, "rev-list", "--reverse", "--topo-order", f"{old_sha}..{new_sha}"))
    commits = [c for c in (listed or "").split() if _OID.match(c)]
    if not commits or commits[-1] != new_sha or len(set(commits)) != len(commits):
        return _refuse("PUSH_NOT_OBSERVED", "PUSHED_COMMITS_LISTED", f"rev-list {old_sha}..{new_sha} lists the pushed commits ending at {new_sha}",
                       "re-run in the pushing clone")
    body = {"schema": RECEIPT_SCHEMA, "repository": repository_name, "ref": ref, "old_sha": old_sha, "new_sha": new_sha,
            "pusher_session": pusher_session, "pushed_commits": commits, "hb_epoch": hb_epoch}
    if change_id is not None:
        body["change_id"] = change_id
    receipt = seal(body)
    if out is not None:
        Path(str(out)).write_bytes(json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    return receipt


def receipt_problem(r: Any) -> str | None:
    """Shape of sv-push-receipt.v1 (closed) plus the seal. None when it holds."""
    if not isinstance(r, dict) or r.get("schema") != RECEIPT_SCHEMA:
        return "schema"
    if set(r) - RECEIPT_FIELDS or RECEIPT_FIELDS - {"change_id"} - set(r):
        return "fields"
    if not (isinstance(r["repository"], str) and _REPO.match(r["repository"]) and isinstance(r["ref"], str) and _BRANCH.match(r["ref"])):
        return "repository_or_ref"
    if not all(isinstance(r[k], str) and _OID.match(r[k]) for k in ("old_sha", "new_sha")):
        return "old_or_new_sha"
    c = r["pushed_commits"]
    if not isinstance(c, list) or not c or any(not (isinstance(x, str) and _OID.match(x)) for x in c) or len(set(c)) != len(c) or c[-1] != r["new_sha"]:
        return "pushed_commits"
    if not (isinstance(r["pusher_session"], str) and r["pusher_session"].strip()):
        return "pusher_session"
    if "change_id" in r and not (isinstance(r["change_id"], str) and _CHANGE_ID.match(r["change_id"])):
        return "change_id"
    if not (isinstance(r["hb_epoch"], str) and _EPOCH.match(r["hb_epoch"])):
        return "hb_epoch"
    if not seal_verifies(r):
        return "seal"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read-ref", help="print the ref's commit; run BEFORE the push for --old-sha")
    r.add_argument("--repository", type=Path, required=True)
    r.add_argument("--ref", required=True)
    e = sub.add_parser("emit", help="run AFTER the push")
    e.add_argument("--repository", type=Path, required=True)
    e.add_argument("--repository-name", required=True)
    e.add_argument("--ref", required=True)
    e.add_argument("--after-ref", default=None)
    e.add_argument("--old-sha", required=True)
    e.add_argument("--pusher-session", required=True)
    e.add_argument("--hb-epoch", default=None)
    e.add_argument("--change-id", default=None)
    e.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.cmd == "read-ref":
        sha = read_ref(args.repository, args.ref)
        print(sha or "")
        return 0 if sha else 1
    result = emit(args.repository, repository_name=args.repository_name, ref=args.ref, old_sha=args.old_sha,
                  pusher_session=args.pusher_session, hb_epoch=args.hb_epoch, after_ref=args.after_ref,
                  change_id=args.change_id, out=args.out)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("schema") == RECEIPT_SCHEMA else 1


if __name__ == "__main__":
    sys.exit(main())
