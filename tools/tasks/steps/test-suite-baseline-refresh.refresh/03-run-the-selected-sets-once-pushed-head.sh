set -uo pipefail
mapfile -t selected < "$RESULTS/test-set-args.txt"
# the step shell is bash -e: capture the status so the adjudication step reads it (never lose a failure)
status=0
python -m unittest -v "${selected[@]}" > "$RESULTS/unittest.txt" 2>&1 || status=$?
echo "$status" > "$RESULTS/unittest-status"
tail -n 4 "$RESULTS/unittest.txt"
