#!/usr/bin/env python3
"""Admission predicate: every expected job at the exact head was observed and passed.

Rule: a job is admission input only when a completed check run for the exact
head SHA concluded ``success``. A job with no check run at all (for example,
one a workflow ``paths:`` filter kept from triggering), a skipped/neutral/
cancelled/stale run, or a pending run is UNKNOWN_NOT_AUTHENTICALLY_OBSERVED,
never a pass. A failure-class conclusion is FAIL.

Input is the JSON of ``GET /repos/{owner}/{repo}/commits/{sha}/check-runs``
(read by the caller; this module does no network or credential access) plus
the caller-declared list of expected job names. Output is a deterministic
evaluation record. Non-authorizing: the record is an input to the
merge-admission transition, not admission itself.

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys

SCHEMA = "stegverse.admission-job-observation/v1"
PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"
FAIL_CONCLUSIONS = {"failure", "timed_out", "action_required", "startup_failure"}
READY = "ADMISSION_INPUT_READY"
NOT_READY = "NOT_ADMISSION_INPUT_READY"


def _classify(runs: list[dict]) -> tuple[str, str]:
    if not runs:
        return UNKNOWN, "NO_CHECK_RUN_AT_HEAD (not triggered, e.g. path-filtered)"
    # Latest attempt wins; ties broken by id for determinism.
    run = max(runs, key=lambda r: (r.get("started_at") or "", r.get("id") or 0))
    status, conclusion = run.get("status"), run.get("conclusion")
    if status != "completed":
        return UNKNOWN, f"NOT_COMPLETED status={status}"
    if conclusion == "success":
        return PASS, "completed success"
    if conclusion in FAIL_CONCLUSIONS:
        return FAIL, f"completed {conclusion}"
    return UNKNOWN, f"NOT_OBSERVED_AS_PASS conclusion={conclusion}"


def evaluate(check_runs_doc: dict, head_sha: str, expected_jobs: list[str]) -> dict:
    if not expected_jobs:
        raise ValueError("expected_jobs must be declared; an empty expectation cannot admit")
    if len(head_sha) != 40 or any(c not in "0123456789abcdef" for c in head_sha):
        raise ValueError("head_sha must be a full lowercase 40-hex commit SHA")
    runs = check_runs_doc.get("check_runs")
    if not isinstance(runs, list):
        raise ValueError("check_runs_doc must contain a check_runs list")
    by_name: dict[str, list[dict]] = {}
    foreign_head = 0
    for run in runs:
        if run.get("head_sha") not in (None, head_sha):
            foreign_head += 1
            continue  # a run for another commit is never evidence for this head
        by_name.setdefault(run.get("name"), []).append(run)
    jobs = []
    for name in sorted(set(expected_jobs)):
        state, reason = _classify(by_name.get(name, []))
        jobs.append({"job": name, "state": state, "reason": reason})
    ready = all(j["state"] == PASS for j in jobs)
    return {
        "schema": SCHEMA,
        "head_sha": head_sha,
        "decision": READY if ready else NOT_READY,
        "counts": {s: sum(j["state"] == s for j in jobs) for s in (PASS, FAIL, UNKNOWN)},
        "jobs": jobs,
        "ignored_runs_for_other_heads": foreign_head,
        "unexpected_jobs_observed": sorted(n for n in by_name if n not in set(expected_jobs)),
        "authority_effect": "NONE_ADMISSION_INPUT_ONLY",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check-runs", required=True, help="path to check-runs JSON for the head")
    ap.add_argument("--head-sha", required=True)
    ap.add_argument("--expect", action="append", required=True, help="expected job name (repeatable)")
    args = ap.parse_args(argv)
    with open(args.check_runs, encoding="utf-8") as fh:
        doc = json.load(fh)
    record = evaluate(doc, args.head_sha, args.expect)
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0 if record["decision"] == READY else 1


if __name__ == "__main__":
    sys.exit(main())
