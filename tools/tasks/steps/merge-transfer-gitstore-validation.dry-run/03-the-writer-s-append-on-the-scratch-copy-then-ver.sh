set -euo pipefail
before=$(git --git-dir="$SCRATCH" rev-parse "$LEDGER_REF")
python3 resident-runtime/merge_transfer_gitstore.py append --commits-file "$RUNNER_TEMP/results/commits.txt" \
  --out "$RUNNER_TEMP/results/append.json"
fresh="$RUNNER_TEMP/fresh-ledger.git"
git init -q --bare "$fresh"
git --git-dir="$fresh" fetch -q "$SCRATCH" "+$LEDGER_REF:$LEDGER_REF"
python3 resident-runtime/merge_transfer_gitstore.py verify --git-dir "$fresh" --ref "$LEDGER_REF" \
  --commits-file "$RUNNER_TEMP/results/commits.txt" --out "$RUNNER_TEMP/results/verify.json"
tip=$(git --git-dir="$SCRATCH" rev-parse "$LEDGER_REF")
python3 resident-runtime/merge_transfer_gitstore.py append --commits-file "$RUNNER_TEMP/results/commits.txt" \
  --out "$RUNNER_TEMP/results/replay.json"
test "$(git --git-dir="$SCRATCH" rev-parse "$LEDGER_REF")" = "$tip"
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); assert all(x["replayed"] is True for x in r), r' "$RUNNER_TEMP/results/replay.json"
# a base already ledgered is a replay that writes nothing; otherwise the append moved the scratch tip
python3 - "$RUNNER_TEMP/results/append.json" "$before" "$tip" <<'PY'
import json, sys
appended, before, tip = json.load(open(sys.argv[1])), sys.argv[2], sys.argv[3]
assert all(x["disposition"] == "ALLOW" for x in appended), appended
assert (tip == before) == all(x["replayed"] is True for x in appended), (before, tip, appended)
print("writer surface:", appended[0]["writer_surface"], "replayed:", appended[0]["replayed"])
PY
# nothing was published: the workspace ref is the fetched tip and the remote never holds a scratch append
test "$(git rev-parse "$LEDGER_REF")" = "$PUBLISHED_TIP"
test "$tip" = "$before" || test "$(git ls-remote origin "$LEDGER_REF" | cut -f1)" != "$tip"
{ echo '### dry run (scratch git dir, not published)'; echo '```json'; cat "$RUNNER_TEMP/results/verify.json"; echo '```'; } >> "$GITHUB_STEP_SUMMARY"
