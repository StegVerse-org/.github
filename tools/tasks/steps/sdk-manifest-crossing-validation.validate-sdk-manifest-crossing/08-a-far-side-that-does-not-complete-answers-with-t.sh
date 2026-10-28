for case in receiver-unavailable installed-adapter-refuses; do
  python tests/fixtures/d6_far_side_registry.py --case "$case" --out "/tmp/d6-registry-$case.json"
  python resident-runtime/sdk_manifest_crossing.py \
    --registry "/tmp/d6-registry-$case.json" \
    --manifest tests/fixtures/sdk-manifests/unadmitted-capability-to-task-registry-disclosure.json \
    --standing tests/fixtures/crossing-standing-genesis.json \
    --packet-id "ci-d6-$case" --out "/tmp/d6-$case.json" || true
done
python - <<'PY'
import json
spec = json.load(open("tests/fixtures/d6-far-side-non-allow.json"))
six = ("failure_code", "failed_predicate", "required_evidence_or_repair",
       "retry_entrypoint", "owning_existing_goal", "next_attempt")
for case, expected in spec["cases"].items():
    x = json.load(open("/tmp/d6-" + case + ".json"))
    assert x["crossing_completed"] is False, (case, x)
    assert x["resolved_service_id"] == expected["admit_on_service"], (case, x)
    assert x["disposition"] == "FAIL_CLOSED", (case, x)
    assert all(isinstance(x.get(f), str) and x[f].strip() for f in six), (case, x)
    assert x["failure_code"] == expected["expected_failure_code"], (case, x)
    assert x["failed_predicate"] == expected["expected_failed_predicate"], (case, x)
    assert x["owning_existing_goal"] == "INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001"
    assert x["receiver_unavailable_disposition"] == "DURABLE_QUEUE_OR_EVENT_EPHEMERAL_MATERIALIZATION"
    assert x["awaits_the_receiver"] is False
    if "expected_next_attempt_prefix" in expected:
        assert x["next_attempt"].startswith(expected["expected_next_attempt_prefix"]), x
    print("D6_FAR_SIDE_SIX_FIELDS=PASS", case, x["failure_code"])
PY
