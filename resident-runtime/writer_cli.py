#!/usr/bin/env python3
"""Run a writer CLI so that every failure leaves as a six-field record, never a traceback.

F-WRITER-TRACE. Every entrypoint that takes an epoch and writes a ledger, a
mesh or its node's own state runs its ``main`` through ``run``:

- every input file the CLI names (``inputs``, its flags) is read first, before
  ``main`` runs and outside the fault classifier: a missing, unreadable,
  non-UTF-8 or non-JSON file, or one whose top level is not an object, is a
  TERMINAL six-field INPUT_UNREADABLE / INPUT_INVALID, exit 1, nothing written
  (F-INPUT-TRACE);
- a fault writing its own state (an OSError, a lost compare-and-swap or
  contention) is a non-terminal six-field WRITE_FAILED and exit 75
  (EX_TEMPFAIL). The write may already be committed (HEAD published, a later
  durability step failed): the same invocation is rerun unchanged and the
  idempotent retry returns the recorded receipt (F-POST-HEAD);
- a ledger receipt collision -- another transition under an id already
  recorded -- and a writer's refusal carrying a message
  (``SystemExit("CODE: detail")``, or its own six-field ``.refusal``) are
  terminal six-field refusals, exit 1, with the message still on stderr;
- any other exception is the input's: terminal six-field WRITER_INPUT_REFUSED,
  exit 1.

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
WRITER_FAULT_MARKERS = ("contention", "lost_comparison")


def writer_fault(exc: BaseException) -> bool:
    """True for a fault writing the writer's own state, which a retry completes.

    RecursionError (a RuntimeError) and MemoryError come from input too deep to
    parse (F-SCAN-RECURSION): the input's fault, terminal, never a writer fault.
    """
    if isinstance(exc, (RecursionError, MemoryError)):
        return False
    if isinstance(exc, (OSError, RuntimeError)):
        return True
    return isinstance(exc, (ValueError, SystemExit)) and any(m in str(exc).lower() for m in WRITER_FAULT_MARKERS)


def input_refusal(flag: str, path: str, reason: str, code: str, entrypoint: str, owning_goal: str) -> dict:
    """The terminal six-field record of an input file the CLI cannot use; nothing was written."""
    return {"disposition": "FAIL_CLOSED", "terminal": True, "failure_code": code,
            "failed_predicate": "CLI_INPUT_IS_A_READABLE_JSON_OBJECT", "detail": (flag + " " + path + ": " + reason)[:240],
            "required_evidence_or_repair": "pass " + flag + " a readable UTF-8 JSON object file",
            "retry_entrypoint": entrypoint, "owning_existing_goal": owning_goal,
            "next_attempt": "rerun with a corrected " + flag + "; nothing was read further or written"}


def read_inputs(argv, inputs, entrypoint, owning_goal):
    """Check every file the named flags point at; the first refusal, or None."""
    values = []
    for index, arg in enumerate(argv):
        for flag in inputs:
            if arg == flag and index + 1 < len(argv):
                values.append((flag, argv[index + 1]))
            elif arg.startswith(flag + "="):
                values.append((flag, arg.split("=", 1)[1]))
    for flag, path in values:
        try:
            with open(path, "rb") as stream:
                document = json.loads(stream.read().decode("utf-8"))
        except OSError as exc:
            return input_refusal(flag, path, type(exc).__name__ + ": " + str(exc), "INPUT_UNREADABLE",
                                 entrypoint, owning_goal)
        except (UnicodeDecodeError, ValueError, RecursionError, MemoryError) as exc:
            return input_refusal(flag, path, type(exc).__name__ + ": " + str(exc)[:160], "INPUT_INVALID",
                                 entrypoint, owning_goal)
        if not isinstance(document, dict):
            return input_refusal(flag, path, "top level is " + type(document).__name__ + ", not an object",
                                 "INPUT_INVALID", entrypoint, owning_goal)
    return None


def record(exc: BaseException, entrypoint: str, owning_goal: str = OWNING_EXISTING_GOAL) -> dict:
    """The six-field record of one failed writer invocation."""
    refusal = getattr(exc, "refusal", None)
    if isinstance(refusal, dict) and all(refusal.get(field) for field in ("failure_code", "failed_predicate")):
        return {"disposition": refusal.get("disposition") or "FAIL_CLOSED", "terminal": writer_fault(exc) is False,
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
                "next_attempt": "rerun the same invocation unchanged. The write may already be committed (HEAD "
                                "published before a durability step failed); the retry is idempotent and returns "
                                "the recorded receipt, and an interrupted append is completed exactly once"}
    if isinstance(exc, ValueError) and "ledger_receipt_collision" in str(exc):
        return {"disposition": "FAIL_CLOSED", "terminal": True, "failure_code": "LEDGER_RECEIPT_COLLISION",
                "failed_predicate": "ONE_TRANSITION_ID_BINDS_ONE_TRANSITION", "detail": str(exc)[:240],
                "required_evidence_or_repair": "a different transition takes its own id; an exact retry carries "
                                               "the recorded transition's fields",
                "retry_entrypoint": entrypoint, "owning_existing_goal": owning_goal,
                "next_attempt": "nothing was written; the recorded transition stands"}
    if isinstance(exc, SystemExit):
        text = str(exc.code)
        return {"disposition": "FAIL_CLOSED", "terminal": True,
                "failure_code": text.split(":", 1)[0].strip()[:120] or "WRITER_REFUSED",
                "failed_predicate": "WRITER_ACCEPTS_THE_SUBMISSION", "detail": text[:240],
                "required_evidence_or_repair": "satisfy the refusal named in failure_code and rerun",
                "retry_entrypoint": entrypoint, "owning_existing_goal": owning_goal,
                "next_attempt": "rerun " + entrypoint + " once the refusal is repaired; the writer refused before "
                                "publishing anything it does not complete on retry"}
    return {"disposition": "FAIL_CLOSED", "terminal": True, "failure_code": "WRITER_INPUT_REFUSED",
            "failed_predicate": type(exc).__name__, "detail": str(exc)[:240],
            "required_evidence_or_repair": "supply well-formed input to " + entrypoint,
            "retry_entrypoint": entrypoint, "owning_existing_goal": owning_goal,
            "next_attempt": "rerun with corrected input"}


def run(main, entrypoint: str, owning_goal: str = OWNING_EXISTING_GOAL, inputs=()):
    """Call ``main()``; return its exit code, or print a six-field record and return a failure code."""
    refused = read_inputs(sys.argv[1:], inputs, entrypoint, owning_goal) if inputs else None
    if refused is not None:
        print(refused["detail"], file=sys.stderr)
        print(json.dumps(refused, sort_keys=True), flush=True)
        return 1
    try:
        return main()
    except SystemExit as exc:
        if exc.code is None or isinstance(exc.code, int):
            raise
        result = record(exc, entrypoint, owning_goal)
        code = TRANSIENT_EXIT if result["terminal"] is False and writer_fault(exc) else 1
        print(str(exc.code), file=sys.stderr)
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001 -- every failure leaves as six fields
        result = record(exc, entrypoint, owning_goal)
        code = TRANSIENT_EXIT if writer_fault(exc) else 1
        print(type(exc).__name__ + ": " + str(exc)[:240], file=sys.stderr)
    print(json.dumps(result, sort_keys=True), flush=True)
    return code
