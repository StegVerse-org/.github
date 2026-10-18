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

change_id / change_digest follow P1's rule (StegVerse-Labs/.github#3264 @725d0f65
``resident-runtime/sv_work_items.py``): change_digest = "sha256:" + sha256 over the
change_id canonical bytes of {target_repository, base_ref {registry_generation,
ledger_head}, content [{path, blob_digest, deleted}]}. Field names, failure codes and
the result seal follow StegVerse-Labs/TVC docs/SV_CHANGE_ADMISSION_PREDICATE_REFERENCE.md
(TVC#519) and its ``tvc_request_digest`` (canonical JSON: sorted keys, (",", ":") separators,
UTF-8, ensure_ascii=False; value ``"sha256:" + hex``).

Order: BASE_STATE_RECEIPT_BOUND, then HB_EPOCH_SUPPLIED, then the rest (nothing else is evaluated while the
epoch is unobserved); ADMISSION_INPUT_READY only if every one is ALLOW.
  HB_EPOCH_SUPPLIED              ADMISSION_HB_EPOCH_IS_THE_BOUND_LEDGER_HEAD_EPOCH, aligned to P1's
      verify_admission_hb_epoch (StegVerse-Labs/.github#3264): the source is the epoch the verified #3266 receipt sealed
      with hb_epoch_source {ledger_head == base_ref ledger_head, receipt, field "$.hb_reference.epoch"}, never a clock or
      the flag; --hb-epoch is an optional cross-check (omitted -> none). Source unobserved, or an explicit --hb-epoch
      of '' / 'null' / UNKNOWN_NOT_AUTHENTICALLY_OBSERVED -> FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED. Any other malformed value (kernel
      supplied_epoch_failure 726248a5) or a differing value -> DENY HB_EPOCH_MISMATCH. --hb-epoch omitted ->
      ALLOW with cross_checked false (detail HB_EPOCH_NOT_CROSS_CHECKED). A #3266 DENY HB_EPOCH_MISMATCH receipt still
      observed (and sealed) the epoch, so it binds like ALLOW (P1 @ae8b105d).
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
  BASE_STATE_RECEIPT_BOUND       (with --base-state-receipt) the sealed StegVerse-Labs/.github#3266
      readback receipt verifies as TVC#519 @af754807 sv_change_base_state checks it (schema,
      component, seal, ALLOW, well-formed base_ref/sources/hb_epoch), is bound to --base-sha
      and agrees with any explicit flag; it then supplies registry_generation / ledger_head
      for change identity and HEAD_CURRENT_WITH_BASE, and its hb_epoch is the HB_EPOCH_SUPPLIED source.
  HEAD_CURRENT_WITH_BASE         judged only from supplied inputs, no git: the PR's
      base_ref (--base-sha, the merge-base the head was built on, and its commit
      time) against the observed current base (--current-base-sha and its commit
      time), plus registry_generation / ledger_head when both sides are supplied
      (TVC B1: unchanged since VERIFIED, else BASE_STALE); a value supplied on one
      side only is FAIL_CLOSED BASE_STATE_NOT_OBSERVED.
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


WRITER_EVIDENCE_CLASSES = ("DECLARED", "OBSERVED_COMMIT_TRAILER", UNKNOWN)  # TVC D7


def writer_session(session: str | None) -> dict:
    """TVC D7 content[].writer_session = {session|null, evidence_class}. P4 asserts DECLARED only when the
    declared session and the reflog writer evidence both hold; otherwise {null, UNKNOWN_NOT_AUTHENTICALLY_OBSERVED}."""
    if session is None:
        return {"session": None, "evidence_class": UNKNOWN}
    return {"session": session, "evidence_class": "DECLARED"}


# ---- P1 change identity (StegVerse-Labs/.github#3264 @725d0f65 resident-runtime/sv_work_items.py) ----
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def change_identity_canonical_bytes(value: Any) -> bytes:
    """P1 canon() / CANONICAL_SERIALIZATION: JSON, sort_keys, (",", ":"), UTF-8, ensure_ascii False, no newline."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def base_bound(base: Any) -> bool:
    """P1 _base_ok: registry_generation int >= 0 (not bool) and ledger_head 40 lowercase hex."""
    return (isinstance(base, Mapping) and isinstance(base.get("registry_generation"), int)
            and not isinstance(base.get("registry_generation"), bool) and base["registry_generation"] >= 0
            and isinstance(base.get("ledger_head"), str) and GIT_SHA.match(base["ledger_head"]) is not None)


def change_identity_input(rec: Mapping[str, Any]) -> dict:
    """P1 change_identity_input: {target_repository, base_ref as recorded, content [{path, blob_digest (null when
    deleted), deleted}] sorted by path}. Only boolean true deletes; writer_session is evidence, not identity."""
    content = []
    for c in rec.get("content") or []:
        if isinstance(c, Mapping):
            deleted = c.get("deleted", False) is True
            content.append({"path": c.get("path"), "blob_digest": None if deleted else c.get("blob_digest"), "deleted": deleted})
    return {"target_repository": rec.get("target_repository"), "base_ref": dict(rec["base_ref"]),
            "content": sorted(content, key=lambda c: str(c["path"]))}


def change_id(rec: Mapping[str, Any]) -> str:
    return "svc:" + hashlib.sha256(change_identity_canonical_bytes(change_identity_input(rec))).hexdigest()


def change_digest(rec: Mapping[str, Any]) -> str:
    """P1 change_digest: "sha256:" + sha256 over the change_id canonical bytes (change_digest[7:] == change_id[4:])."""
    return "sha256:" + hashlib.sha256(change_identity_canonical_bytes(change_identity_input(rec))).hexdigest()


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


# ---- B1 base-state readback receipt (StegVerse-Labs/.github#3266 RTC-SV-CHANGE-BASE-STATE-READBACK-014) ----
# Verified exactly as TVC#519 @af754807 sv_change_base_state.base_state_from_readback does; producer pinned in
# config/admission-predicate/base-state-readback.pin.json (traceability: P4 consumes only the sealed receipt).
BASE_STATE_SCHEMA = "stegverse.sv-change-base-state-readback/v1"
BASE_STATE_COMPONENT = "RTC-SV-CHANGE-BASE-STATE-READBACK-014"
BASE_STATE_LEDGER_REF = "refs/stegverse/organization-ledger"
BASE_STATE_LEDGER_HEAD_FILE = BASE_STATE_LEDGER_REF + ":HEAD.json"
HB_EPOCH_SOURCE_FIELD = "$.hb_reference.epoch"  # #3266 @641f4b03 hb_epoch_source.field (Lane B #46 names)
RECEIPT_KEY = re.compile(r"^receipts/[0-9a-f]{64}\.json$")  # ledger_store.receipt_key
BASE_STATE_LABS_REGISTRY = "data/canonical-task-registry.json"  # receipts without ``repository`` (producer c431bfb0)
BASE_STATE_REGISTRY_PATHS = {"StegVerse-Labs/.github": "data/canonical-task-registry.json",
                             "StegVerse-org/.github": "orchestration/task-registry.json"}  # == producer REGISTRY_PATHS @78a0c78e and @641f4b03
REGISTRY_GENERATION_JOINT_ITEM = "Q-ORG-REGISTRY-GENERATION"
BASE_STATE_PIN = Path(__file__).resolve().parents[1] / "config" / "admission-predicate" / "base-state-readback.pin.json"


def base_state_from_readback(receipt: Any) -> tuple[dict | None, str | None, str | None]:
    """(state, None, None) when TVC's adapter would bind the receipt; else (None, failure_code, reason).
    A DENY HB_EPOCH_MISMATCH receipt binds like ALLOW (#3266 @641f4b03 seals base_ref, hb_epoch and hb_epoch_source on it;
    only the producer's own --hb-epoch cross-check disagreed; P1 @ae8b105d treats it as observed). hb_epoch_source is
    carried as-is and judged by HB_EPOCH_SUPPLIED (P1: a bad source is FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED)."""
    if not isinstance(receipt, Mapping):
        return None, "BASE_STATE_RECEIPT_UNREADABLE", "receipt is not a JSON object"
    if receipt.get("schema") != BASE_STATE_SCHEMA or receipt.get("component_id") != BASE_STATE_COMPONENT:
        return None, "BASE_STATE_RECEIPT_SCHEMA_MISMATCH", f"schema/component_id != {BASE_STATE_SCHEMA}/{BASE_STATE_COMPONENT}"
    if not isinstance(receipt.get(SEAL_FIELD), str) or not seal_verifies(receipt):
        return None, "BASE_STATE_RECEIPT_SEAL_INVALID", "result_sha256 does not verify over the canonical receipt"
    observed = receipt.get("disposition") == "ALLOW" or (receipt.get("disposition") == "DENY"
                                                         and receipt.get("failure_code") == "HB_EPOCH_MISMATCH")
    if not observed:
        return None, "BASE_STATE_NOT_OBSERVED", f"receipt disposition {receipt.get('disposition')} ({receipt.get('failure_code')})"
    base = receipt.get("base_ref")
    gen = base.get("registry_generation") if isinstance(base, Mapping) else None
    head = base.get("ledger_head") if isinstance(base, Mapping) else None
    commit = receipt.get("bound_main_commit")
    sources = receipt.get("sources")
    files = {x.get("file"): x.get("blob_sha") for x in sources if isinstance(x, Mapping)} if isinstance(sources, list) else {}
    epoch = receipt.get("hb_epoch")
    if "repository" in receipt:
        registry_file = BASE_STATE_REGISTRY_PATHS.get(receipt["repository"]) if isinstance(receipt["repository"], str) else None
        if registry_file is None:
            return None, "BASE_STATE_RECEIPT_MALFORMED", f"receipt repository {receipt['repository']!r} has no pinned registry path"
    else:
        registry_file = BASE_STATE_LABS_REGISTRY
    if (not base_bound({"registry_generation": gen, "ledger_head": head})
            or not isinstance(commit, str) or not GIT_SHA.match(commit)
            or not all(isinstance(files.get(f), str) and GIT_SHA.match(files[f]) for f in (registry_file, BASE_STATE_LEDGER_HEAD_FILE))
            or (epoch is not None and not (isinstance(epoch, str) and epoch.isascii() and epoch.isdigit() and int(epoch) >= HB_EPOCH_MINIMUM))):
        return None, "BASE_STATE_RECEIPT_MALFORMED", "base_ref, bound_main_commit, sources or hb_epoch not well formed"
    source = receipt.get("hb_epoch_source")
    key = source.get("receipt") if isinstance(source, Mapping) else None
    return {"registry_generation": gen, "ledger_head": head, "bound_main_commit": commit,
            "result_sha256": receipt[SEAL_FIELD], "hb_epoch": epoch, "hb_epoch_open": epoch is None,
            "registry_blob_sha": files[registry_file], "repository": receipt.get("repository"),
            "registry_file": registry_file, "hb_epoch_source": dict(source) if isinstance(source, Mapping) else source,
            "hb_epoch_source_receipt_blob": files.get(BASE_STATE_LEDGER_REF + ":" + key) if isinstance(key, str) else None,
            "readback_disposition": receipt.get("disposition"), "fixture_only": receipt.get("fixture_only") is True}, None, None


def p_base_state(a) -> dict:
    """BASE_STATE_RECEIPT_BOUND: --base-state-receipt (and optionally --current-base-state-receipt) supply
    registry_generation / ledger_head. Each receipt must verify (TVC rule), be bound to that side's commit
    (--base-sha / --current-base-sha), and agree with any explicit flag. The base receipt also observes the
    current side when --current-base-sha is its bound commit and no current receipt is supplied."""
    r = row("BASE_STATE_RECEIPT_BOUND", producer="StegVerse-Labs/.github#3266 @641f4b03 " + BASE_STATE_COMPONENT,
            verifier="TVC#519 @af754807 sv_change_base_state.base_state_from_readback (reproduced)", receipts={})
    sides = [("base", a.base_state_receipt, a.base_sha), ("current", a.current_base_state_receipt, a.current_base_sha)]
    for side, path, sha in sides:
        if not path:
            continue
        flag = "--base-sha" if side == "base" else "--current-base-sha"
        try:
            receipt = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            receipt = exc
        state, code, why = base_state_from_readback(receipt)
        r["receipts"][side] = {"path": str(path), "result_sha256": receipt.get(SEAL_FIELD) if isinstance(receipt, Mapping) else None,
                               "binds": state}
        if state is None:
            if isinstance(receipt, Mapping) and receipt.get("failure_code"):
                r["receipt_failure_code"] = receipt.get("failure_code")
                r["receipt_failed_predicate"] = receipt.get("failed_predicate")
            if code == "BASE_STATE_NOT_OBSERVED" and r.get("receipt_failure_code") == "REGISTRY_GENERATION_NOT_DECLARED":
                r["joint_item"] = REGISTRY_GENERATION_JOINT_ITEM
                return refuse(r, a, code, f"the {side} repository's registry declares an integer generation >= 0 "
                              f"(receipt REGISTRY_GENERATION_NOT_DECLARED; joint item {REGISTRY_GENERATION_JOINT_ITEM}); "
                              "P4 proposes and makes no registry edit",
                              f"after {REGISTRY_GENERATION_JOINT_ITEM} decides, rerun with a fresh ALLOW readback receipt")
            return refuse(r, a, code, f"a sealed {BASE_STATE_SCHEMA} ALLOW receipt from #3266's read-only producer ({side}: {why})",
                          "rerun with a fresh readback receipt for the bound commit")
        if state["bound_main_commit"] != sha:
            return refuse(r, a, "BASE_STATE_RECEIPT_COMMIT_MISMATCH",
                          f"{side} receipt bound_main_commit {state['bound_main_commit']} equals {flag} ({sha})",
                          f"rerun with a readback receipt produced for {flag}")
        targets = (("registry_generation", "base_registry_generation", "current_registry_generation"),
                   ("ledger_head", "base_ledger_head", "current_ledger_head"))
        fill = [side] + (["current"] if side == "base" and not a.current_base_state_receipt and a.current_base_sha == sha else [])
        for s in fill:
            for key, battr, cattr in targets:
                attr = battr if s == "base" else cattr
                given = getattr(a, attr)
                if given is not None and given != state[key]:
                    return refuse(r, a, "BASE_STATE_RECEIPT_FLAG_MISMATCH",
                                  f"--{attr.replace('_', '-')} ({given}) equals the {side} receipt's {key} ({state[key]}), or omit the flag",
                                  "rerun with flags that agree with the receipt, or the receipt alone")
                setattr(a, attr, state[key])
        r["receipts"][side]["observes"] = fill
    return r


def p_identity(a, content: list) -> tuple[dict, dict | None]:
    """CHANGE_IDENTITY_INPUT_BOUND: P1's change_id / change_digest need target_repository, base_ref
    {registry_generation, ledger_head} and content. They are supplied by --repository,
    --base-registry-generation and --base-ledger-head; nothing is guessed."""
    base = {"registry_generation": a.base_registry_generation, "ledger_head": a.base_ledger_head}
    r = row("CHANGE_IDENTITY_INPUT_BOUND", rule="StegVerse-Labs/.github#3264 @725d0f65 sv_work_items.change_digest",
            identity_base_ref=base, target_repository=a.repository)
    if not isinstance(a.repository, str) or not a.repository:
        return refuse(r, a, "TARGET_REPOSITORY_NOT_SUPPLIED",
                      "--repository owner/name (change_id hashes target_repository)",
                      "rerun with --repository supplied"), None
    if not base_bound(base):
        refuse(r, a, "SV_CHANGE_BASE_UNBOUND",
               "--base-registry-generation (int >= 0) and --base-ledger-head (40 lowercase hex): change_id and "
               "change_digest hash both (P1 BASE_BOUND_TO_REGISTRY_GENERATION_AND_LEDGER_HEAD)",
               "rerun with the registry generation and ledger head supplied")
        r["p1_failed_predicate"] = "BASE_BOUND_TO_REGISTRY_GENERATION_AND_LEDGER_HEAD"
        return r, None
    if not content:
        return refuse(r, a, "CHANGE_CONTENT_NOT_OBSERVED",
                      "a non-empty content[] for the PR's own range (writer range must resolve)",
                      "rerun with a resolvable --range-base/--base-sha"), None
    rec = {"target_repository": a.repository, "base_ref": base, "content": content}
    return r, {"change_id": change_id(rec), "change_digest": change_digest(rec)}


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
        if (base[key] is None) != (current[key] is None):
            side = "base_ref" if base[key] is None else "current_base"
            return refuse(r, a, "BASE_STATE_NOT_OBSERVED",
                          f"{key} supplied on both sides or neither ({side} is missing it); a one-sided value is never compared away",
                          f"rerun with --base-{key.replace('_', '-')} and --current-{key.replace('_', '-')} both supplied")
        if base[key] is not None and base[key] != current[key]:
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


HB_EPOCH_INVARIANT = "ADMISSION_HB_EPOCH_IS_THE_BOUND_LEDGER_HEAD_EPOCH"


HB_EPOCH_NOT_CROSS_CHECKED = "HB_EPOCH_NOT_CROSS_CHECKED"  # P1 @ae8b105d sentinel: the optional cross-check was left out
# P1 SUPPLIED_EPOCH_UNOBSERVED_VALUES (None, "", "null", UNKNOWN): explicit unobserved values -> FAIL_CLOSED, never DENY.
# The CLI cannot pass JSON null; an omitted --hb-epoch is HB_EPOCH_NOT_CROSS_CHECKED, never None.
SUPPLIED_EPOCH_UNOBSERVED_VALUES = (None, "", "null", UNKNOWN)
P1_REFERENCE = {"repository": "StegVerse-Labs/.github", "pull_request": 3264, "ref": "ae8b105d7504565665bf6918367517ffdcb481fd",
                "path": "resident-runtime/sv_work_items.py", "git_blob_sha": "446889c5114c416f34ee4ceadd5c3492c821df50",
                "function": "verify_admission_hb_epoch",
                "supplied_epoch_rule": "org-kernel/kernel.py::supplied_epoch_failure (source segment sha256 726248a5)"}


def supplied_epoch_failure(value: Any, reference: Any = None) -> tuple[str, str] | None:
    """org-kernel/kernel.py::supplied_epoch_failure (sha256 726248a5), reproduced: reference not an object -> HB_EPOCH_INVALID;
    None -> HB_EPOCH_NOT_SUPPLIED; not ASCII [0-9]+ (bool, float, '+33', ' 33', '3_3', '33.0', ...) or < 32 -> HB_EPOCH_INVALID;
    reference.derived_from_clock present and not exactly false -> HB_EPOCH_INVALID."""
    if reference is not None and not isinstance(reference, Mapping):
        return "HB_EPOCH_INVALID", "the carrier's heartbeat reference is not an object"
    if value is None:
        return "HB_EPOCH_NOT_SUPPLIED", "no hb_epoch was supplied and no clock is read"
    if isinstance(value, bool):
        text = None
    elif isinstance(value, int):
        text = str(value)
    else:
        text = value if isinstance(value, str) else None
    if text is None or not text.isascii() or not text.isdigit():
        return "HB_EPOCH_INVALID", "hb_epoch " + repr(value) + " is not ASCII [0-9]+"
    if int(text) < HB_EPOCH_MINIMUM:
        return "HB_EPOCH_INVALID", "hb_epoch " + text + " is below the HB32 anchor (32)"
    if reference is not None and "derived_from_clock" in reference and reference["derived_from_clock"] is not False:
        return "HB_EPOCH_INVALID", "the carrier's derived_from_clock is not exactly false; a clock-derived epoch is not a supplied one"
    return None


def p_hb_epoch(a, receipt_row: dict | None) -> tuple[dict, str | None]:
    """HB_EPOCH_SUPPLIED = P1 verify_admission_hb_epoch (StegVerse-Labs/.github#3264 @ae8b105d, sv_work_items.py blob 446889c5)
    over the receipt BASE_STATE_RECEIPT_BOUND verified (schema, seal, ALLOW or DENY HB_EPOCH_MISMATCH, bound commit/flags):
      FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED: no bound receipt; fixture_only; no hb_epoch_source naming $.hb_reference.epoch
        at base_ref.ledger_head; hb_epoch_source.receipt not receipts/<hex>.json (P4 also requires that receipt in sources);
        a sealed hb_epoch slot failing 726248a5 (with hb_epoch_source as the reference); or an explicit --hb-epoch of
        '', 'null' or UNKNOWN_NOT_AUTHENTICALLY_OBSERVED (checked before 726248a5). Row detail: {ledger_head, detail}.
      ALLOW {hb_epoch, ledger_head, cross_checked: false, detail: HB_EPOCH_NOT_CROSS_CHECKED}: --hb-epoch omitted.
      DENY HB_EPOCH_MISMATCH {ledger_head, expected, hb_epoch (supplied), supplied_epoch_rule?}: any other value failing
        726248a5, or not equal by integer value to the sealed epoch.
      ALLOW {hb_epoch, ledger_head, cross_checked: true}: the cross-check held."""
    bound = (receipt_row or {}).get("receipts", {}).get("base", {}).get("binds") if receipt_row and receipt_row["holds"] else None
    head = bound.get("ledger_head") if bound else None
    supplied = HB_EPOCH_NOT_CROSS_CHECKED if a.hb_epoch is None else a.hb_epoch
    r = row("HB_EPOCH_SUPPLIED", invariant=HB_EPOCH_INVARIANT, aligned_to=P1_REFERENCE, ledger_head=head,
            receipt_hb_epoch=bound.get("hb_epoch") if bound else None,
            receipt_hb_epoch_source=bound.get("hb_epoch_source") if bound else None,
            receipt_result_sha256=bound.get("result_sha256") if bound else None,
            readback_disposition=bound.get("readback_disposition") if bound else None)

    def unobserved(why: str) -> tuple[dict, None]:
        r["detail"] = why
        return refuse(r, a, "HB_EPOCH_SOURCE_UNOBSERVED",
                      f"{HB_EPOCH_INVARIANT}: a sealed ALLOW {BASE_STATE_SCHEMA} receipt (Labs#3266) for base_ref.ledger_head whose "
                      f"hb_epoch slot was read from {HB_EPOCH_SOURCE_FIELD} of the head receipt and passes "
                      f"org-kernel/kernel.py::supplied_epoch_failure (sha256 726248a5) ({why})",
                      "after Lane C's readback (Labs#3266) seals an epoch read at that ledger head; no epoch is minted"), None

    if bound is None:
        return unobserved("no verified --base-state-receipt")
    if bound.get("fixture_only"):
        return unobserved("a fixture_only readback counts only in fixture_mode (P4 has none)")
    src = bound.get("hb_epoch_source")
    if not isinstance(src, Mapping) or src.get("ledger_head") != head or src.get("field") != HB_EPOCH_SOURCE_FIELD:
        return unobserved(f"no hb_epoch_source naming {HB_EPOCH_SOURCE_FIELD} at the bound head")
    receipt_key = src.get("receipt")
    if not (isinstance(receipt_key, str) and RECEIPT_KEY.match(receipt_key)):
        return unobserved("hb_epoch_source.receipt is not the head receipt's ledger path receipts/<hex>.json")
    if not (isinstance(bound.get("hb_epoch_source_receipt_blob"), str) and GIT_SHA.match(bound["hb_epoch_source_receipt_blob"])):
        return unobserved("hb_epoch_source.receipt is not among the receipt's sources with a git blob sha (P4 check)")
    sealed = bound.get("hb_epoch")
    bad = supplied_epoch_failure(sealed, src)
    if sealed is None or bad is not None:
        return unobserved("the sealed hb_epoch slot fails the shared supplied-epoch rule: " + (bad[0] + ": " + bad[1] if bad else "absent"))
    want = int(str(sealed))
    if supplied is HB_EPOCH_NOT_CROSS_CHECKED:
        r.update({"hb_epoch": str(want), "cross_checked": False, "detail": HB_EPOCH_NOT_CROSS_CHECKED})
        return r, str(want)
    if supplied in SUPPLIED_EPOCH_UNOBSERVED_VALUES:
        return unobserved(f"the supplied hb_epoch {supplied!r} is not observed (UNKNOWN_NOT_AUTHENTICALLY_OBSERVED is FAIL_CLOSED, "
                          "never DENY; checked before 726248a5)")
    failure = supplied_epoch_failure(supplied)
    if failure is not None or not (isinstance(supplied, str) and HB_EPOCH.fullmatch(supplied) and int(supplied) == want):
        r.update({"expected": str(want), "hb_epoch": supplied})
        if failure is not None:
            r["supplied_epoch_rule"] = failure[0] + ": " + failure[1]
        return refuse(r, a, "HB_EPOCH_MISMATCH",
                      "the SV_CHANGE's hb_epoch (--hb-epoch) equals the epoch the base-state readback sealed at base_ref.ledger_head",
                      "propose a successor SV_CHANGE at the observed epoch; nothing was admitted", disposition="DENY"), None
    r.update({"hb_epoch": str(want), "cross_checked": True})
    return r, str(want)


def pred_holds(predicates: list, name: str) -> bool:
    return any(p["predicate"] == name and p["holds"] for p in predicates)


def evaluate(a) -> dict:
    a.clone = Path(a.clone)
    head = git(a.clone, "rev-parse", f"refs/heads/{a.branch}").strip()
    range_base = a.range_base or a.base_sha
    if range_base and git(a.clone, "cat-file", "-t", range_base, check=False).strip() != "commit":
        range_base = None  # unresolvable range: the writer predicate fails closed, content stays empty
    runs_raw = Path(a.check_runs).read_bytes() if a.check_runs else None
    job_record = None
    content: list = []
    identity = None
    # BASE_STATE_RECEIPT_BOUND first: the epoch is read only from a verified receipt.
    receipt_row = p_base_state(a) if (a.base_state_receipt or a.current_base_state_receipt) else None
    epoch_row, epoch = p_hb_epoch(a, receipt_row)
    predicates = ([receipt_row] if receipt_row else []) + [epoch_row]
    if epoch is not None:  # nothing else is evaluated while the epoch is unobserved
        a.hb_epoch = epoch
        writer = p_writer(a, head, range_base) if range_base else None
        predicates.append(p_session(a))
        if writer is None:
            writer = refuse(row("BRANCH_WRITER_IS_BRANCH_OWNER"), a, "BRANCH_HAS_FOREIGN_WRITER",
                            "supply a --range-base/--base-sha commit present in the clone so the PR's own range is defined",
                            "rerun with the range supplied")
        predicates.append(writer)
        if range_base:
            sess_ok = pred_holds(predicates, "PR_AUTHOR_SESSION_DECLARED") and writer["holds"]
            for path, deleted in changed_paths(a.clone, range_base, head):
                content.append({"path": path, "deleted": deleted,
                                "blob_digest": None if deleted else blob_digest(a.clone, head, path),
                                "writer_session": writer_session(a.session_id if sess_ok else None)})
        identity_row, identity = p_identity(a, content)
        predicates.append(identity_row)
        jobs, job_record = p_jobs(a, head, identity["change_digest"] if identity else None)
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
        "change_id": identity["change_id"] if identity else None,
        "change_digest": identity["change_digest"] if identity else None,
        "check_runs_input": {"path": str(a.check_runs), "digest": digest(runs_raw)} if runs_raw is not None else None,
        "expected_jobs": sorted(set(a.expect or [])),
        "job_observation": job_record,
        "hb_epoch": int(epoch) if epoch is not None else None,
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
    p.add_argument("--hb-epoch", default=None,
                   help="optional cross-check: must equal the verified base-state receipt's hb_epoch (the source); omitted -> ALLOW, cross_checked false; ''/null/sentinel -> "
                        "FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED, malformed or differing -> DENY HB_EPOCH_MISMATCH")
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
    p.add_argument("--base-state-receipt", default=None,
                   help="sealed #3266 base-state readback receipt for --base-sha (fills base registry_generation/ledger_head)")
    p.add_argument("--current-base-state-receipt", default=None,
                   help="sealed #3266 readback receipt for --current-base-sha (default: the base receipt when the shas match)")
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
