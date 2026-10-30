#!/usr/bin/env python3
"""``sv_change_admit`` -- record the SV_CHANGE_SUPERSEDE -> SV_CHANGE_VERIFY -> SV_CHANGE_ADMIT outcome for one change.

Authoring-Session: p1-ecosystem-ai-lane (StegVerse-org/.github#163; Lane D FAIL_CLOSED StegVerse-org/.github#167
c6513778290; Lane B owns this writer). Port of the StegVerse-Labs/.github operation of the same name to this
organization's own writer: a change is admitted once, on the ledger of the organization that owns its target repository
(CHANGE_BINDS_TARGET_REPOSITORY_LEDGER), so StegVerse-org repositories, the SDK included, are admitted here.

``resident-runtime/sv_work_items.py::transition("SV_CHANGE_ADMIT")`` is a library function whose ``record()`` hands every
outcome, refusals included, to "the existing repository emitter". Nothing called it. This operation is that caller, added to
the existing writer (``organization-ledger-writer.yml`` job ``ledger-ingest``, push to main, no new workflow, no dispatch, no
schedule):

  * it evaluates the lifecycle on the committed request with P1's evaluator at f28c3a76, vendored under
    tests/vendor/p1_f28c3a76 and pinned by data/sv-work-items/contract-pins.json (sha256 5c0c98d4...; the same pin Labs
    uses; this checkout holds no sv_work_items.py of its own, and its org-kernel/kernel.py is not the pinned one, so the
    pinned kernel.py, node_store.py and worker-claim script are vendored beside it and verified before use):
    SV_CHANGE_SUPERSEDE (predecessor -> NATIVE successor), SV_CHANGE_VERIFY, SV_CHANGE_ADMIT;
  * it never invents evidence. The push receipts and the ledger head are READ from the declared ledger, never taken from the
    request: each declared push range is looked up as SV_PUSH_RECEIPT_APPEND:<range id> and passed on only if the ledger holds
    it; an unrecorded range stays unobserved, so branch-writer derivation fails closed. This checkout holds no task registry,
    so the registry generation is the one value the request supplies (``admission.registry_generation``) and the evidence
    labels it SUPPLIED_IN_REQUEST. The resolved SV_ISSUE facts are DERIVED from this organization's own ledger, never taken
    from the request: at the successor's own base_ref.ledger_head the writer reads every retained sv_check_receipt,
    re-derives the NATIVE issue each failing one yields (P1's derive_issue_from_check_receipt) and builds the facts for the
    issues the successor cites in $.resolves (derive_resolved_issue_facts). A cited issue the ledger does not derive is a
    six-field FAIL_CLOSED SV_CHANGE_ADMIT_RESOLVED_ISSUE_FACTS_ABSENT before any write; nothing here fabricates an issue
    and there is no other source. Required-check receipts and sign-offs are not supplied by this
    operation, so a change that needs them is refused by the evaluator, and
    that refusal is the outcome (nothing here turns a gap into ALLOW);
  * the outcome is recorded whatever it is (``record()``): one repository receipt (``transition_class`` SV_CHANGE_ADMIT,
    ``$.evidence`` = the lifecycle result with its six fields, the change record, the chain of step dispositions and what was
    observed) and one organization receipt naming it. A non-ALLOW outcome is a recorded fact that confers nothing;
  * exactly one admit per change: the transition id is ``<change_id>:SV_CHANGE_ADMIT`` (sv_work_items.record), so a second
    request for the same change, byte-identical or not, is a six-field FAIL_CLOSED SV_CHANGE_ADMIT_ALREADY_RECORDED and appends
    nothing; the lookup and both appends run under the writer workflow's ORGANIZATION_LEDGER_LOCK (the push-receipt operation's own order:
    lookup first, a recorded change is refused with nothing written);
  * the ledger of the organization that owns the repository (CHANGE_BINDS_TARGET_REPOSITORY_LEDGER): a change whose
    ``target_repository`` is not owned by this ledger's organization is refused before any write;
  * time is supplied: the request epoch (an int) must pass resident-runtime/aggregate_repo_transition.py::supplied_epoch_failure
    (the shared rule of the push-receipt operation, SHARED_RULE_SHA256 7f36f0e6...) and equal the
    NATIVE successor's own hb_epoch (the push-receipt tie rule). No clock, no network, no key, no dependency.

Refusals before any write are six-field FAIL_CLOSED with consequence_committed false. The operation's own ``disposition`` is
ALLOW exactly when the pair was appended; ``admit_disposition`` is the lifecycle outcome that was recorded. Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import importlib.util
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]

OPERATION_ID = "sv_change_admit"
TRANSITION_CLASS = "SV_CHANGE_ADMIT"
PROFILE_ID = "org-ledger-writer"
LEDGER_REF = "refs/stegverse/organization-ledger"
LEDGER_OWNER = "StegVerse-org"  # the organization whose ledger this checkout writes (CHANGE_BINDS_TARGET_REPOSITORY_LEDGER)
RESULT_SCHEMA = "stegverse.org-sv-change-admit-append-result/v1"
READBACK_SCHEMA = "stegverse.org-sv-change-admit-readback/v1"
OWNING_GOAL = "StegVerse-org/.github#163 (WORK_ITEMS_ARE_TASK_REGISTRY_NATIVE)"
RETRY = "resident-runtime/sv_change_admit_append.py::append_change_admit"
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
ADMISSION_FIELDS = {"predicate_digest", "corpus_head", "actor_session", "change_commits", "push_ranges", "registry_generation"}
CHANGE_ID = re.compile(r"^svc:[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
P1_HEAD = "f28c3a76a8b495d7a815a7ecd513c4d4dc90c9c7"
P1_VENDOR = ROOT / "tests" / "vendor" / "p1_f28c3a76"
P1_MANIFEST = "data/sv-work-items/contract-pins.json"
P1_MANIFEST_SHA256 = "5c0c98d4349274b547a7c4ba8154e77e930e55e0a8dc1827344229661957a4cb"  # blob ef2ff1e8, the pin Labs verifies
P1_USED_FILES = ("resident-runtime/sv_work_items.py", "resident-runtime/sv_push_receipt.py",
                 "data/sv-work-items/required-checks.json", "data/sv-work-items/lifecycle-transitions.json",
                 "schemas/sv-check-receipt.v1.schema.json",
                 "data/sv-work-items/stages/NWI-S0.json", "data/sv-work-items/stages/NWI-S1.json",
                 "data/sv-work-items/stages/NWI-S2.json", "data/sv-work-items/stages/NWI-S3.json",
                 "data/sv-work-items/stages/NWI-S4.json",
                 "org-kernel/kernel.py", "org-kernel/node_store.py", "scripts/project_worker_claim_into_canonical_task.py")


def _module(name: str, relative: str):
    if name in sys.modules:
        return sys.modules[name]
    runtime = str(ROOT / "resident-runtime")
    if runtime not in sys.path:
        sys.path.insert(0, runtime)
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# The same private instance of the ingress the sv_push_receipt operation appends through: one declared store.
pa = _module("sv_push_receipt_append_for_change_admit", "resident-runtime/sv_push_receipt_append.py")
ingress = pa.ingress
sha = ingress.sha
SHARED_RULE_SHA256 = pa.SHARED_RULE_SHA256
_P1: dict[str, Any] = {}


def p1_pin_failure() -> str | None:
    """None when the manifest has its pinned sha256 and every used vendored file has its manifest sha256."""
    try:
        raw = (P1_VENDOR / P1_MANIFEST).read_bytes()
    except OSError as exc:
        return "manifest unreadable: %s" % exc
    if hashlib.sha256(raw).hexdigest() != P1_MANIFEST_SHA256:
        return "manifest sha256 is not the pinned " + P1_MANIFEST_SHA256
    files = json.loads(raw)["files"]
    for rel in P1_USED_FILES:
        pin = (files.get(rel) or {}).get("sha256")
        try:
            have = "sha256:" + hashlib.sha256((P1_VENDOR / rel).read_bytes()).hexdigest()
        except OSError:
            return rel + " is not vendored"
        if pin is None or have != pin:
            return rel + " does not match its manifest digest"
    return None


P1_PIN_FAILURE = p1_pin_failure()


def p1_readers():
    """P1's sv_work_items at P1_HEAD, run over a temporary root holding the vendored files in P1's layout (this checkout's
    own org-kernel/kernel.py is not the pinned one, so the vendored kernel.py, node_store.py and worker-claim script are
    used). Refuses (RuntimeError) unless the manifest pins verify."""
    if "wi" in _P1:
        return _P1["wi"]
    if P1_PIN_FAILURE is not None:
        raise RuntimeError(P1_PIN_FAILURE)
    import atexit
    import shutil
    import tempfile
    root = Path(tempfile.mkdtemp(prefix="p1_f28c3a76_"))
    atexit.register(shutil.rmtree, root, True)
    for rel in P1_USED_FILES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(P1_VENDOR / rel, root / rel)
    name = "sv_work_items_p1_f28c3a76"
    spec = importlib.util.spec_from_file_location(name, root / "resident-runtime" / "sv_work_items.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _P1["wi"] = module
    return module


def refusal(code: str, predicate: str, repair: str, next_attempt: str, **detail: Any) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "operation": OPERATION_ID, "disposition": "FAIL_CLOSED",
            "failure_code": code, "failed_predicate": predicate, "required_evidence_or_repair": repair,
            "retry_entrypoint": RETRY, "owning_existing_goal": OWNING_GOAL, "next_attempt": next_attempt,
            "consequence_committed": False, "authority_effect": "NONE_REFUSAL_ONLY", **detail}


def _epoch_refusal(successor: Mapping[str, Any], hb_epoch: Any) -> dict[str, Any] | None:
    """The supplied-epoch rule of the sibling operations (one shared rule, pinned): the request epoch is an int that passes
    resident-runtime/aggregate_repo_transition.py::supplied_epoch_failure and equals the NATIVE successor's own hb_epoch (ASCII digits)."""
    rule = pa.epoch_rule
    why = "supply the request epoch as an integer and carry the same supplied epoch in the successor's hb_epoch; both must pass " \
          "resident-runtime/aggregate_repo_transition.py::supplied_epoch_failure (SHARED_RULE_SHA256 " + SHARED_RULE_SHA256 + ")"
    if pa.KERNEL_RULE_SHA256 != SHARED_RULE_SHA256:
        return refusal("HB_EPOCH_SOURCE_UNOBSERVED", pa.EPOCH_SOURCE_PREDICATE, why, "after the shared rule is the pinned one; nothing was written",
                       detail="resident-runtime/aggregate_repo_transition.py::supplied_epoch_failure is not the pinned shared rule",
                       shared_rule_sha256=SHARED_RULE_SHA256)
    mine = successor.get("hb_epoch")
    for side, value in (("request epoch", hb_epoch), ("successor hb_epoch", mine)):
        if pa._unobserved_value(value):
            return refusal("HB_EPOCH_SOURCE_UNOBSERVED", pa.EPOCH_SOURCE_PREDICATE, why,
                           "after a supplied epoch is observed on both; nothing was written",
                           detail=side + " is absent, null, '', 'null' or " + pa.UNKNOWN_SENTINEL, side=side, value=repr(value), shared_rule_sha256=SHARED_RULE_SHA256)
    detail = None
    bad = rule(hb_epoch)
    if bad is not None or type(hb_epoch) is not int:
        detail = "request epoch " + repr(hb_epoch) + ": " + (bad[0] + ": " + bad[1] if bad else "not an int")
    else:
        bad = rule(mine)
        if bad is not None or not isinstance(mine, str):
            detail = "successor hb_epoch " + repr(mine) + ": " + (bad[0] + ": " + bad[1] if bad else "not ASCII text")
        elif int(mine) != hb_epoch:
            detail = "the successor's epoch differs from the request epoch"
    if detail is None:
        return None
    out = refusal(pa.EPOCH_MISMATCH, "SUCCESSOR_HB_EPOCH_EQUALS_REQUEST_HB_EPOCH",
                  "the request's hb_epoch (an int) equals the successor's hb_epoch (ASCII digits), both passing "
                  "resident-runtime/aggregate_repo_transition.py::supplied_epoch_failure", "commit the ingest request again with the successor's own supplied epoch; "
                  "nothing was written", detail=detail, shared_rule_sha256=SHARED_RULE_SHA256, hb_epoch=repr(hb_epoch), successor_hb_epoch=repr(mine))
    out["disposition"] = "DENY"
    return out


def _stored_epoch_refusal(row: Any, hb_epoch: int) -> dict[str, Any] | None:
    bad = pa._stored_epoch_refusal(row, hb_epoch)
    if bad is None:
        return None
    return {**bad, "schema": RESULT_SCHEMA, "operation": OPERATION_ID, "retry_entrypoint": RETRY, "owning_existing_goal": OWNING_GOAL}


def transition_id(change_id: str) -> str:
    """sv_work_items.record(): ``<change_id>:<transition_class>``. One admit per change."""
    return change_id + ":" + TRANSITION_CLASS


def _owned_by_this_ledger(repository: Any) -> bool:
    return isinstance(repository, str) and repository.startswith(LEDGER_OWNER + "/") and repository.count("/") == 1


def request_problem(predecessor: Any, successor: Any, admission: Any) -> dict[str, Any] | None:
    """The request's shape, before any evaluation (never a lifecycle result)."""
    if not (isinstance(predecessor, dict) and isinstance(successor, dict) and isinstance(admission, dict)):
        return refusal("SV_CHANGE_ADMIT_REQUEST_MALFORMED", "REQUEST_CARRIES_PREDECESSOR_SUCCESSOR_AND_ADMISSION",
                       "predecessor and successor as one stegverse.sv_change.v1 object each and admission as one object",
                       "commit the ingest request again with all three objects; nothing was written")
    if set(admission) != ADMISSION_FIELDS:
        return refusal("SV_CHANGE_ADMIT_REQUEST_MALFORMED", "ADMISSION_HAS_EXACTLY_THE_DECLARED_FIELDS",
                       "admission takes exactly " + ", ".join(sorted(ADMISSION_FIELDS)), "commit the ingest request again; nothing was written",
                       found=sorted(admission))
    cc = admission["change_commits"]
    ranges = admission["push_ranges"]
    bad = []
    if not (isinstance(admission["predicate_digest"], str) and DIGEST.match(admission["predicate_digest"])):
        bad.append("predicate_digest")
    if not (isinstance(admission["corpus_head"], str) and GIT_SHA.match(admission["corpus_head"])):
        bad.append("corpus_head")
    if not (isinstance(admission["actor_session"], str) and admission["actor_session"].strip()):
        bad.append("actor_session")
    if supplied_registry_generation(admission) is None:
        bad.append("registry_generation")
    if not (isinstance(cc, dict) and set(cc) == {"base_commit", "head_commit"}
            and all(isinstance(v, str) and GIT_SHA.match(v) for v in cc.values())):
        bad.append("change_commits")
    if not (isinstance(ranges, list) and ranges and all(isinstance(r, dict) and set(r) == set(pa.RANGE_FIELDS)
                                                       and all(isinstance(v, str) and v for v in r.values()) for r in ranges)):
        bad.append("push_ranges")
    if not (isinstance(successor.get("change_id"), str) and CHANGE_ID.match(successor["change_id"])):
        bad.append("successor.change_id")
    if bad:
        return refusal("SV_CHANGE_ADMIT_REQUEST_MALFORMED", "ADMISSION_FIELDS_ARE_WELL_FORMED",
                       "predicate_digest sha256:<64 hex>, corpus_head 40 hex, actor_session text, registry_generation a non-negative integer, change_commits {base_commit, head_commit} "
                       "40 hex, push_ranges a non-empty list of {repository, ref, old_sha, new_sha}, and the successor's change_id "
                       "svc:<64 hex>; malformed: " + ", ".join(bad), "commit the ingest request again; nothing was written", malformed=bad)
    if not _owned_by_this_ledger(successor.get("target_repository")):
        return refusal("SV_CHANGE_TARGET_NOT_OWNED_BY_THIS_LEDGER", "CHANGE_BINDS_TARGET_REPOSITORY_LEDGER",
                       "an admit is recorded once, on the ledger of the organization that owns the change's target repository ("
                       + LEDGER_OWNER + " here); the successor targets " + repr(successor.get("target_repository")),
                       "send the request to the writer of the owning organization; nothing was written",
                       target_repository=successor.get("target_repository"))
    if successor.get("record_mode") != "NATIVE":
        return refusal("SV_CHANGE_ADMIT_SUCCESSOR_NOT_NATIVE", "ADMITTED_RECORDS_ARE_NATIVE",
                       "the successor is a NATIVE stegverse.sv_change.v1 record (a MIGRATED_HISTORICAL record is never admitted; "
                       "evaluate_admission refuses it as HISTORICAL_RECORD_NOT_ADMISSIBLE)",
                       "commit the ingest request again with the NATIVE successor; nothing was written",
                       record_mode=successor.get("record_mode"))
    if predecessor.get("target_repository") != successor.get("target_repository"):
        return refusal("SV_CHANGE_SUPERSEDE_CROSSES_REPOSITORIES", "CHANGE_BINDS_TARGET_REPOSITORY_LEDGER",
                       "predecessor and successor name the same target_repository", "commit the ingest request again; nothing was written",
                       predecessor=predecessor.get("target_repository"), successor=successor.get("target_repository"))
    return None


def ledger_head_commit(store: Any) -> str | None:
    """The git commit the declared organization-ledger ref points at (the store's own committed tip): observed, not supplied."""
    try:
        tip = store._tip()
    except Exception:  # noqa: BLE001 - an unreadable ledger is reported as an unobserved base
        return None
    return tip if isinstance(tip, str) and GIT_SHA.match(tip) else None


def supplied_registry_generation(admission: Mapping[str, Any]) -> int | None:
    """The one base value this checkout cannot observe (it holds no task registry): the int the request supplies."""
    value = admission.get("registry_generation")
    return value if type(value) is int and value >= 0 else None


def _step(result: Mapping[str, Any]) -> dict[str, Any]:
    keep = ("transition_class", "disposition") + SIX_FIELDS
    out = {k: result.get(k) for k in keep if k in result or k in ("transition_class", "disposition")}
    rec = result.get("record") or {}
    return out | {"record_sha256": sha(rec), "lifecycle_state": rec.get("lifecycle_state"), "superseded_by": rec.get("superseded_by")}


def _blob(store: Any, commit: str, key: str) -> bytes | None:
    """The bytes of `key` in the ledger tree at `commit`, exactly as stored; None if absent."""
    found = store._git("rev-parse", "--verify", "-q", commit + ":" + store._path(key), check=False)
    if found.returncode != 0:
        return None
    return store._git("cat-file", "blob", found.stdout.decode().strip()).stdout


def ledger_issue_facts(store: Any, successor: Mapping[str, Any], generation: Any, change_commits: Mapping[str, Any]) -> dict[str, Any]:
    """The resolved-issue facts for the issues `successor` cites, read from the organization ledger at the successor's own
    base_ref.ledger_head and derived by P1's pure functions; never from the request.

    Returns {"facts", "issues", "ledger_commit", "check_receipts_read"} or a six-field refusal (disposition FAIL_CLOSED, nothing
    written). The only source of an issue is a retained sv_check_receipt (a non-ALLOW check the sv_check_receipt operation
    appended): an issue is derived from it, not stored. A cited issue that no such receipt derives, or a successor that cites
    none, is SV_CHANGE_ADMIT_RESOLVED_ISSUE_FACTS_ABSENT."""
    wi = p1_readers()
    base = successor.get("base_ref")
    commit = base.get("ledger_head") if isinstance(base, dict) else None
    cited = successor.get("resolves") if isinstance(successor.get("resolves"), list) else []
    gone = lambda why, **d: refusal(  # noqa: E731
        "SV_CHANGE_ADMIT_RESOLVED_ISSUE_FACTS_ABSENT", "RESOLVED_ISSUE_FACTS_ARE_DERIVED_FROM_THE_LEDGER_AT_THE_CHANGE_BASE",
        "a NATIVE SV_ISSUE the successor genuinely resolves, derived by derive_issue_from_check_receipt from a non-ALLOW sv_check_receipt this "
        "ledger retains at the successor's base_ref.ledger_head and cited in $.resolves; this operation reads it from the ledger and "
        "takes no issue from the request. " + why, "after a NATIVE SV_ISSUE the change resolves is on this ledger at the change's base "
        "(a failing sv_check_receipt appended by the sv_check_receipt operation); nothing was written", cited=sorted(map(str, cited)),
        ledger_commit=commit, **d)
    if not (isinstance(commit, str) and GIT_SHA.match(commit)) or store._git("cat-file", "-e", commit + "^{commit}", check=False).returncode != 0:
        return gone("The successor's base_ref.ledger_head is not a commit of this ledger.", detail="BASE_LEDGER_HEAD_NOT_ON_THIS_LEDGER")
    if not cited:
        return gone("The successor cites no issue ($.resolves is empty).", detail="RESOLVES_IS_EMPTY")
    objects: dict[str, bytes] = {}
    issues: list[dict[str, Any]] = []
    read = 0
    listed = store._git("ls-tree", "--name-only", commit, "--", store._path("receipts") + "/", check=False)
    for name in sorted(listed.stdout.decode().splitlines()):
        raw = _blob(store, commit, name)
        try:
            org_receipt = json.loads(raw) if raw is not None else None
        except ValueError:
            continue
        boundary = org_receipt.get("boundary_evidence") if isinstance(org_receipt, dict) else None
        if not (isinstance(boundary, dict) and boundary.get("operation") == wi.SV_CHECK_RECEIPT_OPERATION):
            continue
        repo_sha = org_receipt.get("repo_receipt_sha256")
        if not (isinstance(repo_sha, str) and DIGEST.match(repo_sha)):
            continue
        source_key = "source-receipts/" + repo_sha.split(":", 1)[1] + ".json"
        source = _blob(store, commit, source_key)
        if source is None:
            continue
        read += 1
        objects[commit + ":" + name], objects[commit + ":" + source_key] = raw, source
        # The issue is derived at the commit that appended its receipt (the ref the receipt first appears at); the change's
        # own base is where it must still be present, byte for byte (derive_resolved_issue_facts).
        added = store._git("log", "--diff-filter=A", "--format=%H", commit, "--", store._path(name), check=False).stdout.decode().split()
        first = added[-1] if added else None
        if first is None or _blob(store, first, name) is None or _blob(store, first, source_key) is None:
            continue
        objects[first + ":" + name], objects[first + ":" + source_key] = _blob(store, first, name), _blob(store, first, source_key)
        try:
            issues.append(wi.derive_issue_from_check_receipt(
                objects, LEDGER_REF + "@" + first + ":" + name, observed_base={"registry_generation": generation, "ledger_head": first}))
        except wi.Refusal:
            continue  # an ALLOW check, or one this ledger bytes do not derive an issue from: no issue
    try:
        facts = wi.derive_resolved_issue_facts(objects, LEDGER_REF + "@" + commit, successor, issues, change_commits=change_commits)
    except wi.Refusal as exc:
        rec = exc.record
        out = refusal(rec["failure_code"], rec["failed_predicate"], rec["required_evidence_or_repair"],
                      rec.get("next_attempt") or "after the repair; nothing was written", cited=sorted(map(str, cited)), ledger_commit=commit)
        out["disposition"] = "FAIL_CLOSED"
        return out
    have = {f["issue_id"] for f in facts}
    if not set(cited) <= have:
        return gone("The ledger derives " + str(len(issues)) + " issue(s) from " + str(read) + " retained check receipt(s) at that commit; "
                    "cited and not derived: " + ", ".join(sorted(set(map(str, cited)) - have)) + ".",
                    detail="CITED_ISSUE_NOT_DERIVED_FROM_THE_LEDGER", derived_issue_ids=sorted(i["issue_id"] for i in issues),
                    check_receipts_read=read)
    return {"facts": facts, "issues": issues, "ledger_commit": commit, "check_receipts_read": read}


def evaluate(predecessor: dict[str, Any], successor: dict[str, Any], admission: Mapping[str, Any], push_receipts: list[dict[str, Any]],
             current_base: Mapping[str, Any], hb_epoch: int, resolved_issues: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The lifecycle over the supplied records and the observed ledger facts. Returns {result, chain}: `result` is the
    SV_CHANGE_ADMIT outcome (ALLOW, DENY or FAIL_CLOSED, six fields on every non-ALLOW), `chain` the step dispositions."""
    wi = p1_readers()
    epoch = str(hb_epoch)
    commits = dict(admission["change_commits"])
    writer_ctx = {"push_receipts": push_receipts, "change_commits": commits}
    facts = [dict(f) for f in resolved_issues or []]
    supersede = wi.transition("SV_CHANGE_SUPERSEDE", predecessor, hb_epoch=epoch, context={"successor": successor})
    verify = wi.transition("SV_CHANGE_VERIFY", successor, hb_epoch=epoch, context={**writer_ctx, "resolved_issues": facts})
    state = verify["record"]
    admit_ctx = {**writer_ctx, "resolved_issues": facts, "current_base": dict(current_base),
                 "predicate_digest": admission["predicate_digest"], "corpus_head": admission["corpus_head"],
                 "actor_session": admission["actor_session"]}
    admitted = wi.transition("SV_CHANGE_ADMIT", state, hb_epoch=epoch, context=admit_ctx)
    return {"result": admitted, "chain": [_step(supersede), _step(verify), _step(admitted)]}


def _duplicate(change_id: str, prior: Mapping[str, Any]) -> dict[str, Any]:
    evidence = prior.get("evidence") if isinstance(prior.get("evidence"), dict) else {}
    return refusal("SV_CHANGE_ADMIT_ALREADY_RECORDED", "ONE_ADMIT_PER_CHANGE",
                   "the ledger already holds the admit outcome for " + change_id + " (" + str(evidence.get("disposition")) + "); a second "
                   "request for the same change is a duplicate and is not minted, identical or not. The recorded outcome confers "
                   "nothing it did not already confer",
                   "none for this change: the recorded receipt is the evidence; a NATIVE successor on a newer base is a new change_id "
                   "and may be requested; nothing was written", appended=False, change_id=change_id,
                   recorded_repository_receipt_sha256=prior.get("receipt_sha256"),
                   recorded_disposition=evidence.get("disposition"), recorded_failure_code=evidence.get("failure_code"))


def append_change_admit(predecessor: Any, successor: Any, admission: Any, *, hb_epoch: Any) -> dict[str, Any]:
    """Evaluate the lifecycle for `successor` and record the outcome once per change."""
    bad = request_problem(predecessor, successor, admission) or _epoch_refusal(successor, hb_epoch)
    if bad is not None:
        return bad
    if P1_PIN_FAILURE is not None:
        return refusal("P1_CONTRACT_PINS_UNVERIFIED", "VENDORED_P1_FILES_MATCH_THE_PINNED_CONTRACT_MANIFEST",
                       "re-vendor P1's files against data/sv-work-items/contract-pins.json (sha256 " + P1_MANIFEST_SHA256 + ")",
                       "after the vendored files match the pinned manifest; nothing was written", detail=P1_PIN_FAILURE)
    try:
        rl, org = ingress.repository_ledger, ingress.organization_ledger
        rl.lr()
        org.ledger_root()
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - every resolver refusal is reported, none is retried
        return refusal("ORGANIZATION_LEDGER_LOCATION_UNRESOLVED", "WRITER_LEDGER_LOCATIONS_ARE_SUPPLIED",
                       "supply the repository and organization ledger locations the writer workflow declares",
                       "after the ledger locations resolve; nothing was written", detail=f"{type(exc).__name__}: {exc}")
    change_id = successor["change_id"]
    tid = transition_id(change_id)
    pair: dict[str, Any] = {}
    try:
        store = rl.ledger_store.open_store(rl.lr())
        head = store.get(rl.ledger_store.HEAD_KEY)
        prior = ingress._ledger_write(rl.recorded, store, head, tid, TRANSITION_CLASS)
        if prior is not None:
            return _duplicate(change_id, prior)
        # Observed from the declared ledger: never from the request. The registry generation is the one supplied value.
        ledger_head, generation = ledger_head_commit(store), supplied_registry_generation(admission)
        if ledger_head is None or generation is None:
            return refusal("CURRENT_BASE_UNOBSERVED", "BASE_IS_CURRENT",
                           "the writer reads the ledger ref commit (" + LEDGER_REF + " in the declared store) itself and the request "
                           "supplies admission.registry_generation as a non-negative integer; one of them is unavailable",
                           "after both are available; nothing was written", ledger_head=ledger_head, registry_generation=generation)
        found, unrecorded = [], []
        for rng in admission["push_ranges"]:
            row = ingress._ledger_write(rl.recorded, store, head, pa.transition_id(rng), pa.TRANSITION_CLASS)
            evidence = row.get("evidence") if isinstance(row, dict) else None
            if isinstance(evidence, dict) and pa.push_payload(evidence) is None and pa.range_key(evidence) == dict(rng):
                found.append(evidence)
            else:
                unrecorded.append(dict(rng))
        current_base = {"registry_generation": generation, "ledger_head": ledger_head}
        derived = ledger_issue_facts(rl.ledger_store.open_store(org.ledger_root()), successor, generation, admission["change_commits"])
        if "facts" not in derived:
            return derived
        run = evaluate(predecessor, successor, admission, found, current_base, hb_epoch, derived["facts"])
        wi = p1_readers()
        observed = {"current_base": current_base,
                    "current_base_sources": {"ledger_head": "OBSERVED_FROM_THE_DECLARED_LEDGER_REF",
                                             "registry_generation": "SUPPLIED_IN_REQUEST_NOT_OBSERVED_BY_THIS_CHECKOUT"},
                    "push_receipts_read_from_ledger": [r["result_sha256"] for r in found],
                    "unrecorded_push_ranges": unrecorded, "predecessor_request_digest": predecessor.get("request_digest"),
                    "predecessor_sha256": sha(predecessor), "admission": dict(admission), "chain": run["chain"],
                    "resolved_issue_facts_derived_from_the_ledger": {
                        "ledger_commit": derived["ledger_commit"], "check_receipts_read": derived["check_receipts_read"],
                        "issues": [{"issue_id": i["issue_id"], "source_receipt": i["source_receipt"]} for i in derived["issues"]
                                   if i["issue_id"] in {f["issue_id"] for f in derived["facts"]}]},
                    "not_supplied_by_this_operation": ["required-check ledger receipts", "sign-off receipts",
                                                       "base-state readback receipt"]}

        def append(transition_id_: str, cls: str, pred: str, succ: str, *, evidence: Mapping[str, Any],
                   authority_effect: str, hb_epoch: int) -> dict[str, Any]:  # noqa: ARG001 - authority_effect: the ledger's own NONE
            full = {**evidence, "observed": observed}
            repository_receipt = ingress._ledger_write(rl.append, transition_id_, cls, pred, succ, full, "NONE",
                                                       hb_epoch=hb_epoch, idempotent_on=())
            boundary = {"operation": OPERATION_ID, "profile_id": PROFILE_ID, "change_id": change_id,
                        "target_repository": successor["target_repository"], "transition_id": transition_id_,
                        "admit_disposition": evidence["disposition"], "admit_failure_code": evidence.get("failure_code"),
                        "evidence_sha256": sha(full)}
            organization_receipt = ingress._ledger_write(
                org.append, repository_receipt, "REPO_STATE_PROPAGATION", pred, succ, boundary, "NONE",
                hb_epoch=repository_receipt["hb_reference"]["epoch"], idempotent=True)
            pair.update(repository_receipt=repository_receipt, organization_receipt=organization_receipt)
            return pair

        wi.record(run["result"], successor, hb_epoch=hb_epoch, append=append)
    except (ValueError, SystemExit) as exc:
        return refusal("ORGANIZATION_LEDGER_APPEND_REFUSED", "SV_CHANGE_ADMIT_APPEND_COMPLETES_AT_BOTH_LEVELS",
                       "repair the refusal the ledger reported; the writer publishes only when both receipts exist",
                       "after the ledger refusal is repaired", detail=f"{type(exc).__name__}: {getattr(exc, 'code', None) or exc}")
    repository, organization = pair["repository_receipt"], pair["organization_receipt"]
    for row in (repository, organization):
        stored = _stored_epoch_refusal(row, hb_epoch)
        if stored is not None:
            stored["consequence_committed"] = "LOCAL_ONLY_NOT_PUBLISHED"  # the writer workflow pushes nothing after a refusal
            return stored
    store_mod = rl.ledger_store
    outcome = run["result"]
    return {
        "schema": RESULT_SCHEMA, "operation": OPERATION_ID, "disposition": "ALLOW", "transition_class": TRANSITION_CLASS,
        "appended": True, "change_id": change_id, "transition_id": tid, "target_repository": successor["target_repository"],
        "admit_disposition": outcome["disposition"], "admit_failure_code": outcome.get("failure_code"),
        "chain": [{"transition_class": s["transition_class"], "disposition": s["disposition"], "failure_code": s.get("failure_code")}
                  for s in run["chain"]],
        "repository_receipt_sha256": repository["receipt_sha256"], "organization_receipt_sha256": organization["receipt_sha256"],
        "organization_receipt_key": store_mod.receipt_key(organization["receipt_sha256"]),
        "repository_receipt_source_key": store_mod.source_key(repository["receipt_sha256"]),
        "evidence_sha256": organization["boundary_evidence"]["evidence_sha256"],
        "hb_epoch": repository["hb_reference"]["epoch"], "observed_current_base": observed["current_base"],
        "unrecorded_push_ranges": unrecorded, "consequence_committed": True, "authority_effect": "NONE",
    }


def admit_change_admit(predecessor: Any, successor: Any, admission: Any, *, hb_epoch: Any) -> dict[str, Any]:
    """The admission checks alone (request shape, owning ledger, NATIVE successor, supplied epoch and its tie, P1 pins).
    Reads no ledger and writes nothing, so the PR-facing check can run it on a committed request without appending."""
    bad = request_problem(predecessor, successor, admission) or _epoch_refusal(successor, hb_epoch)
    if bad is None and P1_PIN_FAILURE is not None:
        bad = refusal("P1_CONTRACT_PINS_UNVERIFIED", "VENDORED_P1_FILES_MATCH_THE_PINNED_CONTRACT_MANIFEST",
                      "re-vendor P1's files against data/sv-work-items/contract-pins.json (sha256 " + P1_MANIFEST_SHA256 + ")",
                      "after the vendored files match the pinned manifest; nothing was written", detail=P1_PIN_FAILURE)
    if bad is not None:
        return bad
    return {"schema": RESULT_SCHEMA, "operation": OPERATION_ID, "disposition": "ALLOW", "admitted": True, "writes": False,
            "change_id": successor["change_id"], "transition_id": transition_id(successor["change_id"]),
            "target_repository": successor["target_repository"], "hb_epoch": hb_epoch,
            "authority_effect": "NONE_ADMISSION_ONLY"}


def bind_change_admit(location: str, result: Mapping[str, Any]) -> dict[str, Any]:
    """Read the appended pair back from `location` (a fresh fetch of the ref): sealed, in place, linked, carrying the lifecycle
    outcome, and the only SV_CHANGE_ADMIT receipt on the repository chain for its change."""
    store_mod = ingress.repository_ledger.ledger_store
    store = store_mod.open_store(store_mod.parse_locator(location))
    org_sha, repo_sha = result.get("organization_receipt_sha256"), result.get("repository_receipt_sha256")
    org = store.get(store_mod.receipt_key(org_sha)) if isinstance(org_sha, str) else None
    repo = store.get(store_mod.source_key(repo_sha)) if isinstance(repo_sha, str) else None
    evidence = repo.get("evidence") if isinstance(repo, dict) else None
    change_id = (evidence.get("record") or {}).get("change_id") if isinstance(evidence, dict) else None
    try:
        repo_store = store_mod.open_store(location + ":repository-ledger/" + repo["repository"])
        same = [r for r in ingress.repository_ledger.chain(repo_store, repo_store.get(store_mod.HEAD_KEY))
                if r.get("transition_class") == TRANSITION_CLASS and r.get("transition_id") == transition_id(str(change_id))]
    except Exception:  # noqa: BLE001 - an unreadable chain is a failed check below
        same = []
    checks = {
        "organization_receipt_sealed": pa._self_verifies(org) and org.get("receipt_sha256") == org_sha,
        "repository_receipt_sealed_beside_it": pa._self_verifies(repo) and repo.get("receipt_sha256") == repo_sha,
        "organization_receipt_names_repository_receipt": isinstance(org, dict) and org.get("repo_receipt_sha256") == repo_sha,
        "operation_is_sv_change_admit": isinstance(org, dict) and (org.get("boundary_evidence") or {}).get("operation") == OPERATION_ID,
        "transition_class_is_sv_change_admit": isinstance(repo, dict) and repo.get("transition_class") == TRANSITION_CLASS,
        "evidence_carries_the_lifecycle_outcome": isinstance(evidence, dict) and evidence.get("disposition") == result.get("admit_disposition")
        and evidence.get("failure_code") == result.get("admit_failure_code"),
        "evidence_is_the_appended_evidence": isinstance(evidence, dict) and sha(evidence) == result.get("evidence_sha256"),
        "exactly_one_admit_for_the_change": len(same) == 1,
        "epoch_supplied_not_clock": all(isinstance(r, dict) and (r.get("hb_reference") or {}).get("derived_from_clock") is False
                                        for r in (org, repo)),
    }
    if not all(checks.values()):
        failed = sorted(k for k, v in checks.items() if not v)
        return {"schema": READBACK_SCHEMA, "disposition": "FAIL_CLOSED", "failure_code": "SV_CHANGE_ADMIT_READBACK_FAILED",
                "failed_predicate": failed[0].upper(), "required_evidence_or_repair": "the fresh fetch must hold the sealed pair: "
                + ", ".join(failed), "retry_entrypoint": "resident-runtime/sv_change_admit_append.py::bind_change_admit",
                "owning_existing_goal": OWNING_GOAL, "next_attempt": "after a fresh fetch of the published ref",
                "checks": checks, "readback_writes": False, "authority_effect": "NONE_READBACK_ONLY"}
    return {"schema": READBACK_SCHEMA, "disposition": "ALLOW", "location": location, "checks": checks, "change_id": change_id,
            "admit_disposition": evidence["disposition"], "admit_failure_code": evidence.get("failure_code"),
            "organization_receipt_sha256": org_sha, "repository_receipt_sha256": repo_sha,
            "readback_writes": False, "authority_effect": "NONE_READBACK_ONLY"}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("admit", help="the admission checks alone; reads no ledger and writes nothing")
    for flag in ("--predecessor", "--successor", "--admission"):
        m.add_argument(flag, type=Path, required=True)
    m.add_argument("--hb-epoch", required=True)
    m.add_argument("--out", type=Path, default=None)
    a = sub.add_parser("append")
    a.add_argument("--predecessor", type=Path, required=True)
    a.add_argument("--successor", type=Path, required=True)
    a.add_argument("--admission", type=Path, required=True)
    a.add_argument("--hb-epoch", required=True, help="supplied epoch, ASCII digits >= 32; never from a clock")
    a.add_argument("--out", type=Path, default=None)
    r = sub.add_parser("readback")
    r.add_argument("--location", required=True)
    r.add_argument("--result", type=Path, required=True)
    r.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    if args.cmd in ("append", "admit"):
        epoch = int(args.hb_epoch) if re.fullmatch(r"[0-9]+", args.hb_epoch or "") else args.hb_epoch
        try:
            parts = [_read_json(p) for p in (args.predecessor, args.successor, args.admission)]
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            out = refusal("SV_CHANGE_ADMIT_REQUEST_MALFORMED", "REQUEST_CARRIES_PREDECESSOR_SUCCESSOR_AND_ADMISSION",
                          "supply the three request parts as JSON objects", "after readable parts are supplied; nothing was written",
                          detail=f"{type(exc).__name__}: {exc}")
        else:
            out = (append_change_admit if args.cmd == "append" else admit_change_admit)(*parts, hb_epoch=epoch)
    else:
        out = bind_change_admit(args.location, _read_json(args.result))
    text = json.dumps(out, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(json.dumps(out, sort_keys=True))
    return 0 if out.get("disposition") == "ALLOW" else 1


if __name__ == "__main__":
    sys.exit(main())
