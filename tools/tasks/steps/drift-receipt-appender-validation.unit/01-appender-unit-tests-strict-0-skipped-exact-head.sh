set -euo pipefail
test "$(git rev-parse HEAD^2)" = "$HEAD_SHA"
git config --global user.name ci
git config --global user.email ci@stegverse.invalid
python3 resident-runtime/required_verification.py run --pattern 'test_drift_receipt_appender.py' --base "$BASE_SHA" \
  --retry-entrypoint "$WORKFLOW_REF" --out "$RUNNER_TEMP/appender-unit.json"
python3 resident-runtime/required_verification.py run --pattern 'test_required_verification.py' --base "$BASE_SHA" \
  --retry-entrypoint "$WORKFLOW_REF" --out "$RUNNER_TEMP/required-verification-unit.json"
