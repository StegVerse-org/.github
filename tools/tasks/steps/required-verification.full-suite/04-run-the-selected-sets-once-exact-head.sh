set -uo pipefail
mapfile -t selected < "$RESULTS/test-set-args.txt"
if [ "${#selected[@]}" -eq 0 ]; then echo "no runnable selected set" | tee "$RESULTS/unittest.txt"; echo 5 > "$RESULTS/unittest-status"; exit 0; fi
# the step shell is bash -e: capture the status so the adjudication step reads it (never lose a failure)
status=0
python -m unittest -v "${selected[@]}" > "$RESULTS/unittest.txt" 2>&1 || status=$?
echo "$status" > "$RESULTS/unittest-status"
tail -n 4 "$RESULTS/unittest.txt"
