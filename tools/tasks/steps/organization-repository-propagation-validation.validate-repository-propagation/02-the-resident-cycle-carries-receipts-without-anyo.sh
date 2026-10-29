python - <<'PY'
import importlib.util, json, os
from pathlib import Path

root = Path(".")
def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, root / relative)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

ledger = load("aggregate_repo_transition", "resident-runtime/aggregate_repo_transition.py")
repository = "StegVerse-org/StegVerse-SDK"

# A repository receipt of the shape a repository emitter writes.
body = {"schema": "stegverse.repo-transition-receipt/v1", "repository": repository,
        "transition_id": "NODE_INGRESS_ADMITTED:ci-node", "transition_class": "NODE_INGRESS_ADMITTED",
        "predecessor_state_sha256": "sha256:" + "1" * 64,
        "successor_state_sha256": "sha256:" + "2" * 64,
        "evidence": {"ci": True}, "authority_effect": "NONE",
        "hb_reference": {"epoch": 32, "derived_from_clock": False, "progression_dependency": "OSCILLATOR_ONLY"},
        "ordering": "OSCILLATOR_HEARTBEAT_EPOCH_ONLY", "previous_receipt_sha256": None}
digest = ledger.sha(body)
receipt = {**body, "receipt_sha256": digest}
receipts = Path(os.environ["STEGVERSE_REPO_LEDGER_HOME"]) / repository / "receipts"
receipts.mkdir(parents=True, exist_ok=True)
(receipts / (digest.split(":", 1)[1] + ".json")).write_text(json.dumps(receipt, indent=2, sort_keys=True))
(receipts.parent / "HEAD.json").write_text(json.dumps(
    {"repository": repository, "receipt_sha256": digest}, indent=2, sort_keys=True))

kernel = load("org_kernel", "org-kernel/kernel.py")
cycle = load("federation_cycle", "resident-runtime/federation_cycle.py")
mesh = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "cycle-mesh"
node_state = Path(os.environ["STEGVERSE_NODE_STATE_ROOT"])
reported = cycle.main(mesh_root=mesh, node_state_root=node_state, hb_epoch=32)
carried = reported["repository_propagation"]
assert carried["receipts_propagated"] == 1, carried
assert carried["repositories_present"] == 1, carried
assert carried["crossed_an_organization_boundary"] is False
assert carried["interlock_intr_involved"] is False

# The organization chain carries it, bound to the repository receipt.
organization = [json.loads(p.read_text()) for p in
                (Path(os.environ["STEGVERSE_ORG_LEDGER_ROOT"]) / "receipts").glob("*.json")]
organization = [r for r in organization
                if r.get("schema") == "stegverse.organization-transition-receipt/v1"]
assert len(organization) == 1, len(organization)
assert organization[0]["source_repository"] == repository
assert organization[0]["repo_receipt_sha256"] == digest
assert organization[0]["org_transition_class"] == "REPO_STATE_PROPAGATION"

# Running the cycle again carries nothing rather than failing on a duplicate.
again = cycle.main(mesh_root=mesh, node_state_root=node_state, hb_epoch=32)
assert again["repository_propagation"]["receipts_propagated"] == 0
assert again["repository_propagation"]["receipts_already_carried"] == 1

# A cycle is recorded in this node's own state, addressed by what it
# reported, and the run leaves nothing behind in the checkout.
recorded = kernel.federation_cycles(root=node_state)
assert len(recorded) == 2, len(recorded)
assert sorted(r["repository_propagation"]["receipts_propagated"] for r in recorded) == [0, 1]
# The node state root was told to the node, so it is portable, and
# the run left nothing behind in the checkout.
resolved, provenance = kernel.resolve_node_state_root(node_state)
assert provenance == "SUPPLIED", provenance
assert str(resolved) == str(node_state.resolve()), resolved
assert not (root / "resident-runtime/federation").exists()
print("RESIDENT_CYCLE_CARRIES_REPOSITORY_RECEIPTS=PASS", organization[0]["repo_transition_id"])
PY
