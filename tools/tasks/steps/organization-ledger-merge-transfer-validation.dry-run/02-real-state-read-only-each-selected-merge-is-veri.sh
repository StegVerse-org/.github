set -euo pipefail
export STEGVERSE_ORG_LEDGER_ROOT="git+$GITHUB_WORKSPACE#$DRY_RUN_REF"
export STEGVERSE_REPO_LEDGER_ROOT="git+$GITHUB_WORKSPACE#$DRY_RUN_REF:$REPO_LEDGER_NAMESPACE"
# a mix of ledgered and unledgered merges is expected, so verify may exit 1; any other status is a failure
rc=0
python3 resident-runtime/merge_transfer.py verify \
  --commits-file "$RUNNER_TEMP/results/commits.txt" --out "$RUNNER_TEMP/results/real-state.json" > /dev/null || rc=$?
test "$rc" -le 1
python3 resident-runtime/merge_transfer_dry_run_check.py "$RUNNER_TEMP/results/real-state.json"
