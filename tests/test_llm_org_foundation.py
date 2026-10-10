import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "data" / "llm-org-foundation.json"
REGISTRY = ROOT / "orchestration" / "task-registry.json"
VECTOR = ROOT / "control" / "task-vectors" / "SVORG-LLM-ORG-FOUNDATION-001.json"


def load(path):
    return json.loads(path.read_text())


def test_task_is_registered_without_replacing_existing_active_goal():
    registry = load(REGISTRY)
    assert registry["active_goal"] == "SVORG-STEGOS-PORTABILITY-001"
    task = next(t for t in registry["tasks"] if t["task_id"] == "SVORG-LLM-ORG-FOUNDATION-001")
    assert task["status"] == "complete"
    assert task["unresolved_obligations"] == []
    assert task["issue"] == 74


def test_participating_entities_never_gain_governance_authority():
    contract = load(CONTRACT)
    assert contract["sandbox"]["candidate_output_authority_effect"] == "NONE"
    assert contract["ecosystem_ai"]["role"] == "GOVERNANCE_EVIDENCE_MATCHING"
    assert contract["ecosystem_ai"]["is_llm"] is False
    assert "model_consensus" in contract["ecosystem_ai"]["prohibited_decision_bases"]


def test_provider_execution_is_reused_not_duplicated():
    contract = load(CONTRACT)
    reuse = contract["reuse"]
    assert reuse["distributed_llm_workload"].startswith("StegVerse-org/LLM-adapter/")
    assert reuse["external_llm_connection"].startswith("StegVerse-org/LLM-adapter/")
    assert reuse["duplicate_provider_broker_forbidden"] is True
    assert reuse["duplicate_governance_engine_forbidden"] is True


def test_inference_window_is_disposition_complete_and_not_history():
    iw = load(CONTRACT)["inference_window"]
    assert iw["temporal_role"] == "FORWARD_LOOKING"
    assert iw["disposition_complete"] is True
    assert "might or might not become reachable" in iw["question"]
    assert iw["projection_is_historical_evidence"] is False


def test_cosv_projection_matches_registered_foundation():
    vector = load(VECTOR)
    assert vector["identity"] == "SVORG-LLM-ORG-FOUNDATION-001"
    assert vector["profile"] == "task.v1"
    assert vector["vector"] == "71000000100100"
    assert vector["exact_metrics"]["activated"] is False
    assert vector["exact_metrics"]["propagated"] is False
    assert vector["authority_effect"] == "NONE_SOURCE_COORDINATION_ONLY"


def test_external_ingress_delegates_to_existing_sdk_and_org_ledger():
    boundary = load(CONTRACT)["reuse"]["external_ingress_boundary"]
    assert boundary["path"] == [
        "healthy node", "StegVerse-org/LLM-adapter", "StegVerse-org/StegVerse-SDK",
        "StegVerse-org/.github", "Interlock/InTr", "Organization Ledger",
    ]
    assert boundary["sdk_owns"] == ["manifest_build", "manifest_submission"]
    assert boundary["llm_adapter_authority_effect"] == "NONE_TRANSPORT_AND_NECESSARY_TRANSLATION_ONLY"
    assert boundary["hcb_authority_effect"] == "NONE_OPTIONAL_PROTOCOL_EVIDENCE"
    assert boundary["hcb_mandatory_hop"] is False
    assert boundary["organization_ledger_owner"] == "StegVerse-org/.github"
    assert boundary["master_records_role"] == "DOWNSTREAM_NON_GATING"
    assert boundary["runtime_observation_claimed"] is False


def test_admitted_internal_sandbox_does_not_reenter_external_llm_adapter():
    boundary = load(CONTRACT)["reuse"]["external_ingress_boundary"]
    assert boundary["sandbox_admitted_internal_operations_reenter_llm_adapter"] is False
    assert load(CONTRACT)["sandbox"]["candidate_output_authority_effect"] == "NONE"
