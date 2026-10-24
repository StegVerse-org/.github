python resident-runtime/sdk_manifest_crossing.py \
  --registry org-boundary/registry/services.json \
  --manifest tests/fixtures/sdk-manifests/governance-to-boundary-diagnostic.json \
  --standing tests/fixtures/crossing-standing-genesis.json \
  --packet-id ci-sdk-manifest-crossing --out /tmp/sdk-crossing.json
python -c 'import json; x=json.load(open("/tmp/sdk-crossing.json")); assert x["crossing_completed"] is True; assert x["consumed"] is True; assert x["reconstruction"]=="RECONSTRUCTED"; assert x["authority_effect"]=="NONE"; assert len(x["receipts"])==5'
