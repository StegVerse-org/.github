python resident-runtime/sdk_manifest_crossing.py \
  --registry org-boundary/registry/services.json \
  --manifest tests/fixtures/sdk-manifests/unadmitted-capability-to-task-registry-disclosure.json \
  --standing tests/fixtures/crossing-standing-genesis.json \
  --packet-id ci-sdk-manifest-crossing-gap --out /tmp/gap.json || true
python -c 'import json; x=json.load(open("/tmp/gap.json")); six=("failure_code","failed_predicate","required_evidence_or_repair","retry_entrypoint","owning_existing_goal","next_attempt"); assert x["crossing_completed"] is False; assert x["resolved_service_id"]=="stegverse-org.task-registry-disclosure"; assert x["endpoint_adapter_installed"] is True; assert isinstance(x["far_side_disposition"],str) and x["far_side_disposition"].strip(), "a refused crossing must name its disposition"; assert x["disposition"]=="FAIL_CLOSED", x; assert all(isinstance(x.get(f),str) and x[f].strip() for f in six), x; assert x["failure_code"]=="FAR_SIDE_REFUSED_THE_CROSSING", x; print("UNADMITTED_PAIR_REFUSED_WITH_SIX_FIELDS=PASS")'
