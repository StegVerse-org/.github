#!/usr/bin/env python3
"""The merges one push to main carries, including an unreceipted range base.

resident-runtime/merge_transfer.py::pushed_commits lists the pending merges
(.stegverse/merge-transfer/pending.json) and then ``before..after`` on the
first-parent line. ``before`` is excluded there, as in git: it was carried by
an earlier push. That earlier push may have landed before the merge-transfer
writer existed, or its run may not have appended, so ``before`` can be on main
with no receipt (StegVerse-org/.github#203, f40ad7dd, the base of the 41035e9e
push). This adds ``before`` back, after the pending merges and before the
range, only when all of these hold:

  - it is 40 lowercase hex, not the all-zero sha, and an ancestor of ``after``;
  - it is on ``after``'s first-parent line (it was main's tip);
  - verify_merge_transfer answers FAIL_CLOSED MERGE_TRANSFER_RECEIPT_NOT_LEDGERED
    for it on the ledger the writer is about to append to.

An ALLOW base is already ledgered, and a DENY base contradicts the ledger: neither
is appended (a DENY is printed, never appended over). Only the immediate base is
considered; older gaps are listed in pending.json. merge_transfer.py is
unchanged and is only called.

Dry-run selection (``--select-ledgered-base-when-empty``, the PR dry run's
``--before BASE --after BASE``): once BASE is itself ledgered and nothing is
pending, the range is empty. An empty list is never handed to verify. The
selection is then BASE, the last ledgered first-parent merge, only when
verify_merge_transfer answers ALLOW VERIFIED for it, so verify is a no-op read
of the recorded receipt and the writer's append is an idempotent replay. Any
other answer (absent base, base not on the first-parent line, DENY, another
FAIL_CLOSED) is FAIL_CLOSED DRY_RUN_SELECTION_EMPTY with six fields and exit 1.
No clock and no network are read.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("merge_transfer_for_range", ROOT / "resident-runtime/merge_transfer.py")
mt = importlib.util.module_from_spec(_spec)
sys.modules["merge_transfer_for_range"] = mt
_spec.loader.exec_module(mt)


def unreceipted_base(before: str | None, after: str, organization: Any = None, repository_store: Any = None,
                     git_dir: Path | str = ROOT) -> tuple[str | None, dict[str, Any] | None]:
    """(before, its verify result) when ``before`` is an unreceipted base to include, else (None, result or None)."""
    if not before or not mt.SHA40.fullmatch(before) or set(before) == {"0"}:
        return None, None
    if mt._git("merge-base", "--is-ancestor", before, after, git_dir=git_dir).returncode != 0:
        return None, None
    line = mt._git("rev-list", "--first-parent", after, git_dir=git_dir)
    if line.returncode != 0 or before not in line.stdout.split():
        return None, None
    result = mt.verify_merge_transfer(mt.repository(), before, organization, repository_store)
    if result["disposition"] == mt.FAIL_CLOSED and result["failure_code"] == mt.NOT_LEDGERED:
        return before, result
    return None, result


def commits_for_push(before: str | None, after: str, pending_path: Path | str | None, organization: Any = None,
                     repository_store: Any = None, git_dir: Path | str = ROOT) -> list[str]:
    listed = mt.pushed_commits(before, after, pending_path, git_dir=git_dir)
    pending = [c for c in (mt.pending(pending_path) if pending_path else []) if c in listed]
    pushed = [c for c in listed if c not in pending]
    base, _ = unreceipted_base(before, after, organization, repository_store, git_dir)
    middle = [base] if base and base not in listed else []
    return pending + middle + pushed


SELECTION_EMPTY = "DRY_RUN_SELECTION_EMPTY"


def dry_run_selection(base: str | None, pending_path: Path | str | None, organization: Any = None,
                      repository_store: Any = None, git_dir: Path | str = ROOT) -> tuple[list[str], dict[str, Any] | None]:
    """(commits, None) for the PR dry run, or ([], six-field FAIL_CLOSED); never an empty selection."""
    def refuse(detail: str, verify: Any = None) -> tuple[list[str], dict[str, Any]]:
        out = mt.refusal(SELECTION_EMPTY, "DRY_RUN_SELECTS_AT_LEAST_ONE_MERGE",
                         "the PR base must be a 40-hex first-parent merge on main that is either unreceipted, "
                         "pending, or ledgered ALLOW VERIFIED (then it is re-verified against its recorded receipt)",
                         "re-run the PR's validation once its base is such a merge; nothing was verified or written",
                         range_base=base or "", detail=detail)
        if verify is not None:
            out["verify"] = verify
        return [], out

    if not base or not mt.SHA40.fullmatch(base) or set(base) == {"0"}:
        return refuse("no PR base commit")
    if mt._git("cat-file", "-e", base + "^{commit}", git_dir=git_dir).returncode != 0:
        return refuse("the PR base commit is not in this checkout")
    commits = commits_for_push(base, base, pending_path, organization, repository_store, git_dir)
    if commits:
        return commits, None
    result = mt.verify_merge_transfer(mt.repository(), base, organization, repository_store)
    if result.get("disposition") == mt.ALLOW and result.get("transfer") == "VERIFIED":
        return [base], None
    return refuse("the empty range's base is not ledgered ALLOW VERIFIED", result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--before", default="")
    parser.add_argument("--after", required=True)
    parser.add_argument("--pending")
    parser.add_argument("--select-ledgered-base-when-empty", action="store_true",
                        help="PR dry run: an empty range selects BASE when it is ledgered ALLOW VERIFIED, "
                             "else FAIL_CLOSED with six fields")
    args = parser.parse_args(argv)
    if args.select_ledgered_base_when_empty:
        if args.before != args.after:
            print(json.dumps(mt.refusal(SELECTION_EMPTY, "DRY_RUN_SELECTION_IS_BASE_TO_BASE",
                                        "pass --before BASE --after BASE", "re-run with the PR base; nothing was done"),
                             sort_keys=True), file=sys.stderr)
            return 1
        commits, refused = dry_run_selection(args.after, args.pending)
        if refused is not None:
            print(json.dumps(refused, sort_keys=True), file=sys.stderr)
            return 1
        print("\n".join(commits))
        return 0
    base, result = unreceipted_base(args.before, args.after)
    if result is not None and result["disposition"] == mt.DENY:
        print(json.dumps({"range_base": args.before, "included": False, "verify": result}, sort_keys=True),
              file=sys.stderr)
    print("\n".join(commits_for_push(args.before, args.after, args.pending)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
