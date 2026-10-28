set -eu
LABS="$RUNNER_TEMP/labs-tool"
echo "STEGVERSE_LABS_ROOT=$LABS" >> "$GITHUB_ENV"
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
