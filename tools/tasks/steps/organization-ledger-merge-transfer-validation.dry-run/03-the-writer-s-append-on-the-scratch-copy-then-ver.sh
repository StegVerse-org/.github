set -euo pipefail
python3 resident-runtime/merge_transfer.py append --commits-file "$RUNNER_TEMP/results/commits.txt" \
  --out "$RUNNER_TEMP/results/append.json"
python3 resident-runtime/merge_transfer.py verify --commits-file "$RUNNER_TEMP/results/commits.txt" \
  --out "$RUNNER_TEMP/results/verify.json"
tip=$(git --git-dir="$SCRATCH" rev-parse "$LEDGER_REF")
python3 resident-runtime/merge_transfer.py append --commits-file "$RUNNER_TEMP/results/commits.txt" \
  --out "$RUNNER_TEMP/results/replay.json"
test "$(git --git-dir="$SCRATCH" rev-parse "$LEDGER_REF")" = "$tip"
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); assert all(x["replayed"] is True for x in r), r' "$RUNNER_TEMP/results/replay.json"
# The ledger writer may append to the published ref while this runs (push to main): the guard requires
# append-only growth from the copied tip and no scratch append on the published ref, not an unchanged tip.
# The scratch tip is brought into the workspace under a dry-run ref so the guard reads local objects only.
git fetch -q "$SCRATCH" "+$LEDGER_REF:refs/dry-run/scratch-tip"
git fetch --no-tags origin "+$LEDGER_REF:refs/dry-run/published-now"
python3 resident-runtime/ledger_publish_guard.py --copied-tip "$(cat "$RUNNER_TEMP/results/published-tip")" \
  --published-now "$(git rev-parse refs/dry-run/published-now)" --scratch-tip "$(git rev-parse refs/dry-run/scratch-tip)"
# the workspace copy of the declared ref is never written: still the tip copied at the start
test "$(git rev-parse "$LEDGER_REF")" = "$(cat "$RUNNER_TEMP/results/published-tip")"
{ echo '### dry run (scratch git dir, not published)'; echo '```json'; cat "$RUNNER_TEMP/results/verify.json"; echo '```'; } >> "$GITHUB_STEP_SUMMARY"
