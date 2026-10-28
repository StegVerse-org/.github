set -eu
base_args=""
if [ -n "${DIFF_BASE:-}" ]; then base_args="--base-junit $RUNNER_TEMP/base-junit.xml --base $DIFF_BASE"; fi
# #162 D2 option (d), a draft for the owner to ratify or revert: read the TVC and repo-standards ledger receipts at
# this exact head with the consumers required-verification.full-suite already runs (read-only, the ledger ref step 02
# fetched). A refusal or an error here satisfies nothing; the receipt below then fails closed exactly as before.
test "$(git rev-parse HEAD)" = "$HEAD_SHA"
python3 resident-runtime/tvc_conformance_receipt.py consume --ledger "git+$PWD#refs/stegverse/organization-ledger" \
  --head-root . --out "$RUNNER_TEMP/consumption-tvc.json" || true
python3 resident-runtime/repo_standards_owner_drift_receipt.py consume --ledger "git+$PWD#refs/stegverse/organization-ledger" \
  --head-root . --out "$RUNNER_TEMP/consumption-repo-standards.json" || true
python scripts/test_suite_skip_receipt.py \
  --junit "$RUNNER_TEMP/head-junit.xml" --head "$HEAD_SHA" --tested-commit "$(git rev-parse HEAD)" \
  --selection "$RUNNER_TEMP/test-selection.json" $base_args \
  --out "$RUNNER_TEMP/test-suite-skip-receipt.json" --skip-items data/test-suite-skip-items.json \
  --receipt-consumption "tvc=$RUNNER_TEMP/consumption-tvc.json" \
  --receipt-consumption "repo-standards=$RUNNER_TEMP/consumption-repo-standards.json" --root . \
  --retry-entrypoint "python3 tools/tasks/run_catalog.py run --group test-suite-selected.selected (validation-dispatcher.yml) on the next pull request head" \
  --owning-goal "StegVerse-org/.github#162 (selected tests on the exact head, 0 skipped)"
