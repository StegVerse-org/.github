set -eu
HEAD_SHA="${PR_HEAD_SHA:-$PUSH_SHA}"
BASE_SHA="${PR_BASE_SHA:-$PUSH_BEFORE}"
printf 'HEAD_SHA=%s\nBASE_SHA=%s\n' "$HEAD_SHA" "$BASE_SHA" >> "$GITHUB_ENV"
git checkout -q --detach "$HEAD_SHA"
test "$(git rev-parse HEAD)" = "$HEAD_SHA"
