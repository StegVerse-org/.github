#!/usr/bin/env python3
"""Dry-run publish guard: the scratch appends were not published, and the published ledger only grew.

A PR or push dry run copies the published ledger ref to a scratch ref, appends
there and must leave the published ref untouched. The ledger writer (push to
main) may append to the published ref while the dry run runs, so "the published
tip still equals the copied tip" is the wrong predicate: it fails on a correct
writer append (SV-LLM/.github push run 40123764551, writer run 40123764615).

The predicate checked here, from local git objects only (no clock, no network;
the caller fetches the current published tip first):

  ALLOW        the current published tip equals the copied tip; or the copied
               tip is an ancestor of it (append-only growth by the writer) and
               no scratch-only commit (copied..scratch) is reachable from it.
  DENY         LEDGER_PUBLISHED_REF_NOT_APPEND_ONLY: the copied tip is not an
               ancestor of the current published tip.
               DRY_RUN_APPEND_PUBLISHED: a scratch-only commit is on the
               published ref.
  FAIL_CLOSED  LEDGER_PUBLISHED_TIP_UNREADABLE: a tip is not 40 hex or not a
               local commit object.

Every non-ALLOW result carries the six fields. Exit 0 only on ALLOW.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any

SHA40 = re.compile(r"[0-9a-f]{40}")
SCHEMA = "stegverse.ledger-publish-guard-result/v1"
GOAL = "StegVerse-org/.github#162 (INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001)"
ENTRYPOINT = "the dry-run group that called resident-runtime/ledger_publish_guard.py (re-run on the PR or push)"
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")


def _git(git_dir: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", git_dir, *args], capture_output=True, text=True)


def _refuse(disposition: str, code: str, predicate: str, repair: str, next_attempt: str, **extra: Any) -> dict[str, Any]:
    out = {"schema": SCHEMA, "disposition": disposition, "failure_code": code, "failed_predicate": predicate,
           "required_evidence_or_repair": repair, "retry_entrypoint": ENTRYPOINT, "owning_existing_goal": GOAL,
           "next_attempt": next_attempt}
    out.update(extra)
    return out


def _is_commit(git_dir: str, sha: str) -> bool:
    return bool(SHA40.fullmatch(sha or "")) and _git(git_dir, "cat-file", "-e", sha + "^{commit}").returncode == 0


def check(git_dir: str, copied_tip: str, published_now: str, scratch_tip: str) -> dict[str, Any]:
    tips = {"copied_tip": copied_tip, "published_now": published_now, "scratch_tip": scratch_tip}
    for name, value in tips.items():
        if not _is_commit(git_dir, value):
            return _refuse("FAIL_CLOSED", "LEDGER_PUBLISHED_TIP_UNREADABLE", "DRY_RUN_TIPS_ARE_LOCAL_COMMITS",
                           "fetch the published ledger ref into the checkout before the guard; " + name
                           + " " + repr(value) + " is not a local commit",
                           "re-run the dry run; nothing was published", **tips)
    if published_now != copied_tip and _git(git_dir, "merge-base", "--is-ancestor", copied_tip,
                                            published_now).returncode != 0:
        return _refuse("DENY", "LEDGER_PUBLISHED_REF_NOT_APPEND_ONLY", "PUBLISHED_LEDGER_ONLY_GROWS",
                       "the published ledger ref was rewritten during the dry run; inspect " + published_now,
                       "repair the published ref through the ledger writer only; nothing was published by this run",
                       **tips)
    scratch_only = _git(git_dir, "rev-list", copied_tip + ".." + scratch_tip)
    if scratch_only.returncode != 0:
        return _refuse("FAIL_CLOSED", "LEDGER_PUBLISHED_TIP_UNREADABLE", "DRY_RUN_TIPS_ARE_LOCAL_COMMITS",
                       "the scratch range " + copied_tip + ".." + scratch_tip + " is not readable",
                       "re-run the dry run; nothing was published", **tips)
    published = [c for c in scratch_only.stdout.split()
                 if _git(git_dir, "merge-base", "--is-ancestor", c, published_now).returncode == 0]
    if published:
        return _refuse("DENY", "DRY_RUN_APPEND_PUBLISHED", "DRY_RUN_NEVER_PUBLISHES",
                       "scratch append(s) " + ", ".join(published) + " are on the published ledger ref",
                       "inspect the published ref; a dry run holds no write credential", published=published, **tips)
    grown = _git(git_dir, "rev-list", "--count", copied_tip + ".." + published_now).stdout.strip()
    return {"schema": SCHEMA, "disposition": "ALLOW", **tips, "scratch_appends": len(scratch_only.stdout.split()),
            "published_grew_by": int(grown or 0)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--git-dir", default=".")
    parser.add_argument("--copied-tip", required=True)
    parser.add_argument("--published-now", default="")
    parser.add_argument("--scratch-tip", required=True)
    args = parser.parse_args(argv)
    result = check(args.git_dir, args.copied_tip.strip(), args.published_now.strip(), args.scratch_tip.strip())
    print("LEDGER_PUBLISH_GUARD", json.dumps(result, sort_keys=True))
    return 0 if result["disposition"] == "ALLOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
