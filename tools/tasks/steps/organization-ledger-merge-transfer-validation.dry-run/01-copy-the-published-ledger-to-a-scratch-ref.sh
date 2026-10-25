set -euo pipefail
git fetch --no-tags origin "+$LEDGER_REF:$DRY_RUN_REF"
echo "published ledger tip: $(git rev-parse "$DRY_RUN_REF")"
mkdir -p "$RUNNER_TEMP/results"
git rev-parse "$DRY_RUN_REF" > "$RUNNER_TEMP/results/published-tip"
namespace=$(python3 -c 'import json; print(json.load(open(".stegverse/transition-ledger/contract.json"))["repository_ledger_location"]["namespace"])')
echo "REPO_LEDGER_NAMESPACE=$namespace" >> "$GITHUB_ENV"
mkdir -p "$RUNNER_TEMP/results"
export STEGVERSE_ORG_LEDGER_ROOT="git+$GITHUB_WORKSPACE#$DRY_RUN_REF"
export STEGVERSE_REPO_LEDGER_ROOT="git+$GITHUB_WORKSPACE#$DRY_RUN_REF:$namespace"
# An empty range (BASE already ledgered, nothing pending) selects BASE when it is ledgered ALLOW VERIFIED, so
# verify is a no-op read of its recorded receipt; anything else is FAIL_CLOSED with six fields (stderr), exit 1.
python3 resident-runtime/merge_transfer_range.py --before "$BASE_SHA" --after "$BASE_SHA" \
  --pending .stegverse/merge-transfer/pending.json --select-ledgered-base-when-empty > "$RUNNER_TEMP/results/commits.txt"
cat "$RUNNER_TEMP/results/commits.txt"
grep -Eq '^[0-9a-f]{40}$' "$RUNNER_TEMP/results/commits.txt"
