set -euo pipefail
# a mix of ledgered and unledgered merges is expected, so verify may exit 1; any other status is a failure
rc=0
python3 resident-runtime/merge_transfer.py verify \
  --commits-file "$RUNNER_TEMP/results/commits.txt" --out "$RUNNER_TEMP/results/real-state.json" > /dev/null || rc=$?
test "$rc" -le 1
python3 resident-runtime/merge_transfer_dry_run_check.py "$RUNNER_TEMP/results/real-state.json"
