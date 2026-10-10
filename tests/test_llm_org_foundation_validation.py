import copy

from llm_org_foundation_validation import validate_work_context, validate_sandbox_work


def sample():
    return {
        "work_id": "SVORG-LLM-ORG-FOUNDATION-001",
        "manifested_request": {"manifest_ref": "sha256:source"},
        "canonical_context_refs": ["orchestration/task-registry.json"],
        "permitted_capabilities": ["text"],
        "participating_entities": [{"id": "entity-1"}],
        "candidate_outputs": [{"authority_effect": "NONE", "content_ref": "sha256:candidate"}],
        "disagreements_refusals_uncertainty": [],
        "tests_and_derived_artifacts": [],
        "evidence_refs": ["sha256:source"],
        "governance_handoff_state": "NOT_SUBMITTED",
    }


def test_context_rejects_missing_and_duplicate_references():
    assert validate_work_context({"work_id": "x", "evidence_classes": ["tests"],
                                  "canonical_context_refs": []})["disposition"] == "FAIL_CLOSED"
    assert validate_work_context({"work_id": "x", "evidence_classes": ["tests"],
                                  "canonical_context_refs": ["a", "a"]})["disposition"] == "FAIL_CLOSED"


def test_context_accepts_bounded_refs_without_authorizing():
    r = validate_work_context({"work_id": "x", "evidence_classes": ["tests"],
                               "canonical_context_refs": ["tests/test_llm_org_foundation.py"]})
    assert r["disposition"] == "ALLOW"
    assert r["authority_effect"] == "NONE"
    assert r["evidence"]["source_only"] is True


def test_sandbox_accepts_evidence_not_execution():
    r = validate_sandbox_work(sample())
    assert r["disposition"] == "ALLOW"
    assert r["authority_effect"] == "NONE"
    assert r["evidence"]["source_only"] is True


def test_sandbox_rejects_candidate_authority_and_fake_admission():
    for change in (
        lambda s: s["candidate_outputs"][0].update(authority_effect="ALLOW"),
        lambda s: s["candidate_outputs"][0].update(disposition="ADMITTED"),
        lambda s: s.update(governance_handoff_state="ADMITTED"),
    ):
        s = copy.deepcopy(sample())
        change(s)
        r = validate_sandbox_work(s)
        assert r["disposition"] == "DENY"
        assert len([k for k in ("failure_code", "failed_predicate", "required_evidence_or_repair",
                               "retry_entrypoint", "owning_existing_goal", "next_attempt") if k in r]) == 6


def test_sandbox_rejects_unbounded_evidence():
    s = sample()
    s["evidence_refs"] = [str(i) for i in range(129)]
    assert validate_sandbox_work(s)["disposition"] == "FAIL_CLOSED"
