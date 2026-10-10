"""Source-only, non-authorizing foundation work-context and Sandbox validator.

No I/O, network, credentials, provider invocation, or governance transitions.
Validation of candidate evidence is not admission by Interlock/InTr.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

GOAL = "SVORG-LLM-ORG-FOUNDATION-001"
CONTEXT_CLASSES = frozenset({
    "repository_documentation", "schemas", "tests", "task_registry",
    "mirror_handoffs", "manifests", "receipts", "master_records_references",
    "cross_repository_contracts",
})
SANDBOX_FIELDS = frozenset({
    "work_id", "manifested_request", "canonical_context_refs",
    "permitted_capabilities", "participating_entities", "candidate_outputs",
    "disagreements_refusals_uncertainty", "tests_and_derived_artifacts",
    "evidence_refs", "governance_handoff_state",
})
FORBIDDEN_AUTHORITY = frozenset({"ALLOW", "ADMITTED", "EXECUTE", "PUBLISH", "GRANT"})
MAX_REFS = 128


def _digest(value):
    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _result(kind, code, predicate, repair, retry, next_attempt, evidence=None):
    result = {
        "schema": "stegverse.llm-org-foundation.validation/v1",
        "kind": kind,
        "disposition": "DENY" if code.startswith("FORBIDDEN") else "FAIL_CLOSED" if code else "ALLOW",
        "authority_effect": "NONE",
        "owning_existing_goal": GOAL,
        "evidence": evidence or {},
    }
    if code:
        result.update(failure_code=code, failed_predicate=predicate,
                      required_evidence_or_repair=repair, retry_entrypoint=retry,
                      next_attempt=next_attempt)
    return result


def _valid_refs(refs):
    return (isinstance(refs, list) and 0 < len(refs) <= MAX_REFS
            and all(isinstance(r, str) and r.strip() and len(r) <= 2048 for r in refs)
            and len(refs) == len(set(refs)))


def validate_work_context(value):
    retry = "StegVerse-org/.github foundation work-context validation"
    if not isinstance(value, Mapping):
        return _result("work_context", "INVALID_CONTEXT", "context_is_object",
                       "submit a bounded work-context object", retry, "resubmit context")
    refs = value.get("canonical_context_refs")
    if not _valid_refs(refs):
        return _result("work_context", "INVALID_CONTEXT_REFS", "bounded_unique_nonempty_refs",
                       "supply 1..128 distinct nonempty canonical references", retry, "resubmit references")
    classes = value.get("evidence_classes")
    if not isinstance(classes, list) or not classes or any(c not in CONTEXT_CLASSES for c in classes):
        return _result("work_context", "INVALID_EVIDENCE_CLASSES", "known_context_evidence_classes",
                       "declare supported evidence classes", retry, "resubmit classes")
    if not isinstance(value.get("work_id"), str) or not value["work_id"].strip():
        return _result("work_context", "MISSING_WORK_ID", "work_id_nonempty",
                       "bind existing work identity", retry, "resubmit work identity")
    return _result("work_context", None, None, None, None, None,
                   {"context_sha256": _digest({"work_id": value["work_id"],
                                               "canonical_context_refs": refs,
                                               "evidence_classes": classes}),
                    "reference_count": len(refs), "source_only": True})


def validate_sandbox_work(value):
    retry = "StegVerse-org/.github foundation Sandbox validation"
    if not isinstance(value, Mapping) or not SANDBOX_FIELDS.issubset(value):
        return _result("sandbox", "INCOMPLETE_SANDBOX_OBJECT", "all_existing_sandbox_fields_present",
                       "supply canonical foundation Sandbox fields", retry, "resubmit bounded work object")
    context = validate_work_context({
        "work_id": value["work_id"], "canonical_context_refs": value["canonical_context_refs"],
        "evidence_classes": value.get("evidence_classes", ["task_registry"]),
    })
    if context["disposition"] != "ALLOW":
        return _result("sandbox", context["failure_code"], context["failed_predicate"],
                       context["required_evidence_or_repair"], retry, "repair context references")
    if not _valid_refs(value["evidence_refs"]):
        return _result("sandbox", "INVALID_SANDBOX_EVIDENCE", "bounded_evidence_refs",
                       "provide bounded, unique evidence references", retry, "resubmit evidence")
    for key in ("permitted_capabilities", "participating_entities", "candidate_outputs",
                "disagreements_refusals_uncertainty", "tests_and_derived_artifacts"):
        if not isinstance(value[key], list):
            return _result("sandbox", "INVALID_SANDBOX_FIELD", key + "_is_list",
                           "supply a list for " + key, retry, "resubmit work object")
    for candidate in value["candidate_outputs"]:
        if not isinstance(candidate, Mapping) or candidate.get("authority_effect") != "NONE":
            return _result("sandbox", "FORBIDDEN_CANDIDATE_AUTHORITY", "candidate_authority_effect_NONE",
                           "candidate output must explicitly have authority_effect NONE",
                           retry, "resubmit non-authorizing candidate")
        if candidate.get("disposition") in FORBIDDEN_AUTHORITY:
            return _result("sandbox", "FORBIDDEN_CANDIDATE_AUTHORITY", "no_candidate_governance_disposition",
                           "remove candidate's governance claim", retry, "resubmit candidate")
    if value["governance_handoff_state"] not in ("NOT_SUBMITTED", "CANDIDATE_EVIDENCE_ONLY"):
        return _result("sandbox", "FORBIDDEN_HANDOFF_AUTHORITY", "non_authorizing_handoff_state",
                       "governance is decided only by existing SDK/Interlock/InTr path",
                       retry, "resubmit non-authorizing handoff")
    if not isinstance(value["manifested_request"], Mapping):
        return _result("sandbox", "INVALID_MANIFESTED_REQUEST", "request_is_object",
                       "supply source-bound manifested request reference data", retry, "resubmit request")
    return _result("sandbox", None, None, None, None, None,
                   {"work_id": value["work_id"], "context_sha256": context["evidence"]["context_sha256"],
                    "evidence_reference_count": len(value["evidence_refs"]),
                    "candidate_count": len(value["candidate_outputs"]), "source_only": True})
