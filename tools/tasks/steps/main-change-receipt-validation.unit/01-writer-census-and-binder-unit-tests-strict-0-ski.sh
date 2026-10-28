set -euo pipefail
test "$(git rev-parse HEAD^2)" = "$HEAD_SHA"
git config --global user.name ci
git config --global user.email ci@stegverse.invalid
python3 resident-runtime/required_verification.py run --pattern 'test_main_change_receipt*.py' --base "$BASE_SHA" \
  --retry-entrypoint "$WORKFLOW_REF" --out "$RUNNER_TEMP/writer-unit.json"
python3 resident-runtime/required_verification.py run --pattern 'test_push_receipt_session_binder.py' --base "$BASE_SHA" \
  --retry-entrypoint "$WORKFLOW_REF" --out "$RUNNER_TEMP/binder-unit.json"
