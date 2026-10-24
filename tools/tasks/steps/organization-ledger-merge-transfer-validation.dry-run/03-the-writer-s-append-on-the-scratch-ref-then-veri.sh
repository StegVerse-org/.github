set -euo pipefail
export STEGVERSE_ORG_LEDGER_ROOT="git+$GITHUB_WORKSPACE#$DRY_RUN_REF"
export STEGVERSE_REPO_LEDGER_ROOT="git+$GITHUB_WORKSPACE#$DRY_RUN_REF:$REPO_LEDGER_NAMESPACE"
python3 resident-runtime/merge_transfer.py append --commits-file "$RUNNER_TEMP/results/commits.txt" \
  --out "$RUNNER_TEMP/results/append.json"
python3 resident-runtime/merge_transfer.py verify --commits-file "$RUNNER_TEMP/results/commits.txt" \
  --out "$RUNNER_TEMP/results/verify.json"
tip=$(git rev-parse "$DRY_RUN_REF")
python3 resident-runtime/merge_transfer.py append --commits-file "$RUNNER_TEMP/results/commits.txt" \
  --out "$RUNNER_TEMP/results/replay.json"
test "$(git rev-parse "$DRY_RUN_REF")" = "$tip"
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); assert all(x["replayed"] is True for x in r), r' "$RUNNER_TEMP/results/replay.json"
# the published ref is untouched by this run: still the tip copied at the start
test "$(git ls-remote origin "$LEDGER_REF" | cut -f1)" = "$(cat "$RUNNER_TEMP/results/published-tip")"
{ echo '### dry run (scratch ref, not published)'; echo '```json'; cat "$RUNNER_TEMP/results/verify.json"; echo '```'; } >> "$GITHUB_STEP_SUMMARY"
