set -eu
test "$(git rev-parse HEAD)" = "$HEAD_SHA"
if git cat-file -e "${BASE_SHA}^{commit}" 2>/dev/null; then
  BASE="$(git merge-base "$BASE_SHA" HEAD)"
  git diff --name-only "$BASE" HEAD > "$RUNNER_TEMP/changed.txt"
else
  BASE=""
  echo "<no base commit: ${BASE_SHA}>" > "$RUNNER_TEMP/changed.txt"
fi
echo "DIFF_BASE=$BASE" >> "$GITHUB_ENV"
python scripts/select_tests_for_change.py --changed "$RUNNER_TEMP/changed.txt" \
  --out "$RUNNER_TEMP/test-selection.json" --print-modules > "$RUNNER_TEMP/selected.txt"
wc -l < "$RUNNER_TEMP/selected.txt"
