set -euo pipefail
status=0
python3 resident-runtime/merge_transfer_gitstore.py verify --commits-file "$RUNNER_TEMP/results/commits.txt" \
  --out "$RUNNER_TEMP/results/real-state.json" || status=$?
python3 - "$RUNNER_TEMP/results/real-state.json" <<'PY'
import json, sys
for r in json.load(open(sys.argv[1])):
    ok = r["disposition"] == "ALLOW" or (r["disposition"] == "FAIL_CLOSED"
                                         and r["failure_code"] == "MERGE_TRANSFER_RECEIPT_NOT_LEDGERED")
    assert ok, r
    print(r["merge_commit"], r["disposition"], r.get("failure_code"))
PY
