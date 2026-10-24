python - <<'PY'
import importlib.util, json, os
from pathlib import Path

os.environ["STEGVERSE_ORG_FEDERATION_ROOT"] = os.environ["RUNNER_TEMP"] + "/mesh"
os.environ["STEGVERSE_NODE_STATE_ROOT"] = os.environ["RUNNER_TEMP"] + "/node"

def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, relative)
    loaded = importlib.util.module_from_spec(spec); spec.loader.exec_module(loaded)
    return loaded

kernel = module("kernel", "org-kernel/kernel.py")
manifest = json.loads(Path(
    "tests/fixtures/sdk-manifests/task-registry-disclosure-to-llm-adapter.json").read_text())
standing = {k: v for k, v in json.loads(Path(
    "tests/fixtures/crossing-standing-genesis.json").read_text()).items()
    if not k.startswith("_")}

# No checkout of this repository on the submitting side, and no CLI:
# a frame in the shared mesh addressed to this organization's address
# for the capability. This is the path that did not exist.
address = kernel.organization_slug("StegVerse-org") + ".sdk-manifest-ingress"
packet = kernel.build_packet(
    origin_org="StegVerse-Labs",
    origin_service=kernel.organization_slug("StegVerse-Labs") + ".sdk-manifest-ingress",
    destination_org="StegVerse-org",
    destination_service=address,
    payload={"schema": "stegverse.sdk-manifest-crossing-payload/v1",
             "declared_transition_surface": "LLM_ADAPTER",
             "manifest_sha256": kernel.sha(manifest),
             "manifest": manifest},
    standing=standing,
    transition_reference="intr:transition:ci-peer-manifest-submission",
    authority_effect="NONE", packet_id="ci-peer-manifest-submission")
kernel.publish_packet(packet, root=Path(os.environ["STEGVERSE_ORG_FEDERATION_ROOT"]))

consumed = kernel.consume_addressed_frames(Path.cwd(), mesh_root=Path(os.environ["STEGVERSE_ORG_FEDERATION_ROOT"]),
    repo_ledger_root=Path(os.environ["STEGVERSE_REPO_LEDGER_ROOT"]),
    org_ledger_root=Path(os.environ["STEGVERSE_ORG_LEDGER_ROOT"]))
assert len(consumed) == 1, consumed
execution = consumed[0]["result"]["execution_result"]
assert consumed[0]["result"]["status"] == "CONSUMED"
assert execution["service_id"] == address
assert execution["consumed"] is True
# No processor is selected at the address; the capability is processed
# one layer in, by the operation the overlay binds.
assert execution["processing_selection"] == "BOUNDARY_LOCAL_NO_PROCESSOR_SELECTED"

application = execution["application_result"]
assert application["capability_received"] is True
assert application["capability_profile_id"] == "sdk-manifest-ingress"
assert application["receiving_operation_id"] == "ORGANIZATION_SDK_MANIFEST_INGRESS"
assert application["capability_resolution_source"] == "ORGANIZATION_CAPABILITY_OVERLAY"
assert application["declared_capability_processed_at_this_address"] is False
assert application["addressability_grants_admission_authority"] is False

operation = application["receiving_operation_result"]
assert operation["disposition"] == "ALLOW", operation.get("detail")
assert operation["received"] is True
assert operation["resolved_service_id"] == "stegverse-org.llm-adapter"
assert operation["intr_admission_observed"] is True
assert operation["far_side_transition_observed"] is True
assert operation["organization_receipt_observed"] is True
assert operation["repository_receipt_observed"] is True
assert operation["organization_receipt_preserves_repository_receipt"] is True

# Both levels recorded it, from a submission published by a peer.
def receipts(variable, schema):
    return [json.loads(p.read_text()) for p in Path(os.environ[variable]).rglob("*.json")
            if json.loads(p.read_text()).get("schema") == schema]

repository, = receipts("STEGVERSE_REPO_LEDGER_ROOT",
                       "stegverse.repo-transition-receipt/v1")
organization, = receipts("STEGVERSE_ORG_LEDGER_ROOT",
                         "stegverse.organization-transition-receipt/v1")
assert repository["transition_class"] == "ORGANIZATION_SDK_MANIFEST_INGRESS"
assert organization["repo_receipt_sha256"] == repository["receipt_sha256"]
print("PEER_MANIFEST_SUBMISSION_OVER_THE_MESH=PASS",
      execution["reconstruction"]["terminal_receipt_id"])
PY
