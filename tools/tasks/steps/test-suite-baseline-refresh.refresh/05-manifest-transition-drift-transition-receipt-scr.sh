set -euo pipefail
test "$(git rev-parse HEAD)" = "$HEAD_SHA"
scratch="$RUNNER_TEMP/scratch.git"
fresh="$RUNNER_TEMP/fresh.git"
git init -q --bare "$scratch"
git init -q --bare "$fresh"
python3 resident-runtime/drift_receipt_appender.py dry-run --root . --payload "$RESULTS/detect/receipt.json" \
  --writer-ref "$HEAD_SHA" --scratch "$scratch" --fresh "$fresh" --out "$RESULTS/appender.json" > /dev/null
python3 resident-runtime/test_suite_baseline_refresh.py transition --head "$HEAD_SHA" \
  --detect-receipt "$RESULTS/detect/receipt.json" --appender-result "$RESULTS/appender.json" \
  --previous .stegverse/test-suite-baseline/main-receipt.json \
  --out "$RESULTS/refresh.json" --candidate-out "$RESULTS/main-receipt.candidate.json"
{ echo '### test suite baseline refresh (candidate retained; admission FAIL_CLOSED pending genesis)'
  echo '```json'; cat "$RESULTS/refresh.json"; echo '```'; } >> "$GITHUB_STEP_SUMMARY"
