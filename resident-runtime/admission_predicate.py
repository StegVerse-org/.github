#!/usr/bin/env python3
"""Merge-admission input predicates for one PR head branch.

Stdlib only. No network request and no clock read. Only the branch-writer and
binder predicates read the writing clone (reflogs and objects); everything else
comes from values the caller supplies: the declared session id, the hb_epoch, the
check-run JSON and expected jobs (passed to Lane A's pinned evaluator), the B1
base_ref and the observed current base, and optionally GitHub branch activity. The output is one sealed JSON
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
  BRANCH_WRITER_IS_BRANCH_OWNER  (own code; the only predicate that reads git) branch
      created in this clone; every move of the remote-tracking ref is "update by push"
      from this clone; last push == head; every commit of range_base..head is in the
      local branch reflog; with --activity, every server push/creation sha matches a
      local push.
  ALL_JOBS_RAN_AND_PASSED        DELEGATED to Lane A's job-observation predicate
      (StegVerse-Labs/.github#3262), vendored at vendor/lane_a/ and loaded only when
      its git blob sha and sha256 equal config/admission-predicate/lane-a-job-observation.pin.json
      (TVC#519 pattern). Lane A v2 receives head, expected jobs, hb_epoch,
      change_digest and goal and returns a sealed record (seal verified here). P4
      keeps no classifier: READY -> ALLOW, any FAIL -> DENY REQUIRED_CHECK_DENIED,
      Lane A FAIL_CLOSED -> FAIL_CLOSED with Lane A's own code, otherwise FAIL_CLOSED
      CHECK_SKIPPED_OR_UNOBSERVED (TVC sv_change_job_observation mapping).
  HEAD_CURRENT_WITH_BASE         judged only from supplied inputs, no git: the PR's
      base_ref (--base-sha, the merge-base the head was built on, and its commit
      time) against the observed current base (--current-base-sha and its commit
      time), plus registry_generation / ledger_head when both sides are supplied
      (TVC B1: unchanged since VERIFIED, else BASE_STALE).
  BINDER_PINS_MATCH              (own code; with --pin) pinned sha256s still match the bytes at head.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import subprocess
import sys
import types
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


LANE_A_PIN = Path(__file__).resolve().parents[1] / "config" / "admission-predicate" / "lane-a-job-observation.pin.json"


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def load_job_observation_reference(pin_path: Path | None = None):
    """Lane A's module iff the vendored bytes equal the pin (git blob sha AND sha256); else (None, reason)."""
    pin_path = pin_path if pin_path is not None else LANE_A_PIN
    try:
        pin = json.loads(pin_path.read_text(encoding="utf-8"))
        want = (pin.get("producer") or {}).get("git_blob_sha")
        path = pin_path.resolve().parents[2] / pin["vendored_path"]
        data = path.read_bytes()
        got_blob, got_sha = git_blob_sha(data), hashlib.sha256(data).hexdigest()
        ref = {"pin_file": str(pin_path.relative_to(pin_path.resolve().parents[2])), "producer": pin.get("producer"),
               "vendored_path": pin["vendored_path"], "pinned_sha256": pin.get("sha256"), "vendored_sha256": got_sha,
               "pinned_git_blob_sha": want, "vendored_git_blob_sha": got_blob}
        if not isinstance(want, str) or len(want) != 40 or got_blob != want or got_sha != pin.get("sha256"):
            return None, ref, "vendored bytes do not equal the pin (git blob sha / sha256)"
        mod = types.ModuleType("lane_a_evaluate_admission_job_observation")
        exec(compile(data, str(path), "exec"), mod.__dict__)  # noqa: S102 - pinned bytes only
        if mod.__dict__.get("SCHEMA") != pin.get("result_schema"):
            return None, ref, "vendored module schema != pin result_schema"
        return mod, ref, None
    except Exception as exc:  # unreadable pin or bytes -> unavailable, fail closed
        return None, {"pin_file": str(pin_path)}, f"reference unreadable: {exc}"


def p_jobs(a, head: str, change: str | None) -> tuple[dict, dict | None]:
    r = row("ALL_JOBS_RAN_AND_PASSED", delegated_to="StegVerse-Labs/.github#3262 scripts/evaluate_admission_job_observation.py")
    mod, ref, why = load_job_observation_reference()
    r["reference"] = ref
    if mod is None:
        return refuse(r, a, "JOB_OBSERVATION_REFERENCE_UNAVAILABLE",
                      f"vendored Lane A evaluator bytes equal to its pin ({why})",
                      "re-vendor the pinned bytes or re-pin to a new #3262 head"), None
    try:
        doc = json.loads(Path(a.check_runs).read_text(encoding="utf-8")) if a.check_runs else None
    except (OSError, json.JSONDecodeError):
        doc = None  # Lane A refuses a malformed document with its own six-field FAIL_CLOSED
    record = mod.evaluate(doc, head, list(a.expect or []), hb_epoch=int(a.hb_epoch),
                          change_digest_value=change, owning_existing_goal=a.goal)
    r["lane_a_decision"] = record.get("decision")
    if record.get("schema") != mod.SCHEMA or not seal_verifies(record, mod.SEAL_FIELD):
        return refuse(r, a, "JOB_OBSERVATION_REFERENCE_UNAVAILABLE",
                      "a Lane A record with the pinned result schema and a verifying result_sha256 seal",
                      "re-vendor the pinned bytes or re-pin to a new #3262 head"), record
    if record["decision"] == mod.READY:
        return r, record
    if record["decision"] == mod.FAIL_CLOSED:  # Lane A refused the input: carry its own code
        refuse(r, a, record["failure_code"], record["required_evidence_or_repair"], record["next_attempt"])
        r["lane_a_failed_predicate"] = record["failed_predicate"]
        return r, record
    if record["counts"].get(mod.FAIL):
        return refuse(r, a, "REQUIRED_CHECK_DENIED", "every expected job at the exact head concludes success",
                      "a repair pushed to the head branch; checks rerun on pull_request", disposition="DENY"), record
    return refuse(r, a, "CHECK_SKIPPED_OR_UNOBSERVED",
                  "every expected job at the exact head runs and concludes success (a skipped, pending, "
                  "path-filtered, null-head or other-head run is never a pass)",
                  "rerun on the head's check runs once every expected job has run"), record


def p_base(a) -> dict:
    """B1 currency from supplied inputs only; no git is read."""
    base = {"sha": a.base_sha, "commit_time": a.base_commit_time,
            "registry_generation": a.base_registry_generation, "ledger_head": a.base_ledger_head}
    current = {"sha": a.current_base_sha, "commit_time": a.current_base_commit_time,
               "registry_generation": a.current_registry_generation, "ledger_head": a.current_ledger_head}
    r = row("HEAD_CURRENT_WITH_BASE", base_ref=base, current_base=current, stale_days_limit=a.stale_days,
            evidence_source="supplied inputs only (no git, no clock)")
    if not a.base_sha or not a.current_base_sha:
        return refuse(r, a, "BASE_STATE_NOT_OBSERVED",
                      "supply --base-sha (the PR's merge-base / base_ref) and --current-base-sha (observed base tip)",
                      "rerun with both base inputs supplied")
    moved = {}
    if a.current_base_sha != a.base_sha:
        moved["sha"] = {"verified": a.base_sha, "current": a.current_base_sha}
    for key in ("registry_generation", "ledger_head"):
        if base[key] is not None and current[key] is not None and base[key] != current[key]:
            moved[key] = {"verified": base[key], "current": current[key]}
    if a.stale_days is not None:
        if a.base_commit_time is None or a.current_base_commit_time is None:
            return refuse(r, a, "BASE_STATE_NOT_OBSERVED",
                          "supply --base-commit-time and --current-base-commit-time for the --stale-days limit",
                          "rerun with both commit times supplied")
        age = round(max(0, a.current_base_commit_time - a.base_commit_time) / 86400, 2)
        r["base_age_days"] = age
        if age > a.stale_days:
            moved["age_days"] = {"limit": a.stale_days, "observed": age}
    r["moved"] = moved
    if moved:
        refuse(r, a, "BASE_STALE", "base_ref unchanged since the head was built (re-base or merge the base and re-run checks)",
               "BASE_ADVANCED_REVALIDATE: rerun with the new merge-base after the head moves", disposition="DENY")
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
    runs_raw = Path(a.check_runs).read_bytes() if a.check_runs else None
    job_record = None
    epoch_fail = hb_epoch_refusal(a)
    content: list = []
    if epoch_fail is not None:
        predicates = [epoch_fail]
    else:
        writer = p_writer(a, head, range_base) if range_base else None
        predicates = [p_session(a)]
        if writer is None:
            writer = refuse(row("BRANCH_WRITER_IS_BRANCH_OWNER"), a, "BRANCH_HAS_FOREIGN_WRITER",
                            "supply a --range-base/--base-sha commit present in the clone so the PR's own range is defined",
                            "rerun with the range supplied")
        predicates.append(writer)
        if range_base:
            sess_ok = predicates[0]["holds"] and writer["holds"]
            for path, deleted in changed_paths(a.clone, range_base, head):
                content.append({"path": path, "deleted": deleted,
                                "blob_digest": None if deleted else blob_digest(a.clone, head, path),
                                "writer_session": a.session_id if sess_ok else UNKNOWN})
        jobs, job_record = p_jobs(a, head, change_digest(content) if content else None)
        predicates += [jobs, p_base(a)]
        if a.pin:
            predicates.append(p_binder(a, head))
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
        "current_base": {"sha": a.current_base_sha, "commit_time": a.current_base_commit_time,
                         "registry_generation": a.current_registry_generation, "ledger_head": a.current_ledger_head},
        "range_base": range_base,
        "content": sorted(content, key=lambda e: e["path"]),
        "change_digest": change_digest(content) if content else None,
        "check_runs_input": {"path": str(a.check_runs), "digest": digest(runs_raw)} if runs_raw is not None else None,
        "expected_jobs": sorted(set(a.expect or [])),
        "job_observation": job_record,
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
    p.add_argument("--check-runs", default=None, help="check-runs JSON for the head, passed to Lane A's evaluator")
    p.add_argument("--expect", action="append", default=None, help="expected job name for Lane A (repeatable)")
    p.add_argument("--base-sha", default=None, help="B1 base_ref: the PR's merge-base the head was built on")
    p.add_argument("--base-commit-time", type=int, default=None, help="base_ref commit time (unix seconds, supplied)")
    p.add_argument("--base-registry-generation", type=int, default=None)
    p.add_argument("--base-ledger-head", default=None)
    p.add_argument("--current-base-sha", default=None, help="observed current base tip (supplied)")
    p.add_argument("--current-base-commit-time", type=int, default=None, help="current base tip commit time (supplied)")
    p.add_argument("--current-registry-generation", type=int, default=None)
    p.add_argument("--current-ledger-head", default=None)
    p.add_argument("--repository", default=None, help="target repository, e.g. owner/name")
    p.add_argument("--remote", default="origin")
    p.add_argument("--range-base", default=None, help="start of the PR's own range (stacked PRs); default --base-sha")
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
