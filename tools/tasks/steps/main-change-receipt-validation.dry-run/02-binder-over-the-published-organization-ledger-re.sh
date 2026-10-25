set -euo pipefail
ledger="$RUNNER_TEMP/ledger.git"
git init -q --bare "$ledger"
git --git-dir="$ledger" fetch -q "https://github.com/$GITHUB_REPOSITORY" "+refs/stegverse/organization-ledger:refs/stegverse/organization-ledger"
status=0
python3 resident-runtime/push_receipt_session_binder.py --repository "$GITHUB_REPOSITORY" --base-sha "$BASE_SHA" \
  --head-sha "$HEAD_SHA" --branch "refs/heads/$HEAD_REF" --ledger-git-dir "$ledger" > "$RUNNER_TEMP/results/binding.json" || status=$?
python3 - "$RUNNER_TEMP/results/binding.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
six = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint", "owning_existing_goal", "next_attempt")
assert r["disposition"] == "ALLOW" or (r["disposition"] == "FAIL_CLOSED" and all(r.get(k) for k in six)), r
print(r["disposition"], r.get("failure_code"), r.get("authoring_session"), r.get("detail", {}).get("gap"))
PY
{ echo '### binder (read-only ledger readback)'; echo '```json'; cat "$RUNNER_TEMP/results/binding.json"; echo '```'; } >> "$GITHUB_STEP_SUMMARY"
