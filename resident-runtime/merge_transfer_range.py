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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--before", default="")
    parser.add_argument("--after", required=True)
    parser.add_argument("--pending")
    args = parser.parse_args(argv)
    base, result = unreceipted_base(args.before, args.after)
    if result is not None and result["disposition"] == mt.DENY:
        print(json.dumps({"range_base": args.before, "included": False, "verify": result}, sort_keys=True),
              file=sys.stderr)
    print("\n".join(commits_for_push(args.before, args.after, args.pending)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
