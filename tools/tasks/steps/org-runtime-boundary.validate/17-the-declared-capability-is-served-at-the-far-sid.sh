python resident-runtime/sdk_manifest_crossing.py \
  --registry org-boundary/registry/services.json \
  --manifest tests/fixtures/sdk-manifests/task-registry-disclosure.json \
  --standing tests/fixtures/crossing-standing-genesis.json \
  --packet-id ci-task-registry-disclosure --out /tmp/task-registry-disclosure.json
python -c 'import json; x=json.load(open("/tmp/task-registry-disclosure.json")); assert x["declared_capability_processed"] is True; assert x["processing_selection"]=="MANIFEST_DECLARED"; assert x["reconstruction"]=="RECONSTRUCTED"; assert len(x["receipts"])==5'
