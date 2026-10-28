set -uo pipefail
mapfile -t selected < "$RESULTS/test-set-args.txt"
python "$LABS/scripts/test_suite_baseline_drift.py" detect --root . --head HEAD \
  --repository StegVerse-org/.github --owning-goal "$GOAL" \
  --baseline .stegverse/test-suite-baseline/baseline.json \
  --selection "$RESULTS/test-set-selection.json" \
  --unittest-output "$RESULTS/unittest.txt" --unittest-modules "${selected[@]}" \
  --writer resident-runtime/main_change_receipt.py --writer-sha256 "$WRITER_SHA256" \
  --detect-entrypoint "$WORKFLOW_REF" --out-dir "$RESULTS/detect"
echo $? > "$RESULTS/detect-status"
test -s "$RESULTS/detect/receipt.json"
