export GIT_AUTHOR_NAME=dry-run GIT_AUTHOR_EMAIL=dry-run@invalid GIT_COMMITTER_NAME=dry-run GIT_COMMITTER_EMAIL=dry-run@invalid
python3 resident-runtime/intr_path_ledger.py which
set -euo pipefail
# a main merge whose main-merge transfer receipt is on the ledger (pinned in the expected real state)
base=$(python3 -c 'import json; print(json.load(open("tests/fixtures/intr-path-transfer/expected-real-state.json"))["verified_transfer_commit"])')
# an organization with no main-merge transfer receipt yet: append the pinned merges to the scratch copy first
for c in $(python3 -c 'import json; print(" ".join(json.load(open("tests/fixtures/intr-path-transfer/expected-real-state.json")).get("temp_merge_transfers") or []))'); do
  python3 resident-runtime/intr_path_ledger.py append-merge-transfer --commit "$c" > /dev/null
done
python3 resident-runtime/intr_path_transfer.py append --transfer-commit "$base" --out "$RUNNER_TEMP/results/append.json" > /dev/null
python3 resident-runtime/intr_path_transfer.py verify --expect-source ALLOW --out "$RUNNER_TEMP/results/verify.json" > /dev/null
tip=$(git --git-dir="$SCRATCH" rev-parse "$LEDGER_REF")
python3 resident-runtime/intr_path_transfer.py append --transfer-commit "$base" --out "$RUNNER_TEMP/results/replay.json" > /dev/null
test "$(git --git-dir="$SCRATCH" rev-parse "$LEDGER_REF")" = "$tip"
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); assert all(x.get("replayed") is True for x in r), r' "$RUNNER_TEMP/results/replay.json"
# A previously ledgered path replays without moving the scratch tip; the appends landed on the
# scratch copy only: the workspace ref is unchanged by this dry run.
test "$(git rev-parse "$LEDGER_REF")" = "$(cat "$RUNNER_TEMP/published-tip")"
# The ledger writer may append to the published ref while this runs (push to main): the guard requires
# append-only growth from the copied tip and no scratch append on the published ref, not an unchanged tip.
git fetch --no-tags origin "+$LEDGER_REF:refs/dry-run/published-now"
git fetch -q "$SCRATCH" "+$LEDGER_REF:refs/dry-run/scratch"
python3 resident-runtime/ledger_publish_guard.py --copied-tip "$(cat "$RUNNER_TEMP/published-tip")" \
  --published-now "$(git rev-parse refs/dry-run/published-now)" --scratch-tip "$(git rev-parse refs/dry-run/scratch)"
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); print("INTR_PATH_DRY_RUN", json.dumps(r["counts"]))' "$RUNNER_TEMP/results/verify.json"
