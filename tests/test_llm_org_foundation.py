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
    assert task["status"] == "accepted"
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
    assert vector["vector"] == "20011100110000"
    assert vector["authority_effect"] == "NONE_SOURCE_COORDINATION_ONLY"
