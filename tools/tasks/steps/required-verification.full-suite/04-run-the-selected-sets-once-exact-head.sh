set -uo pipefail
mapfile -t selected < "$RESULTS/test-set-args.txt"
if [ "${#selected[@]}" -eq 0 ]; then echo "no runnable selected set" | tee "$RESULTS/unittest.txt"; echo 5 > "$RESULTS/unittest-status"; exit 0; fi
# the step shell is bash -e: capture the status so the adjudication step reads it (never lose a failure)
# each run group of the sealed selection (the pinned inputs its sets declare) runs once in its own process
# with only that pin's exports; sets that declare no pinned input run exactly as before
status=0
python "$LABS/scripts/test_set_selection.py" run --selection "$RESULTS/test-set-selection.json" \
  --out "$RESULTS/unittest.txt" --status-out "$RESULTS/unittest-status" || status=$?
test -s "$RESULTS/unittest-status" || echo "$status" > "$RESULTS/unittest-status"
grep -E '^### test-set run group |^Ran [0-9]+ test|^(OK|FAILED)' "$RESULTS/unittest.txt" | tail -n 12
