python resident-runtime/sdk_manifest_crossing.py \
  --registry org-boundary/registry/services.json \
  --manifest tests/fixtures/sdk-manifests/task-registry-disclosure.json \
  --standing tests/fixtures/crossing-standing-genesis.json \
  --packet-id ci-task-registry-disclosure --out /tmp/disclosure.json
python -c 'import json; x=json.load(open("/tmp/disclosure.json")); assert x["crossing_completed"] is True; assert x["processing_selection"]=="MANIFEST_DECLARED"; assert x["declared_capability_processed"] is True; assert x["resolved_service_id"]=="stegverse-org.task-registry-disclosure"; assert x["reconstruction"]=="RECONSTRUCTED"; assert len(x["receipts"])==5; r=x["egress"]["payload"]["execution_result"]["application_result"]; assert r["authority_effect"]=="NONE_DISCLOSURE_ONLY"; print("DECLARED_CAPABILITY_SERVED_AT_FAR_SIDE=PASS", r["active_goal"], r["task_count"])'
