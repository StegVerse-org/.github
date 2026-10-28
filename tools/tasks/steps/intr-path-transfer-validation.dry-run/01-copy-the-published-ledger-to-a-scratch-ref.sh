set -euo pipefail
git fetch --no-tags origin "+$LEDGER_REF:$DRY_RUN_REF"
echo "published ledger tip: $(git rev-parse "$DRY_RUN_REF")"
git rev-parse "$DRY_RUN_REF" > "$RUNNER_TEMP/published-tip"
namespace=$(python3 -c 'import json; print(json.load(open(".stegverse/transition-ledger/contract.json"))["repository_ledger_location"]["namespace"])')
echo "REPO_LEDGER_NAMESPACE=$namespace" >> "$GITHUB_ENV"
mkdir -p "$RUNNER_TEMP/results"
