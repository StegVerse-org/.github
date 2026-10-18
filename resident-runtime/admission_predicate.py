#!/usr/bin/env python3
"""Merge-admission input predicates for one PR head branch, from git data only.

Stdlib only. Makes no network request and reads no clock: every input is the
local clone (its reflogs and objects) plus optional JSON files the caller
already holds (GitHub check runs and branch activity for the head). Emits one
JSON document; each failing predicate carries a six-field FAIL_CLOSED record
(failure_code, failed_predicate, required_evidence_or_repair, retry_entrypoint,
owning_existing_goal, next_attempt). The output is admission input only; it
admits nothing and grants no authority.

Predicates
  BRANCH_WRITER_IS_BRANCH_OWNER  the head branch was created in this clone,
      every move of refs/remotes/<remote>/<branch> is "update by push" from
      this clone, the last push equals the head, every commit on the PR's own
      range (range_base..head) is in the local branch reflog, and (with
      --activity) every server-side push/creation sha matches a local push.
  NO_SKIPPED_REQUIRED_JOBS  (with --check-runs) every check run at the head
      completed with conclusion success; skipped, neutral, cancelled, missing
      or pending is never a pass. --required names must all be present.
  PR_NOT_STALE  head is not behind base, and the head commit is not older than
      --stale-days measured against the base tip's committer time (git data).
  BINDER_PINS_MATCH  (with --pin) every sha256 pinned in the given pin files,
      read at the head commit, still matches the bytes at the head commit.

Usage
  admission_predicate.py --clone PATH --branch BR [--remote origin]
      [--base origin/main] [--range-base REF] [--check-runs FILE]
      [--required NAME ...] [--activity FILE] [--stale-days N] [--pin PATH ...]
      [--goal "StegVerse-org/.github#166"]
Exit status 0 when every evaluated predicate holds, 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import subprocess
import sys
from pathlib import Path

SCHEMA = "stegverse.admission-predicate-result/v1"
DEFAULT_GOAL = "StegVerse-org/.github#166"


def git(clone: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def git_bytes(clone: Path, *args: str) -> bytes | None:
    proc = subprocess.run(["git", "-C", str(clone), *args], capture_output=True)
    return proc.stdout if proc.returncode == 0 else None


def reflog(clone: Path, ref: str) -> list[dict]:
    """Oldest-first reflog entries: {time, sha, action}. Empty if absent."""
    out = git(clone, "reflog", "show", "--date=iso-strict", "--format=%H%x09%gd%x09%gs", ref, "--", check=False)
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        sha, selector, action = parts
        time = selector[selector.find("@{") + 2:-1] if "@{" in selector else ""
        rows.append({"time": time, "sha": sha, "action": action})
    return list(reversed(rows))


def fail(code: str, predicate: str, repair: str, entry: str, goal: str, nxt: str) -> dict:
    return {
        "disposition": "FAIL_CLOSED",
        "failure_code": code,
        "failed_predicate": predicate,
        "required_evidence_or_repair": repair,
        "retry_entrypoint": entry,
        "owning_existing_goal": goal,
        "next_attempt": nxt,
    }


def branch_writer(a, head: str) -> dict:
    clone, br, goal = a.clone, a.branch, a.goal
    entry = f"admission_predicate.py --clone {clone} --branch {br}"
    local = reflog(clone, f"refs/heads/{br}")
    remote = reflog(clone, f"refs/remotes/{a.remote}/{br}")
    head_log = reflog(clone, "HEAD")
    clone_entry = next((r for r in head_log if r["action"].startswith("clone:")), None)
    created = [r for r in local if r["action"].startswith("branch: Created")]
    pushes = [r for r in remote if r["action"] == "update by push"]
    foreign = [r for r in remote if r["action"] != "update by push"]
    local_shas = {r["sha"] for r in local}
    pushed = {r["sha"] for r in pushes}
    range_base = a.range_base or a.base
    own = git(clone, "rev-list", "--reverse", f"{range_base}..{head}", check=False).split()
    commits = [{"sha": c, "in_local_branch_reflog": c in local_shas} for c in own]
    server = []
    if a.activity:
        for ev in json.loads(Path(a.activity).read_text(encoding="utf-8")):
            server.append({
                "time": ev.get("timestamp"), "type": ev.get("activity_type"),
                "before": ev.get("before"), "after": ev.get("after"),
                "actor": (ev.get("actor") or {}).get("login"),
                "matches_local_push": ev.get("after") in pushed,
            })
    problems = []
    if not created:
        problems.append("no local branch-creation entry in refs/heads reflog")
    if not pushes:
        problems.append("no 'update by push' entry in the remote-tracking reflog")
    elif pushes[-1]["sha"] != head:
        problems.append(f"last local push {pushes[-1]['sha'][:12]} != head {head[:12]}")
    if foreign:
        problems.append("remote-tracking ref moved other than by a push from this clone: "
                        + ", ".join(f"{r['sha'][:12]} '{r['action']}'" for r in foreign))
    missing = [c["sha"][:12] for c in commits if not c["in_local_branch_reflog"]]
    if missing:
        problems.append("PR commits not in local branch reflog: " + ", ".join(missing))
    unmatched = [s for s in server if s["type"] in ("push", "branch_creation", "force_push") and not s["matches_local_push"]]
    if unmatched:
        problems.append("server push events with no matching local push: "
                        + ", ".join(f"{s['type']} {str(s['after'])[:12]} at {s['time']}" for s in unmatched))
    other = [s for s in server if s["type"] not in ("push", "branch_creation")]
    if other:
        problems.append("server activity other than push/creation: " + ", ".join(str(s["type"]) for s in other))
    result = {
        "predicate": "BRANCH_WRITER_IS_BRANCH_OWNER",
        "holds": not problems,
        "clone_path": str(clone.resolve()),
        "clone": clone_entry,
        "branch_created": created[0] if created else None,
        "pushes": pushes,
        "local_branch_reflog": local,
        "range": f"{range_base}..{head}",
        "commits": commits,
        "server_activity": server or None,
        "problems": problems,
    }
    if problems:
        result["fail_closed"] = fail(
            "BRANCH_WRITER_EVIDENCE_ABSENT", "BRANCH_WRITER_IS_BRANCH_OWNER: " + "; ".join(problems),
            "reflog evidence from the writing clone (branch creation and every push of every PR commit), "
            "or re-create the branch from a clone that holds it", entry, goal,
            "rerun from the writing clone after repair; a foreign-writer branch is not admitted")
    return result


def required_jobs(a, head: str) -> dict:
    data = json.loads(Path(a.check_runs).read_text(encoding="utf-8"))
    runs = data.get("check_runs", data) if isinstance(data, dict) else data
    rows, problems = [], []
    for r in runs:
        sha = r.get("head_sha")
        if sha and sha != head:
            problems.append(f"check run {r.get('name')} is for {sha[:12]}, not head")
        ok = r.get("status") == "completed" and r.get("conclusion") == "success"
        rows.append({"name": r.get("name"), "status": r.get("status"), "conclusion": r.get("conclusion"),
                     "url": r.get("html_url"), "pass": ok})
        if not ok:
            problems.append(f"{r.get('name')}: {r.get('status')}/{r.get('conclusion')} is not a pass")
    names = {r["name"] for r in rows}
    for name in a.required or []:
        if name not in names:
            problems.append(f"required job {name} has no check run at head")
    if not rows:
        problems.append("no check runs at head")
    result = {"predicate": "NO_SKIPPED_REQUIRED_JOBS", "holds": not problems, "head": head,
              "jobs": rows, "required": a.required or "all check runs at head", "problems": problems}
    if problems:
        result["fail_closed"] = fail(
            "REQUIRED_JOB_NOT_PASSED", "NO_SKIPPED_REQUIRED_JOBS: " + "; ".join(problems),
            "every job at the exact head runs and concludes success (a PR-safe variant for dispatch-only jobs), "
            "or a declared transition removes the job from the required set",
            "push a repair to the head branch; checks rerun on pull_request", a.goal,
            "rerun this predicate on the new head's check runs")
    return result


def stale(a, head: str) -> dict:
    behind = int(git(a.clone, "rev-list", "--count", f"{head}..{a.base}").strip() or 0)
    ahead = int(git(a.clone, "rev-list", "--count", f"{a.base}..{head}").strip() or 0)
    head_ct = int(git(a.clone, "show", "-s", "--format=%ct", head).strip())
    base_ct = int(git(a.clone, "show", "-s", "--format=%ct", a.base).strip())
    age_days = round(max(0, base_ct - head_ct) / 86400, 2)
    problems = []
    if behind:
        problems.append(f"head is {behind} commit(s) behind {a.base}")
    if a.stale_days is not None and age_days > a.stale_days:
        problems.append(f"head commit is {age_days} days older than {a.base} tip (limit {a.stale_days})")
    result = {"predicate": "PR_NOT_STALE", "holds": not problems, "base": a.base,
              "behind_base": behind, "ahead_of_base": ahead,
              "head_age_days_vs_base_tip": age_days, "stale_days_limit": a.stale_days,
              "time_source": "git committer timestamps (no clock read)", "problems": problems}
    if problems:
        result["fail_closed"] = fail(
            "PR_HEAD_STALE", "PR_NOT_STALE: " + "; ".join(problems),
            f"rebase or merge {a.base} into the head branch and re-run checks",
            f"head branch {a.branch}", a.goal, "rerun this predicate after the head moves")
    return result


def binder(a, head: str) -> dict:
    rows, problems = [], []
    for pin_path in a.pin:
        raw = git_bytes(a.clone, "show", f"{head}:{pin_path}")
        if raw is None:
            problems.append(f"pin file {pin_path} absent at head")
            continue
        pin = json.loads(raw.decode("utf-8"))
        entries = []
        if "files" in pin:
            root = pin.get("vendor_root", "")
            entries = [(posixpath.join(root, f["path"]) if root else f["path"], f["sha256"]) for f in pin["files"]]
        elif "vendored_path" in pin:
            entries = [(pin["vendored_path"], pin["sha256"])]
        else:
            problems.append(f"pin file {pin_path}: no files/vendored_path entry")
        for path, want in entries:
            data = git_bytes(a.clone, "show", f"{head}:{path}")
            got = hashlib.sha256(data).hexdigest() if data is not None else None
            ok = got == want
            rows.append({"pin_file": pin_path, "path": path, "pinned_sha256": want, "head_sha256": got, "match": ok})
            if not ok:
                problems.append(f"{path}: pinned {want[:12]} != head {got[:12] if got else 'absent'}")
    result = {"predicate": "BINDER_PINS_MATCH", "holds": not problems, "pins": rows, "problems": problems}
    if problems:
        result["fail_closed"] = fail(
            "BINDER_PIN_MISMATCH", "BINDER_PINS_MATCH: " + "; ".join(problems),
            "restore the pinned bytes, or re-pin with new provenance in the pin file",
            f"pin file(s) {', '.join(a.pin)} on {a.branch}", a.goal, "rerun this predicate on the repaired head")
    return result


def evaluate(a) -> dict:
    a.clone = Path(a.clone)
    head = git(a.clone, "rev-parse", f"refs/heads/{a.branch}").strip()
    results = [branch_writer(a, head), stale(a, head)]
    if a.check_runs:
        results.insert(1, required_jobs(a, head))
    if a.pin:
        results.append(binder(a, head))
    failed = [r for r in results if not r["holds"]]
    return {
        "schema": SCHEMA,
        "authority_effect": "NONE_ADMISSION_INPUT_ONLY",
        "branch": a.branch,
        "head": head,
        "admission_input": "admission-input-ready" if not failed else "not-ready",
        "predicates": results,
        "fail_closed": [r["fail_closed"] for r in failed],
    }


def parse(argv: list[str]):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--clone", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--remote", default="origin")
    p.add_argument("--base", default="origin/main")
    p.add_argument("--range-base", default=None, help="start of the PR's own range (stacked PRs)")
    p.add_argument("--check-runs", default=None)
    p.add_argument("--required", nargs="*", default=None)
    p.add_argument("--activity", default=None)
    p.add_argument("--stale-days", type=float, default=None)
    p.add_argument("--pin", nargs="*", default=[])
    p.add_argument("--goal", default=DEFAULT_GOAL)
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    out = evaluate(parse(argv))
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out["admission_input"] == "admission-input-ready" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
