"""StegVerse-native work items: SV_ISSUE and SV_CHANGE (WORK_ITEMS_ARE_TASK_REGISTRY_NATIVE).

An SV_ISSUE is a Task Registry work record whose body is a six-field non-ALLOW
disposition, the invariant it violates and the receipt it was observed in. An
SV_CHANGE is the PR analogue: a content-addressed proposed transition bound to
its base (registry generation plus organization-ledger head), its declared
author session and the SV_ISSUEs it resolves. GitHub is a one-way projection.

Every lifecycle step is a transition declared in
data/sv-work-items/lifecycle-transitions.json. `transition()` evaluates it and
returns ALLOW/DENY/FAIL_CLOSED (six fields on every non-ALLOW); `record()`
hands the outcome, refusals included, to the existing repository emitter
(.stegverse/transition-ledger/emit.py::append) with the supplied epoch, whose
receipt the organization ledger aggregates. The supplied-epoch rule is
org-kernel/kernel.py::supplied_epoch_failure. Stdlib only, no clock, no
network, no environment read.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("sv_work_items_kernel", ROOT / "org-kernel/kernel.py")
kernel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kernel)
# sv-push-receipt.v1 (Labs#3267): the branch-writer session is DERIVED from the sealed push-receipt chain, never declared
_push_spec = importlib.util.spec_from_file_location("sv_work_items_push_receipt", ROOT / "resident-runtime/sv_push_receipt.py")
push_receipt = importlib.util.module_from_spec(_push_spec)
_push_spec.loader.exec_module(push_receipt)


def supplied_epoch_rule_sha256(source: str) -> str | None:
    """sha256 hex of the supplied_epoch_failure source segment in `source` (kernel.py text), else None."""
    if "def supplied_epoch_failure" not in source:
        return None
    a = source.index("def supplied_epoch_failure")
    b = source.find("\ndef ", a + 5)
    return hashlib.sha256(source[a:b if b >= 0 else len(source)].rstrip().encode("utf-8")).hexdigest()


KERNEL_RULE_SHA256 = supplied_epoch_rule_sha256((ROOT / "org-kernel/kernel.py").read_text(encoding="utf-8"))

ISSUE_SCHEMA = "stegverse.sv_issue.v1"
CHANGE_SCHEMA = "stegverse.sv_change.v1"
LIFECYCLE = json.loads((ROOT / "data/sv-work-items/lifecycle-transitions.json").read_text())
REQUIRED_CHECKS = json.loads((ROOT / "data/sv-work-items/required-checks.json").read_text())
STAGES_DIR = ROOT / "data/sv-work-items/stages"


def _gate_checks() -> dict[str, dict[str, Any]]:
    """STAGE_GATE_RECEIPT_DERIVES_NATIVE_ISSUE: the check each stage manifest declares for its gate (exit_gate_check), emitted
    by the NWI-S1 verifier like a row check. Its home is the stage manifest (stage_gate.py reads gates only from there),
    not the required-checks row: no SV_CHANGE requires a stage gate."""
    out: dict[str, dict[str, Any]] = {}
    for f in sorted(STAGES_DIR.glob("NWI-S*.json")):
        m = json.loads(f.read_text())
        c = m.get("exit_gate_check")
        if isinstance(c, dict):
            rel = f.relative_to(ROOT).as_posix()
            out[c["check_id"]] = {**c, "declared_in": {"repository": REQUIRED_CHECKS["row_file"]["repository"], "file": rel,
                                                       "stage_id": m["stage_id"],
                                                       "rule_id": m["stage_id"] + "#exit_gate_check." + c["check_id"]}}
    return out


GATE_CHECKS = _gate_checks()
CHECK_RECEIPT_INVARIANT = "REQUIRED_CHECK_RECEIPTS_ARE_S1_VERIFIER_OUTPUTS_APPENDED_BY_ORG_WRITER"
CHECK_RECEIPT_SCHEMA = "stegverse.sv_check_receipt.v1"
EXACT_HEAD_PREDICATE = "RECEIPT_CHANGE_DIGEST_EQUALS_HEAD"  # TVC#519: CHECK_SKIPPED_OR_UNOBSERVED, kept distinct by this predicate
CHECK_ALLOW_PREDICATE = "CHECK_RECEIPT_DISPOSITION_IS_ALLOW"  # TVC#519: a FAIL_CLOSED check receipt -> CHECK_SKIPPED_OR_UNOBSERVED
SIGNOFF_RECEIPT_SCHEMA = "stegverse.sv-change-signoff-receipt/v0.1"  # the sealed sign-off receipt TVC resolves (TVC#519)
FIXTURE_REF_MARK = "#fixture:"  # a fixture validation-receipt ref; counted only in fixture_mode
LEDGER_RECEIPT_REF = re.compile(r"^refs/stegverse/organization-ledger@(?P<commit>[0-9a-f]{40}):(?P<path>receipts/(?P<hex>[0-9a-f]{64})\.json)$")
OWNING_GOAL = "StegVerse-org/.github#163 (WORK_ITEMS_ARE_TASK_REGISTRY_NATIVE)"
HB_EPOCH_LEDGER_INVARIANT = "NATIVE_RECORD_HB_EPOCH_IS_BASE_LEDGER_HEAD_EPOCH"  # native-record application of the next
ADMISSION_HB_EPOCH_INVARIANT = "ADMISSION_HB_EPOCH_IS_THE_BOUND_LEDGER_HEAD_EPOCH"  # decided (JD-P4-3, partial)
HB_EPOCH_MISMATCH = "HB_EPOCH_MISMATCH"
EPOCH_BINDER_CHECK_ID = "supplied-epoch-binder-check"
BASE_STATE_READBACK_SCHEMA = "stegverse.sv-change-base-state-readback/v1"  # Labs#3266 RTC-SV-CHANGE-BASE-STATE-READBACK-014
HB_EPOCH_SOURCE_FIELD = "$.hb_reference.epoch"
# hb_epoch_source.receipt: ledger_store.receipt_key of the head receipt, relative to refs/stegverse/organization-ledger
READBACK_RECEIPT_PATH = re.compile(r"^receipts/[0-9a-f]{64}\.json$")
# The producer this reader is aligned to (Labs#3266 RTC-014): the hb_epoch slot and hb_epoch_source {ledger_head, receipt,
# field}, sealed on ALLOW and DENY HB_EPOCH_MISMATCH, present and null on every FAIL_CLOSED.
# SINGLE SOURCE for the #3266 pin: data/sv-work-items/invariants.json (ADMISSION_HB_EPOCH...readback_pin) and
# data/sv-work-items/stages/NWI-S0.json (exit_gate_check.hb_epoch.readback_pin) are synced from this constant by
# scripts/build_sv_native_fixtures.py (--check flags drift). Commit 5: Labs#3266 @7ad6d81f (always-emitted cross_checked;
# supersedes 9c9b9f51, whose cross-checked ALLOW carried no cross_checked key).
BASE_STATE_READBACK_PIN = {"repository": "StegVerse-Labs/.github", "pull_request": 3266,
                           "head": "7ad6d81fb6715b68b79dac6c3cbc2f484004ab2d",
                           "file": "resident-runtime/sv_change_base_state_readback.py",
                           "blob": "17ef44016411852dde7c142e3faaa803f4ee63bd",
                           "sha256": "c0365226ddc4fa2bf97ad2ebd1c089b2c8b51034df27783d99164e5f26d5c637",
                           "tests_file": "tests/test_sv_change_base_state_readback_component.py",
                           "tests_blob": "81cf78b9dff646859b3f017e83966ac25b8fc222"}


class _NotCrossChecked:
    """The caller supplied no epoch to cross-check (an optional flag left out): nothing to compare, proceed on the sealed epoch.
    Distinct from an explicit null, which is a supplied UNKNOWN."""
    def __repr__(self) -> str: return "HB_EPOCH_NOT_CROSS_CHECKED"


HB_EPOCH_NOT_CROSS_CHECKED = _NotCrossChecked()
NOT_CROSS_CHECKED_DETAIL = "HB_EPOCH_NOT_CROSS_CHECKED"  # the canonical marker's detail value
# Ruling ~17:15Z (NOT_CROSS_CHECKED_MARKER): the producer always emits cross_checked; a cross-checked ALLOW carries the
# supplied value under this key (confirmed at Labs#3266 @7ad6d81f: "supplied_hb_epoch", verbatim if JSON-scalar; also on
# DENY HB_EPOCH_MISMATCH and on a FAIL_CLOSED whose flag was given)
READBACK_SUPPLIED_FIELD = "supplied_hb_epoch"
# Explicit unobserved values: FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED (contract invariant: UNKNOWN is FAIL_CLOSED, never DENY)
SUPPLIED_EPOCH_UNOBSERVED_VALUES = (None, "", "null", "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED")
# sha256 of the source segment of org-kernel/kernel.py::supplied_epoch_failure (from "def supplied_epoch_failure" to the
# next top-level def, trailing whitespace stripped): the shared rule pinned as 726248a5 by SV-LLM/.github#46 and Labs#3266
SUPPLIED_EPOCH_RULE_SHA256 = "726248a585904b52cfe2eec1754e7ce582f67d6b501bd664bb7bee80bce9b7ef"
CHECK_DERIVED_ISSUE_INVARIANT = "CHECK_DERIVED_ISSUES_ARE_DERIVED_FROM_THE_LEDGERED_FAILING_RECEIPT"
CHECK_COMMAND_PREDICATE = "CHECK_HAS_OFFLINE_COMMAND"
LEDGER_HEAD_KEY = "HEAD.json"  # ledger_store.HEAD_KEY
ISSUE_DERIVATION_SESSION = "derivation:sv_work_items.derive_issue_from_check_receipt"
# Q-SV-NATIVE-BOOTSTRAP, decided by invariant (orchestrator): a stage gate is an admitted transition, so a failing gate
# receipt is a ledgered failing check receipt and derive_issue_from_check_receipt applies to it unchanged; no exception.
STAGE_GATE_ISSUE_INVARIANT = "STAGE_GATE_RECEIPT_DERIVES_NATIVE_ISSUE"
S1_VERIFIER_REF = "SV-LLM/.github#46"
RESOLVES_PREDICATE = "CHANGE_RESOLVES_CLAIMED_SV_ISSUES"
SELF_SOURCED_PREDICATE = "RESOLVING_CHANGE_DID_NOT_SOURCE_ITS_ISSUE"
ONE_ISSUE_PREDICATE = "ONE_RECEIPT_DERIVES_ONE_ISSUE"
RESOLVED_ONCE_PREDICATE = "RECEIPT_DERIVED_ISSUE_IS_RESOLVED_ONCE"
NATIVE_PREDICATE = "ADMITTED_RECORDS_ARE_NATIVE"
EPOCH_PREDICATE = "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH"
# Orchestrator decision UNKNOWN_IN_NATIVE_RECORD (2026-10-18): a NATIVE record field holding UNKNOWN_NOT_AUTHENTICALLY_OBSERVED
# was not observed, so it is FAIL_CLOSED (contract invariant: UNKNOWN is FAIL_CLOSED, never DENY); DENY stays only for
# values that were observed and are wrong (e.g. MIGRATION_FIELDS_ON_NATIVE_RECORD).
NATIVE_FIELDS_PREDICATE = "NATIVE_RECORD_FIELDS_ARE_OBSERVED"
# At admission /hb_epoch is excluded: an unobserved epoch has its own, earlier-decided FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED
ADMISSION_UNKNOWN_EXCLUDED = ("/hb_epoch",)
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
DISPOSITIONS = ("ALLOW", "DENY", "FAIL_CLOSED")
ISSUE_STATES = ("OPENED", "CLAIMED", "RESOLVED", "CLOSED_BY_INVARIANT", "SUPERSEDED")
CHANGE_STATES = ("PROPOSED", "VERIFIED", "ADMITTED", "DENIED", "FAIL_CLOSED", "APPLIED", "SUPERSEDED", "WITHDRAWN")
RESOLUTION_CLASSES = ("A", "B", "C", "D")
SOURCE_KINDS = ("ORGANIZATION_LEDGER_RECEIPT", "REPOSITORY_LEDGER_RECEIPT", "MIGRATION_EVIDENCE")
SURFACE_KINDS = ("workflow", "transition", "schema", "ledger_writer", "registry", "doc")
# RF-3: box-local paths are evidence, never a surface. Classified, kept distinct for identity, not admissible.
NON_REPOSITORY_EVIDENCE = "NON_REPOSITORY_EVIDENCE"
BOX_LOCAL_PREFIXES = ("patches/", "/workspace/", "/tmp/", "/home/", "/", "~/", "./", "../")


def is_box_local(path: str) -> bool:
    return any(path.startswith(p) for p in BOX_LOCAL_PREFIXES)
# Record mode. A MIGRATED_HISTORICAL record carries history that predates the
# native path; it may hold UNKNOWN only at the pointers listed below (and must
# list each one in unknown_fields), and it is never admissible. It becomes NATIVE
# only through a superseding record whose values are observed.
UNKNOWN = "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"
RECORD_MODES = ("NATIVE", "MIGRATED_HISTORICAL")
MIGRATED_UNKNOWN_ALLOWED = {
    "SV_ISSUE": ("/hb_epoch", "/resolution_class", "/owning_goal", "/disposition/owning_existing_goal", "/surface",
                 "/restatements/*/owning_existing_goal"),
    "SV_CHANGE": ("/hb_epoch", "/owning_goal", "/required_checks_ref/blob_sha"),
}
MIGRATION_FLAG_RESOLVES = "RESOLVES_NOT_RECORDED"
# FB-2: an SV_ISSUE surface taken from the lane table's Class column (sv_migration.derive_surface_with_class_column)
# because the retry_entrypoint resolved to UNKNOWN. Derived by a published rule, never observed.
MIGRATION_FLAG_SURFACE_FROM_CLASS = "SURFACE_DERIVED_FROM_CLASS_COLUMN"
ISSUE_MIGRATION_FLAGS = (MIGRATION_FLAG_SURFACE_FROM_CLASS,)
WRITER_EVIDENCE = ("DECLARED", "OBSERVED_COMMIT_TRAILER", UNKNOWN)
VALIDATION_EVIDENCE = ("LEDGER_RECEIPT", "OBSERVED_ARTIFACT")  # only LEDGER_RECEIPT counts toward VERIFIED
# Fields outside the full-request digest (TVC#527 pattern: everything else,
# including any field added later, is bound by default).
CHANGE_NON_REQUEST_FIELDS = frozenset({"_note", "request_digest", "lifecycle_state", "validation_receipts",
                                       "signoffs", "governance_decision_ref", "projection", "hb_epoch", "superseded_by"})
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
LEDGER_REF = "refs/stegverse/organization-ledger"
# CHANGE_BINDS_TARGET_REPOSITORY_LEDGER: base_ref.ledger_head is the head of the TARGET repository's own LEDGER_REF (each
# organization repository carries its own; StegVerse-Labs/.github's is not StegVerse-org/.github's)
LEDGER_BINDING_INVARIANT = "CHANGE_BINDS_TARGET_REPOSITORY_LEDGER"


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha(value: Any) -> str:
    raw = value if isinstance(value, (bytes, bytearray)) else canon(value)
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def seal(body: Mapping[str, Any], field: str) -> dict[str, Any]:
    clean = {k: v for k, v in body.items() if k != field}
    return {**clean, field: sha(clean)}


class Refusal(Exception):
    def __init__(self, disposition: str, code: str, predicate: str, repair: str, entry: str, nxt: str, **detail: Any):
        super().__init__(code)
        self.record = {"disposition": disposition, "failure_code": code, "failed_predicate": predicate,
                       "required_evidence_or_repair": repair, "retry_entrypoint": "resident-runtime/sv_work_items.py::" + entry,
                       "owning_existing_goal": OWNING_GOAL, "next_attempt": nxt, **detail}


def _fail(code, predicate, repair, entry, nxt="resubmit the corrected record; nothing was recorded as ALLOW", **d):
    return Refusal("FAIL_CLOSED", code, predicate, repair, entry, nxt, **d)


def _deny(code, predicate, repair, entry, nxt="propose a successor record bound to the observed state", **d):
    return Refusal("DENY", code, predicate, repair, entry, nxt, **d)


def epoch_check(hb_epoch: Any, entry: str) -> str:
    failure = kernel.supplied_epoch_failure(hb_epoch)
    if failure is not None:
        code, detail = failure
        raise _fail(code, EPOCH_PREDICATE, "supply hb_epoch as ASCII digits with value >= 32; it is never derived from a clock",
                    entry, "resubmit with the supplied epoch; nothing was written", detail=detail)
    return str(hb_epoch)


def _str(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _base_ok(base: Any) -> bool:
    return (isinstance(base, Mapping) and isinstance(base.get("registry_generation"), int)
            and not isinstance(base.get("registry_generation"), bool) and base["registry_generation"] >= 0
            and isinstance(base.get("ledger_head"), str) and GIT_SHA.match(base["ledger_head"]) is not None)


# ------------------------------------------------------------------ SV_ISSUE
def source_receipt_ref(src: Mapping[str, Any]) -> str:
    """The receipt (or migration evidence) an issue was observed in, as one normalized reference."""
    if src.get("kind") == "MIGRATION_EVIDENCE":
        return "migration:%s@%s" % (src.get("evidence_path"), src.get("evidence_sha256"))
    return "%s@%s" % (src.get("ledger_ref"), src.get("receipt_sha256"))


def issue_identity_inputs(rec: Mapping[str, Any]) -> dict[str, Any]:
    inv = rec.get("violated_invariant") or {}
    goal = rec.get("owning_goal")
    goal = goal.strip() if isinstance(goal, str) else goal
    out = {"violated_invariant": {k: inv.get(k) for k in ("repository", "file", "rule_id")},
           "failed_predicate": (rec.get("disposition") or {}).get("failed_predicate"),
           "owning_goal": goal,
           "surface": rec.get("surface"),
           "source_receipt_ref": source_receipt_ref(rec.get("source_receipt") or {})}
    if goal == UNKNOWN:  # FB-3: only here; records with a known goal keep their identity bytes unchanged
        out["source_locator"] = (rec.get("source_receipt") or {}).get("evidence_locator")
    return out


def issue_identity(rec: Mapping[str, Any]) -> str:
    """issue_id = "svi:" + sha256(canon({violated_invariant{repository,file,rule_id}, failed_predicate, owning_goal,
    surface, source_receipt_ref})). No free text: a reworded restatement of the same failure is the same issue.
    RF-1: owning_goal is identity, so one predicate under two goals stays two issues. FB-3: when owning_goal is
    UNKNOWN_NOT_AUTHENTICALLY_OBSERVED the goal cannot separate two entries of one evidence file, so the entry's
    position in the evidence (source_receipt.evidence_locator, required then) joins the inputs as source_locator.
    validate_issue_set refuses any record set that still repeats an issue_id (SV_ISSUE_ID_COLLISION)."""
    return "svi:" + sha(issue_identity_inputs(rec))[7:]


def sentinel_pointers(rec: Any, path: str = "") -> list[str]:
    """JSON pointers holding UNKNOWN (exact or embedded). /projection is a non-authority view and is not scanned;
    writer_session.evidence_class is an enum whose value happens to be the sentinel."""
    out: list[str] = []
    if isinstance(rec, Mapping):
        for k, v in rec.items():
            p = path + "/" + str(k)
            if p == "/projection" or (k == "evidence_class" and "/writer_session" in path):
                continue
            out += sentinel_pointers(v, p)
    elif isinstance(rec, list):
        for i, v in enumerate(rec):
            out += sentinel_pointers(v, path + "/" + str(i))
    elif isinstance(rec, str) and UNKNOWN in rec:
        out.append(path or "/")
    return out


def _pointer_match(pointer: str, allowed: str) -> bool:
    a, b = pointer.split("/"), allowed.split("/")
    return len(a) == len(b) and all(y == x or (y == "*" and x.isdigit()) for x, y in zip(a, b))


def native_unknown_refusal(pointers: Any, e: str) -> Refusal:
    """UNKNOWN_IN_NATIVE_RECORD is FAIL_CLOSED, never DENY (orchestrator decision): the field was not observed, so
    nothing about it can be judged wrong; the record is refused until the value is authentically observed."""
    return _fail("UNKNOWN_IN_NATIVE_RECORD", NATIVE_FIELDS_PREDICATE,
                 "authentically observe every field the NATIVE record holds as " + UNKNOWN + ", or record the history as "
                 "MIGRATED_HISTORICAL (UNKNOWN is FAIL_CLOSED, never DENY)", e,
                 "after the field is observed, propose a successor record carrying the observed value; nothing was recorded as ALLOW",
                 unknown=pointers)


def mode_check(rec: Mapping[str, Any], kind: str, base_field: str, e: str) -> str:
    mode = rec.get("record_mode")
    if mode not in RECORD_MODES:
        raise _deny("RECORD_MODE_INVALID", "RECORD_MODE_DECLARED", "record_mode NATIVE or MIGRATED_HISTORICAL", e)
    found = sentinel_pointers(rec)
    if mode == "NATIVE":
        if found:
            raise native_unknown_refusal(found, e)
        extra = [k for k in ("unknown_fields", "migration_provenance", "migration_flags") if k in rec]
        if extra:
            raise _deny("MIGRATION_FIELDS_ON_NATIVE_RECORD", "NATIVE_RECORD_FIELDS_ARE_OBSERVED",
                        "a NATIVE record carries no migration fields", e, fields=extra)
        return mode
    listed = rec.get("unknown_fields")
    if not isinstance(listed, list) or sorted(set(listed)) != sorted(found) or len(listed) != len(found):
        raise _deny("UNKNOWN_FIELDS_NOT_DECLARED", "MIGRATED_UNKNOWN_ONLY_WHERE_LISTED",
                    "unknown_fields lists exactly the pointers that hold " + UNKNOWN, e, found=sorted(found), listed=listed)
    bad = sorted(p for p in found if not any(_pointer_match(p, allowed) for allowed in MIGRATED_UNKNOWN_ALLOWED[kind]))
    if bad:
        raise _deny("UNKNOWN_FIELD_NOT_PERMITTED", "MIGRATED_UNKNOWN_ONLY_WHERE_LISTED",
                    "observe these fields; UNKNOWN is permitted only at " + ", ".join(MIGRATED_UNKNOWN_ALLOWED[kind]), e, fields=bad)
    mp = rec.get("migration_provenance")
    if not isinstance(mp, Mapping) or set(mp) != {"original_base_observed", "original_base_ref", "migrated_at_base"} \
            or not isinstance(mp["original_base_observed"], bool) or not _base_ok(mp["migrated_at_base"]) \
            or mp["migrated_at_base"] != rec.get(base_field) \
            or (mp["original_base_observed"] and not _base_ok(mp["original_base_ref"])) \
            or (not mp["original_base_observed"] and mp["original_base_ref"] is not None):
        raise _deny("MIGRATION_PROVENANCE_INVALID", "MIGRATED_RECORD_NAMES_ITS_BASES",
                    "migration_provenance{original_base_observed bool, original_base_ref base|null (null iff not observed), "
                    "migrated_at_base == " + base_field + "}", e)
    return mode


def _epoch_or_unknown(rec: Mapping[str, Any], e: str) -> None:
    if rec.get("hb_epoch") == UNKNOWN and rec.get("record_mode") == "MIGRATED_HISTORICAL":
        return  # listed and permitted by mode_check; such a record is never admissible
    epoch_check(rec.get("hb_epoch"), e)


def validate_issue(rec: Any, ledger_objects: Mapping[str, bytes] | None = None) -> dict[str, Any]:
    e = "validate_issue"
    if not isinstance(rec, Mapping) or rec.get("schema") != ISSUE_SCHEMA:
        raise _deny("SV_ISSUE_SCHEMA_MISMATCH", "RECORD_SCHEMA_IS_" + ISSUE_SCHEMA, "supply a stegverse.sv_issue.v1 record", e)
    d = rec.get("disposition")
    if not isinstance(d, Mapping) or d.get("disposition") not in ("DENY", "FAIL_CLOSED"):
        raise _deny("SV_ISSUE_BODY_NOT_NON_ALLOW", "ISSUE_BODY_IS_SIX_FIELD_NON_ALLOW",
                    "the issue body is a DENY or FAIL_CLOSED disposition", e)
    missing = [f for f in SIX_FIELDS if not _str(d.get(f))]
    if missing:
        raise _deny("SV_ISSUE_SIX_FIELDS_INCOMPLETE", "ISSUE_BODY_IS_SIX_FIELD_NON_ALLOW", "fill every one of the six fields", e, missing=missing)
    inv = rec.get("violated_invariant")
    if not isinstance(inv, Mapping) or not _str(inv.get("rule_id")) or not _str(inv.get("file")):
        raise _deny("SV_ISSUE_INVARIANT_UNNAMED", "ISSUE_NAMES_VIOLATED_INVARIANT",
                    "name the violated invariant by rule_id and file (blob_sha when the file is in a repository)", e)
    src = rec.get("source_receipt")
    if not isinstance(src, Mapping) or src.get("kind") not in SOURCE_KINDS:
        raise _deny("SV_ISSUE_SOURCE_RECEIPT_ABSENT", "ISSUE_NAMES_SOURCE_RECEIPT", "name the receipt the failure was observed in", e)
    if src["kind"] == "MIGRATION_EVIDENCE":
        if not _str(src.get("evidence_path")) or not isinstance(src.get("evidence_sha256"), str) or not DIGEST.match(src["evidence_sha256"]):
            raise _deny("SV_ISSUE_SOURCE_RECEIPT_ABSENT", "ISSUE_NAMES_SOURCE_RECEIPT",
                        "migration evidence names its path and sha256; the OPEN receipt becomes its ledger receipt", e)
    elif not isinstance(src.get("receipt_sha256"), str) or not DIGEST.match(src["receipt_sha256"]) or not str(src.get("ledger_ref", "")).startswith("refs/"):
        raise _deny("SV_ISSUE_SOURCE_RECEIPT_ABSENT", "ISSUE_NAMES_SOURCE_RECEIPT", "a ledger source names ledger_ref and receipt_sha256", e)
    mode_check(rec, "SV_ISSUE", "observed_base", e)
    if rec.get("resolution_class") not in RESOLUTION_CLASSES + (UNKNOWN,):
        raise _deny("SV_ISSUE_CLASS_INVALID", "ISSUE_RESOLUTION_CLASS_IS_A_B_C_OR_D", "classify the issue A, B, C or D", e)
    sf = rec.get("surface")
    kinds = SURFACE_KINDS + (NON_REPOSITORY_EVIDENCE,)
    if sf != UNKNOWN and not (isinstance(sf, Mapping) and set(sf) == {"kind", "path"} and sf.get("kind") in kinds and _str(sf.get("path"))):
        raise _deny("SV_ISSUE_SURFACE_INVALID", "ISSUE_NAMES_SURFACE", "surface{kind in " + "/".join(kinds) + ", path}", e)
    if isinstance(sf, Mapping) and sf["kind"] != NON_REPOSITORY_EVIDENCE and is_box_local(sf["path"]):
        raise _deny("SURFACE_NOT_IN_REPOSITORY_TREE", "SURFACE_IS_A_REPOSITORY_PATH",
                    "a box-local path is NON_REPOSITORY_EVIDENCE, not a surface; name the repository path it concerns", e, path=sf["path"])
    if isinstance(sf, Mapping) and sf["kind"] == NON_REPOSITORY_EVIDENCE and rec.get("record_mode") == "NATIVE":
        raise _deny("SURFACE_NOT_IN_REPOSITORY_TREE", "SURFACE_IS_A_REPOSITORY_PATH",
                    "a NATIVE issue names a repository path as its surface; non-repository evidence is not admissible as a surface", e,
                    path=sf["path"])
    if not _str(rec.get("owning_goal")):
        raise _deny("SV_ISSUE_GOAL_ABSENT", "ISSUE_NAMES_OWNING_GOAL", "name the owning goal", e)
    if rec["owning_goal"].strip() == UNKNOWN and not _str(src.get("evidence_locator")):
        raise _fail("SV_ISSUE_UNKNOWN_GOAL_UNLOCATED", "ISSUE_ID_IS_UNIQUE_IN_RECORD_SET",
                    "an issue whose owning_goal is UNKNOWN names source_receipt.evidence_locator (the entry's position in the "
                    "evidence, e.g. L586); issue_id then hashes it as source_locator", e)
    flags = rec.get("migration_flags")
    if flags is not None and (not isinstance(flags, list) or len(set(flags)) != len(flags)
                              or any(f not in ISSUE_MIGRATION_FLAGS for f in flags)
                              or (MIGRATION_FLAG_SURFACE_FROM_CLASS in flags and not isinstance(rec.get("surface"), Mapping))):
        raise _deny("MIGRATION_FLAG_MISMATCH", "MIGRATED_GAPS_ARE_FLAGGED",
                    "migration_flags lists only " + ", ".join(ISSUE_MIGRATION_FLAGS) + " (once each); "
                    + MIGRATION_FLAG_SURFACE_FROM_CLASS + " only with a resolved surface", e, flags=flags)
    for r in rec.get("restatements") or []:
        if not isinstance(r, Mapping) or any(not _str(r.get(f)) for f in SIX_FIELDS):
            raise _deny("SV_ISSUE_RESTATEMENT_INVALID", "ISSUE_BODY_IS_SIX_FIELD_NON_ALLOW", "each restatement is a six-field body", e)
    if rec.get("lifecycle_state") not in ISSUE_STATES:
        raise _deny("SV_ISSUE_STATE_INVALID", "LIFECYCLE_STATE_DECLARED", "one of " + ", ".join(ISSUE_STATES), e)
    if not _base_ok(rec.get("observed_base")):
        raise _deny("SV_ISSUE_BASE_UNBOUND", "BASE_BOUND_TO_REGISTRY_GENERATION_AND_LEDGER_HEAD",
                    "observed_base{registry_generation int, ledger_head 40-hex}", e)
    if not _str(rec.get("opened_by_session")):  # schema-required attribution label (schemas/sv-issue.v1.schema.json)
        raise _deny("SV_ISSUE_SCHEMA_MISMATCH", "RECORD_SCHEMA_IS_" + ISSUE_SCHEMA, "opened_by_session is a non-empty string", e,
                    field="opened_by_session")
    if rec.get("issue_id") != issue_identity(rec):
        raise _deny("SV_ISSUE_IDENTITY_MISMATCH", "ISSUE_IDENTITY_IS_CONTENT_ADDRESSED", "issue_id = issue_identity(record)", e,
                    expected=issue_identity(rec))
    _epoch_or_unknown(rec, e)
    if rec.get("issue_sha256") != sha({k: v for k, v in rec.items() if k != "issue_sha256"}):
        raise _fail("SV_ISSUE_DIGEST_MISMATCH", "RECORD_DIGEST_VERIFIES", "reseal the record (issue_sha256)", e)
    if ledger_objects is not None and rec.get("record_mode") == "NATIVE":
        verify_native_hb_epoch(rec, ledger_objects)
    return dict(rec)


def source_receipt_collision(many: Mapping[str, Any], entry: str) -> Refusal:
    """ONE_RECEIPT_DERIVES_ONE_ISSUE (STAGE_GATE_RECEIPT_DERIVES_NATIVE_ISSUE (b)): the derivation is deterministic, so one
    ledgered receipt yields exactly one issue_id; two different issues naming one receipt mean one was not derived by
    derive_issue_from_check_receipt. FAIL_CLOSED like SV_ISSUE_ID_COLLISION: the set cannot say which one is the receipt's."""
    return _fail("SV_ISSUE_SOURCE_RECEIPT_COLLISION", ONE_ISSUE_PREDICATE,
                 "keep only the issue derive_issue_from_check_receipt yields from that receipt's ledger bytes; drop the other", entry,
                 "rebuild the record set from the ledgered receipts and resubmit it whole; nothing was accepted", issues_by_receipt=dict(many))


def validate_issue_set(records: Iterable[Any]) -> list[dict[str, Any]]:
    """FB-3: validate every record, then refuse the set if any issue_id appears twice. A duplicate is never merged
    here: restatements of one issue are merged before storage (sv_migration.merge_issues), so a stored set that still
    repeats an id holds two different failures under one identity."""
    e = "validate_issue_set"
    out = [validate_issue(r) for r in records]
    seen: dict[str, int] = {}
    dup: dict[str, list[int]] = {}
    for i, r in enumerate(out):
        if r["issue_id"] in seen:
            dup.setdefault(r["issue_id"], [seen[r["issue_id"]]]).append(i)
        else:
            seen[r["issue_id"]] = i
    by_receipt: dict[str, set[str]] = {}
    for r in out:
        src = r.get("source_receipt") or {}
        if src.get("kind") == "ORGANIZATION_LEDGER_RECEIPT":
            by_receipt.setdefault(src["receipt_sha256"], set()).add(r["issue_id"])
    many = {k: sorted(v) for k, v in sorted(by_receipt.items()) if len(v) > 1}
    if many:
        raise source_receipt_collision(many, e)
    if dup:
        raise _fail("SV_ISSUE_ID_COLLISION", "ISSUE_ID_IS_UNIQUE_IN_RECORD_SET",
                    "give every entry its own identity inputs (an UNKNOWN-goal issue names source_receipt.evidence_locator), "
                    "or merge true restatements into one record (restatements[]) before storing the set", e,
                    "rebuild the record set and resubmit it whole; no record of this set was accepted",
                    collisions={k: v for k, v in sorted(dup.items())})
    return out


# ------------------------------------------------------------------ SV_CHANGE
def change_digest(rec: Mapping[str, Any]) -> str:
    """head.change_digest = "sha256:" + sha256 over the same canonical bytes as change_id
    (canon(change_identity_input(rec))), so change_digest[7:] == change_id[4:]. Validation receipts bind it."""
    return "sha256:" + hashlib.sha256(canon(change_identity_input(rec))).hexdigest()


CANONICAL_SERIALIZATION = {"format": "JSON", "sort_keys": True, "separators": [",", ":"], "encoding": "UTF-8",
                           "ensure_ascii": False, "trailing_newline": False}  # == canon()


def change_identity_input(rec: Mapping[str, Any]) -> dict[str, Any]:
    """The hashed form: {target_repository, base_ref (registry_generation and ledger_head kept, as recorded),
    content: [{path, blob_digest (null when deleted), deleted}] sorted by path}."""
    base = rec.get("base_ref")
    if not _base_ok(base):
        raise _deny("SV_CHANGE_BASE_UNBOUND", "BASE_BOUND_TO_REGISTRY_GENERATION_AND_LEDGER_HEAD",
                    "base_ref keeps registry_generation (int) and ledger_head (40-hex); change_id hashes both", "change_identity")
    content = []
    for c in rec.get("content") or []:
        if isinstance(c, Mapping):
            deleted = c.get("deleted", False) is True
            content.append({"path": c.get("path"), "blob_digest": None if deleted else c.get("blob_digest"), "deleted": deleted})
    return {"target_repository": rec.get("target_repository"), "base_ref": dict(base),
            "content": sorted(content, key=lambda c: str(c["path"]))}


def change_identity(rec: Mapping[str, Any]) -> str:
    """change_id = "svc:" + hex sha256(canon(change_identity_input(rec))). canon() is the pinned serialization
    (CANONICAL_SERIALIZATION). Writer evidence is not identity: the same content on the same base is one change."""
    return "svc:" + hashlib.sha256(canon(change_identity_input(rec))).hexdigest()


def request_digest(rec: Mapping[str, Any]) -> str:
    return sha({k: v for k, v in rec.items() if k not in CHANGE_NON_REQUEST_FIELDS})


def validate_change(rec: Any, ledger_objects: Mapping[str, bytes] | None = None) -> dict[str, Any]:
    """Without ledger_objects the behavior is unchanged (UNKNOWN in a NATIVE record is DENY). With the bytes a read of
    refs/stegverse/organization-ledger returned, a NATIVE record's hb_epoch is also bound to the base ledger head
    (NATIVE_RECORD_HB_EPOCH_IS_BASE_LEDGER_HEAD_EPOCH, decided with JD-P4-3, partial)."""
    e = "validate_change"
    if not isinstance(rec, Mapping) or rec.get("schema") != CHANGE_SCHEMA:
        raise _deny("SV_CHANGE_SCHEMA_MISMATCH", "RECORD_SCHEMA_IS_" + CHANGE_SCHEMA, "supply a stegverse.sv_change.v1 record", e)
    if not _str(rec.get("declared_session")):  # a schema-required attribution label; it grants and refuses nothing
        raise _deny("SV_CHANGE_SCHEMA_MISMATCH", "RECORD_SCHEMA_IS_" + CHANGE_SCHEMA,
                    "declared_session is a non-empty string (schemas/sv-change.v1.schema.json); admission never reads it: the "
                    "branch writer is derived from the sv-push-receipt chain (BRANCH_WRITER_IS_BRANCH_OWNER)", e, field="declared_session")
    mode = mode_check(rec, "SV_CHANGE", "base_ref", e)
    if not _base_ok(rec.get("base_ref")):
        raise _deny("SV_CHANGE_BASE_UNBOUND", "BASE_BOUND_TO_REGISTRY_GENERATION_AND_LEDGER_HEAD",
                    "base_ref{registry_generation int, ledger_head 40-hex}", e)
    if not _str(rec.get("target_repository")) or rec.get("change_id") != change_identity(rec):
        raise _deny("SV_CHANGE_IDENTITY_INVALID", "CHANGE_IDENTITY_IS_CONTENT_ADDRESSED",
                    "change_id = change_identity(record) over {target_repository, base_ref, content}", e, expected=change_identity(rec))
    res = rec.get("resolves")
    if not isinstance(res, list) or any(not (isinstance(i, str) and re.match(r"^svi:[0-9a-f]{64}$", i)) for i in res):
        raise _deny("SV_CHANGE_RESOLVES_INVALID", "CHANGE_RESOLVES_CLAIMED_SV_ISSUES", "resolves lists svi: ids", e)
    if not res and mode == "NATIVE":
        raise _deny("SV_CHANGE_RESOLVES_NOTHING", "CHANGE_RESOLVES_CLAIMED_SV_ISSUES", "resolves lists at least one svi: id", e)
    flags = rec.get("migration_flags") or []
    if mode == "MIGRATED_HISTORICAL" and (MIGRATION_FLAG_RESOLVES in flags) != (not res):
        raise _deny("MIGRATION_FLAG_MISMATCH", "MIGRATED_GAPS_ARE_FLAGGED",
                    "migration_flags carries " + MIGRATION_FLAG_RESOLVES + " exactly when resolves is empty", e)
    if not _str(rec.get("owning_goal")):
        raise _deny("SV_CHANGE_GOAL_ABSENT", "CHANGE_NAMES_OWNING_GOAL", "name the owning goal", e)
    if not _base_ok(rec.get("base_ref")):
        raise _deny("SV_CHANGE_BASE_UNBOUND", "BASE_BOUND_TO_REGISTRY_GENERATION_AND_LEDGER_HEAD",
                    "base_ref{registry_generation int, ledger_head 40-hex}", e)
    content = rec.get("content")
    if not isinstance(content, list) or not content:
        raise _deny("SV_CHANGE_CONTENT_EMPTY", "CHANGE_DIGEST_COVERS_CONTENT", "content lists every changed path", e)
    for c in content:
        if not isinstance(c, Mapping) or set(c) != {"path", "blob_digest", "deleted", "writer_session"}:
            raise _deny("SV_CHANGE_CONTENT_ENTRY_INVALID", "CHANGE_DIGEST_COVERS_CONTENT",
                        "each entry has exactly path, blob_digest, deleted and writer_session (TVC#519: deleted is required)", e,
                        keys=sorted(c) if isinstance(c, Mapping) else None)
        deleted = c["deleted"]
        blob_ok = isinstance(c, Mapping) and (c.get("blob_digest") is None if deleted is True
                                              else isinstance(c.get("blob_digest"), str) and DIGEST.match(c["blob_digest"]) is not None)
        if not isinstance(c, Mapping) or not _str(c.get("path")) or deleted not in (True, False) or not blob_ok \
                or not _writer_ok(c.get("writer_session")):
            raise _deny("SV_CHANGE_CONTENT_ENTRY_INVALID", "CHANGE_DIGEST_COVERS_CONTENT",
                        "each entry has path, writer_session{session|null, evidence_class}, deleted bool, and blob_digest "
                        "sha256 (null exactly when deleted)", e)
    if len({c["path"] for c in content}) != len(content):
        raise _deny("SV_CHANGE_CONTENT_DUPLICATE_PATH", "CHANGE_DIGEST_COVERS_CONTENT", "one entry per path", e)
    if not isinstance(rec.get("head"), Mapping) or set(rec["head"]) != {"change_digest"}:
        raise _deny("SV_CHANGE_HEAD_INVALID", "CHANGE_DIGEST_COVERS_CONTENT", "head is exactly {change_digest}", e)
    if rec["head"]["change_digest"] != change_digest(rec):
        raise _fail("SV_CHANGE_DIGEST_MISMATCH", "CHANGE_DIGEST_COVERS_CONTENT",
                    "head.change_digest = change_digest(record) (same canonical bytes as change_id)", e, expected=change_digest(rec))
    tp = rec.get("touched_paths")
    if not isinstance(tp, list) or len(set(tp)) != len(tp) or set(tp) != {c["path"] for c in content}:
        raise _deny("SV_CHANGE_TOUCHED_PATHS_MISMATCH", "TOUCHED_PATHS_EQUAL_CONTENT_PATHS", "touched_paths equals the content paths", e)
    if rec.get("lifecycle_state") not in CHANGE_STATES:
        raise _deny("SV_CHANGE_STATE_INVALID", "LIFECYCLE_STATE_DECLARED", "one of " + ", ".join(CHANGE_STATES), e)
    ref = rec.get("required_checks_ref")
    if not isinstance(ref, Mapping) or not all(_str(ref.get(k)) for k in ("file", "blob_sha", "row_id")):
        raise _fail("REQUIRED_CHECKS_ROW_ABSENT", "REQUIRED_CHECKS_ROW_RESOLVES", "required_checks_ref{file, blob_sha, row_id}", e)
    if not GIT_SHA.match(ref["blob_sha"]) and not (mode == "MIGRATED_HISTORICAL" and ref["blob_sha"] == UNKNOWN):
        raise _fail("REQUIRED_CHECKS_ROW_NOT_PINNED", "REQUIRED_CHECKS_ROW_RESOLVES",
                    "required_checks_ref.blob_sha is the 40-hex git blob of the row file (UNKNOWN only in MIGRATED_HISTORICAL)", e,
                    blob_sha=ref["blob_sha"])
    for v in rec.get("validation_receipts") or []:
        if not isinstance(v, Mapping) or v.get("disposition") not in DISPOSITIONS or not _str(v.get("check_id")) \
                or v.get("evidence_class") not in VALIDATION_EVIDENCE or not _str(v.get("ref")) \
                or not (isinstance(v.get("digest"), str) and DIGEST.match(v["digest"])) \
                or (v["evidence_class"] == "LEDGER_RECEIPT" and not v["ref"].startswith("refs/")):
            raise _deny("VALIDATION_RECEIPT_INVALID", "VALIDATION_RECEIPT_IS_DISPOSITION",
                        "{check_id, disposition, change_digest, evidence_class LEDGER_RECEIPT (ref refs/...) | OBSERVED_ARTIFACT, ref, digest sha256}", e)
        if v["check_id"] not in declared_check_ids():
            raise check_id_undeclared(v["check_id"], e)
    if rec.get("request_digest") != request_digest(rec):
        raise _fail("REQUEST_DIGEST_MISMATCH", "AUTHORIZATION_BINDS_FULL_REQUEST", "request_digest = request_digest(record)", e,
                    expected=request_digest(rec))
    native_epoch_type_check(rec, e)
    _epoch_or_unknown(rec, e)
    if ledger_objects is not None and rec.get("record_mode") == "NATIVE":
        verify_native_hb_epoch(rec, ledger_objects)
    return dict(rec)


def native_epoch_type_check(rec: Mapping[str, Any], e: str) -> None:
    """NATIVE_RECORD_HB_EPOCH_IS_A_STRING (commit 4; orchestrator 16:55Z): a NATIVE SV_CHANGE's hb_epoch is a string
    (schemas/sv-change.v1.schema.json 6b43b6ec). An observed value of another JSON type (an int such as 1024, a float, a
    bool, an array or object) is malformed and is DENY HB_EPOCH_MISMATCH, as admission's supplied-epoch rule already gives
    for bools and non-digits (verify_admission_hb_epoch). Absent / null stays unobserved (FAIL_CLOSED, unchanged).
    NATIVE_RECORD_HB_EPOCH_IS_WELL_FORMED (commit 5): a string that fails 726248a5 ('abc', '+33', '31', ' 44') is DENY
    HB_EPOCH_MISMATCH, as in admission; "" and "null" are FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED, as in admission."""
    if rec.get("record_mode") != "NATIVE" or "hb_epoch" not in rec or rec["hb_epoch"] is None:
        return
    v = rec["hb_epoch"]
    if isinstance(v, str):
        # commit 5 (open item closed): a malformed epoch STRING is DENY HB_EPOCH_MISMATCH here too, as admission gives
        # (verify_admission_hb_epoch: 726248a5 failures other than the unobserved values are DENY); "", "null" and the
        # UNKNOWN sentinel stay unobserved (FAIL_CLOSED, never DENY), checked first, as in admission
        if v == UNKNOWN:
            return  # mode_check: UNKNOWN_IN_NATIVE_RECORD (FAIL_CLOSED)
        if v in SUPPLIED_EPOCH_UNOBSERVED_VALUES:
            raise _fail("HB_EPOCH_SOURCE_UNOBSERVED", ADMISSION_HB_EPOCH_INVARIANT,
                        "a NATIVE SV_CHANGE carries the observed base ledger head epoch as ASCII digits", e,
                        "after the epoch is observed at base_ref.ledger_head; nothing was recorded", hb_epoch=v,
                        rule="UNKNOWN_IS_FAIL_CLOSED_NEVER_DENY")
        bad = kernel.supplied_epoch_failure(v)
        if bad is None:
            return
        raise _deny(HB_EPOCH_MISMATCH, ADMISSION_HB_EPOCH_INVARIANT,
                    "a NATIVE SV_CHANGE carries hb_epoch as ASCII digits >= 32 in a JSON string (the base ledger head's epoch)",
                    e, "propose a successor SV_CHANGE whose hb_epoch is the epoch string; nothing was recorded",
                    hb_epoch=v, supplied_epoch_rule=bad[0] + ": " + bad[1], rule="NATIVE_RECORD_HB_EPOCH_IS_WELL_FORMED")
    raise _deny(HB_EPOCH_MISMATCH, ADMISSION_HB_EPOCH_INVARIANT,
                "a NATIVE SV_CHANGE carries hb_epoch as ASCII digits in a JSON string (the base ledger head's epoch, e.g. \"469411750\")",
                e, "propose a successor SV_CHANGE whose hb_epoch is the epoch string; nothing was recorded",
                hb_epoch_json_type=type(rec["hb_epoch"]).__name__, rule="NATIVE_RECORD_HB_EPOCH_IS_A_STRING")


def _writer_ok(w: Any) -> bool:
    if not isinstance(w, Mapping) or set(w) != {"session", "evidence_class"} or w.get("evidence_class") not in WRITER_EVIDENCE:
        return False
    return w["session"] is None if w["evidence_class"] == UNKNOWN else _str(w["session"])


# ------------------------------------------------------------------ branch writer from the sv-push-receipt chain
# BRANCH_WRITER_IS_BRANCH_OWNER (Lane C alignment, TVC#531 v2 p_writer; Labs#3267 producer): the authoring session is
# DERIVED as the pusher_session of the sealed sv-push-receipt.v1 at the change's head. PR_AUTHOR_SESSION_DECLARED is
# retired: no PR body line, commit trailer or record field (declared_session) is read for authority. A per-path
# content[*].writer_session can only refuse (a named session other than the derived writer or a receipted co-author).
WRITER_PREDICATE = "BRANCH_WRITER_IS_BRANCH_OWNER"
PUSH_RECEIPT_RETRY = ("resident-runtime/sv_push_receipt.py::emit at push time (read_ref before the push, emit after it), then the "
                      "org-ledger writer's append of the receipt to refs/stegverse/organization-ledger (StegVerse-Labs/.github#3255)")
_OID40 = re.compile(r"^[0-9a-f]{40}$")


def _writer_gap(gap: str, entry: str, code: str = "BRANCH_WRITER_UNOBSERVED", **d: Any) -> Refusal:
    """Six-field FAIL_CLOSED: the branch writer is not observed (a gap in the push-receipt chain). Never DENY."""
    return _fail(code, WRITER_PREDICATE,
                 "a contiguous chain of sealed sv-push-receipt.v1 receipts for the change's target repository and one branch ref, "
                 "from change_commits.base_commit to change_commits.head_commit, every pushed commit covered; the authoring "
                 "session is the pusher_session of the receipt sealed at the head", entry,
                 "re-run admission after the missing push receipt is emitted and appended to the organization ledger; nothing "
                 "was admitted", retry_entrypoint=PUSH_RECEIPT_RETRY, writer_evidence=gap, **d)


def derive_branch_writer(push_receipts: Any, change_commits: Any, *, target_repository: Any, change_id: Any = None,
                         entry: str = "derive_branch_writer") -> dict[str, Any]:
    """{session, ref, pushers, chain, base_commit, head_commit} from the push-receipt chain, or a six-field FAIL_CLOSED Refusal:
      BRANCH_WRITER_UNOBSERVED    no receipts or commits, a receipt that is malformed or unsealed, another repository or
                                  change, more than one ref, a fork, a receipt outside the chain, or no receipt at base_commit;
      WRITER_EVIDENCE_NOT_AT_HEAD the contiguous chain from base_commit ends at a commit other than head_commit.
    Pure over the supplied receipts (read from the organization ledger by the caller); no git, no clock, no network."""
    cc = change_commits if isinstance(change_commits, Mapping) else {}
    base, head = cc.get("base_commit"), cc.get("head_commit")
    if not (isinstance(base, str) and _OID40.match(base) and isinstance(head, str) and _OID40.match(head)):
        raise _writer_gap("CHANGE_COMMITS_UNOBSERVED", entry, change_commits=dict(cc) or None)
    rs = list(push_receipts) if isinstance(push_receipts, (list, tuple)) else None
    if not rs:
        raise _writer_gap("NO_PUSH_RECEIPT", entry)
    for n, r in enumerate(rs):
        why = push_receipt.receipt_problem(r)
        if why is not None:
            raise _writer_gap("PUSH_RECEIPT_INVALID", entry, receipt_index=n, receipt_problem=why)
    other = sorted({r["repository"] for r in rs} - {target_repository})
    if other:
        raise _writer_gap("PUSH_RECEIPT_OTHER_REPOSITORY", entry, repositories=other, target_repository=target_repository)
    refs = sorted({r["ref"] for r in rs})
    if len(refs) != 1:
        raise _writer_gap("PUSH_RECEIPT_REFS_DIFFER", entry, refs=refs)
    wrong_change = sorted({r["change_id"] for r in rs if "change_id" in r} - {change_id})
    if wrong_change:
        raise _writer_gap("PUSH_RECEIPT_OTHER_CHANGE", entry, change_ids=wrong_change, change_id=change_id)
    by_old: dict[str, dict] = {}
    for r in rs:
        if r["old_sha"] in by_old:
            raise _writer_gap("PUSH_RECEIPT_CHAIN_FORKS", entry, old_sha=r["old_sha"])
        by_old[r["old_sha"]] = r
    if base not in by_old:
        raise _writer_gap("PUSH_RECEIPT_CHAIN_NOT_AT_BASE", entry, base_commit=base, old_shas=sorted(by_old))
    chain, at = [], base
    while at in by_old and len(chain) < len(rs):
        chain.append(by_old[at]); at = by_old[at]["new_sha"]
    if len(chain) != len(rs):
        raise _writer_gap("PUSH_RECEIPT_CHAIN_GAP", entry, chained=len(chain), supplied=len(rs),
                          unchained=sorted(r["result_sha256"] for r in rs if r not in chain))
    if at != head:
        raise _writer_gap("WRITER_EVIDENCE_NOT_AT_HEAD", entry, "WRITER_EVIDENCE_NOT_AT_HEAD", chain_tip=at, head_commit=head)
    return {"session": chain[-1]["pusher_session"], "ref": refs[0], "pushers": sorted({r["pusher_session"] for r in chain}),
            "chain": [r["result_sha256"] for r in chain], "base_commit": base, "head_commit": head}


def verify_branch_writer(obs: Mapping[str, Any], entry: str = "evaluate_admission") -> dict[str, Any]:
    """BRANCH_WRITER_IS_BRANCH_OWNER over admission_inputs(): every pusher in the chain and every named per-path writer is
    the derived session or a receipted co-author grant, else FAIL_CLOSED BRANCH_HAS_FOREIGN_WRITER."""
    bw = derive_branch_writer(obs.get("push_receipts"), obs.get("change_commits"), target_repository=obs.get("target_repository"),
                              change_id=obs.get("change_id"), entry=entry)
    allowed = {bw["session"]} | set(obs.get("co_author_grants") or [])
    foreign = sorted((set(bw["pushers"]) | set(obs.get("writer_sessions") or [])) - allowed)
    if foreign:
        raise _fail("BRANCH_HAS_FOREIGN_WRITER", WRITER_PREDICATE,
                    "a superseding SV_CHANGE by the owner that carries the foreign content openly, or a receipted co-author grant", entry,
                    derived_session=bw["session"], foreign_writers=foreign)
    return bw


def _derived_writer_or_none(obs: Mapping[str, Any]) -> str | None:
    try:
        return derive_branch_writer(obs.get("push_receipts"), obs.get("change_commits"), target_repository=obs.get("target_repository"),
                                    change_id=obs.get("change_id"))["session"]
    except Refusal:
        return None


# ------------------------------------------------------------------ surfaces and admission inputs
LEDGER_WRITER_PATHS = ("resident-runtime/aggregate_repo_transition.py", "resident-runtime/ledger_store.py",
                       ".stegverse/transition-ledger/emit.py", "org-kernel/kernel.py", "org-kernel/organization-ledger/",
                       "resident-runtime/propagate_repository_receipts.py", "resident-runtime/federation_cycle.py",
                       ".github/workflows/organization-ledger-transition.yml")


def surface_kind(path: str) -> str:
    """Typed surface for coverage (Q-SCENARIO-GENERALIZATION rule S1)."""
    if any(path == p or (p.endswith("/") and path.startswith(p)) for p in LEDGER_WRITER_PATHS):
        return "ledger_writer"
    if path.startswith(".github/workflows/"):
        return "workflow"
    if path.startswith("schemas/") or path.endswith(".schema.json"):
        return "schema"
    if path == "data/canonical-task-registry.json" or path.startswith("data/canonical-task-records/"):
        return "registry"
    if path.endswith(".py"):
        return "transition"
    return "doc"


def required_for(paths: Iterable[str], row: Mapping[str, Any] = REQUIRED_CHECKS) -> tuple[list[str], list[str]]:
    kinds = {surface_kind(p) for p in paths}
    checks, signoffs = set(row["surface_kinds"]["all"]["checks"]), set()
    for k in kinds:
        checks |= set(row["surface_kinds"][k]["checks"])
        signoffs |= set(row["surface_kinds"][k]["signoffs"])
    return sorted(checks), sorted(signoffs)


def declared_check_ids(row: Mapping[str, Any] = REQUIRED_CHECKS) -> list[str]:
    """The only check ids any receipt may carry: the ids the NWI-S1 verifier emits (row["checks"], plus each stage
    manifest's exit_gate_check, STAGE_GATE_RECEIPT_DERIVES_NATIVE_ISSUE)."""
    return sorted(_checks(row))


def _checks(row: Mapping[str, Any] = REQUIRED_CHECKS) -> dict[str, Any]:
    return {**GATE_CHECKS, **row["checks"]}


def check_id_undeclared(check_id: Any, entry: str) -> Refusal:
    return _fail("CHECK_ID_UNDECLARED", CHECK_RECEIPT_INVARIANT,
                 "a receipt names a check id of row " + REQUIRED_CHECKS["row_id"] + " (" + ", ".join(declared_check_ids())
                 + "); no other minter exists", entry, check_id=check_id)


def validate_check_receipt(receipt: Any, change: Mapping[str, Any] | None = None, head_sha: str | None = None) -> dict[str, Any]:
    """The receipt the NWI-S1 verifier (SV-LLM/.github#46) emits (schemas/sv-check-receipt.v1.schema.json). Validating it
    makes nothing a LEDGER_RECEIPT; only the org-ledger writer transition (Labs#3255) appends it."""
    e = "validate_check_receipt"
    r = receipt
    if not isinstance(r, Mapping) or r.get("schema") != CHECK_RECEIPT_SCHEMA:
        raise _deny("SV_CHECK_RECEIPT_SCHEMA_MISMATCH", "RECORD_SCHEMA_IS_" + CHECK_RECEIPT_SCHEMA, "supply a " + CHECK_RECEIPT_SCHEMA + " receipt", e)
    if not isinstance(r.get("check_id"), str) or not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", r["check_id"]) \
            or r["check_id"] not in declared_check_ids():
        raise check_id_undeclared(r.get("check_id"), e)
    if r.get("disposition") not in DISPOSITIONS:
        raise _deny("SV_CHECK_RECEIPT_INVALID", CHECK_RECEIPT_INVARIANT, "disposition ALLOW, DENY or FAIL_CLOSED", e)
    if not isinstance(r.get("change_digest"), str) or not DIGEST.match(r["change_digest"]) \
            or not isinstance(r.get("head_sha"), str) or not GIT_SHA.match(r["head_sha"]) or not _str(r.get("verifier_ref")):
        raise _deny("SV_CHECK_RECEIPT_INVALID", CHECK_RECEIPT_INVARIANT, "change_digest sha256:<hex>, head_sha 40-hex, verifier_ref", e)
    six = [f for f in SIX_FIELDS if _str(r.get(f))]
    if r["disposition"] != "ALLOW" and len(six) != len(SIX_FIELDS):
        raise _deny("SV_CHECK_RECEIPT_SIX_FIELDS_INCOMPLETE", "ISSUE_BODY_IS_SIX_FIELD_NON_ALLOW",
                    "a non-ALLOW receipt carries all six fields", e, missing=[f for f in SIX_FIELDS if f not in six])
    allowed = {"schema", "check_id", "disposition", "change_digest", "head_sha", "hb_epoch", "verifier_ref"} | set(SIX_FIELDS)
    if set(r) - allowed:
        raise _deny("SV_CHECK_RECEIPT_INVALID", CHECK_RECEIPT_INVARIANT, "no fields beyond the pinned receipt shape", e, extra=sorted(set(r) - allowed))
    epoch_check(r.get("hb_epoch"), e)
    if not command_declared(r["check_id"]) and not (r["disposition"] == "FAIL_CLOSED" and r.get("failure_code") == "CHECK_COMMAND_UNDECLARED"):
        # the only receipt for a check whose row command is UNKNOWN is the verifier's explicit FAIL_CLOSED
        # CHECK_COMMAND_UNDECLARED (six fields); an ALLOW (or any other outcome) cannot have been produced by running it
        raise _fail("CHECK_COMMAND_UNDECLARED", CHECK_COMMAND_PREDICATE,
                    "the row declares no offline command for this check; the only acceptable receipt is FAIL_CLOSED "
                    "CHECK_COMMAND_UNDECLARED with the six fields", e, check_id=r["check_id"], receipt_disposition=r["disposition"])
    if change is not None and r["change_digest"] != (change.get("head") or {}).get("change_digest"):
        raise _fail("CHECK_SKIPPED_OR_UNOBSERVED", EXACT_HEAD_PREDICATE, "re-run the check at the exact head.change_digest", e)
    if head_sha is not None and r["head_sha"] != head_sha:
        raise _fail("CHECK_SKIPPED_OR_UNOBSERVED", EXACT_HEAD_PREDICATE, "re-run the check at the exact head commit", e)
    return dict(r)


def verifier_builtin(c: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """A command built into the NWI-S1 verifier: offline_command = {verifier_builtin, verifier_ref, predicate}, all
    non-empty strings (the builtin's name is the check id), with command_paths empty; else None."""
    oc = c.get("offline_command")
    if isinstance(oc, Mapping) and all(_str(oc.get(k)) for k in ("verifier_builtin", "verifier_ref", "predicate")) \
            and c.get("command_paths") == []:
        return oc
    return None


def command_declared(check_id: str, row: Mapping[str, Any] = REQUIRED_CHECKS) -> bool:
    """argv in this repo (a non-empty list), or a verifier built-in naming this check id."""
    c = _checks(row).get(check_id) or {}
    if isinstance(c.get("offline_command"), list) and bool(c["offline_command"]):
        return True
    b = verifier_builtin(c)
    return b is not None and b["verifier_builtin"] == check_id


def check_command_surface(check_id: str, row: Mapping[str, Any] = REQUIRED_CHECKS) -> str:
    """The repository path a check's command runs: argv[1] for a script, the first command_path naming the unittest
    module for `-m unittest`; for an undeclared command or a verifier built-in (no script in this repo), the row file
    itself (the row is where this repo declares it). A stage gate check's surface is the stage manifest that declares it."""
    if check_id not in row["checks"] and check_id in GATE_CHECKS:
        return GATE_CHECKS[check_id]["declared_in"]["file"]
    c = row["checks"][check_id]
    if not command_declared(check_id, row) or verifier_builtin(c) is not None:
        return row["row_file"]["file"]
    argv = c["offline_command"]
    if argv[1:3] == ["-m", "unittest"]:
        mod = argv[3]
        return next(p for p in c["command_paths"] if p.endswith(".py") and (mod + ".").startswith(p[:-3].replace("/", ".") + "."))
    return argv[1]


def check_command(check_id: Any, paths_at_head: Iterable[str], row: Mapping[str, Any] = REQUIRED_CHECKS) -> dict[str, Any]:
    """Pure: the offline command a check id binds through the row (never the head). Undeclared id -> CHECK_ID_UNDECLARED;
    a verifier built-in -> ALLOW with no argv (paths not checked); offline_command UNKNOWN (or any other non-command)
    -> FAIL_CLOSED CHECK_COMMAND_UNDECLARED; a command_path absent at the head being verified
    (`paths_at_head`, as listed from that head) -> FAIL_CLOSED CHECK_COMMAND_ABSENT_AT_HEAD."""
    e = "check_command"
    if check_id not in _checks(row):
        raise check_id_undeclared(check_id, e)
    c = _checks(row)[check_id]
    if check_id not in row["checks"] and check_id in GATE_CHECKS:
        # a stage gate check is runnable only from a complete declaration (STAGE_GATE_DECLARATION_IS_COMPLETE)
        validate_gate_declaration(json.loads((ROOT / GATE_CHECKS[check_id]["declared_in"]["file"]).read_text()), row)
    b = verifier_builtin(c)
    if b is not None and b["verifier_builtin"] == check_id:
        # built into the verifier: nothing in this repo to locate, so CHECK_COMMAND_ABSENT_AT_HEAD does not apply
        return {"disposition": "ALLOW", "failed_predicate": None, "check_id": check_id, "argv": None,
                "verifier_builtin": dict(b), "argument_bindings": {}, "expected": dict(c["expected"])}
    if not isinstance(c.get("offline_command"), list) or not c["offline_command"]:
        st = c.get("command_status") or {}
        raise _fail("CHECK_COMMAND_UNDECLARED", "CHECK_HAS_OFFLINE_COMMAND",
                    st.get("required_evidence_or_repair") or "declare offline_command, expected and command_paths in the row", e,
                    st.get("next_attempt") or "after the row declares the command", check_id=check_id)
    have = set(paths_at_head)
    absent = sorted(p for p in c["command_paths"] if p not in have)
    if absent:
        raise _fail("CHECK_COMMAND_ABSENT_AT_HEAD", "CHECK_COMMAND_PATHS_PRESENT_AT_HEAD",
                    "a head that carries every command_path of the check (rebase onto a base that has them)", e,
                    "after the head carries the command's files; nothing was run", check_id=check_id, absent=absent)
    return {"disposition": "ALLOW", "failed_predicate": None, "check_id": check_id, "argv": list(c["offline_command"]),
            "argument_bindings": dict(c.get("argument_bindings") or {}), "expected": dict(c["expected"])}


# ------------------------------------------------------------------ STAGE GATE DECLARATION (commit 3)
# What a stage manifest's exit_gate_check must declare so the NWI-S1 verifier (Lane B, SV-LLM/.github#46) can emit it.
GATE_DECLARATION_PREDICATE = "STAGE_GATE_DECLARATION_IS_COMPLETE"
STAGE_EVALUATION_SUBJECT_SCHEMA = "stegverse.nwi-stage-evaluation-subject/v1"
STAGE_EVALUATION_SUBJECT_FIELDS = ("base_ref", "evaluated_commit", "manifest_blob", "repository", "stage_id")
STAGE_EVALUATION_DIGEST_FUNCTION = "sv_work_items.stage_evaluation_digest"
CANONICAL_SERIALIZATION_REF = "schemas/sv-change.v1.schema.json#/properties/change_id/x-canonical-serialization"
# How a gate (or gate-evidence) receipt fills the closed sv-check-receipt.v1 shape, unchanged:
GATE_RECEIPT_BINDING = {"schema": "stegverse.sv_check_receipt.v1", "change_digest": "evaluation_subject.digest",
                        "head_sha": "evaluation_subject.evaluated_commit", "hb_epoch": "hb_epoch",
                        "verifier_ref": "SV-LLM/.github#46@<verifier commit>"}
GATE_CADENCE = {"per": "STAGE_EVALUATION", "transition": "STAGE_GATE", "not_per_head": True, "in_required_checks_row": False,
                "one_failing_receipt_derives_one_issue": True}
REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def gate_declaration_incomplete(missing: list[str], stage_id: Any, entry: str) -> Refusal:
    return _fail("STAGE_GATE_DECLARATION_INCOMPLETE", GATE_DECLARATION_PREDICATE,
                 "the stage manifest's exit_gate_check declares evidence_producers (one S1 row check per receipt predicate, with the "
                 "row's offline_command, command_paths and expected), receipt_form, evaluation_subject, hb_epoch (the pinned Labs#3266 "
                 "readback at the subject's ledger head) and cadence (per stage evaluation)", entry,
                 "after the manifest declares every part; the verifier emits nothing for an incomplete declaration",
                 stage_id=stage_id, missing=missing)


def validate_gate_declaration(manifest: Any, row: Mapping[str, Any] = REQUIRED_CHECKS) -> dict[str, Any]:
    """Pure. FAIL_CLOSED STAGE_GATE_DECLARATION_INCOMPLETE (six fields, `missing` lists every gap) unless the manifest's
    exit_gate_check is complete. A manifest that declares no exit_gate_check is not a gate-check stage (returns None)."""
    e = "validate_gate_declaration"
    if not isinstance(manifest, Mapping):
        raise gate_declaration_incomplete(["manifest"], None, e)
    c = manifest.get("exit_gate_check")
    if c is None:
        return None
    sid = manifest.get("stage_id")
    if not isinstance(c, Mapping):
        raise gate_declaration_incomplete(["exit_gate_check"], sid, e)
    miss: list[str] = []
    oc = c.get("offline_command")
    if not (_str(c.get("check_id")) and isinstance(oc, Mapping) and oc.get("verifier_builtin") == c.get("check_id")
            and oc.get("verifier_ref") == S1_VERIFIER_REF and S1_VERIFIER_REF in str(c.get("minter")) and c.get("command_paths") == []):
        miss.append("exit_gate_check (S1 verifier built-in)")
    if sentinel_pointers(c):
        miss.append("no UNKNOWN_NOT_AUTHENTICALLY_OBSERVED in exit_gate_check: " + ", ".join(sentinel_pointers(c)))
    wanted = sorted(g.get("predicate") for g in manifest.get("exit_gate") or [] if isinstance(g, Mapping) and g.get("evidence") == "receipt")
    prods = c.get("evidence_producers")
    if not isinstance(prods, list) or sorted(p.get("predicate") for p in prods if isinstance(p, Mapping)) != wanted or len(prods) != len(wanted):
        miss.append("evidence_producers (exactly one per receipt predicate: " + ", ".join(wanted) + ")")
    else:
        for p in prods:
            cid = p.get("check_id")
            rc = row["checks"].get(cid) if isinstance(cid, str) else None
            if rc is None or not isinstance(rc.get("offline_command"), list) or not rc["offline_command"]:
                miss.append("evidence_producers[%s].check_id (a row check with a declared argv)" % p.get("predicate")); continue
            for k in ("offline_command", "command_paths", "expected"):
                if p.get(k) != rc.get(k):
                    miss.append("evidence_producers[%s].%s (= row %s)" % (p.get("predicate"), k, cid))
            if S1_VERIFIER_REF not in str(p.get("producer")) or S1_VERIFIER_REF not in str(rc.get("minter")):
                miss.append("evidence_producers[%s].producer (the NWI-S1 verifier)" % p.get("predicate"))
            if not _str(p.get("covers")):
                miss.append("evidence_producers[%s].covers" % p.get("predicate"))
    rf = c.get("receipt_form")
    if not isinstance(rf, Mapping) or any(rf.get(k) != v for k, v in GATE_RECEIPT_BINDING.items()) \
            or rf.get("ledger_paths") != ["receipts/<org receipt sha256 hex>.json", "source-receipts/<repo receipt sha256 hex>.json"] \
            or rf.get("ledger") != "evaluation_subject.repository" or not _str(rf.get("ledger_ref")) or LEDGER_REF not in rf["ledger_ref"] \
            or rf.get("manifest_source") != MANIFEST_SOURCE:
        miss.append("receipt_form")
    es = c.get("evaluation_subject")
    if not isinstance(es, Mapping) or es.get("schema") != STAGE_EVALUATION_SUBJECT_SCHEMA \
            or not isinstance(es.get("fields"), Mapping) or tuple(sorted(es["fields"])) != STAGE_EVALUATION_SUBJECT_FIELDS \
            or not all(_str(v) for v in es["fields"].values()) or es.get("digest_function") != STAGE_EVALUATION_DIGEST_FUNCTION \
            or es.get("serialization") != CANONICAL_SERIALIZATION_REF or not _str(es.get("carried_by")) \
            or es.get("manifest_source") != MANIFEST_SOURCE:
        miss.append("evaluation_subject")
    he = c.get("hb_epoch")
    pin = {k: BASE_STATE_READBACK_PIN[k] for k in ("repository", "pull_request", "head", "file", "blob", "sha256")}
    if not isinstance(he, Mapping) or he.get("readback_pin") != pin or he.get("at") != "evaluation_subject.base_ref.ledger_head" \
            or he.get("field") != HB_EPOCH_SOURCE_FIELD or not _str(he.get("unobserved")):
        miss.append("hb_epoch (the pinned Labs#3266 readback at evaluation_subject.base_ref.ledger_head)")
    cad = c.get("cadence")
    if not isinstance(cad, Mapping) or any(cad.get(k) != v for k, v in GATE_CADENCE.items()) or not _str(cad.get("trigger")):
        miss.append("cadence (per stage evaluation, not per head, not in the required-checks row; trigger)")
    if miss:
        raise gate_declaration_incomplete(miss, sid, e)
    return {"disposition": "ALLOW", "failed_predicate": None, "stage_id": sid, "check_id": c["check_id"],
            "producers": {p["predicate"]: p["check_id"] for p in prods}}


def stage_evaluation_subject(repository: Any, stage_id: Any, manifest_blob: Any, evaluated_commit: Any, base_ref: Any) -> dict[str, Any]:
    """The subject a stage evaluation's receipts bind (no SV_CHANGE requires a gate, so there is no change digest to bind):
    the repository and commit the stage is evaluated at (evaluated_commit identifies the subject only), the git blob of the
    gate manifest as the gate declaration's contract-pins.json pins it (manifest_source CONTRACT_PINS; never read from the
    subject: GATE_MANIFEST_IS_THE_CONTRACT_PINNED_MANIFEST), and the observed base
    {registry_generation at that commit, ledger_head of the repository's own refs/stegverse/organization-ledger}.
    Anything missing or malformed is FAIL_CLOSED STAGE_EVALUATION_SUBJECT_UNOBSERVED (nothing is defaulted)."""
    bad = [k for k, ok in (("repository", isinstance(repository, str) and REPO_NAME.match(repository)),
                           ("stage_id", isinstance(stage_id, str) and re.fullmatch(r"NWI-S[0-9]+", stage_id)),
                           ("manifest_blob", isinstance(manifest_blob, str) and GIT_SHA.match(manifest_blob)),
                           ("evaluated_commit", isinstance(evaluated_commit, str) and GIT_SHA.match(evaluated_commit)),
                           ("base_ref", _base_ok(base_ref) and set(base_ref) == {"registry_generation", "ledger_head"})) if not ok]
    if bad:
        raise _fail("STAGE_EVALUATION_SUBJECT_UNOBSERVED", GATE_DECLARATION_PREDICATE,
                    "observe repository, stage_id, manifest_blob (the contract-pinned manifest blob), evaluated_commit and base_ref", "stage_evaluation_subject",
                    "after every subject field is observed; nothing is evaluated", fields=bad)
    return {"repository": repository, "stage_id": stage_id, "manifest_blob": manifest_blob, "evaluated_commit": evaluated_commit,
            "base_ref": {"registry_generation": base_ref["registry_generation"], "ledger_head": base_ref["ledger_head"]}}


def stage_evaluation_digest(subject: Mapping[str, Any]) -> str:
    """change_digest of every receipt of one stage evaluation: "sha256:" + hex sha256(canon(subject)), canon being the pinned
    change_id serialization (sort_keys, separators (',',':'), UTF-8, ensure_ascii false, no trailing newline)."""
    s = stage_evaluation_subject(subject.get("repository"), subject.get("stage_id"), subject.get("manifest_blob"),
                                 subject.get("evaluated_commit"), subject.get("base_ref")) if isinstance(subject, Mapping) \
        else stage_evaluation_subject(None, None, None, None, None)
    if set(subject) != set(STAGE_EVALUATION_SUBJECT_FIELDS):
        raise _fail("STAGE_EVALUATION_SUBJECT_UNOBSERVED", GATE_DECLARATION_PREDICATE, "exactly the subject fields "
                    + ", ".join(STAGE_EVALUATION_SUBJECT_FIELDS), "stage_evaluation_digest", "rebuild the subject", extra=sorted(set(subject)))
    return "sha256:" + hashlib.sha256(canon(s)).hexdigest()


def validate_gate_receipt(receipt: Any, subject: Mapping[str, Any], readback: Any, *, fixture_mode: bool = False,
                          contract_pins: Any = None) -> dict[str, Any]:
    """A receipt of one stage evaluation (the gate check or one of its evidence producers): the pinned sv-check-receipt.v1
    shape (validate_check_receipt, unchanged), head_sha = the subject's evaluated_commit, change_digest = its digest
    (else FAIL_CLOSED CHECK_SKIPPED_OR_UNOBSERVED, STAGE_EVALUATION_SUBJECT_BINDS_RECEIPT), and hb_epoch = the Labs#3266
    readback epoch at the subject's ledger head of the subject's own repository (verify_admission_hb_epoch: DENY
    HB_EPOCH_MISMATCH / FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED)."""
    e = "validate_gate_receipt"
    digest = stage_evaluation_digest(subject)
    r = validate_check_receipt(receipt, head_sha=subject["evaluated_commit"])
    gate = GATE_CHECKS.get(r["check_id"]) or next((g for g in GATE_CHECKS.values()
                                                   if r["check_id"] in {p.get("check_id") for p in g.get("evidence_producers") or []}), None)
    if gate is None or gate["declared_in"]["stage_id"] != subject["stage_id"]:
        raise _fail("CHECK_NOT_PART_OF_STAGE_EVALUATION", GATE_DECLARATION_PREDICATE,
                    "a stage-evaluation receipt names the stage's gate check or one of its evidence producers", e,
                    "re-emit under the stage's declared checks", check_id=r["check_id"], stage_id=subject["stage_id"])
    if r["change_digest"] != digest:
        raise _fail("CHECK_SKIPPED_OR_UNOBSERVED", "STAGE_EVALUATION_SUBJECT_BINDS_RECEIPT",
                    "re-run the check for this stage evaluation (change_digest = stage_evaluation_digest(subject))", e,
                    "re-evaluate the stage; nothing moved", expected=digest, change_digest=r["change_digest"])
    if contract_pins is not None:  # GATE_MANIFEST_IS_THE_CONTRACT_PINNED_MANIFEST (manifest_source CONTRACT_PINS)
        pin = pinned_gate_manifest(contract_pins, subject["stage_id"])
        if pin is None:
            raise _fail("GATE_PAIR_PINNED_MANIFEST_UNOBSERVED", GATE_MANIFEST_PREDICATE, "a contract-pins.json that pins the stage manifest",
                        e, "re-validate with the gate declaration's contract-pins.json")
        if subject["manifest_blob"] != pin["blob"]:
            raise manifest_read_from_subject(subject, pin, e)
    verify_admission_hb_epoch(r["hb_epoch"], readback, subject["base_ref"]["ledger_head"], fixture_mode=fixture_mode,
                              target_repository=subject["repository"])
    return {"disposition": "ALLOW", "failed_predicate": None, "check_id": r["check_id"], "evaluation_subject_digest": digest}


def check_outcome_matches(expected: Mapping[str, Any], exit_code: int, stdout: str, stderr: str) -> bool:
    """Pure: exit_code equal; every stdout_json_subset key equal in the JSON stdout; stderr_last_line equal."""
    if exit_code != expected.get("exit_code"):
        return False
    if "stdout_json_subset" in expected:
        try:
            out = json.loads(stdout)
        except ValueError:
            return False
        if not isinstance(out, Mapping) or any(out.get(k) != v for k, v in expected["stdout_json_subset"].items()):
            return False
    if "stderr_last_line" in expected:
        lines = [l for l in stderr.splitlines() if l.strip()]
        if not lines or lines[-1].strip() != expected["stderr_last_line"]:
            return False
    return True


def row_receipt_status(appended: Iterable[Mapping[str, Any]] = (), row: Mapping[str, Any] = REQUIRED_CHECKS) -> dict[str, Any]:
    """The real row fails closed until the org writer has appended a verifier receipt for every declared check id.
    `appended` is the set of LEDGER_RECEIPT references already read back from refs/stegverse/organization-ledger;
    nothing here reads the ledger, a clock or a CI job."""
    have = {a.get("check_id") for a in appended if a.get("evidence_class") == "LEDGER_RECEIPT" and str(a.get("ref") or "").startswith("refs/")}
    missing = [c for c in sorted(row["checks"]) if c not in have]  # the row's own checks (a stage gate check is not a row check)
    if not missing:
        return {"disposition": "ALLOW", "failed_predicate": None}
    return {**row["row_status"], "missing_check_ids": missing}


def signoff_resolves(so: Any, receipts: Iterable[Mapping[str, Any]], change_digest_: Any, fixture_mode: bool = False) -> bool:
    """A sign-off counts only if its receipt_ref is the receipt_sha256 of a sealed ALLOW sign-off receipt for this
    change (change_digest), by the same role and session. A fixture_only receipt counts only in fixture_mode."""
    if not isinstance(so, Mapping) or not _str(so.get("receipt_ref")) or not _str(so.get("session")):
        return False
    for r in receipts:
        if isinstance(r, Mapping) and r.get("schema") == SIGNOFF_RECEIPT_SCHEMA and r.get("receipt_sha256") == so["receipt_ref"] \
                and r["receipt_sha256"] == sha({k: v for k, v in r.items() if k != "receipt_sha256"}) \
                and r.get("role") == so.get("role") and r.get("session") == so.get("session") \
                and r.get("change_digest") == change_digest_ and r.get("disposition") == "ALLOW" \
                and (fixture_mode or r.get("fixture_only") is not True):
            return True
    return False


def ledger_receipt_digest(receipt_bytes: bytes) -> str:
    """'sha256:' + hex over canon(receipt object): the same pinned canonical JSON as change_id."""
    return "sha256:" + hashlib.sha256(canon(json.loads(receipt_bytes.decode("utf-8")))).hexdigest()


ORG_RECEIPT_SCHEMA = "stegverse.organization-transition-receipt/v1"  # aggregate_repo_transition.py:1074
REPO_RECEIPT_SCHEMA = "stegverse.repo-transition-receipt/v1"          # .stegverse/transition-ledger/emit.py:116
HB_ANCHOR_EPOCH = 32                                                   # org-kernel/kernel.py:22
SV_CHECK_RECEIPT_OPERATION = "sv_check_receipt"  # Lane D's append operation (boundary_evidence.operation / $.evidence.kind)


def _ledger_object(ledger_objects: Mapping[str, bytes], commit: str, path: str) -> Any:
    raw = ledger_objects.get(commit + ":" + path)
    if not isinstance(raw, (bytes, bytearray)):
        return None
    try:
        return json.loads(bytes(raw).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def _self_verifies(doc: Any) -> bool:
    """The ledger seal rule: receipt_sha256 = sha256 over the canonical body without receipt_sha256
    (aggregate_repo_transition.py:1089, emit.py:117, organization_ledger_readback.py:69-73)."""
    return isinstance(doc, Mapping) and isinstance(doc.get("receipt_sha256"), str) \
        and doc["receipt_sha256"] == sha({k: v for k, v in doc.items() if k != "receipt_sha256"})


def _sealed_at(ledger_objects: Mapping[str, bytes], commit: str, key: str, digest: Any) -> Mapping[str, Any] | None:
    """The sealed receipt stored at `key` in commit `commit` whose receipt_sha256 is `digest`, else None."""
    doc = _ledger_object(ledger_objects, commit, key)
    return doc if _self_verifies(doc) and doc["receipt_sha256"] == digest else None


def verify_ledger_receipt_binding(receipt: Mapping[str, Any], ledger_objects: Mapping[str, bytes]) -> dict[str, Any]:
    """Pure: binds a validation receipt's `digest` to the ledger receipt its `ref` names. `ref` addresses the stored
    receipt the way the org ledger stores it (ledger_store.receipt_key: receipts/<hex>.json, ledger_store.py:49-56;
    written at aggregate_repo_transition.py:1089-1093): refs/stegverse/organization-ledger@<commit 40-hex>:receipts/<hex>.json.
    `ledger_objects` maps "<commit>:<path>" to the bytes a read of that ref returned; nothing here fetches.
    Unparsable ref, absent object, non-JSON bytes, a receipt that does not verify against its own body (the seal), or
    whose receipt_sha256 is not the one its path names -> FAIL_CLOSED LEDGER_RECEIPT_UNRESOLVED;
    digest != ledger_receipt_digest(bytes) -> FAIL_CLOSED LEDGER_RECEIPT_DIGEST_MISMATCH."""
    e = "verify_ledger_receipt_binding"
    nxt = "after a fresh read of refs/stegverse/organization-ledger holds the receipt; nothing was counted"
    ref = receipt.get("ref") if isinstance(receipt, Mapping) else None
    m = LEDGER_RECEIPT_REF.match(ref) if isinstance(ref, str) else None
    obj = _sealed_at(ledger_objects, m.group("commit"), m.group("path"), "sha256:" + m.group("hex")) if m else None
    if obj is None:
        raise _fail("LEDGER_RECEIPT_UNRESOLVED", "VALIDATION_RECEIPT_REF_RESOLVES_ON_ORGANIZATION_LEDGER",
                    "ref = refs/stegverse/organization-ledger@<commit>:receipts/<receipt_sha256 hex>.json naming a sealed receipt a "
                    "read of that ref returns", e, nxt, ref=ref)
    want = ledger_receipt_digest(bytes(ledger_objects[m.group("commit") + ":" + m.group("path")]))
    if receipt.get("digest") != want:
        raise _fail("LEDGER_RECEIPT_DIGEST_MISMATCH", "VALIDATION_RECEIPT_DIGEST_BINDS_LEDGER_RECEIPT",
                    "digest = 'sha256:' + hex sha256 of the canonical JSON of the receipt at ref", e, nxt, expected=want, ref=ref)
    return {"disposition": "ALLOW", "failed_predicate": None, "ref": ref, "digest": want}


def base_ledger_head_epoch(ledger_head: Any, ledger_objects: Mapping[str, bytes]) -> int | None:
    """Pure: $.hb_reference.epoch of the organization-transition receipt at commit `ledger_head` of
    refs/stegverse/organization-ledger: HEAD.json (ledger_store.HEAD_KEY, aggregate_repo_transition.py:1092) ->
    receipts/<hex>.json (ledger_store.receipt_key) -> seal verified -> hb_reference.epoch (kernel.hb_reference,
    kernel.py:68-74). The epoch must be an int (not bool, no coercion) >= 32 and the reference not derived from a clock;
    otherwise None. Read only from the supplied bytes."""
    if not isinstance(ledger_head, str) or not GIT_SHA.match(ledger_head):
        return None
    head = _ledger_object(ledger_objects, ledger_head, LEDGER_HEAD_KEY)
    digest = head.get("receipt_sha256") if isinstance(head, Mapping) else None
    if not isinstance(digest, str) or not DIGEST.match(digest):
        return None
    rec = _sealed_at(ledger_objects, ledger_head, "receipts/%s.json" % digest.split(":", 1)[1], digest)
    if rec is None or rec.get("schema") != ORG_RECEIPT_SCHEMA:
        return None
    hb = rec.get("hb_reference")
    ep = hb.get("epoch") if isinstance(hb, Mapping) else None
    if type(ep) is not int or ep < HB_ANCHOR_EPOCH or hb.get("derived_from_clock") is not False:
        return None
    return ep


def verify_native_hb_epoch(record: Mapping[str, Any], ledger_objects: Mapping[str, bytes]) -> dict[str, Any]:
    """NATIVE_RECORD_HB_EPOCH_IS_BASE_LEDGER_HEAD_EPOCH (decided with JD-P4-3, partial). A NATIVE record's hb_epoch (ASCII
    digits) equals, by integer value, $.hb_reference.epoch of the org receipt at its base ledger head (SV_CHANGE
    base_ref, SV_ISSUE observed_base), read from the supplied ledger bytes only, never a clock. Unobserved (no HEAD,
    no receipt, broken seal, missing/invalid epoch) -> FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED; mismatch -> DENY
    HB_EPOCH_MISMATCH. The native-record application of ADMISSION_HB_EPOCH_IS_THE_BOUND_LEDGER_HEAD_EPOCH."""
    base = record.get("base_ref") if record.get("schema") == CHANGE_SCHEMA else record.get("observed_base")
    head = (base or {}).get("ledger_head") if isinstance(base, Mapping) else None
    want = base_ledger_head_epoch(head, ledger_objects)
    if want is None:
        r = Refusal("FAIL_CLOSED", "HB_EPOCH_SOURCE_UNOBSERVED", HB_EPOCH_LEDGER_INVARIANT,
                    "bind base_ref.ledger_head to an org-ledger receipt carrying hb_epoch", "verify_native_hb_epoch",
                    "after the org writer appends at that head", ledger_head=head)
        r.record["retry_entrypoint"] = "native record re-derivation"
        raise r
    mine = record.get("hb_epoch")
    if not (isinstance(mine, str) and re.fullmatch(r"[0-9]+", mine) and int(mine) == want):
        r = Refusal("DENY", HB_EPOCH_MISMATCH, HB_EPOCH_LEDGER_INVARIANT,
                    "re-derive the native record with hb_epoch = the base ledger head receipt's hb_reference.epoch",
                    "verify_native_hb_epoch", "propose a successor record bound to the base ledger head's epoch",
                    ledger_head=head, expected=str(want), hb_epoch=mine)
        r.record["retry_entrypoint"] = "native record re-derivation"
        raise r
    return {"disposition": "ALLOW", "failed_predicate": None, "hb_epoch": str(want), "ledger_head": head}


def _readback_epoch_unobserved(why: str, ledger_head: Any) -> Refusal:
    r = Refusal("FAIL_CLOSED", "HB_EPOCH_SOURCE_UNOBSERVED", ADMISSION_HB_EPOCH_INVARIANT,
                "a sealed ALLOW " + BASE_STATE_READBACK_SCHEMA + " receipt (Labs#3266) for base_ref.ledger_head whose hb_epoch slot "
                "was read from " + HB_EPOCH_SOURCE_FIELD + " of the head receipt and passes org-kernel/kernel.py::supplied_epoch_failure "
                "(sha256 " + SUPPLIED_EPOCH_RULE_SHA256[:8] + ")", "verify_admission_hb_epoch",
                "after Lane C's readback (Labs#3266) seals an epoch read at that ledger head; no epoch is minted",
                ledger_head=ledger_head, detail=why)
    return r


READBACK_SHAPE_PREDICATE = "READBACK_SHAPE_MATCHES_PINNED_PRODUCER"


def readback_shape_violation(rb: Mapping[str, Any]) -> str | None:
    """READBACK_SHAPE_MATCHES_PINNED_PRODUCER (rulings 2026-10-18 ~17:05Z and ~17:15Z, NOT_CROSS_CHECKED_MARKER): the
    producer ALWAYS emits cross_checked. A cross-checked ALLOW carries cross_checked true and the supplied value
    (READBACK_SUPPLIED_FIELD, equal by integer value to the sealed hb_epoch); an omitted-flag ALLOW carries exactly
    {cross_checked: false, detail: HB_EPOCH_NOT_CROSS_CHECKED} at top level. A readback with no cross_checked key, with
    an hb_epoch_cross_check key (the void 2ba0e329 shape), or with any other combination is void: a self-seal
    (result_sha256) cannot prove which producer path ran, so a stripped-and-resealed readback is not observed. Returns
    the reason, or None."""
    if "hb_epoch_cross_check" in rb:
        return "carries hb_epoch_cross_check, which the producer never emits (void 2ba0e329 shape)"
    if "cross_checked" not in rb:
        return "no cross_checked key: the producer always emits it, and a self-seal cannot prove which producer path ran"
    cc = rb["cross_checked"]
    if not isinstance(cc, bool):
        return "cross_checked is not a JSON boolean"
    if rb.get("disposition") == "DENY" and rb.get("failure_code") == HB_EPOCH_MISMATCH:
        # the producer's cross-check ran and disagreed (7ad6d81f: cross_checked true, supplied_hb_epoch, no detail)
        if cc is not True or rb.get("detail") == NOT_CROSS_CHECKED_DETAIL or READBACK_SUPPLIED_FIELD not in rb:
            return ("a DENY HB_EPOCH_MISMATCH readback that does not carry cross_checked true and " + READBACK_SUPPLIED_FIELD
                    + " (only a cross-check can mismatch)")
        return None
    if rb.get("disposition") != "ALLOW":
        # 7ad6d81f FAIL_CLOSED: cross_checked false (no comparison with a sealed epoch was made)
        if cc is not False:
            return "a non-ALLOW readback other than DENY HB_EPOCH_MISMATCH carries cross_checked false (no comparison was made)"
        return None
    if cc is False:
        if rb.get("detail") != NOT_CROSS_CHECKED_DETAIL or READBACK_SUPPLIED_FIELD in rb:
            return ("an omitted-flag ALLOW whose marker is not exactly the canonical top-level "
                    "{cross_checked: false, detail: HB_EPOCH_NOT_CROSS_CHECKED}")
        return None
    sv, ep = rb.get(READBACK_SUPPLIED_FIELD), rb.get("hb_epoch")
    # 7ad6d81f emits the supplied value verbatim: ASCII digits, or a JSON integer equal by value ("equal-int" is ALLOW there)
    sv_ok = (isinstance(sv, str) and re.fullmatch(r"[0-9]+", sv) is not None) or (isinstance(sv, int) and not isinstance(sv, bool))
    if rb.get("detail") == NOT_CROSS_CHECKED_DETAIL or not sv_ok \
            or not (isinstance(ep, str) and re.fullmatch(r"[0-9]+", ep)) or int(sv) != int(ep):
        return ("a cross-checked ALLOW that does not carry cross_checked true with the supplied value (" + READBACK_SUPPLIED_FIELD
                + ", ASCII digits or a JSON integer equal to the sealed hb_epoch) and no not-cross-checked detail")
    return None


def _readback_shape_unobserved(why: str, ledger_head: Any) -> Refusal:
    return Refusal("FAIL_CLOSED", "HB_EPOCH_SOURCE_UNOBSERVED", READBACK_SHAPE_PREDICATE,
                   "a readback in the exact shape the pinned producer emits (Labs#3266 @" + BASE_STATE_READBACK_PIN["head"][:8]
                   + ", readback blob " + BASE_STATE_READBACK_PIN["blob"][:8] + "): cross_checked always present, no "
                   "hb_epoch_cross_check key; a cross-checked ALLOW carries cross_checked true and " + READBACK_SUPPLIED_FIELD
                   + "; an omitted --hb-epoch ALLOW carries exactly {cross_checked: false, detail: HB_EPOCH_NOT_CROSS_CHECKED}",
                   "verify_admission_hb_epoch",
                   "re-run the pinned readback (Labs#3266 @" + BASE_STATE_READBACK_PIN["head"][:8] + ") at the bound ledger head and "
                   "re-admit with its receipt; nothing was admitted", ledger_head=ledger_head, detail=why)


def verify_admission_hb_epoch(supplied: Any, readback: Any, ledger_head: Any, *, fixture_mode: bool = False,
                              target_repository: Any = None) -> dict[str, Any]:
    """ADMISSION_HB_EPOCH_IS_THE_BOUND_LEDGER_HEAD_EPOCH (JD-P4-3, part-decided by invariant). The admission hb_epoch is
    the epoch on the org-ledger head receipt the SV_CHANGE base is bound to, as read and sealed by Lane C's base-state
    readback (Labs#3266): the in-repo reference of the supplied-epoch-binder-check predicate (built into the NWI-S1
    verifier, SV-LLM/.github#46). Pure over the supplied receipt; nothing is read, minted or clocked here.
      FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED: no readback, not that schema, broken seal (result_sha256), neither ALLOW nor
        DENY HB_EPOCH_MISMATCH (a FAIL_CLOSED readback seals hb_epoch and hb_epoch_source as null), hb_epoch_source.receipt
        not receipts/<hex>.json,
        a fixture_only receipt outside fixture_mode, bound to another ledger head, no hb_epoch_source naming
        $.hb_reference.epoch at that head, or an hb_epoch slot that fails the shared supplied-epoch rule (726248a5:
        ASCII digits, >= 32, the source reference's derived_from_clock exactly false), or that rule is not the pinned one.
      FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED (contract invariant: UNKNOWN is FAIL_CLOSED, never DENY): the supplied hb_epoch,
        where it is the epoch source (an SV_CHANGE record's hb_epoch; absent reads as null), is null, "", "null" or the
        literal UNKNOWN_NOT_AUTHENTICALLY_OBSERVED; checked BEFORE 726248a5 (a deliberate, recorded precedence).
      ALLOW with cross_checked false and detail HB_EPOCH_NOT_CROSS_CHECKED: `supplied` is HB_EPOCH_NOT_CROSS_CHECKED (an optional
        cross-check left out; the canonical not-cross-checked marker).
      FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED (READBACK_SHAPE_MATCHES_PINNED_PRODUCER): the readback carries hb_epoch_cross_check,
        has no cross_checked key (the producer always emits it; a self-seal cannot prove which path ran), or a non-canonical
        cross_checked / marker combination (readback_shape_violation): not produced by the pinned readback.
      DENY HB_EPOCH_MISMATCH: any other supplied hb_epoch that fails 726248a5 (non-digit, coerced such as '+33', below 32,
        an int or bool rather than ASCII text) or is not equal by integer value to the sealed epoch."""
    if KERNEL_RULE_SHA256 != SUPPLIED_EPOCH_RULE_SHA256:
        raise _readback_epoch_unobserved("org-kernel/kernel.py::supplied_epoch_failure is not the pinned rule "
                                         + SUPPLIED_EPOCH_RULE_SHA256[:8], ledger_head)
    rb = readback
    if not isinstance(rb, Mapping):
        raise _readback_epoch_unobserved("no base-state readback receipt", ledger_head)
    if rb.get("schema") != BASE_STATE_READBACK_SCHEMA:
        raise _readback_epoch_unobserved("not a " + BASE_STATE_READBACK_SCHEMA + " receipt", ledger_head)
    if not isinstance(rb.get("result_sha256"), str) or rb["result_sha256"] != sha({k: v for k, v in rb.items() if k != "result_sha256"}):
        raise _readback_epoch_unobserved("the readback receipt does not verify against its own body (result_sha256)", ledger_head)
    # Labs#3266 @7ad6d81f producer semantics (epoch slots unchanged since 2ba0e329): the epoch and its source are sealed on ALLOW and on DENY HB_EPOCH_MISMATCH (the
    # epoch was observed; only the producer's --hb-epoch cross-check disagreed); on every FAIL_CLOSED both are present and null.
    shape = readback_shape_violation(rb)
    if shape is not None:
        raise _readback_shape_unobserved(shape, ledger_head)
    observed = rb.get("disposition") == "ALLOW" or (rb.get("disposition") == "DENY" and rb.get("failure_code") == HB_EPOCH_MISMATCH)
    if not observed:
        raise _readback_epoch_unobserved("the readback receipt is %s %s: no epoch was observed (hb_epoch %r, hb_epoch_source %r)"
                                         % (rb.get("disposition"), rb.get("failure_code"), rb.get("hb_epoch"), rb.get("hb_epoch_source")),
                                         ledger_head)
    if rb.get("fixture_only") is True and not fixture_mode:
        raise _readback_epoch_unobserved("a fixture_only readback counts only in fixture_mode", ledger_head)
    if target_repository is not None and rb.get("repository") != target_repository:
        # CHANGE_BINDS_TARGET_REPOSITORY_LEDGER: the base is the target repository's own refs/stegverse/organization-ledger
        raise _readback_epoch_unobserved("the readback read %r's ledger, not the target repository %r's own ledger ref"
                                         % (rb.get("repository"), target_repository), ledger_head)
    if not (isinstance(ledger_head, str) and GIT_SHA.match(ledger_head)) or (rb.get("base_ref") or {}).get("ledger_head") != ledger_head:
        raise _readback_epoch_unobserved("the readback is bound to another ledger head", ledger_head)
    src = rb.get("hb_epoch_source")
    if not isinstance(src, Mapping) or src.get("ledger_head") != ledger_head or src.get("field") != HB_EPOCH_SOURCE_FIELD:
        raise _readback_epoch_unobserved("no hb_epoch_source naming " + HB_EPOCH_SOURCE_FIELD + " at the bound head", ledger_head)
    receipt = src.get("receipt")
    if not (isinstance(receipt, str) and READBACK_RECEIPT_PATH.match(receipt)) \
            and not (receipt == UNKNOWN and rb.get("fixture_only") is True and fixture_mode):
        raise _readback_epoch_unobserved("hb_epoch_source.receipt is not the head receipt's ledger path receipts/<hex>.json "
                                         "(UNKNOWN only in a fixture_only readback in fixture_mode)", ledger_head)
    bad = kernel.supplied_epoch_failure(rb.get("hb_epoch"), src)
    if rb.get("hb_epoch") is None or bad is not None:
        raise _readback_epoch_unobserved("the sealed hb_epoch slot fails the shared supplied-epoch rule: "
                                         + (bad[0] + ": " + bad[1] if bad else "absent"), ledger_head)
    want = int(str(rb["hb_epoch"]))
    if supplied is HB_EPOCH_NOT_CROSS_CHECKED:
        # an optional cross-check left out is not a failure: nothing to compare, the sealed epoch stands
        # canonical placement (orchestrator ruling 16:30Z, invariants.json#NOT_CROSS_CHECKED_MARKER): top-level
        # cross_checked false plus detail HB_EPOCH_NOT_CROSS_CHECKED; P4 and Labs#3266 match it
        return {"disposition": "ALLOW", "failed_predicate": None, "hb_epoch": str(want), "ledger_head": ledger_head,
                "cross_checked": False, "detail": NOT_CROSS_CHECKED_DETAIL}
    # Contract invariant (orchestrator 15:59Z, narrowed 16:03Z): anything not observed is UNKNOWN_NOT_AUTHENTICALLY_OBSERVED,
    # which is FAIL_CLOSED, never DENY. Where the supplied value IS the epoch source (an SV_CHANGE record's hb_epoch), an
    # absent field (read as null), JSON null, "", "null" or the UNKNOWN sentinel is FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED.
    # This precedes the kernel rule: 726248a5 alone would call None HB_EPOCH_NOT_SUPPLIED and "", "null" and the sentinel
    # HB_EPOCH_INVALID (malformed, i.e. DENY here). The pin is unchanged; the precedence is recorded in the row.
    if any(supplied is v if v is None else (isinstance(supplied, str) and supplied == v) for v in SUPPLIED_EPOCH_UNOBSERVED_VALUES):
        raise _readback_epoch_unobserved("the supplied hb_epoch %r is not observed (UNKNOWN_NOT_AUTHENTICALLY_OBSERVED is FAIL_CLOSED, "
                                         "never DENY; checked before 726248a5)" % (supplied,), ledger_head)
    # Ruling (orchestrator, both verifiers, 60 cases): any other SUPPLIED epoch that fails 726248a5 is DENY
    # HB_EPOCH_MISMATCH, as is a well-formed one that differs from the sealed epoch.
    supplied_failure = kernel.supplied_epoch_failure(supplied)
    if supplied_failure is not None or not (isinstance(supplied, str) and re.fullmatch(r"[0-9]+", supplied) and int(supplied) == want):
        raise _deny(HB_EPOCH_MISMATCH, ADMISSION_HB_EPOCH_INVARIANT,
                    "the SV_CHANGE's hb_epoch equals the epoch the base-state readback sealed at base_ref.ledger_head",
                    "verify_admission_hb_epoch", "propose a successor SV_CHANGE at the observed epoch; nothing was admitted",
                    ledger_head=ledger_head, expected=str(want), hb_epoch=supplied,
                    **({"supplied_epoch_rule": supplied_failure[0] + ": " + supplied_failure[1]} if supplied_failure else {}))
    # ruling ~17:15Z: our own output always carries cross_checked; cross-checked: true plus the supplied value
    return {"disposition": "ALLOW", "failed_predicate": None, "hb_epoch": str(want), "ledger_head": ledger_head,
            "cross_checked": True, READBACK_SUPPLIED_FIELD: supplied}


def _check_receipt_from_evidence(ev: Any) -> Mapping[str, Any] | None:
    """Lane D's sv_check_receipt append puts the verifier receipt under the repo receipt's $.evidence, self-identified by
    $.evidence.schema == stegverse.sv_check_receipt.v1 or $.evidence.kind == 'sv_check_receipt'. With the kind marker the
    object minus `kind` must still be the pinned receipt shape (validate_check_receipt checks it)."""
    if not isinstance(ev, Mapping):
        return None
    if ev.get("schema") == CHECK_RECEIPT_SCHEMA and "kind" not in ev:
        return ev
    if ev.get("kind") == SV_CHECK_RECEIPT_OPERATION:
        return {k: v for k, v in ev.items() if k != "kind"}
    return None


def _violated_check_invariant(check_id: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """Where the check is declared: the row (rule_id <row_id>#checks.<id>), or for a stage gate check
    (STAGE_GATE_RECEIPT_DERIVES_NATIVE_ISSUE) the stage manifest (rule_id <stage_id>#exit_gate_check.<id>)."""
    if check_id not in row["checks"] and check_id in GATE_CHECKS:
        d = GATE_CHECKS[check_id]["declared_in"]
        return {"repository": d["repository"], "file": d["file"], "rule_id": d["rule_id"], "blob_sha": None, "invariant_declared": True}
    return {"repository": row["row_file"]["repository"], "file": row["row_file"]["file"],
            "rule_id": row["row_id"] + "#checks." + check_id, "blob_sha": None, "invariant_declared": True}


def derive_issue_from_check_receipt(ledger_objects: Mapping[str, bytes], ledger_ref: str, row: Mapping[str, Any] = REQUIRED_CHECKS, *,
                                    observed_base: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """CHECK_DERIVED_ISSUES_ARE_DERIVED_FROM_THE_LEDGERED_FAILING_RECEIPT. The sanctioned, deterministic derivation of a
    NATIVE SV_ISSUE from an org-ledger-appended non-ALLOW check receipt, read only from the supplied bytes of
    refs/stegverse/organization-ledger (`ledger_objects`: "<commit>:<path>" -> bytes):
      ledger_ref = refs/stegverse/organization-ledger@<commit>:receipts/<hex>.json names the sealed
      stegverse.organization-transition-receipt/v1 (aggregate_repo_transition.py:1073-1089);
      its repo_receipt_sha256 (verify_source, :627-651) names the sealed stegverse.repo-transition-receipt/v1 the org
      ledger retains beside it at source-receipts/<hex>.json (ledger_store.source_key; :1064-1066; readback :89-91);
      the check receipt is that repo receipt's $.evidence (emit.py:116), self-identified.
    The issue_id depends only on these bytes, the ref and the row, never on who derives it."""
    e = "derive_issue_from_check_receipt"
    inv = CHECK_DERIVED_ISSUE_INVARIANT

    def not_ledgered(why: str) -> Refusal:
        return _fail("SOURCE_RECEIPT_NOT_LEDGERED", inv,
                     "the org-ledger writer appends the verifier's receipt (Lane D sv_check_receipt operation); derive from the "
                     "org receipt at its ledger ref and the repo receipt the org ledger retains beside it", e,
                     "after the org writer appends the receipt; nothing was derived", ledger_ref=ledger_ref, detail=why)

    def not_check(why: str) -> Refusal:
        return _fail("LEDGER_EVIDENCE_NOT_A_CHECK_RECEIPT", inv,
                     "the repo receipt's $.evidence is a stegverse.sv_check_receipt.v1 self-identified by $.evidence.schema "
                     "(or $.evidence.kind == 'sv_check_receipt'), appended by the sv_check_receipt operation", e,
                     "after the check receipt is appended through the sv_check_receipt operation; nothing was derived",
                     ledger_ref=ledger_ref, detail=why)

    m = LEDGER_RECEIPT_REF.match(ledger_ref) if isinstance(ledger_ref, str) else None
    if m is None:
        raise not_ledgered("ref is not refs/stegverse/organization-ledger@<commit>:receipts/<hex>.json")
    commit = m.group("commit")
    org = _sealed_at(ledger_objects, commit, m.group("path"), "sha256:" + m.group("hex"))
    if org is None or org.get("schema") != ORG_RECEIPT_SCHEMA:
        raise not_ledgered("no sealed organization-transition receipt at the ref")
    repo_sha = org.get("repo_receipt_sha256")
    if not isinstance(repo_sha, str) or not DIGEST.match(repo_sha):
        raise not_check("the org receipt names no repo receipt (repo_receipt_sha256)")
    repo = _sealed_at(ledger_objects, commit, "source-receipts/%s.json" % repo_sha.split(":", 1)[1], repo_sha)
    if repo is None:
        raise not_ledgered("the repo receipt the org receipt names is not retained (sealed) in the org ledger at that commit")
    if repo.get("schema") != REPO_RECEIPT_SCHEMA:
        raise not_check("the retained source is not a repo-transition receipt")
    op = (org.get("boundary_evidence") or {}).get("operation") if isinstance(org.get("boundary_evidence"), Mapping) else None
    if op is not None and op != SV_CHECK_RECEIPT_OPERATION:
        raise not_check("boundary_evidence.operation is %r, not 'sv_check_receipt'" % (op,))
    r = _check_receipt_from_evidence(repo.get("evidence"))
    if r is None:
        raise not_check("$.evidence is not self-identified as an sv_check_receipt")
    try:
        validate_check_receipt(r)
    except Refusal as x:
        if x.record["failure_code"] == "CHECK_ID_UNDECLARED":
            raise
        raise not_check("$.evidence is not a valid stegverse.sv_check_receipt.v1: " + x.record["failure_code"])
    if r["disposition"] == "ALLOW":
        raise _deny("CHECK_RECEIPT_NOT_FAILING", inv, "only a non-ALLOW check receipt derives an issue", e,
                    "nothing to derive; the check passed", ledger_ref=ledger_ref)
    if not isinstance(observed_base, Mapping) or type(observed_base.get("registry_generation")) is not int \
            or not (isinstance(observed_base.get("ledger_head"), str) and GIT_SHA.match(observed_base["ledger_head"])):
        raise _fail("ISSUE_OBSERVED_BASE_UNSUPPLIED", inv,
                    "supply the observed base {registry_generation, ledger_head} the check ran against (not part of issue_id)", e,
                    "after the base is supplied; nothing was derived")
    path = check_command_surface(r["check_id"], row)
    rec = {"schema": ISSUE_SCHEMA, "record_mode": "NATIVE",
           "disposition": {"disposition": r["disposition"], **{f: r[f] for f in SIX_FIELDS}},
           "violated_invariant": _violated_check_invariant(r["check_id"], row),
           "source_receipt": {"kind": "ORGANIZATION_LEDGER_RECEIPT", "ledger_ref": ledger_ref, "receipt_sha256": org["receipt_sha256"]},
           "surface": {"kind": surface_kind(path), "path": path},
           "owning_goal": row["owning_goal"],
           "observed_base": {k: observed_base[k] for k in ("registry_generation", "ledger_head", "tree_sha") if k in observed_base},
           "opened_by_session": ISSUE_DERIVATION_SESSION, "lifecycle_state": "OPENED",
           "resolution_class": row["check_derived_issue_rule"]["resolution_class"], "hb_epoch": r["hb_epoch"]}
    rec["issue_id"] = issue_identity(rec)
    return validate_issue(seal(rec, "issue_sha256"))


def is_s1_verifier(ref: Any) -> bool:
    """The NWI-S1 verifier (SV-LLM/.github#46), optionally qualified by a run: '#46', '#46@<commit>', '#46:<run>'."""
    return isinstance(ref, str) and (ref == S1_VERIFIER_REF or (len(ref) > len(S1_VERIFIER_REF) + 1
                                     and ref.startswith(S1_VERIFIER_REF) and ref[len(S1_VERIFIER_REF)] in "@:"))


def resolved_issue_facts(issues: Iterable[Mapping[str, Any]], ledger_objects: Mapping[str, bytes],
                         issue_set: Iterable[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The observed facts admission needs about the SV_ISSUEs a change cites (STAGE_GATE_RECEIPT_DERIVES_NATIVE_ISSUE).
    A receipt-derived issue is observed only if it is exactly what derive_issue_from_check_receipt yields from the
    supplied bytes of refs/stegverse/organization-ledger at its ledger_ref (so its receipt is ledgered and was appended by
    the org writer's sv_check_receipt operation); otherwise no fact is emitted and the issue counts as unobserved.
      receipt_ledger_paths: receipts/<org hex>.json and source-receipts/<repo hex>.json (the ledger keys);
      receipt_file_sha256: sha256 of those files' bytes (a change carrying the receipt anywhere);
      verifier_ref / emitter_session: the check receipt's verifier_ref, the only emitter identity the receipt carries;
      derived_issue_ids_from_receipt: every issue in `issue_set` naming the same source receipt;
      resolved_by: the change_id an SV_ISSUE_RESOLVE recorded, or null.
    Pure over the supplied bytes; nothing is read, minted or clocked."""
    pool = [dict(i) for i in (issue_set if issue_set is not None else issues)]
    out = []
    for i in issues:
        rec = validate_issue(i)
        fact = {"issue_id": rec["issue_id"], "record_mode": rec["record_mode"], "source_kind": rec["source_receipt"]["kind"],
                "lifecycle_state": rec["lifecycle_state"], "resolved_by": rec.get("resolved_by"), "fixture_only": False}
        if fact["source_kind"] == "ORGANIZATION_LEDGER_RECEIPT":
            ref = rec["source_receipt"]["ledger_ref"]
            try:
                again = derive_issue_from_check_receipt(ledger_objects, ref, observed_base=rec["observed_base"])
            except Refusal:
                continue  # not derivable from these ledger bytes: unobserved
            if again["issue_id"] != rec["issue_id"]:
                continue
            m = LEDGER_RECEIPT_REF.match(ref)
            commit = m.group("commit")
            org_bytes = ledger_objects[commit + ":" + m.group("path")]
            org = json.loads(org_bytes)
            repo_key = "source-receipts/%s.json" % org["repo_receipt_sha256"].split(":", 1)[1]
            repo_bytes = ledger_objects[commit + ":" + repo_key]
            r = _check_receipt_from_evidence(json.loads(repo_bytes).get("evidence")) or {}
            fact.update({"ledger_ref": ref, "receipt_sha256": rec["source_receipt"]["receipt_sha256"], "check_id": r.get("check_id"),
                         "receipt_ledger_paths": sorted([m.group("path"), repo_key]),
                         "receipt_file_sha256": sorted({"sha256:" + hashlib.sha256(b).hexdigest() for b in (org_bytes, repo_bytes)}),
                         "verifier_ref": r.get("verifier_ref"), "emitter_session": r.get("verifier_ref"),
                         "derived_issue_ids_from_receipt": sorted({p["issue_id"] for p in pool
                                                                   if (p.get("source_receipt") or {}).get("receipt_sha256")
                                                                   == rec["source_receipt"]["receipt_sha256"]})})
        out.append(fact)
    return sorted(out, key=lambda f: f["issue_id"])


LEDGER_AT_REF = re.compile(r"^refs/stegverse/organization-ledger@(?P<commit>[0-9a-f]{40})$")


def derive_resolved_issue_facts(ledger_objects: Mapping[str, bytes], ledger_ref: Any, change: Mapping[str, Any],
                                issues: Iterable[Mapping[str, Any]], *, evaluations: Iterable[Mapping[str, Any]] | None = None,
                                change_commits: Mapping[str, Any] | None = None,
                                contract_pins: Any = None) -> list[dict[str, Any]]:
    """PUBLIC, pure and re-derivable (TVC#519 re-derives instead of trusting supplied facts; admission uses the same
    function when it is given ledger bytes). Inputs:
      ledger_objects  "<commit>:<path>" -> bytes of the target repository's refs/stegverse/organization-ledger;
      ledger_ref      "refs/stegverse/organization-ledger@<commit>", the ledger state the change is bound to; <commit> must be
                      the change's base_ref.ledger_head (CHANGE_BINDS_TARGET_REPOSITORY_LEDGER), else FAIL_CLOSED
                      RESOLVED_ISSUE_LEDGER_NOT_CHANGE_BASE;
      change          the SV_CHANGE (its resolves names the cited issues);
      issues          the SV_ISSUE records known (cited and others; the others count only for ONE_RECEIPT_DERIVES_ONE_ISSUE).
    Output: resolved_issue_facts() for the cited issues, keeping a receipt-derived fact only if every receipt file it names
    (receipt_ledger_paths) is present at <commit> with the same bytes (receipt_file_sha256), i.e. the receipt is on the
    ledger as of the change's base. A cited issue with no record, or not derivable from these bytes, yields no fact
    (unobserved). Nothing is read, minted or clocked; the same inputs always give the same facts.
    Gate-derived issues (check_id a stage gate check; GATE_RECEIPT_PAIR_RESOLVES_GATE_DERIVED_ISSUE, commit 4) are kept even
    when their base receipt is not at <commit>, and carry resolution_pair(...) built from `evaluations` (the STAGE_GATE outcomes'
    {subject, receipt_ref}), `change_commits` ({base_commit, head_commit}, observed) and `contract_pins` (the gate declaration's
    contract-pins.json, the only manifest source);
    verify_resolutions decides the pair with its own six-field codes."""
    e = "derive_resolved_issue_facts"
    m = LEDGER_AT_REF.match(ledger_ref) if isinstance(ledger_ref, str) else None
    head = (change.get("base_ref") or {}).get("ledger_head") if isinstance(change, Mapping) else None
    if m is None or m.group("commit") != head:
        raise _fail("RESOLVED_ISSUE_LEDGER_NOT_CHANGE_BASE", RESOLVES_PREDICATE,
                    "ledger_ref is refs/stegverse/organization-ledger@<the change's base_ref.ledger_head> (the target repository's own ledger)",
                    e, "re-derive at the change's bound ledger head; nothing was derived", ledger_ref=ledger_ref, base_ledger_head=head)
    pool = [dict(i) for i in issues]
    cited = set(change.get("resolves") or [])
    facts = resolved_issue_facts([i for i in pool if i.get("issue_id") in cited], ledger_objects, issue_set=pool)
    out = []
    for f in facts:
        if f["source_kind"] == "ORGANIZATION_LEDGER_RECEIPT" and f.get("check_id") in GATE_CHECKS:
            f["resolution_pair"] = resolution_pair(ledger_objects, head, change, f["ledger_ref"], evaluations, change_commits, contract_pins)
            out.append(f)
            continue
        if f["source_kind"] == "ORGANIZATION_LEDGER_RECEIPT":
            have = {"sha256:" + hashlib.sha256(ledger_objects[head + ":" + p]).hexdigest()
                    for p in f.get("receipt_ledger_paths") or [] if head + ":" + p in ledger_objects}
            if len(f.get("receipt_ledger_paths") or []) == 0 or have != set(f.get("receipt_file_sha256") or []) \
                    or not all(head + ":" + p in ledger_objects for p in f["receipt_ledger_paths"]):
                continue  # not on the ledger as of the change's base: unobserved
        out.append(f)
    return out


# ------------------------------------------------------------------ GATE RECEIPT PAIR (commit 4; orchestrator 16:58Z)
# A stage-gate-derived issue is SOURCED by the BASE-side failing gate receipt (stage-evaluation subject at the change's base
# commit; derive_issue_from_check_receipt) and RESOLVED by the HEAD-side ALLOW gate receipt (subject at the change's head).
GATE_PAIR_PREDICATE = "GATE_RECEIPT_PAIR_RESOLVES_GATE_DERIVED_ISSUE"
# GATE_MANIFEST_IS_THE_CONTRACT_PINNED_MANIFEST (orchestrator ~17:10Z, under SUBJECT_NEVER_SUPPLIES_ITS_OWN_ACCEPTANCE_CRITERIA):
# the gate manifest is the one the gate declaration's data/sv-work-items/contract-pins.json pins (manifest_source CONTRACT_PINS),
# never the blob at evaluated_commit (which only identifies the subject). Base and head subjects carry exactly that pinned
# blob; there is no other equivalence.
GATE_MANIFEST_PREDICATE = "GATE_MANIFEST_IS_THE_CONTRACT_PINNED_MANIFEST"
MANIFEST_SOURCE = "CONTRACT_PINS"
CONTRACT_PINS_FILE = "data/sv-work-items/contract-pins.json"


def pinned_gate_manifest(contract_pins: Any, stage_id: Any) -> dict[str, Any] | None:
    """The stage manifest's {file, blob, sha256} as contract-pins.json (bytes or parsed) pins it, plus the manifest's own
    sha256 (contract_pins_sha256 when bytes are given); None if not pinned there."""
    data = contract_pins
    cp_sha = None
    if isinstance(contract_pins, (bytes, bytearray)):
        cp_sha = "sha256:" + hashlib.sha256(contract_pins).hexdigest()
        try:
            data = json.loads(contract_pins)
        except ValueError:
            return None
    if not isinstance(data, Mapping) or not isinstance(stage_id, str) or not isinstance(data.get("files"), Mapping):
        return None
    rel = "data/sv-work-items/stages/%s.json" % stage_id
    pin = data["files"].get(rel)
    if not isinstance(pin, Mapping) or not (isinstance(pin.get("blob"), str) and GIT_SHA.match(pin["blob"])):
        return None
    return {"file": rel, "blob": pin["blob"], "sha256": pin.get("sha256"), "contract_pins_sha256": cp_sha}


def manifest_read_from_subject(subject: Mapping[str, Any], pinned: Mapping[str, Any], entry: str) -> Refusal:
    return _deny("GATE_MANIFEST_READ_FROM_SUBJECT", GATE_MANIFEST_PREDICATE,
                 "the subject's manifest_blob is the blob the gate declaration's contract-pins.json pins (manifest_source "
                 "CONTRACT_PINS); a subject never supplies its own acceptance criteria", entry,
                 "re-evaluate with the contract-pinned manifest; nothing was admitted",
                 manifest_blob=subject.get("manifest_blob"), pinned_manifest_blob=pinned.get("blob"), evaluated_commit=subject.get("evaluated_commit"))


def _ledgered_check_receipt(ledger_objects: Mapping[str, bytes], ref: Any, head: str) -> dict[str, Any] | None:
    """The check receipt the org ledger holds at `ref` (org receipt -> retained repo receipt -> $.evidence), with whether both
    files are present with the same bytes at the change's base ledger head `head`; None if not readable at `ref`."""
    m = LEDGER_RECEIPT_REF.match(ref) if isinstance(ref, str) else None
    if m is None:
        return None
    commit = m.group("commit")
    org = _sealed_at(ledger_objects, commit, m.group("path"), "sha256:" + m.group("hex"))
    if org is None or org.get("schema") != ORG_RECEIPT_SCHEMA or not (isinstance(org.get("repo_receipt_sha256"), str)
                                                                      and DIGEST.match(org["repo_receipt_sha256"])):
        return None
    repo_key = "source-receipts/%s.json" % org["repo_receipt_sha256"].split(":", 1)[1]
    repo = _sealed_at(ledger_objects, commit, repo_key, org["repo_receipt_sha256"])
    r = _check_receipt_from_evidence(repo.get("evidence")) if isinstance(repo, Mapping) and repo.get("schema") == REPO_RECEIPT_SCHEMA else None
    if r is None:
        return None
    try:
        validate_check_receipt(r)
    except Refusal:
        return None
    paths = sorted([m.group("path"), repo_key])
    files = {p: ledger_objects[commit + ":" + p] for p in paths}
    at_base = all(ledger_objects.get(head + ":" + p) == b for p, b in files.items())
    return {"receipt_ledger_ref": ref, "check_id": r["check_id"], "disposition": r["disposition"], "change_digest": r["change_digest"],
            "head_sha": r["head_sha"], "verifier_ref": r["verifier_ref"], "receipt_ledger_paths": paths,
            "receipt_file_sha256": sorted({"sha256:" + hashlib.sha256(b).hexdigest() for b in files.values()}), "ledgered_at_base": at_base}


def _pair_side(ledger_objects: Mapping[str, bytes], head: str, ev: Any) -> dict[str, Any]:
    subject = ev.get("subject") if isinstance(ev, Mapping) else None
    try:
        digest = stage_evaluation_digest(subject) if isinstance(subject, Mapping) else None
    except Refusal:
        digest = None
    return {"subject": json.loads(json.dumps(subject)) if digest else None, "subject_digest": digest,
            "receipt": _ledgered_check_receipt(ledger_objects, ev.get("receipt_ref") if isinstance(ev, Mapping) else None, head)}


def resolution_pair(ledger_objects: Mapping[str, bytes], head: str, change: Mapping[str, Any], source_ref: str,
                    evaluations: Iterable[Mapping[str, Any]] | None, change_commits: Any,
                    contract_pins: Any = None) -> dict[str, Any]:
    """The observed pair for one gate-derived issue (pure). `evaluations`: the STAGE_GATE outcomes' {subject, receipt_ref}
    (receipt_ref = the org ledger ref of that evaluation's gate receipt); the base side is the one whose receipt_ref is the
    issue's source ledger_ref, the head side the other evaluation of the same stage (an ALLOW at the change's head commit
    first). `change_commits`: the observed {base_commit, head_commit} of the change (read from git by the caller; the
    GitHub projection is never authority). `contract_pins`: the gate declaration's contract-pins.json (bytes or parsed); the
    pinned manifest is read from it (manifest_source CONTRACT_PINS). verify_resolution_pair decides."""
    evs = [dict(x) for x in evaluations or [] if isinstance(x, Mapping)]
    base_ev = next((x for x in evs if x.get("receipt_ref") == source_ref), {"subject": None, "receipt_ref": source_ref})
    base = _pair_side(ledger_objects, head, base_ev)
    cc = change_commits if isinstance(change_commits, Mapping) else {}
    sid = (base["subject"] or {}).get("stage_id")
    others = [_pair_side(ledger_objects, head, x) for x in evs if x.get("receipt_ref") != source_ref]
    others = [s for s in others if s["subject"] is not None and (sid is None or s["subject"]["stage_id"] == sid)]
    others.sort(key=lambda s: (not ((s["receipt"] or {}).get("disposition") == "ALLOW" and s["subject"]["evaluated_commit"] == cc.get("head_commit")),
                               (s["receipt"] or {}).get("disposition") != "ALLOW", canon(s)))
    return {"rule": GATE_PAIR_PREDICATE, "ledger_head": head, "target_repository": change.get("target_repository"),
            "change_commits": {"base_commit": cc.get("base_commit"), "head_commit": cc.get("head_commit")},
            "manifest_source": MANIFEST_SOURCE,
            "pinned_manifest": pinned_gate_manifest(contract_pins, sid or (others[0]["subject"]["stage_id"] if others else None)),
            "base": base, "head": others[0] if others else None}


def _pair_refusal(deny: bool, code: str, repair: str, nxt: str, **d: Any) -> Refusal:
    return (_deny if deny else _fail)(code, GATE_PAIR_PREDICATE, repair, "verify_resolution_pair", nxt, **d)


def verify_resolution_pair(pair: Any, base_check_id: Any = None) -> dict[str, Any]:
    """GATE_RECEIPT_PAIR_RESOLVES_GATE_DERIVED_ISSUE over resolution_pair() (pure; each failure has its own six-field code):
      FAIL_CLOSED GATE_PAIR_CHANGE_COMMITS_UNOBSERVED  the change's base/head commits are not observed;
      FAIL_CLOSED GATE_PAIR_BASE_RECEIPT_MISSING       no base-side evaluation (subject) or its receipt is not on the target
                                                       repository's ledger at the change's base ledger_head;
      FAIL_CLOSED GATE_PAIR_HEAD_RECEIPT_MISSING       the same for the head side;
      DENY GATE_PAIR_SUBJECT_NOT_BOUND_BY_RECEIPT      a receipt's change_digest is not its subject's digest, or its head_sha is
                                                       not the subject's evaluated_commit;
      DENY GATE_PAIR_HEAD_RECEIPT_NOT_ALLOW            the head-side gate receipt is not an ALLOW of the same gate check;
      DENY GATE_PAIR_REPOSITORY_MISMATCH               the subjects name different repositories, or not the change's target;
      DENY GATE_PAIR_MANIFEST_MISMATCH                 different stage_id or manifest_blob (an exact match is required);
      FAIL_CLOSED GATE_PAIR_PINNED_MANIFEST_UNOBSERVED the gate declaration's contract-pins.json (pinned manifest) is not supplied;
      DENY GATE_MANIFEST_READ_FROM_SUBJECT             the subjects' manifest_blob is not the contract-pinned one;
      DENY GATE_PAIR_SUBJECT_COMMIT_WRONG              base subject not at the change's base commit, or head subject not at its head."""
    p = pair if isinstance(pair, Mapping) else {}
    cc = p.get("change_commits") or {}
    if not all(isinstance(cc.get(k), str) and GIT_SHA.match(cc[k]) for k in ("base_commit", "head_commit")):
        raise _pair_refusal(False, "GATE_PAIR_CHANGE_COMMITS_UNOBSERVED", "observe the change's base and head commits (git), never the GitHub projection",
                            "re-derive with the observed commits; nothing was admitted", change_commits=cc or None)
    sides = {}
    for name in ("base", "head"):
        s = p.get(name) if isinstance(p.get(name), Mapping) else {}
        rc = s.get("receipt") if isinstance(s.get("receipt"), Mapping) else None
        if s.get("subject") is None or not s.get("subject_digest") or rc is None or rc.get("ledgered_at_base") is not True:
            raise _pair_refusal(False, "GATE_PAIR_%s_RECEIPT_MISSING" % name.upper(),
                                "the %s-side nwi-s0-exit-gate receipt (stage-evaluation subject at the change's %s commit) is appended by the "
                                "org writer to the target repository's ledger and is present at the change's base ledger_head, and its "
                                "evaluation subject is supplied" % (name.upper(), name),
                                "after the NWI-S1 verifier's %s-side receipt is ledgered; re-propose on that ledger head" % name,
                                ledger_head=p.get("ledger_head"), receipt=rc and rc.get("receipt_ledger_ref"),
                                subject_supplied=s.get("subject") is not None)
        sides[name] = (s["subject"], s["subject_digest"], rc)
    for name, (subj, digest, rc) in sides.items():
        if rc["change_digest"] != digest or rc["head_sha"] != subj["evaluated_commit"]:
            raise _pair_refusal(True, "GATE_PAIR_SUBJECT_NOT_BOUND_BY_RECEIPT",
                                "each receipt binds its subject: change_digest = stage_evaluation_digest(subject), head_sha = evaluated_commit",
                                "supply the subject the receipt was minted for", side=name, expected=digest, change_digest=rc["change_digest"])
    (bs, _, brc), (hs, _, hrc) = sides["base"], sides["head"]
    if hrc["disposition"] != "ALLOW" or hrc["check_id"] != brc["check_id"] or (base_check_id is not None and brc["check_id"] != base_check_id):
        raise _pair_refusal(True, "GATE_PAIR_HEAD_RECEIPT_NOT_ALLOW", "the head-side receipt is an ALLOW of the same gate check",
                            "after the gate passes at the change's head; nothing was admitted", head_disposition=hrc["disposition"],
                            head_check_id=hrc["check_id"], base_check_id=brc["check_id"])
    if bs["repository"] != hs["repository"] or bs["repository"] != p.get("target_repository"):
        raise _pair_refusal(True, "GATE_PAIR_REPOSITORY_MISMATCH", "both subjects name the change's target repository",
                            "re-evaluate the gate in the target repository", base=bs["repository"], head=hs["repository"],
                            target_repository=p.get("target_repository"))
    if bs["stage_id"] != hs["stage_id"] or bs["manifest_blob"] != hs["manifest_blob"]:
        raise _pair_refusal(True, "GATE_PAIR_MANIFEST_MISMATCH",
                            "both subjects bind exactly the same contract-pinned stage manifest (stage_id and manifest_blob)",
                            "re-evaluate both sides under the one contract-pinned manifest", base=[bs["stage_id"], bs["manifest_blob"]],
                            head=[hs["stage_id"], hs["manifest_blob"]])
    pin = p.get("pinned_manifest") if isinstance(p.get("pinned_manifest"), Mapping) else None
    if pin is None or not (isinstance(pin.get("blob"), str) and GIT_SHA.match(pin["blob"])):
        raise _pair_refusal(False, "GATE_PAIR_PINNED_MANIFEST_UNOBSERVED",
                            "supply the gate declaration's contract-pins.json; the gate manifest is read only from it (CONTRACT_PINS)",
                            "re-derive with contract-pins.json; nothing was admitted")
    if bs["manifest_blob"] != pin["blob"]:
        raise manifest_read_from_subject(bs, pin, "verify_resolution_pair")
    if bs["evaluated_commit"] != cc["base_commit"] or hs["evaluated_commit"] != cc["head_commit"]:
        raise _pair_refusal(True, "GATE_PAIR_SUBJECT_COMMIT_WRONG",
                            "the base receipt's subject is at the change's base commit and the head receipt's at its head commit",
                            "re-evaluate the gate at the change's base and head commits", base_subject=bs["evaluated_commit"],
                            head_subject=hs["evaluated_commit"], change_commits=dict(cc))
    return {"disposition": "ALLOW", "failed_predicate": None, "base_receipt": brc["receipt_ledger_ref"], "head_receipt": hrc["receipt_ledger_ref"],
            "pinned_manifest_blob": pin["blob"]}


def verify_resolutions(obs: Mapping[str, Any], *, fixture_mode: bool = False) -> dict[str, Any]:
    """STAGE_GATE_RECEIPT_DERIVES_NATIVE_ISSUE at admission, for every NATIVE SV_CHANGE, over admission_inputs():
      DENY SV_CHANGE_RESOLVES_NOTHING (CHANGE_RESOLVES_CLAIMED_SV_ISSUES): resolves is empty, or no cited issue is observed
        (a receipt-derived issue exists only once the org writer has appended its receipt; before that the change
        resolves nothing; never relaxed);
      FAIL_CLOSED RESOLVED_ISSUE_UNOBSERVED: some cited issue is observed, another is not;
      FAIL_CLOSED HISTORICAL_RECORD_NOT_ADMISSIBLE (ADMITTED_RECORDS_ARE_NATIVE): a cited issue is MIGRATED_HISTORICAL
        (a migrated GitHub issue is never admissible; it is resolved through a NATIVE successor);
      DENY SV_CHANGE_SELF_SOURCED_ISSUE (RESOLVING_CHANGE_DID_NOT_SOURCE_ITS_ISSUE): for a receipt-derived issue, the
        change touches the receipt's ledger path or carries the receipt's bytes, a writer (or the declared session) is
        the receipt's emitter, or the receipt's verifier_ref is not the NWI-S1 verifier;
      FAIL_CLOSED SV_ISSUE_SOURCE_RECEIPT_COLLISION (ONE_RECEIPT_DERIVES_ONE_ISSUE): another issue names the same receipt;
      DENY SV_ISSUE_ALREADY_RESOLVED (RECEIPT_DERIVED_ISSUE_IS_RESOLVED_ONCE): another change already resolved it.
    A fixture_only fact counts only in fixture_mode."""
    e = "verify_resolutions"
    cited = list(obs.get("resolves") or [])
    if not cited:
        raise _deny("SV_CHANGE_RESOLVES_NOTHING", RESOLVES_PREDICATE, "resolves lists at least one svi: id", e,
                    "cite the SV_ISSUE derived from the ledgered failing receipt once the org writer has appended it")
    facts = {f.get("issue_id"): f for f in obs.get("resolved_issues") or []
             if isinstance(f, Mapping) and f.get("issue_id") in cited and (fixture_mode or f.get("fixture_only") is not True)}
    migrated = sorted(i for i, f in facts.items() if f.get("record_mode") != "NATIVE")
    if migrated:
        r = historical_refusal(e)
        r.record["migrated_issues"] = migrated
        raise r
    if not facts:
        raise _deny("SV_CHANGE_RESOLVES_NOTHING", RESOLVES_PREDICATE,
                    "cite an SV_ISSUE that is observed: a receipt-derived issue is derived (derive_issue_from_check_receipt) only "
                    "from a receipt the org writer has appended to refs/stegverse/organization-ledger", e,
                    "after the org writer appends the receipt and the issue is derived from it; nothing was admitted", unobserved=sorted(cited))
    missing = sorted(set(cited) - set(facts))
    if missing:
        raise _fail("RESOLVED_ISSUE_UNOBSERVED", RESOLVES_PREDICATE,
                    "every cited svi: id is an observed SV_ISSUE (receipt-derived: derivable from the ledgered receipt)", e,
                    "after every cited issue is observed, or cite only the observed ones", unobserved=missing)
    derived = _derived_writer_or_none(obs)
    writers = set(obs.get("writer_sessions") or []) | ({derived} if derived else set())
    paths, blobs = set(obs.get("touched_paths") or []), set(obs.get("content_blob_digests") or [])
    for i in sorted(facts):
        f = facts[i]
        if f.get("source_kind") != "ORGANIZATION_LEDGER_RECEIPT":
            continue
        why = [w for w, bad in (("the change touches the receipt's ledger path", bool(paths & set(f.get("receipt_ledger_paths") or []))),
                                ("the change carries the receipt's bytes", bool(blobs & set(f.get("receipt_file_sha256") or []))),
                                ("a writer of the change is the receipt's emitter", f.get("emitter_session") in writers),
                                ("the receipt's verifier_ref is not the NWI-S1 verifier", not is_s1_verifier(f.get("verifier_ref")))) if bad]
        if why:
            raise _deny("SV_CHANGE_SELF_SOURCED_ISSUE", SELF_SOURCED_PREDICATE,
                        "the issue's receipt is emitted by the NWI-S1 verifier (" + S1_VERIFIER_REF + ") and appended by the org writer "
                        "(Labs#3255/#3270), never minted or ledgered by the change that resolves it", e,
                        "propose a change that only repairs the failing predicate; the verifier re-runs the gate", issue_id=i, why=why)
        ids = set(f.get("derived_issue_ids_from_receipt") or [])
        if ids != {i}:
            raise source_receipt_collision({str(f.get("receipt_sha256")): sorted(ids | {i})}, e)
        if f.get("resolved_by") not in (None, obs.get("change_id")):
            raise _deny("SV_ISSUE_ALREADY_RESOLVED", RESOLVED_ONCE_PREDICATE,
                        "a receipt-derived issue is resolved by exactly one change; cite an open issue", e,
                        "nothing to resolve; a new failing receipt derives a new issue", issue_id=i, resolved_by=f.get("resolved_by"))
    for i in sorted(facts):
        f = facts[i]
        if f.get("source_kind") != "ORGANIZATION_LEDGER_RECEIPT" or f.get("check_id") not in GATE_CHECKS:
            continue
        if "resolution_pair" not in f:
            if fixture_mode and f.get("fixture_only") is True:
                continue  # a pre-commit-4 fixture fact (corpus lines are never rewritten); never on the real path
            raise _pair_refusal(False, "GATE_PAIR_HEAD_RECEIPT_MISSING", "a gate-derived issue resolves only with its head-side ALLOW "
                                "gate receipt (derive_resolved_issue_facts with the stage evaluations)", "re-derive the facts with the "
                                "stage evaluations; nothing was admitted", issue_id=i)
        hr = ((f["resolution_pair"].get("head") or {}).get("receipt") or {}) if isinstance(f["resolution_pair"], Mapping) else {}
        why = [w for w, bad in (("the change touches the head receipt's ledger path", bool(paths & set(hr.get("receipt_ledger_paths") or []))),
                                ("the change carries the head receipt's bytes", bool(blobs & set(hr.get("receipt_file_sha256") or []))),
                                ("a writer of the change is the head receipt's emitter", hr.get("verifier_ref") in writers),
                                ("the head receipt's verifier_ref is not the NWI-S1 verifier",
                                 bool(hr) and not is_s1_verifier(hr.get("verifier_ref")))) if bad]
        if why:
            raise _deny("SV_CHANGE_SELF_SOURCED_ISSUE", SELF_SOURCED_PREDICATE,
                        "both gate receipts are emitted by the NWI-S1 verifier and appended by the org writer, never by the change", e,
                        "propose a change that only repairs the failing predicate; the verifier re-runs the gate", issue_id=i, why=why)
        verify_resolution_pair(f["resolution_pair"], f.get("check_id"))
    return {"disposition": "ALLOW", "failed_predicate": None, "resolved": sorted(facts)}


def admission_inputs(change: Mapping[str, Any], current_base: Mapping[str, Any],
                     signoff_receipts: Iterable[Mapping[str, Any]] = (),
                     hb_epoch_readback: Mapping[str, Any] | None = None,
                     resolved_issues: Iterable[Mapping[str, Any]] | None = None, *,
                     ledger_objects: Mapping[str, bytes] | None = None, ledger_ref: Any = None,
                     issue_records: Iterable[Mapping[str, Any]] | None = None,
                     evaluations: Iterable[Mapping[str, Any]] | None = None, change_commits: Mapping[str, Any] | None = None,
                     contract_pins: Any = None, push_receipts: Iterable[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """The observed inputs the admission predicate and the scenario corpus bind to (registry/ledger, not GitHub).
    With `ledger_objects` the resolved-issue facts are DERIVED by derive_resolved_issue_facts(ledger_objects, ledger_ref,
    change, issue_records), the same public function TVC re-derives with; supplying facts as well is refused.
    `hb_epoch_readback` is Lane C's sealed base-state readback receipt (Labs#3266) for the change's base, or None.
    `resolved_issues` are the facts resolved_issue_facts() observed for the cited SV_ISSUEs (none: nothing observed).
    `push_receipts` are the sealed sv-push-receipt.v1 receipts (Labs#3267) the organization ledger holds for the change's branch
    and `change_commits` its observed {base_commit, head_commit}: the branch writer is derived from them (derive_branch_writer)."""
    if ledger_objects is not None:
        if resolved_issues is not None:
            raise _fail("RESOLVED_ISSUE_FACTS_DOUBLY_SOURCED", RESOLVES_PREDICATE,
                        "supply ledger bytes (facts are derived) or facts, not both", "admission_inputs",
                        "re-run with one source of resolved-issue facts")
        resolved_issues = derive_resolved_issue_facts(ledger_objects, ledger_ref, change, issue_records or [], evaluations=evaluations,
                                                      change_commits=change_commits, contract_pins=contract_pins)
    checks, signoffs = required_for(change["touched_paths"])
    ws = [c["writer_session"] for c in change["content"]]
    writers = sorted({w["session"] for w in ws if w["evidence_class"] != UNKNOWN})
    grants = sorted(g["session"] for g in change.get("co_author_grants") or [] if _str((g or {}).get("receipt_ref")))
    return {
        "record_mode": change.get("record_mode"),
        "base_ref": dict(change["base_ref"]),
        "current_base": dict(current_base),
        "head_change_digest": change["head"]["change_digest"],
        "writer_sessions": writers,
        "co_author_grants": grants,
        "required_check_ids": checks,
        "validation_receipts": [dict(v) for v in change.get("validation_receipts") or []],
        "required_signoff_roles": signoffs,
        "signoffs": [dict(s) for s in change.get("signoffs") or []],
        "signoff_receipts": [dict(r) for r in signoff_receipts],
        "bound_request_digest": change.get("request_digest"),
        "recomputed_request_digest": request_digest(change),
        "touched_paths": sorted(change["touched_paths"]),
        "touched_surface_kinds": sorted({surface_kind(p) for p in change["touched_paths"]}),
        "admission_order_slot": change.get("admission_order_slot"),
        "supplied_hb_epoch": change.get("hb_epoch"),
        "native_unknown_pointers": [p for p in sentinel_pointers(change) if p not in ADMISSION_UNKNOWN_EXCLUDED],
        "hb_epoch_readback": dict(hb_epoch_readback) if isinstance(hb_epoch_readback, Mapping) else None,
        "change_id": change.get("change_id"),
        "target_repository": change.get("target_repository"),
        "resolves": sorted(change.get("resolves") or []),
        "content_blob_digests": sorted({c["blob_digest"] for c in change["content"] if isinstance(c.get("blob_digest"), str)}),
        "resolved_issues": [json.loads(json.dumps(f)) for f in resolved_issues or []],
        "push_receipts": None if push_receipts is None else [json.loads(json.dumps(r)) for r in push_receipts],
        "change_commits": ({"base_commit": change_commits.get("base_commit"), "head_commit": change_commits.get("head_commit")}
                           if isinstance(change_commits, Mapping) else None),
    }


def evaluate_admission(obs: Mapping[str, Any], covered_kinds: Iterable[str] | None = None, *,
                       fixture_mode: bool = False) -> dict[str, Any]:
    """Native admission predicate over admission_inputs(). Lane C's reference
    implementation (#164) replaces this by injection; the corpus tests run
    against whichever evaluator is supplied. Fixture receipts (a validation ref carrying #fixture:, a sign-off
    receipt with fixture_only true) count only when fixture_mode is True (scenario corpus and tests); the real
    admission path never sets it, so a fixture is never counted as a LEDGER_RECEIPT or a sign-off there."""
    e = "evaluate_admission"
    if obs.get("record_mode") != "NATIVE":
        raise historical_refusal(e)
    unknown = obs.get("native_unknown_pointers")
    if not isinstance(unknown, list):
        raise native_unknown_refusal(UNKNOWN, e)  # which fields hold UNKNOWN was itself not observed
    if unknown:
        raise native_unknown_refusal(sorted(unknown), e)
    if obs.get("base_ref") != obs.get("current_base"):
        raise _deny("BASE_STALE", "BASE_IS_CURRENT", "re-propose on the current registry generation and ledger head", e,
                    base_ref=obs.get("base_ref"), current_base=obs.get("current_base"))
    if obs.get("bound_request_digest") != obs.get("recomputed_request_digest"):
        raise _fail("REQUEST_DIGEST_MISMATCH", "AUTHORIZATION_BINDS_FULL_REQUEST",
                    "a successor decision bound to the full request digest", e)
    verify_branch_writer(obs, e)  # BRANCH_WRITER_IS_BRANCH_OWNER: derived from the sv-push-receipt chain, never declared
    # STAGE_GATE_RECEIPT_DERIVES_NATIVE_ISSUE: what the change resolves, for every NATIVE admission
    verify_resolutions(obs, fixture_mode=fixture_mode)
    required = list(obs.get("required_check_ids") or [])
    if not required:
        raise _fail("REQUIRED_CHECKS_ROW_ABSENT", "REQUIRED_CHECKS_ROW_RESOLVES", "resolve the required-checks row", e)
    undeclared = sorted({str(v.get("check_id")) for v in obs.get("validation_receipts") or []} - set(declared_check_ids()))
    if undeclared:
        raise check_id_undeclared(undeclared, e)
    by_id = {v.get("check_id"): v for v in obs.get("validation_receipts") or []
             if v.get("evidence_class") == "LEDGER_RECEIPT" and str(v.get("ref") or "").startswith("refs/")
             and (fixture_mode or FIXTURE_REF_MARK not in str(v.get("ref")))}
    unobserved = sorted(c for c in required if c not in by_id)
    if unobserved:
        artifact_only = sorted(c for c in unobserved if any(v.get("check_id") == c for v in obs.get("validation_receipts") or []))
        raise _fail("CHECK_SKIPPED_OR_UNOBSERVED", "MERGE_READY_REQUIRES_EVERY_JOB_RAN_AND_PASSED",
                    "a ledger-receipted ALLOW for every required check at the exact head (OBSERVED_ARTIFACT does not count)",
                    e, unobserved=unobserved, artifact_only=artifact_only)
    stale = sorted(c for c in required if by_id[c].get("change_digest") != obs.get("head_change_digest"))
    if stale:
        raise _fail("CHECK_SKIPPED_OR_UNOBSERVED", EXACT_HEAD_PREDICATE,
                    "a receipt whose change_digest equals head.change_digest for every required check (re-run at the exact head)", e, stale=stale)
    failed_closed = sorted(c for c in required if by_id[c].get("disposition") not in ("ALLOW", "DENY"))
    no_command = [c for c in failed_closed if not command_declared(c)]
    if no_command:
        st = REQUIRED_CHECKS["checks"][no_command[0]].get("command_status") or {}
        raise _fail("CHECK_COMMAND_UNDECLARED", CHECK_COMMAND_PREDICATE,
                    st.get("required_evidence_or_repair") or "declare the check's offline command in the row", e,
                    st.get("next_attempt") or "after the row declares the command", command_undeclared=no_command)
    if failed_closed:
        raise _fail("CHECK_SKIPPED_OR_UNOBSERVED", CHECK_ALLOW_PREDICATE,
                    "the check runs to an ALLOW receipt at the exact head (a FAIL_CLOSED receipt is not a pass)", e, failed_closed=failed_closed)
    denied = sorted(c for c in required if by_id[c].get("disposition") == "DENY")
    if denied:
        raise _deny("REQUIRED_CHECK_DENIED", "CHECK_PASSES", "every required check ALLOW", e, denied=denied)
    # ADMISSION_HB_EPOCH_IS_THE_BOUND_LEDGER_HEAD_EPOCH applies to every admission (the row requires the
    # supplied-epoch-binder-check on the 'all' surface); evaluated over the sealed readback after the check receipts
    # and before the sign-offs
    verify_admission_hb_epoch(obs.get("supplied_hb_epoch"), obs.get("hb_epoch_readback"),
                              (obs.get("base_ref") or {}).get("ledger_head"), fixture_mode=fixture_mode,
                              target_repository=obs.get("target_repository") or UNKNOWN)
    have = {s.get("role") for s in obs.get("signoffs") or []
            if signoff_resolves(s, obs.get("signoff_receipts") or [], obs.get("head_change_digest"), fixture_mode)}
    absent = sorted(set(obs.get("required_signoff_roles") or []) - have)
    if absent:
        raise _fail("SIGNOFF_RECEIPT_ABSENT", "REQUIRED_SIGNOFF_RECORDED", "a receipted sign-off by each required role", e, absent=absent)
    if covered_kinds is not None:
        need = set(REQUIRED_CHECKS["coverage_required_kinds"])
        gap = sorted(k for k in obs.get("touched_surface_kinds") or [] if k in need and k not in set(covered_kinds))
        if gap:
            raise _fail("NO_SCENARIO_COVERAGE_FOR_SURFACE", "SCENARIO_COVERAGE_FOR_EVERY_TOUCHED_SURFACE",
                        "derive the scenario class for the surface first (SCENARIO_CORPUS_APPEND)", e, uncovered=gap)
    return {"disposition": "ALLOW", "failed_predicate": None}


def historical_refusal(entry: str) -> Refusal:
    return _fail("HISTORICAL_RECORD_NOT_ADMISSIBLE", "ADMITTED_RECORDS_ARE_NATIVE",
                 "a superseding NATIVE record (SV_CHANGE_SUPERSEDE) whose every unknown_fields pointer holds an observed value",
                 entry, "propose the NATIVE successor; this record stays history and is never admitted")


def admit(obs: Mapping[str, Any], evaluator: Callable[..., dict] = evaluate_admission, **kw: Any) -> dict[str, Any]:
    try:
        return evaluator(obs, **kw)
    except Refusal as r:
        return dict(r.record)


# ------------------------------------------------------------------ lifecycle
TRANSITIONS = {t["transition_class"]: t for t in LIFECYCLE["transitions"]}
_wc = importlib.util.spec_from_file_location("sv_work_items_worker_claim", ROOT / "scripts/project_worker_claim_into_canonical_task.py")
worker_claim = importlib.util.module_from_spec(_wc)
_wc.loader.exec_module(worker_claim)


def claim_projection(worker_registry: Mapping[str, Any], task_id: str) -> dict[str, Any]:
    """CLAIMED is a projection of a WorkerCoordinator claim/fence (C3); no second claim path."""
    try:
        proj = worker_claim.worker_projection(dict(worker_registry), task_id)
    except SystemExit as exc:
        raise _fail("WORKERCOORDINATOR_CLAIM_AMBIGUOUS", "WORKERCOORDINATOR_HOLDS_EXACTLY_ONE_CLAIM",
                    "one WorkerCoordinator row per work item", "claim_projection", detail=str(exc))
    if not proj.get("matched") or not _str(proj.get("claim_ref")) or proj.get("fence_ref") in (None, ""):
        raise _fail("WORKERCOORDINATOR_CLAIM_ABSENT", "CLAIM_IS_A_WORKERCOORDINATOR_CLAIM_AND_FENCE",
                    "WorkerCoordinator records the claim and fence first (control/worker-registry.json)", "claim_projection",
                    "re-project once WorkerCoordinator holds the claim; nothing waits")
    return {"session": proj.get("worker_id"), "claim_ref": proj["claim_ref"], "fence_ref": proj["fence_ref"],
            "worker_instance_id": proj.get("worker_instance_id"), "projection_only": True}


def work_items_projection(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The canonical task's work_items[] (#160 6249905378 merged, C7): native id first, GitHub as a projection field, no approval flag."""
    out = []
    for r in records:
        kind = "SV_ISSUE" if r.get("schema") == ISSUE_SCHEMA else "SV_CHANGE"
        pj = r.get("projection") or {}
        out.append({"work_item_id": r.get("issue_id") or r.get("change_id"), "kind": kind,
                    "owning_goal": r.get("owning_goal"), "record_mode": r.get("record_mode"),
                    "record_sha256": r.get("issue_sha256") or r.get("request_digest"),
                    "lifecycle_state": r.get("lifecycle_state"),
                    "canonical_coordination_state": LIFECYCLE["canonical_coordination_state"][kind][r.get("lifecycle_state")],
                    "projection": {k: pj.get(k) for k in ("repo", "pr", "issue", "head_sha", "github_state")} if pj else None})
    return sorted(out, key=lambda w: w["work_item_id"])


COORDINATION_TASK_ID = "STEGVERSE-CANONICAL-WORK-COORDINATION-001"


def work_items_record(records: Iterable[Mapping[str, Any]], coordination_task_id: str = COORDINATION_TASK_ID) -> dict[str, Any]:
    """SF-9: one work-items record per coordination task; goal_index is the multi-goal index (UNKNOWN goals included)."""
    items = work_items_projection(records)
    index: dict[str, list[str]] = {}
    for w in items:
        index.setdefault(w["owning_goal"], []).append(w["work_item_id"])
    return {"schema": "stegverse.canonical-task-work-items.v1", "coordination_task_id": coordination_task_id,
            "goal_index": {g: sorted(ids) for g, ids in sorted(index.items())}, "work_items": items}


def _ledger_kw(ctx: Mapping[str, Any]) -> dict[str, Any]:
    """transition() context carrying ledger bytes: facts are derived (derive_resolved_issue_facts), never trusted."""
    if ctx.get("ledger_objects") is None:
        return {}
    return {"ledger_objects": ctx["ledger_objects"], "ledger_ref": ctx.get("ledger_ref"), "issue_records": ctx.get("issue_records") or [],
            "evaluations": ctx.get("evaluations"), "change_commits": ctx.get("change_commits"), "contract_pins": ctx.get("contract_pins")}


def _writer_kw(ctx: Mapping[str, Any]) -> dict[str, Any]:
    """transition() context carrying the change's push receipts and commits (change_commits once, with or without ledger bytes)."""
    kw = {"push_receipts": ctx.get("push_receipts")}
    if ctx.get("ledger_objects") is None:
        kw["change_commits"] = ctx.get("change_commits")
    return kw


def transition(transition_class: str, record: Mapping[str, Any] | None, *, hb_epoch: Any,
               context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate one lifecycle transition. Returns {disposition, ..., record}; never raises for a refusal."""
    ctx = dict(context or {})
    e = "transition"
    try:
        epoch_check(hb_epoch, e)
        t = TRANSITIONS.get(transition_class)
        if t is None:
            raise _fail("TRANSITION_UNDECLARED", "TRANSITION_IS_IN_LIFECYCLE_MANIFEST",
                        "declare the transition in data/sv-work-items/lifecycle-transitions.json", e)
        state = None if record is None or t["from_states"] == [None] else record.get("lifecycle_state")
        if state not in t["from_states"]:
            raise _deny("LIFECYCLE_STATE_NOT_ADMISSIBLE", "FROM_STATE_IS_DECLARED",
                        transition_class + " applies from " + repr(t["from_states"]), e, observed=state)
        new = dict(record or {})
        if transition_class == "SV_ISSUE_OPEN":
            validate_issue(record)
        if transition_class == "SV_ISSUE_CLAIM":
            if ctx.get("observed_generation") != (ctx.get("current_base") or {}).get("registry_generation"):
                raise _deny("STOP_STALE_COORDINATION", "SESSION_OBSERVED_REGISTRY_GENERATION_EQUALS_CURRENT",
                            "re-read the registry generation, then claim", e)
            new["claim"] = {**claim_projection(ctx.get("worker_registry") or {}, record["issue_id"]),
                            "observed_generation": ctx["observed_generation"]}
        if transition_class == "SV_ISSUE_RELEASE":
            try:
                claim_projection(ctx.get("worker_registry") or {}, record["issue_id"])
            except Refusal:
                new.pop("claim", None)
            else:
                raise _deny("WORKERCOORDINATOR_CLAIM_STILL_HELD", "RELEASE_FOLLOWS_WORKERCOORDINATOR_RELEASE",
                            "WorkerCoordinator releases the claim first", e)
        if transition_class == "SV_ISSUE_RESOLVE":
            ch = ctx.get("resolving_change") or {}
            if ch.get("lifecycle_state") != "APPLIED" or record.get("issue_id") not in (ch.get("resolves") or []):
                raise _fail("RESOLVING_CHANGE_NOT_APPLIED", "RESOLVING_SV_CHANGE_IS_APPLIED", "an APPLIED SV_CHANGE that lists this issue", e)
            new["resolved_by"] = ch.get("change_id")
        if transition_class == "SV_ISSUE_CLOSE_BY_INVARIANT":
            det = ctx.get("determination") or {}
            if det.get("disposition") != "ALLOW" or not _str(det.get("deciding_rule")) or not _str(det.get("receipt_ref")):
                raise _fail("INVARIANT_UNDECLARED", "INVARIANT_DETERMINATION_RECEIPT_NAMES_DECIDING_RULE",
                            "an INVARIANT_DETERMINATION ALLOW receipt naming the deciding rule", e)
            new["closed_by"] = {k: det[k] for k in ("deciding_rule", "receipt_ref")}
        if transition_class == "SV_CHANGE_PROPOSE":
            validate_change(record)
            obs = admission_inputs(record, record["base_ref"], **_writer_kw(ctx))
            writer = verify_branch_writer(obs, e)["session"]  # derived from the push-receipt chain, never declared
            claimed = {i.get("issue_id"): i for i in ctx.get("issues") or []}
            bad = [i for i in record["resolves"] if (claimed.get(i) or {}).get("lifecycle_state") != "CLAIMED"
                   or ((claimed.get(i) or {}).get("claim") or {}).get("session") != writer]
            if bad:
                raise _fail("RESOLVED_ISSUE_NOT_CLAIMED_BY_AUTHOR", "CHANGE_RESOLVES_CLAIMED_SV_ISSUES",
                            "claim each resolved SV_ISSUE with the branch writer's session first (SV_ISSUE_CLAIM)", e, unclaimed=bad,
                            derived_session=writer)
        if transition_class == "SV_CHANGE_VERIFY":
            validate_change(record)
            obs = admission_inputs(record, record["base_ref"], (), ctx.get("hb_epoch_readback"), ctx.get("resolved_issues"),
                                   **_ledger_kw(ctx), **_writer_kw(ctx))
            out = admit({**obs, "required_signoff_roles": []}, fixture_mode=bool(ctx.get("fixture_mode")))
            if out["disposition"] != "ALLOW":
                raise Refusal(out["disposition"], out["failure_code"], out["failed_predicate"], out["required_evidence_or_repair"],
                              "transition", "re-verify once every required check is receipted at the exact head")
        if transition_class == "SV_CHANGE_ADMIT":
            validate_change(record)
            if not (_str(ctx.get("predicate_digest")) and _str(ctx.get("corpus_head"))):
                raise _fail("ADMISSION_PROVENANCE_ABSENT", "MERGE_PROVENANCE_DECLARED",
                            "the admit receipt names the predicate digest and the corpus head", e)
            if record.get("record_mode") != "NATIVE":
                out = dict(historical_refusal(e).record)
                new["lifecycle_state"] = LIFECYCLE["admit_outcome_states"][out["disposition"]]
                return {**out, "predicate_digest": ctx["predicate_digest"], "corpus_head": ctx["corpus_head"],
                        "actor_session": ctx.get("actor_session"), "transition_class": transition_class, "record": new}
            obs = admission_inputs(record, ctx.get("current_base") or {}, ctx.get("signoff_receipts") or (), ctx.get("hb_epoch_readback"),
                                   ctx.get("resolved_issues"), **_ledger_kw(ctx), **_writer_kw(ctx))
            kw = {"fixture_mode": True} if ctx.get("fixture_mode") else {}
            out = admit(obs, ctx.get("evaluator") or evaluate_admission, covered_kinds=ctx.get("covered_kinds"), **kw)
            new["lifecycle_state"] = LIFECYCLE["admit_outcome_states"][out["disposition"]]
            out = {**out, "predicate_digest": ctx["predicate_digest"], "corpus_head": ctx["corpus_head"],
                   "actor_session": ctx.get("actor_session")}
            return {**out, "transition_class": transition_class, "record": new}
        if transition_class == "SV_CHANGE_APPLY":
            if record.get("base_ref") != ctx.get("current_base"):
                raise _deny("BASE_STALE", "BASE_IS_CURRENT", "re-propose on the current base", e)
            new["applied"] = {"registry_generation": record["base_ref"]["registry_generation"] + 1}
        if transition_class in ("SV_ISSUE_SUPERSEDE", "SV_CHANGE_SUPERSEDE"):
            issue = transition_class == "SV_ISSUE_SUPERSEDE"
            succ, seal_field = ctx.get("successor"), ("issue_sha256" if issue else "request_digest")
            if not isinstance(succ, Mapping):
                raise _fail("SUCCESSOR_NOT_RECORDED", "SUCCESSOR_ISSUE_IS_RECORDED" if issue else "SUCCESSOR_CHANGE_IS_PROPOSED",
                            "supply the successor record", e)
            (validate_issue if issue else validate_change)(succ)
            if succ.get("supersedes") != record.get(seal_field):
                raise _fail("SUCCESSOR_DOES_NOT_NAME_PREDECESSOR", "SUCCESSOR_ISSUE_IS_RECORDED" if issue else "SUCCESSOR_CHANGE_IS_PROPOSED",
                            "successor.supersedes = predecessor " + seal_field, e)
            new["superseded_by"] = succ.get(seal_field)
        if transition_class == "SV_CHANGE_PROJECT_GITHUB":
            new["projection"] = {**(record.get("projection") or {}), **(ctx.get("projection") or {}), "authority_effect": "NONE"}
        new["lifecycle_state"] = t["to_state"]
        return {"disposition": "ALLOW", "transition_class": transition_class, "record": new}
    except Refusal as r:
        return {**r.record, "transition_class": transition_class, "record": dict(record or {})}


def record(result: Mapping[str, Any], predecessor: Mapping[str, Any] | None, *, hb_epoch: Any,
           append: Callable[..., dict]) -> dict[str, Any]:
    """Hand a transition outcome (ALLOW or refusal) to the existing repository emitter."""
    epoch_check(hb_epoch, "record")
    rec = result["record"]
    rid = rec.get("issue_id") or rec.get("change_id") or rec.get("class_id")
    six = {f: result.get(f) for f in SIX_FIELDS}
    return append(str(rid) + ":" + result["transition_class"], result["transition_class"],
                  sha(predecessor), sha(rec if result["disposition"] == "ALLOW" else predecessor),
                  evidence={"record": rec, "disposition": result["disposition"], **six,
                            "invariant": LIFECYCLE["invariant"]},
                  authority_effect="NONE_RECORD_ONLY", hb_epoch=int(epoch_check(hb_epoch, "record")))
