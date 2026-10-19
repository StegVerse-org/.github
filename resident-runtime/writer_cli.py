#!/usr/bin/env python3
"""Run a writer CLI so that every failure leaves as a six-field record, never a traceback.

F-WRITER-TRACE. Every entrypoint that takes an epoch and writes a ledger, a
mesh or its node's own state runs its ``main`` through ``run``:

- a fault writing its own state (an OSError, a lost compare-and-swap or
  contention, a store collision) is a non-terminal six-field WRITE_FAILED and
  exit 75 (EX_TEMPFAIL): nothing was half-published that the next run does not
  complete, so the same invocation is retried unchanged;
- a writer's refusal carrying a message (``SystemExit("CODE: detail")``, or
  one carrying its own six-field ``.refusal``) is that refusal, six-field, and
  exit 1, with the message still on stderr;
- any other exception is the input's: six-field WRITER_INPUT_REFUSED, exit 1.

An integer exit (argparse's 2, a main's own return code) passes through
unchanged. No clock is read.
"""
from __future__ import annotations

import json
import sys

OWNING_EXISTING_GOAL = "INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001"
TRANSIENT_EXIT = 75
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
WRITER_FAULT_MARKERS = ("collision", "contention", "lost_comparison")


def writer_fault(exc: BaseException) -> bool:
    """True for a fault writing the writer's own state, which a retry completes."""
    if isinstance(exc, (OSError, RuntimeError)):
        return True
    return isinstance(exc, ValueError) and any(m in str(exc).lower() for m in WRITER_FAULT_MARKERS)


def record(exc: BaseException, entrypoint: str, owning_goal: str = OWNING_EXISTING_GOAL) -> dict:
    """The six-field record of one failed writer invocation."""
    refusal = getattr(exc, "refusal", None)
    if isinstance(refusal, dict) and all(refusal.get(field) for field in ("failure_code", "failed_predicate")):
        return {"disposition": refusal.get("disposition") or "FAIL_CLOSED", "terminal": False,
                **{field: refusal.get(field) for field in SIX_FIELDS},
                "retry_entrypoint": refusal.get("retry_entrypoint") or entrypoint,
                "owning_existing_goal": refusal.get("owning_existing_goal") or owning_goal,
                "required_evidence_or_repair": refusal.get("required_evidence_or_repair")
                or "satisfy the failed predicate and rerun",
                "next_attempt": refusal.get("next_attempt") or "rerun " + entrypoint + " once the predicate holds",
                "detail": str(refusal.get("detail") or exc)[:240]}
    if writer_fault(exc):
        return {"disposition": "FAIL_CLOSED", "terminal": False, "failure_code": "WRITE_FAILED",
                "failed_predicate": type(exc).__name__, "detail": str(exc)[:240],
                "required_evidence_or_repair": "this writer's own state (ledger, mesh or node state) accepts the write",
                "retry_entrypoint": entrypoint, "owning_existing_goal": owning_goal,
                "next_attempt": "rerun the same invocation unchanged; an interrupted append is completed exactly once"}
    if isinstance(exc, SystemExit):
        text = str(exc.code)
        return {"disposition": "FAIL_CLOSED", "terminal": False,
                "failure_code": text.split(":", 1)[0].strip()[:120] or "WRITER_REFUSED",
                "failed_predicate": "WRITER_ACCEPTS_THE_SUBMISSION", "detail": text[:240],
                "required_evidence_or_repair": "satisfy the refusal named in failure_code and rerun",
                "retry_entrypoint": entrypoint, "owning_existing_goal": owning_goal,
                "next_attempt": "rerun " + entrypoint + " once the refusal is repaired; the writer refused before "
                                "publishing anything it does not complete on retry"}
    return {"disposition": "FAIL_CLOSED", "terminal": False, "failure_code": "WRITER_INPUT_REFUSED",
            "failed_predicate": type(exc).__name__, "detail": str(exc)[:240],
            "required_evidence_or_repair": "supply well-formed input to " + entrypoint,
            "retry_entrypoint": entrypoint, "owning_existing_goal": owning_goal,
            "next_attempt": "rerun with corrected input"}


def run(main, entrypoint: str, owning_goal: str = OWNING_EXISTING_GOAL):
    """Call ``main()``; return its exit code, or print a six-field record and return a failure code."""
    try:
        return main()
    except SystemExit as exc:
        if exc.code is None or isinstance(exc.code, int):
            raise
        result, code = record(exc, entrypoint, owning_goal), 1
        print(str(exc.code), file=sys.stderr)
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001 -- every failure leaves as six fields
        result = record(exc, entrypoint, owning_goal)
        code = TRANSIENT_EXIT if writer_fault(exc) else 1
        print(type(exc).__name__ + ": " + str(exc)[:240], file=sys.stderr)
    print(json.dumps(result, sort_keys=True), flush=True)
    return code
