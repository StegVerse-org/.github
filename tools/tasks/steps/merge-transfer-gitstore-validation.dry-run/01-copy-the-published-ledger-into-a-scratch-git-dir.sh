set -euo pipefail
git fetch --no-tags origin "+$LEDGER_REF:$LEDGER_REF"
published=$(git rev-parse "$LEDGER_REF")
echo "PUBLISHED_TIP=$published" >> "$GITHUB_ENV"
echo "published ledger tip: $published"
# the snapshot the unit job reads is a tip of this ref, tree for tree
pinned=$(python3 -c 'import json; print(json.load(open("tests/fixtures/merge-transfer-gitstore/pin.json"))["ledger_tip"])')
tree=$(python3 -c 'import json; print(json.load(open("tests/fixtures/merge-transfer-gitstore/pin.json"))["ledger_tree"])')
git merge-base --is-ancestor "$pinned" "$published"
test "$(git rev-parse "$pinned^{tree}")" = "$tree"
scratch="$RUNNER_TEMP/scratch-ledger.git"
git init -q --bare "$scratch"
git --git-dir="$scratch" fetch -q "$GITHUB_WORKSPACE" "+$LEDGER_REF:$LEDGER_REF"
namespace=$(python3 -c 'import json; print(json.load(open(".stegverse/transition-ledger/contract.json"))["repository_ledger_location"]["namespace"])')
{
  echo "SCRATCH=$scratch"
  echo "STEGVERSE_ORG_LEDGER_ROOT=git+$scratch#$LEDGER_REF"
  echo "STEGVERSE_ORG_LEDGER_GIT_DIR=$scratch"
  echo "STEGVERSE_REPO_LEDGER_ROOT=git+$scratch#$LEDGER_REF:$namespace"
} >> "$GITHUB_ENV"
mkdir -p "$RUNNER_TEMP/results"
echo "$BASE_SHA" > "$RUNNER_TEMP/results/commits.txt"
