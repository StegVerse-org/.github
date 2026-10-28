set -eu
git worktree add --quiet --detach "$RUNNER_TEMP/base" "$DIFF_BASE"
python scripts/unittest_junit.py --root "$RUNNER_TEMP/base" \
  --tests-from "$RUNNER_TEMP/selected.txt" --out "$RUNNER_TEMP/base-junit.xml"
