set -euo pipefail
# The writers hold both halves to the declared ref name (resident-runtime/ledger_gitstore.py
# preflight, through intr_destination_ingress._append), so the copy keeps that name in a scratch
# bare git dir instead of a second ref name in the workspace. It is never pushed.
git fetch --no-tags origin "+$LEDGER_REF:$LEDGER_REF"
published=$(git rev-parse "$LEDGER_REF")
echo "published ledger tip: $published"
mkdir -p "$RUNNER_TEMP/results"
echo "$published" > "$RUNNER_TEMP/results/published-tip"
scratch="$RUNNER_TEMP/scratch-ledger.git"
git init -q --bare "$scratch"
git --git-dir="$scratch" fetch -q "$GITHUB_WORKSPACE" "+$LEDGER_REF:$LEDGER_REF"
namespace=$(python3 -c 'import json; print(json.load(open(".stegverse/transition-ledger/contract.json"))["repository_ledger_location"]["namespace"])')
{
  echo "SCRATCH=$scratch"
  echo "STEGVERSE_ORG_LEDGER_ROOT=git+$scratch#$LEDGER_REF"
  echo "STEGVERSE_REPO_LEDGER_ROOT=git+$scratch#$LEDGER_REF:$namespace"
} >> "$GITHUB_ENV"
export STEGVERSE_ORG_LEDGER_ROOT="git+$scratch#$LEDGER_REF"
export STEGVERSE_REPO_LEDGER_ROOT="git+$scratch#$LEDGER_REF:$namespace"
# An empty range (BASE already ledgered, nothing pending) selects BASE when it is ledgered ALLOW VERIFIED, so
# verify is a no-op read of its recorded receipt; anything else is FAIL_CLOSED with six fields (stderr), exit 1.
python3 resident-runtime/merge_transfer_range.py --before "$BASE_SHA" --after "$BASE_SHA" \
  --pending .stegverse/merge-transfer/pending.json --select-ledgered-base-when-empty > "$RUNNER_TEMP/results/commits.txt"
cat "$RUNNER_TEMP/results/commits.txt"
grep -Eq '^[0-9a-f]{40}$' "$RUNNER_TEMP/results/commits.txt"
