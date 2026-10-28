set -euo pipefail
test "$(git rev-parse HEAD^2)" = "$HEAD_SHA"
python3 resident-runtime/required_verification.py path-scope --base "$BASE_SHA" --head "$HEAD_SHA" \
  --retry-entrypoint "tools/tasks/task_catalog.json group required-verification.path-scope" --out "$RUNNER_TEMP/path-scope.json"
