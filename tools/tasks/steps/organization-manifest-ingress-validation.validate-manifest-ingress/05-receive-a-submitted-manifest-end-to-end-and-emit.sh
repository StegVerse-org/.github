python resident-runtime/organization_manifest_ingress.py \
  --registry org-boundary/registry/services.json \
  --manifest tests/fixtures/sdk-manifests/task-registry-disclosure.json \
  --standing tests/fixtures/crossing-standing-genesis.json \
  --packet-id ci-organization-manifest-ingress --hb-epoch 32 \
  --out "$RUNNER_TEMP/org-ingress.json"
python - <<'PY'
import json, os
x = json.load(open(os.environ["RUNNER_TEMP"] + "/org-ingress.json"))
assert x["disposition"] == "ALLOW", x.get("detail")
assert x["received"] is True
assert x["owner_repository"] == "StegVerse-org/.github"
assert x["receiving_operation"] == "ORGANIZATION_SDK_MANIFEST_INGRESS"
assert x["destination_resolution_source"] == "CANONICAL_CONNECTOR_CAPABILITY_OVERLAY"
assert x["destination_resolution_environment_inputs"] == []
# The three that were false on every handoff before this operation existed.
assert x["intr_admission_observed"] is True
assert x["far_side_transition_observed"] is True
assert x["organization_receipt_observed"] is True
assert x["organization_receipt_sha256"].startswith("sha256:")
# Two levels, written in order: the organization consumed a repository
# receipt rather than one it wrote itself.
assert x["repository_receipt_observed"] is True
assert x["repository"] == "StegVerse-org/.github"
assert x["repository_receipt_sha256"].startswith("sha256:")
assert x["organization_receipt_preserves_repository_receipt"] is True
assert x["replay_requires_only_verified_repo_and_organization_receipts"] is True
# The SDK admitted it, bound to the receipt that exists.
assert x["sdk_admitted_result"]["state"] == "COMPLETE"
assert x["sdk_admitted_result"]["manifest_receipt_id"] == x["organization_receipt_sha256"]
assert x["boundary_receipt_chain_reconstructed_independently"] is True
assert [c["transition_id"] for c in x["transition_closures"]] == [
    "INGRESS_ACCEPTED", "DISPATCHED", "CONSUMED", "RESULT_BOUND", "EGRESS_EMITTED"]
# Organization records are published to Master Records separately and never awaited.
assert x["master_records_organization_record_observed"] is False
assert "master_records_closure_observed" not in x
assert x["authority_effect"] == "NONE_RECEIVING_OPERATION_ONLY"
print("ORGANIZATION_MANIFEST_INGRESS=PASS", x["organization_transition_id"])
PY
