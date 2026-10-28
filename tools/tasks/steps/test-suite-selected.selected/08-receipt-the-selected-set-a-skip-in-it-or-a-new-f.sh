set -eu
base_args=""
if [ -n "${DIFF_BASE:-}" ]; then base_args="--base-junit $RUNNER_TEMP/base-junit.xml --base $DIFF_BASE"; fi
python scripts/test_suite_skip_receipt.py \
  --junit "$RUNNER_TEMP/head-junit.xml" --head "$HEAD_SHA" --tested-commit "$(git rev-parse HEAD)" \
  --selection "$RUNNER_TEMP/test-selection.json" $base_args \
  --out "$RUNNER_TEMP/test-suite-skip-receipt.json" --skip-items data/test-suite-skip-items.json \
  --retry-entrypoint "python3 tools/tasks/run_catalog.py run --group test-suite-selected.selected (validation-dispatcher.yml) on the next pull request head" \
  --owning-goal "StegVerse-org/.github#162 (selected tests on the exact head, 0 skipped)"
