set -euo pipefail
export STEGVERSE_ORG_LEDGER_ROOT="git+$GITHUB_WORKSPACE#$DRY_RUN_REF"
export STEGVERSE_REPO_LEDGER_ROOT="git+$GITHUB_WORKSPACE#$DRY_RUN_REF:$REPO_LEDGER_NAMESPACE"
python3 resident-runtime/merge_transfer_admission.py append --commits-file "$RUNNER_TEMP/results/commits.txt" \
  --out "$RUNNER_TEMP/results/append.json"
python3 resident-runtime/merge_transfer.py verify --commits-file "$RUNNER_TEMP/results/commits.txt" \
  --out "$RUNNER_TEMP/results/verify.json"
tip=$(git rev-parse "$DRY_RUN_REF")
python3 resident-runtime/merge_transfer_admission.py append --commits-file "$RUNNER_TEMP/results/commits.txt" \
  --out "$RUNNER_TEMP/results/replay.json"
test "$(git rev-parse "$DRY_RUN_REF")" = "$tip"
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); assert all(x["replayed"] is True for x in r), r' "$RUNNER_TEMP/results/replay.json"
# B2: every checkpoint is ALLOW or FAIL_CLOSED with six fields (exit 0 or 1), never missing
rc=0
python3 resident-runtime/merge_transfer_admission.py checkpoint --commits-file "$RUNNER_TEMP/results/commits.txt" \
  --out "$RUNNER_TEMP/results/admission-checkpoint.json" > /dev/null || rc=$?
test "$rc" -le 1
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); six=("failure_code","failed_predicate","required_evidence_or_repair","retry_entrypoint","owning_existing_goal","next_attempt"); assert r and all(x["disposition"]=="ALLOW" or (x["disposition"]=="FAIL_CLOSED" and all(x.get(k) for k in six)) for x in r), r' "$RUNNER_TEMP/results/admission-checkpoint.json"
# The ledger writer may append to the published ref while this runs (push to main): the guard requires
# append-only growth from the copied tip and no scratch append on the published ref, not an unchanged tip.
git fetch --no-tags origin "+$LEDGER_REF:refs/dry-run/published-now"
python3 resident-runtime/ledger_publish_guard.py --copied-tip "$(cat "$RUNNER_TEMP/results/published-tip")" \
  --published-now "$(git rev-parse refs/dry-run/published-now)" --scratch-tip "$(git rev-parse "$DRY_RUN_REF")"
{ echo '### dry run (scratch ref, not published)'; echo '```json'; cat "$RUNNER_TEMP/results/verify.json"; echo '```'; } >> "$GITHUB_STEP_SUMMARY"
