set -euo pipefail
test "$(git rev-parse HEAD^2)" = "$HEAD_SHA"
git config --global user.name ci
git config --global user.email ci@stegverse.invalid
LABS="$RUNNER_TEMP/labs-tool"
RESULTS="$RUNNER_TEMP/results"
printf 'LABS=%s\nRESULTS=%s\nSTEGVERSE_LABS_ROOT=%s\n' "$LABS" "$RESULTS" "$LABS" >> "$GITHUB_ENV"
mkdir -p "$RESULTS"
pin=.stegverse/test-suite-baseline/labs-tool-pin.json
commit=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["commit"])' "$pin")
url=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["url"])' "$pin")
git init -q "$LABS"
git -C "$LABS" -c 'http.https://github.com/.extraheader=' fetch --no-tags --quiet --depth=1 "$url" "$commit"
git -C "$LABS" checkout -q FETCH_HEAD
test "$(git -C "$LABS" rev-parse HEAD)" = "$commit"
python3 - "$pin" "$LABS" <<'PY'
import hashlib, json, sys
pin = json.load(open(sys.argv[1]))
for path, want in sorted(pin["files"].items()):
    got = hashlib.sha256(open(f"{sys.argv[2]}/{path}", "rb").read()).hexdigest()
    print(path, got)
    if got != want:
        raise SystemExit(f"{path}: sha256 {got} is not the pinned {want}")
PY
