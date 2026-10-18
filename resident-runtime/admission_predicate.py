#!/usr/bin/env python3
"""Merge-admission input predicates for one PR head branch, from git data only.

Stdlib only. No network request and no clock read: the inputs are the local clone
(reflogs and objects) plus values the caller supplies — the declared session id,
the hb_epoch, the check-run JSON for the head (required), the B1 base_ref (sha and
commit time) and optionally GitHub branch activity. The output is one sealed JSON
document (schema ``stegverse.admission-predicate-result/v2``). Every non-ALLOW
predicate carries the six fields (failure_code, failed_predicate,
required_evidence_or_repair, retry_entrypoint, owning_existing_goal, next_attempt).
It is admission input only: it admits nothing and grants no authority.

Field names, failure codes, the change_digest rule and the seal scheme follow
StegVerse-Labs/TVC docs/SV_CHANGE_ADMISSION_PREDICATE_REFERENCE.md (TVC#519) and
its ``tvc_request_digest`` (canonical JSON: sorted keys, (",", ":") separators,
UTF-8, ensure_ascii=False; value ``"sha256:" + hex``).

Predicates (all evaluated after HB_EPOCH_SUPPLIED; ADMISSION_INPUT_READY only if every one is ALLOW)
  PR_AUTHOR_SESSION_DECLARED     --session-id matches the SV_CHANGE session pattern.
  BRANCH_WRITER_IS_BRANCH_OWNER  branch created in this clone; every move of the
      remote-tracking ref is "update by push" from this clone; last push == head;
      every commit of range_base..head is in the local branch reflog; with
      --activity, every server push/creation sha matches a local push.
  ALL_JOBS_RAN_AND_PASSED        every check run in --check-runs is for the head and
      completed/success; skipped, neutral, pending or absent is never a pass.
  HEAD_CURRENT_WITH_BASE         head contains the supplied base_ref sha, and the head
      commit is not older than --stale-days against the supplied base commit time.
  BINDER_PINS_MATCH              (with --pin) pinned sha256s still match the bytes at head.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "stegverse.admission-predicate-result/v2"
DEFAULT_GOAL = "StegVerse-org/.github#166"
RETRY_ENTRYPOINT = "StegVerse-org/.github resident-runtime/admission_predicate.py (run from the writing clone)"
SEAL_FIELD = "result_sha256"
UNKNOWN = "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
SESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{3,127}$")  # TVC sv_change_admission._SESSION
HB_EPOCH = re.compile(r"^[0-9]+$")
HB_EPOCH_MINIMUM = 32
PREFIX = "sha256:"


# ---- TVC digest rule (tvc_request_digest), reproduced, not imported: stdlib only, other repo ----
def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value: Any) -> str:
    raw = value if isinstance(value, (bytes, bytearray)) else canonical_bytes(value)
    return PREFIX + hashlib.sha256(raw).hexdigest()


def seal(body: Mapping[str, Any], field: str = SEAL_FIELD) -> dict:
    clean = {k: v for k, v in body.items() if k != field}
    return {**clean, field: digest(clean)}


def seal_verifies(record: Any, field: str = SEAL_FIELD) -> bool:
    return isinstance(record, Mapping) and record.get(field) == digest({k: v for k, v in record.items() if k != field})


def change_digest(content: list) -> str:
    """TVC sv_change_admission.change_digest: digest over content sorted by path (B2)."""
    return digest(sorted((dict(e) for e in content), key=lambda e: str(e.get("path"))))


# ---- git ----
def git(clone: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def git_bytes(clone: Path, *args: str) -> bytes | None:
    proc = subprocess.run(["git", "-C", str(clone), *args], capture_output=True)
    return proc.stdout if proc.returncode == 0 else None


def blob_digest(clone: Path, rev: str, path: str) -> str | None:
    data = git_bytes(clone, "show", f"{rev}:{path}")
    return digest(data) if data is not None else None


def changed_paths(clone: Path, a: str, b: str) -> list[tuple[str, bool]]:
    """(path, deleted) for the net diff a..b, renames split into delete + add."""
    out = git(clone, "diff", "--no-renames", "--name-status", "-z", a, b)
    parts = [p for p in out.split("\0") if p]
    rows = []
    for i in range(0, len(parts) - 1, 2):
        rows.append((parts[i + 1], parts[i] == "D"))
    return sorted(rows)


def reflog(clone: Path, ref: str) -> list[dict]:
    out = git(clone, "reflog", "show", "--date=iso-strict", "--format=%H%x09%gd%x09%gs", ref, "--", check=False)
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            sha, selector, action = parts
            rows.append({"time": selector[selector.find("@{") + 2:-1] if "@{" in selector else "",
                         "sha": sha, "action": action})
    return list(reversed(rows))


# ---- result rows ----
def row(name: str, **evidence: Any) -> dict:
    return {"predicate": name, "disposition": "ALLOW", "holds": True, **evidence}


def refuse(r: dict, a, code: str, repair: str, nxt: str, disposition: str = "FAIL_CLOSED") -> dict:
    r.update({"disposition": disposition, "holds": False, "failure_code": code, "failed_predicate": r["predicate"],
              "required_evidence_or_repair": repair, "retry_entrypoint": RETRY_ENTRYPOINT,
              "owning_existing_goal": a.goal, "next_attempt": nxt})
    return r


def p_session(a) -> dict:
    r = row("PR_AUTHOR_SESSION_DECLARED", declared_session=a.session_id)
    if not isinstance(a.session_id, str) or not SESSION.match(a.session_id):
        refuse(r, a, "AUTHOR_SESSION_NOT_DECLARED",
               "--session-id names the authoring session (^[A-Za-z0-9][A-Za-z0-9._:/@-]{3,127}$)",
               "rerun with --session-id")
    return r


def p_writer(a, head: str, range_base: str) -> dict:
    clone, br = a.clone, a.branch
    local = reflog(clone, f"refs/heads/{br}")
    remote = reflog(clone, f"refs/remotes/{a.remote}/{br}")
    clone_entry = next((x for x in reflog(clone, "HEAD") if x["action"].startswith("clone:")), None)
    created = [x for x in local if x["action"].startswith("branch: Created")]
    pushes = [x for x in remote if x["action"] == "update by push"]
    foreign = [x for x in remote if x["action"] != "update by push"]
    local_shas = {x["sha"] for x in local}
    pushed = {x["sha"] for x in pushes}
    commits = []
    for c in git(clone, "rev-list", "--reverse", f"{range_base}..{head}", check=False).split():
        parents = git(clone, "rev-list", "--parents", "-n1", c).split()[1:]
        first = parents[0] if parents else git(clone, "hash-object", "-t", "tree", "/dev/null").strip()
        paths = [{"path": p, "deleted": d, "blob_digest": None if d else blob_digest(clone, c, p)}
                 for p, d in changed_paths(clone, first, c)]
        commits.append({"sha": c, "in_local_branch_reflog": c in local_shas, "paths": paths})
    server = []
    if a.activity:
        for ev in json.loads(Path(a.activity).read_text(encoding="utf-8")):
            server.append({"time": ev.get("timestamp"), "type": ev.get("activity_type"),
                           "before": ev.get("before"), "after": ev.get("after"),
                           "actor": (ev.get("actor") or {}).get("login"),
                           "matches_local_push": ev.get("after") in pushed})
    problems = []
    if not created:
        problems.append("no local branch-creation entry in refs/heads reflog")
    if not pushes:
        problems.append("no 'update by push' entry in the remote-tracking reflog")
    elif pushes[-1]["sha"] != head:
        problems.append(f"last local push {pushes[-1]['sha'][:12]} != head {head[:12]}")
    if foreign:
        problems.append("remote-tracking ref moved other than by a push from this clone: "
                        + ", ".join(f"{x['sha'][:12]} '{x['action']}'" for x in foreign))
    missing = [c["sha"][:12] for c in commits if not c["in_local_branch_reflog"]]
    if missing:
        problems.append("range commits not in local branch reflog: " + ", ".join(missing))
    unmatched = [s for s in server if s["type"] in ("push", "branch_creation", "force_push") and not s["matches_local_push"]]
    if unmatched:
        problems.append("server push events with no matching local push: "
                        + ", ".join(f"{s['type']} {str(s['after'])[:12]} at {s['time']}" for s in unmatched))
    other = [s for s in server if s["type"] not in ("push", "branch_creation")]
    if other:
        problems.append("server activity other than push/creation: " + ", ".join(str(s["type"]) for s in other))
    r = row("BRANCH_WRITER_IS_BRANCH_OWNER", clone=clone_entry,
            branch_created=created[0] if created else None, pushes=pushes, local_branch_reflog=local,
            range=f"{range_base}..{head}", commits=commits, server_activity=server or None, problems=problems)
    if problems:
        refuse(r, a, "BRANCH_HAS_FOREIGN_WRITER",
               "reflog evidence from the writing clone for branch creation and every push of every range commit; "
               "otherwise a superseding change by the owner or adopter",
               "rerun from the writing clone after repair; a foreign-writer branch is not admitted")
    return r


def p_jobs(a, head: str, runs_raw: bytes) -> dict:
    data = json.loads(runs_raw.decode("utf-8"))
    runs = data.get("check_runs", []) if isinstance(data, dict) else data
    jobs, unobserved, denied = [], [], []
    for x in runs:
        sha = x.get("head_sha")
        ok = x.get("status") == "completed" and x.get("conclusion") == "success" and (not sha or sha == head)
        jobs.append({"name": x.get("name"), "head_sha": sha, "status": x.get("status"),
                     "conclusion": x.get("conclusion"), "url": x.get("html_url"), "pass": ok})
        if sha and sha != head:
            unobserved.append(f"{x.get('name')}: check run is for {sha[:12]}, not head")
        elif x.get("status") == "completed" and x.get("conclusion") in ("failure", "timed_out", "action_required"):
            denied.append(f"{x.get('name')}: {x.get('conclusion')}")
        elif not ok:
            unobserved.append(f"{x.get('name')}: {x.get('status')}/{x.get('conclusion')} is not a pass")
    names = {j["name"] for j in jobs}
    unobserved += [f"required job {n} has no check run at head" for n in (a.required or []) if n not in names]
    if not jobs:
        unobserved.append("no check runs at head")
    r = row("ALL_JOBS_RAN_AND_PASSED", head=head, jobs=jobs,
            required=a.required or "every check run at head", problems=denied + unobserved)
    if denied:
        refuse(r, a, "REQUIRED_CHECK_DENIED", "every job at the exact head concludes success",
               "a repair pushed to the head branch; checks rerun on pull_request", disposition="DENY")
    elif unobserved:
        refuse(r, a, "CHECK_SKIPPED_OR_UNOBSERVED",
               "every job at the exact head runs and concludes success (a PR-safe variant for dispatch-only jobs), "
               "or a declared transition removes the job from the required set",
               "rerun this predicate on the head's check runs once every job has run")
    return r


def p_base(a, head: str) -> dict:
    base = {"sha": a.base_sha, "commit_time": a.base_commit_time,
            "registry_generation": a.base_registry_generation, "ledger_head": a.base_ledger_head}
    r = row("HEAD_CURRENT_WITH_BASE", base_ref=base, stale_days_limit=a.stale_days,
            time_source="supplied base_ref commit_time vs head committer timestamp (no clock read)")
    if not a.base_sha or a.base_commit_time is None:
        return refuse(r, a, "BASE_STATE_NOT_OBSERVED", "supply --base-sha and --base-commit-time (B1 base_ref)",
                      "rerun with the base_ref supplied")
    if git(a.clone, "cat-file", "-t", a.base_sha, check=False).strip() != "commit":
        return refuse(r, a, "BASE_STATE_NOT_OBSERVED", f"base_ref sha {a.base_sha} present in the clone (fetch it)",
                      "rerun after the base_ref commit is fetched")
    contains = subprocess.run(["git", "-C", str(a.clone), "merge-base", "--is-ancestor", a.base_sha, head]).returncode == 0
    behind = int(git(a.clone, "rev-list", "--count", f"{head}..{a.base_sha}").strip() or 0)
    head_ct = int(git(a.clone, "show", "-s", "--format=%ct", head).strip())
    age_days = round(max(0, a.base_commit_time - head_ct) / 86400, 2)
    r.update(head_contains_base=contains, behind_base=behind, head_commit_time=head_ct,
             head_age_days_vs_base=age_days)
    problems = []
    if not contains:
        problems.append(f"head is {behind} commit(s) behind base_ref {a.base_sha[:12]}")
    if a.stale_days is not None and age_days > a.stale_days:
        problems.append(f"head commit is {age_days} days older than base_ref commit_time (limit {a.stale_days})")
    r["problems"] = problems
    if problems:
        refuse(r, a, "BASE_STALE", "re-base or merge the base_ref into the head branch and re-run checks",
               "BASE_ADVANCED_REVALIDATE: rerun this predicate after the head moves", disposition="DENY")
    return r


def p_binder(a, head: str) -> dict:
    pins, problems = [], []
    for pin_path in a.pin:
        raw = git_bytes(a.clone, "show", f"{head}:{pin_path}")
        if raw is None:
            problems.append(f"pin file {pin_path} absent at head")
            continue
        pin = json.loads(raw.decode("utf-8"))
        if "files" in pin:
            root = pin.get("vendor_root", "")
            entries = [(posixpath.join(root, f["path"]) if root else f["path"], f["sha256"]) for f in pin["files"]]
        elif "vendored_path" in pin:
            entries = [(pin["vendored_path"], pin["sha256"])]
        else:
            entries = []
            problems.append(f"pin file {pin_path}: no files/vendored_path entry")
        for path, want in entries:
            data = git_bytes(a.clone, "show", f"{head}:{path}")
            got = hashlib.sha256(data).hexdigest() if data is not None else None
            pins.append({"pin_file": pin_path, "pin_file_digest": digest(raw), "path": path,
                         "pinned_sha256": want, "head_sha256": got, "match": got == want})
            if got != want:
                problems.append(f"{path}: pinned {want[:12]} != head {got[:12] if got else 'absent'}")
    r = row("BINDER_PINS_MATCH", pins=pins, problems=problems)
    if problems:
        refuse(r, a, "BINDER_PIN_MISMATCH", "restore the pinned bytes, or re-pin with new provenance in the pin file",
               "rerun this predicate on the repaired head")
    return r


def hb_epoch_refusal(a) -> dict | None:
    text = a.hb_epoch
    r = row("HB_EPOCH_SUPPLIED")
    if text is None or text == "":
        return refuse(r, a, "HB_EPOCH_NOT_SUPPLIED", "supply --hb-epoch from the carrier; no clock is read",
                      "rerun with --hb-epoch supplied")
    if not HB_EPOCH.fullmatch(text) or int(text) < HB_EPOCH_MINIMUM:
        return refuse(r, a, "HB_EPOCH_INVALID", "hb_epoch as ASCII digits >= 32; no clock is read",
                      "rerun with --hb-epoch as digits >= 32")
    return None


def evaluate(a) -> dict:
    a.clone = Path(a.clone)
    head = git(a.clone, "rev-parse", f"refs/heads/{a.branch}").strip()
    range_base = a.range_base or a.base_sha
    if range_base and git(a.clone, "cat-file", "-t", range_base, check=False).strip() != "commit":
        range_base = None  # unresolvable range: the writer predicate fails closed, content stays empty
    runs_raw = Path(a.check_runs).read_bytes()
    epoch_fail = hb_epoch_refusal(a)
    content: list = []
    if epoch_fail is not None:
        predicates = [epoch_fail]
    else:
        writer = p_writer(a, head, range_base) if range_base else None
        predicates = [p_session(a)]
        if writer is not None:
            predicates.append(writer)
        predicates += [p_jobs(a, head, runs_raw), p_base(a, head)]
        if writer is None:
            predicates.insert(1, refuse(row("BRANCH_WRITER_IS_BRANCH_OWNER"), a, "BRANCH_HAS_FOREIGN_WRITER",
                                        "supply a --range-base/--base-sha commit present in the clone so the PR's own range is defined",
                                        "rerun with the range supplied"))
        if a.pin:
            predicates.append(p_binder(a, head))
        if range_base:
            sess_ok = predicates[0]["holds"] and predicates[1]["holds"]
            for path, deleted in changed_paths(a.clone, range_base, head):
                content.append({"path": path, "deleted": deleted,
                                "blob_digest": None if deleted else blob_digest(a.clone, head, path),
                                "writer_session": a.session_id if sess_ok else UNKNOWN})
    failed = [p for p in predicates if p["disposition"] != "ALLOW"]
    disposition = "ALLOW" if not failed else failed[0]["disposition"]  # TVC: first non-ALLOW decides
    body = {
        "schema": SCHEMA,
        "authority_effect": "NONE_ADMISSION_INPUT_ONLY",
        "declared_session": a.session_id,
        "target_repository": a.repository,
        "branch": a.branch,
        "head": head,
        "base_ref": {"sha": a.base_sha, "commit_time": a.base_commit_time,
                     "registry_generation": a.base_registry_generation, "ledger_head": a.base_ledger_head},
        "range_base": range_base,
        "content": sorted(content, key=lambda e: e["path"]),
        "change_digest": change_digest(content) if content else None,
        "check_runs_input": {"path": str(a.check_runs), "digest": digest(runs_raw)},
        "hb_epoch": int(a.hb_epoch) if epoch_fail is None else None,
        "owning_existing_goal": a.goal,
        "admission_input": "admission-input-ready" if not failed else "not-ready",
        "disposition": disposition,
        "predicates": predicates,
        "fail_closed": [{"disposition": p["disposition"], **{f: p[f] for f in SIX_FIELDS}} for p in failed],
    }
    if failed:
        body.update({f: failed[0][f] for f in SIX_FIELDS})
    return seal(body)


def parse(argv: list[str]):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--clone", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--session-id", required=True, help="declared authoring session (declared input)")
    p.add_argument("--hb-epoch", required=True, help="carrier-supplied epoch, ASCII digits >= 32; no clock is read")
    p.add_argument("--check-runs", required=True, help="GitHub check-runs JSON for the head (input, not fetched)")
    p.add_argument("--base-sha", default=None, help="B1 base_ref sha")
    p.add_argument("--base-commit-time", type=int, default=None, help="B1 base_ref commit time (unix seconds, supplied)")
    p.add_argument("--base-registry-generation", type=int, default=None, help="B1 registry generation (carried, not evaluated)")
    p.add_argument("--base-ledger-head", default=None, help="B1 ledger head (carried, not evaluated)")
    p.add_argument("--repository", default=None, help="target repository, e.g. owner/name")
    p.add_argument("--remote", default="origin")
    p.add_argument("--range-base", default=None, help="start of the PR's own range (stacked PRs); default --base-sha")
    p.add_argument("--required", nargs="*", default=None)
    p.add_argument("--activity", default=None)
    p.add_argument("--stale-days", type=float, default=None)
    p.add_argument("--pin", nargs="*", default=[])
    p.add_argument("--goal", default=DEFAULT_GOAL)
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    out = evaluate(parse(argv))
    print(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if out["admission_input"] == "admission-input-ready" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
