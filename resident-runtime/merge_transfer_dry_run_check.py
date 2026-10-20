#!/usr/bin/env python3
"""Dry-run gate: every selected merge is ALLOW VERIFIED or FAIL_CLOSED NOT_LEDGERED with six fields.

The validation workflow reads the real ledger state for the merges a push selects. A mix of ledgered and
unledgered merges is expected, so the gate accepts exactly two record shapes and nothing weaker:

- disposition ALLOW with transfer VERIFIED;
- disposition FAIL_CLOSED with failure_code MERGE_TRANSFER_RECEIPT_NOT_LEDGERED, every one of the six
  fields a non-empty string without surrounding whitespace.

Any other record (DENY, another failure code, a non-string or padded field, a non-object record, a
non-list result) fails the gate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from merge_transfer import ALLOW, FAIL_CLOSED, NOT_LEDGERED, SIX_FIELDS  # noqa: E402


def _field_ok(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value.strip() == value


def record_ok(record: object) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("disposition") == ALLOW:
        return record.get("transfer") == "VERIFIED"
    return (record.get("disposition") == FAIL_CLOSED
            and record.get("failure_code") == NOT_LEDGERED
            and all(_field_ok(record.get(f)) for f in SIX_FIELDS))


def check(results: object) -> list[str]:
    """Return one failure line per rejected record; an empty list means the gate passes."""
    if not isinstance(results, list):
        return ["results must be a list of merge records"]
    if not results:
        return ["no merges selected"]
    return [f"record {i} rejected: {json.dumps(r, sort_keys=True)}" for i, r in enumerate(results) if not record_ok(r)]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: merge_transfer_dry_run_check.py <real-state.json>", file=sys.stderr)
        return 2
    results = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    for r in results if isinstance(results, list) else []:
        if isinstance(r, dict):
            print(r.get("merge_commit"), r.get("disposition"), r.get("transfer"), r.get("failure_code"))
    failures = check(results)
    for line in failures:
        print("DRY_RUN_GATE_FAIL:", line)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
