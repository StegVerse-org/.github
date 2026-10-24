set -euo pipefail
git init -q --bare "$RUNNER_TEMP/one-ref.git"
ns=$(python -c 'import json; print(json.load(open(".stegverse/transition-ledger/contract.json"))["repository_ledger_location"]["namespace"])')
export STEGVERSE_ORG_LEDGER_ROOT="git+$RUNNER_TEMP/one-ref.git#refs/stegverse/organization-ledger"
export STEGVERSE_REPO_LEDGER_ROOT="$STEGVERSE_ORG_LEDGER_ROOT:$ns"
for n in 1 2; do
  python - "$n" <<'PY'
import json, sys
from pathlib import Path
fixture = json.loads(Path("tests/fixtures/sdk-manifests/task-registry-disclosure-to-llm-adapter.json").read_text())
fixture["source_output_id"] = fixture["source_output_id"] + "-durable-" + sys.argv[1]
Path("/tmp/durable-manifest-" + sys.argv[1] + ".json").write_text(json.dumps(fixture))
PY
  python resident-runtime/organization_manifest_ingress.py \
    --registry org-boundary/registry/services.json \
    --manifest "/tmp/durable-manifest-$n.json" \
    --standing tests/fixtures/crossing-standing-genesis.json \
    --packet-id "ci-durable-$n" --hb-epoch 4$n \
    --out "$RUNNER_TEMP/durable-ingress-$n.json"
done
git init -q --bare "$RUNNER_TEMP/fresh.git"
git --git-dir="$RUNNER_TEMP/fresh.git" fetch -q "$RUNNER_TEMP/one-ref.git" "+refs/stegverse/organization-ledger:refs/stegverse/organization-ledger"
python resident-runtime/organization_ledger_readback.py \
  --location "git+$RUNNER_TEMP/fresh.git#refs/stegverse/organization-ledger" \
  --ingress-result "$RUNNER_TEMP/durable-ingress-2.json" --repository-namespace "$ns" \
  --out "$RUNNER_TEMP/durable-readback.json"
python - <<'PY'
import json, os
x = json.load(open(os.environ["RUNNER_TEMP"] + "/durable-readback.json"))
one = json.load(open(os.environ["RUNNER_TEMP"] + "/durable-ingress-1.json"))
two = json.load(open(os.environ["RUNNER_TEMP"] + "/durable-ingress-2.json"))
assert x["disposition"] == "ALLOW" and x["chain_length"] == 2, x
r = x["repository_ledger"]
assert r["chain_length"] == 2 and r["replay_read_organization_receipts"] is False, r
assert r["chain"][0]["receipt_sha256"] == one["repository_receipt_sha256"]
assert r["chain"][1]["receipt_sha256"] == two["repository_receipt_sha256"]
assert r["chain"][1]["previous_receipt_sha256"] == one["repository_receipt_sha256"], "second run did not extend the first run's chain"
assert r["chain"][0]["previous_receipt_sha256"] is None
assert r["every_receipt_retained_in_organization_ledger"] is True
assert r["ingress_repository_receipt_in_chain"] is True
assert r["consumed_by_organization_receipt_sha256"] == two["organization_receipt_sha256"]
print("REPOSITORY_CHAIN_DURABLE_IN_DESIGNATED_REF=PASS", r["head_receipt_sha256"])
PY
