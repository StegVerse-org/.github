set -euo pipefail
test -s "$RESULTS/unittest.txt"
mapfile -t selected < "$RESULTS/test-set-args.txt"
python "$LABS/scripts/test_suite_baseline_drift.py" pr --root . --base "$BASE_SHA" \
  --repository StegVerse-org/.github \
  --owning-goal "StegVerse-org/.github#166 ENTERPRISE-HOST-PROVIDER-ERADICATION-001" \
  --baseline .stegverse/test-suite-baseline/baseline.json \
  --baseline-receipt .stegverse/test-suite-baseline/main-receipt.json \
  --selection "$RESULTS/test-set-selection.json" \
  --unittest-output "$RESULTS/unittest.txt" --suite-status "$(cat "$RESULTS/unittest-status")" \
  --unittest-modules "${selected[@]}" \
  --pytest-proof "$WORKFLOW_REF (step: Module-level test functions of the selected sets)" \
  --writer resident-runtime/main_change_receipt.py \
  --writer-sha256 884168399f8ac54309aac86af6ab34481635de54426f635bb2229eb5073e2ebf \
  --retry-entrypoint "$WORKFLOW_REF" \
  --detect-entrypoint "$WORKFLOW_REF (main-head receipt: .stegverse/test-suite-baseline/main-receipt.json)" \
  --out-dir "$RESULTS"
