set -euo pipefail
export STEGVERSE_ORG_LEDGER_ROOT="git+$GITHUB_WORKSPACE#$DRY_RUN_REF"
export STEGVERSE_REPO_LEDGER_ROOT="git+$GITHUB_WORKSPACE#$DRY_RUN_REF:$REPO_LEDGER_NAMESPACE"
# a main merge whose main-merge transfer receipt is on the ledger (pinned in the expected real state)
base=$(python3 -c 'import json; print(json.load(open("tests/fixtures/intr-path-transfer/expected-real-state.json"))["verified_transfer_commit"])')
# an organization with no main-merge transfer receipt yet: append the pinned merges to the scratch ref first
for c in $(python3 -c 'import json; print(" ".join(json.load(open("tests/fixtures/intr-path-transfer/expected-real-state.json")).get("temp_merge_transfers") or []))'); do
  python3 resident-runtime/merge_transfer.py append --commit "$c" > /dev/null
done
python3 resident-runtime/intr_path_transfer.py append --transfer-commit "$base" --out "$RUNNER_TEMP/results/append.json" > /dev/null
python3 resident-runtime/intr_path_transfer.py verify --expect-source ALLOW --out "$RUNNER_TEMP/results/verify.json" > /dev/null
tip=$(git rev-parse "$DRY_RUN_REF")
python3 resident-runtime/intr_path_transfer.py append --transfer-commit "$base" --out "$RUNNER_TEMP/results/replay.json" > /dev/null
test "$(git rev-parse "$DRY_RUN_REF")" = "$tip"
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); assert all(x.get("replayed") is True for x in r), r' "$RUNNER_TEMP/results/replay.json"
# A previously ledgered path replays without moving the scratch tip.
# The published ref must remain unchanged by this read-only dry run.
test "$(git ls-remote origin "$LEDGER_REF" | cut -f1)" = "$(cat "$RUNNER_TEMP/published-tip")"
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); print("INTR_PATH_DRY_RUN", json.dumps(r["counts"]))' "$RUNNER_TEMP/results/verify.json"
