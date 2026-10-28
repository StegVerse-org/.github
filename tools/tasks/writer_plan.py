#!/usr/bin/env python3
"""Select the writer transitions a push to main carries (stdlib only).

The manifest is control/workflow-surface-registry.json writer_jobs[]: a job with
"paths" runs when the pushed range changes a matching path (the push path filter
its original workflow declared); a job without "paths" is gated by its "after"
dependency in .github/workflows/organization-ledger-writer.yml instead. Prints
`<job>=true|false` lines for GITHUB_OUTPUT. No clock, no network beyond the
checkout this job already holds.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "control/workflow-surface-registry.json"
ZERO = "0" * 40


def pattern(glob):
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**", i):
            out += ".*"
            i += 2
        elif glob[i] == "*":
            out += "[^/]*"
            i += 1
        elif glob[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(glob[i])
            i += 1
    return re.compile(out + r"\Z")


def changed(before, after):
    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if before and before != ZERO and git("cat-file", "-e", before + "^{commit}").returncode == 0:
        result = git("diff", "--name-only", before, after)
    else:
        # A new ref or an unreadable before: the pushed head commit's own changes.
        result = git("diff-tree", "--no-commit-id", "--name-only", "-r", "--root", after)
    if result.returncode != 0:
        raise SystemExit(result.stderr)
    return [line for line in result.stdout.splitlines() if line]


def select(paths, jobs):
    selected = {}
    for job in jobs:
        globs = job.get("paths")
        if globs is None:
            continue
        compiled = [pattern(g) for g in globs]
        selected[job["job"]] = any(c.match(p) for c in compiled for p in paths)
    return selected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--before", default="")
    parser.add_argument("--after", required=True)
    args = parser.parse_args(argv)
    jobs = json.loads(REGISTRY.read_text(encoding="utf-8"))["writer_jobs"]
    for job, run in select(changed(args.before, args.after), jobs).items():
        print(f"{job}={'true' if run else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
