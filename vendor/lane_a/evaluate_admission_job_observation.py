#!/usr/bin/env python3
"""Admission predicate: every expected job at the exact head was observed and passed.

Rule (UNKNOWN never yields PASS): a job is admission input only when a completed
check run whose ``head_sha`` equals the exact head SHA concluded ``success``.
UNKNOWN_NOT_AUTHENTICALLY_OBSERVED, never PASS:
- no check run at all (for example, a workflow ``paths:`` filter kept it from triggering);
- skipped, neutral, cancelled, stale or null conclusions;
- pending runs;
- runs whose ``head_sha`` is missing, null or different. Such runs are not evidence for this head.
A failure-class conclusion is FAIL.

Retry resolution: when several runs exist for one job at the head, the one with the latest
``started_at`` wins; ties (or missing ``started_at``) fall back to the larger ``id``. This
lets a fail-then-success retry resolve to PASS. TVC's native receipts carry no ordering and
fail closed on duplicate dispositions instead (TVC#519 docs/SV_CHANGE_ADMISSION_PREDICATE_REFERENCE.md
L134-137), which diverges only in the safe direction.

Refusals: an empty expected-job list, a head SHA that is not 40 lowercase hex, a missing or
invalid ``hb_epoch``, an invalid ``change_digest`` or a malformed check-run document
returns a sealed six-field FAIL_CLOSED record with a nonzero exit. It does not raise.

Binding (TVC scheme, StegVerse-Labs/TVC@7863ce36 ``tvc_request_digest.py`` blob ac242efa
L26-57 and ``github_repository_operation_broker.py`` blob 73867ef1 L49-56, L195-241, as
named in docs/SV_CHANGE_ADMISSION_PREDICATE_REFERENCE.md blob 07a18cb3 L39-45, L81-85, L107):
- ``hb_epoch`` is caller-supplied ASCII digits with value >= 32; no clock is read.
- ``change_digest`` is ``sha256:`` + 64 lowercase hex. It is either supplied by the caller,
  or computed from the SV_CHANGE ``content`` list sorted by ``path``.
- The record is sealed in ``result_sha256`` = ``sha256:`` + sha256 over canonical JSON
  (sorted keys, ``(",", ":")`` separators, UTF-8, ``ensure_ascii=False``) of every other field.

Input is the JSON of ``GET /repos/{owner}/{repo}/commits/{sha}/check-runs``, read by the caller.
This module does no network, clock or credential access. Its output is an input to the
merge-admission transition, not admission. Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from typing import Any, Mapping

SCHEMA = "stegverse.admission-job-observation/v2"
PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"
FAIL_CONCLUSIONS = {"failure", "timed_out", "action_required", "startup_failure"}
READY = "ADMISSION_INPUT_READY"
NOT_READY = "NOT_ADMISSION_INPUT_READY"
FAIL_CLOSED = "FAIL_CLOSED"
SEAL_FIELD = "result_sha256"
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
DEFAULT_GOAL = "OWNING_EXISTING_GOAL_NOT_SUPPLIED_BY_CONSUMER"
RETRY_ENTRYPOINT = ("re-run scripts/evaluate_admission_job_observation.py with --check-runs, a 40-hex "
                    "--head-sha, at least one --expect and --hb-epoch <digits >= 32>")
HB_EPOCH_MINIMUM = 32
_HEX40 = re.compile(r"[0-9a-f]{40}")
_DIGITS = re.compile(r"[0-9]+")
_PREFIX = "sha256:"


# --- TVC digest/seal rule (tvc_request_digest.py L26-57 at TVC@7863ce36) ---
def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value: Any) -> str:
    raw = value if isinstance(value, (bytes, bytearray)) else canonical_bytes(value)
    return _PREFIX + hashlib.sha256(raw).hexdigest()


def is_prefixed_sha256(value: Any) -> bool:
    return (isinstance(value, str) and value.startswith(_PREFIX) and len(value) == len(_PREFIX) + 64
            and all(c in "0123456789abcdef" for c in value[len(_PREFIX):]))


def seal(body: Mapping[str, Any], field: str = SEAL_FIELD) -> dict:
    clean = {k: v for k, v in body.items() if k != field}
    return {**clean, field: digest(clean)}


def seal_verifies(record: Any, field: str = SEAL_FIELD) -> bool:
    if not isinstance(record, Mapping):
        return False
    claimed = record.get(field)
    return is_prefixed_sha256(claimed) and claimed == digest({k: v for k, v in record.items() if k != field})


def change_digest(content: Any) -> str:
    """TVC change_digest rule (sv_change_admission.py L71-73 at TVC@7863ce36)."""
    return digest(sorted((dict(e) for e in content), key=lambda e: str(e.get("path"))))


# --- predicate ---
class _Refusal(Exception):
    def __init__(self, code: str, predicate: str, repair: str, nxt: str) -> None:
        super().__init__(code)
        self.code, self.predicate, self.repair, self.nxt = code, predicate, repair, nxt


def _epoch(hb_epoch: Any) -> int:
    if hb_epoch is None or hb_epoch == "":
        raise _Refusal("HB_EPOCH_NOT_SUPPLIED", "HB_EPOCH_IS_SUPPLIED_BY_THE_CARRIER_AS_DIGITS_GE_32",
                       "supply hb_epoch from the carrier; no clock is read", "re-run with --hb-epoch <digits >= 32>")
    text = str(hb_epoch) if isinstance(hb_epoch, int) and not isinstance(hb_epoch, bool) else hb_epoch
    if not isinstance(text, str) or not _DIGITS.fullmatch(text) or int(text) < HB_EPOCH_MINIMUM:
        raise _Refusal("HB_EPOCH_INVALID", "HB_EPOCH_IS_SUPPLIED_BY_THE_CARRIER_AS_DIGITS_GE_32",
                       "hb_epoch must be ASCII digits with value >= 32", "re-run with --hb-epoch <digits >= 32>")
    return int(text)


def _classify(runs: list) -> tuple[str, str]:
    if not runs:
        return UNKNOWN, "NO_CHECK_RUN_AT_HEAD (not triggered, e.g. path-filtered)"
    # Retry resolution: latest started_at, then larger id (see module docstring).
    run = max(runs, key=lambda r: (r.get("started_at") or "", r.get("id") or 0))
    status, conclusion = run.get("status"), run.get("conclusion")
    if status != "completed":
        return UNKNOWN, f"NOT_COMPLETED status={status}"
    if conclusion == "success":
        return PASS, "completed success"
    if conclusion in FAIL_CONCLUSIONS:
        return FAIL, f"completed {conclusion}"
    return UNKNOWN, f"NOT_OBSERVED_AS_PASS conclusion={conclusion}"


def _is_evidence_for_head(run: Mapping[str, Any], head_sha: str) -> bool:
    return run.get("head_sha") == head_sha  # missing, null or other head is never evidence


def evaluate(check_runs_doc: Any, head_sha: Any, expected_jobs: Any, *, hb_epoch: Any,
             change_digest_value: Any = None, owning_existing_goal: str | None = None) -> dict:
    """Return a sealed record. Never raises for bad input; refusals are six-field FAIL_CLOSED."""
    goal = owning_existing_goal if isinstance(owning_existing_goal, str) and owning_existing_goal.strip() else DEFAULT_GOAL
    base = {"schema": SCHEMA, "head_sha": head_sha if isinstance(head_sha, str) else None,
            "change_digest": change_digest_value if is_prefixed_sha256(change_digest_value) else None,
            "hb_epoch": None, "authority_effect": "NONE_ADMISSION_INPUT_ONLY"}
    try:
        base["hb_epoch"] = _epoch(hb_epoch)
        if not isinstance(expected_jobs, (list, tuple)) or not expected_jobs \
                or not all(isinstance(j, str) and j for j in expected_jobs):
            raise _Refusal("EXPECTED_JOBS_NOT_DECLARED", "EXPECTED_JOB_SET_IS_DECLARED_AND_NON_EMPTY",
                           "declare at least one expected job name; an empty expectation cannot admit",
                           "re-run with one --expect per expected job")
        if not isinstance(head_sha, str) or not _HEX40.fullmatch(head_sha):
            raise _Refusal("HEAD_SHA_INVALID", "HEAD_SHA_IS_40_LOWERCASE_HEX",
                           "supply the full 40-character lowercase hex commit SHA of the exact head",
                           "re-run with --head-sha <40 lowercase hex>")
        if change_digest_value is not None and not is_prefixed_sha256(change_digest_value):
            raise _Refusal("CHANGE_DIGEST_INVALID", "CHANGE_DIGEST_IS_PREFIXED_SHA256",
                           "change_digest must be 'sha256:' + 64 lowercase hex (TVC rule)",
                           "re-run with a valid --change-digest or --content")
        runs = check_runs_doc.get("check_runs") if isinstance(check_runs_doc, Mapping) else None
        if not isinstance(runs, list) or not all(isinstance(r, Mapping) for r in runs):
            raise _Refusal("CHECK_RUNS_DOCUMENT_MALFORMED", "CHECK_RUNS_DOCUMENT_HAS_CHECK_RUNS_LIST",
                           "the check-runs JSON for the exact head, with a check_runs list of objects",
                           "re-read GET /repos/{owner}/{repo}/commits/{sha}/check-runs and re-run")
    except _Refusal as r:
        return seal({**base, "decision": FAIL_CLOSED, "failure_code": r.code, "failed_predicate": r.predicate,
                     "required_evidence_or_repair": r.repair, "retry_entrypoint": RETRY_ENTRYPOINT,
                     "owning_existing_goal": goal, "next_attempt": r.nxt})
    by_name: dict = {}
    not_evidence = 0
    for run in runs:
        if not _is_evidence_for_head(run, head_sha):
            not_evidence += 1
            continue
        by_name.setdefault(run.get("name"), []).append(run)
    expected = set(expected_jobs)
    jobs = []
    for name in sorted(expected):
        state, reason = _classify(by_name.get(name, []))
        jobs.append({"job": name, "state": state, "reason": reason})
    ready = all(j["state"] == PASS for j in jobs)
    return seal({
        **base,
        "decision": READY if ready else NOT_READY,
        "counts": {s: sum(j["state"] == s for j in jobs) for s in (PASS, FAIL, UNKNOWN)},
        "jobs": jobs,
        "runs_not_evidence_for_head": not_evidence,
        "unexpected_jobs_observed": sorted(str(n) for n in by_name if n not in expected),
        "owning_existing_goal": goal,
    })


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check-runs", required=True, help="path to check-runs JSON for the head")
    ap.add_argument("--head-sha", default=None)
    ap.add_argument("--expect", action="append", default=[], help="expected job name (repeatable)")
    ap.add_argument("--hb-epoch", default=None, help="carrier-supplied epoch, ASCII digits >= 32")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--change-digest", default=None, help="sha256:<64 hex> per the TVC rule")
    g.add_argument("--content", default=None, help="path to SV_CHANGE content[] JSON; change_digest is computed")
    ap.add_argument("--owning-existing-goal", default=None)
    args = ap.parse_args(argv)
    try:
        with open(args.check_runs, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        doc = None
    cd = args.change_digest
    if args.content is not None:
        try:
            with open(args.content, encoding="utf-8") as fh:
                cd = change_digest(json.load(fh))
        except (OSError, ValueError, TypeError, AttributeError):
            cd = "INVALID_CONTENT"
    record = evaluate(doc, args.head_sha, args.expect, hb_epoch=args.hb_epoch,
                      change_digest_value=cd, owning_existing_goal=args.owning_existing_goal)
    print(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False))
    return {READY: 0, NOT_READY: 1}.get(record["decision"], 2)


if __name__ == "__main__":
    sys.exit(main())
