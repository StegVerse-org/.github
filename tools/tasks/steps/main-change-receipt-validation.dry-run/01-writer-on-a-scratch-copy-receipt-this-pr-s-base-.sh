set -euo pipefail
mkdir -p "$RUNNER_TEMP/results"
scratch="$RUNNER_TEMP/scratch.git"
git clone -q --bare "$GITHUB_WORKSPACE" "$scratch"
git --git-dir="$scratch" fetch -q "$GITHUB_WORKSPACE" "+$HEAD_SHA:refs/heads/main"
# the range this PR adds on top of main (base.sha can be ahead of the branch point)
before=$(git merge-base "$BASE_SHA" "$HEAD_SHA")
writer_sha=$(sha256sum resident-runtime/main_change_receipt.py | cut -d' ' -f1)
python3 resident-runtime/main_change_receipt.py observe --root "$scratch" --repository "$GITHUB_REPOSITORY" \
  --before "$before" --after "$HEAD_SHA" --writer-ref "$HEAD_SHA" --writer-sha256 "$writer_sha" \
  --organization-ledger-writer-installed --out "$RUNNER_TEMP/results/receipts.json" > /dev/null
python3 resident-runtime/main_change_receipt.py append --root "$scratch" --receipts "$RUNNER_TEMP/results/receipts.json" \
  --out "$RUNNER_TEMP/results/append.json" > /dev/null
tip=$(git --git-dir="$scratch" rev-parse refs/stegverse/main-change-receipts)
python3 resident-runtime/main_change_receipt.py append --root "$scratch" --receipts "$RUNNER_TEMP/results/receipts.json" \
  --out "$RUNNER_TEMP/results/replay.json" > /dev/null
test "$(git --git-dir="$scratch" rev-parse refs/stegverse/main-change-receipts)" = "$tip"
fresh="$RUNNER_TEMP/fresh.git"
git init -q --bare "$fresh"
git --git-dir="$fresh" fetch -q "$scratch" "+refs/stegverse/main-change-receipts:refs/stegverse/main-change-receipts"
python3 resident-runtime/main_change_receipt.py verify --root "$fresh" --receipts "$RUNNER_TEMP/results/receipts.json" \
  --out "$RUNNER_TEMP/results/verify.json"
python3 - "$RUNNER_TEMP/results/receipts.json" "$HEAD_SHA" <<'PY'
import json, sys
receipts, head = json.load(open(sys.argv[1])), sys.argv[2]
assert receipts and receipts[-1]["commit"] == head and not receipts[-1]["push"]["history_rewritten"], receipts
for r in receipts:
    assert r["lowest_supported_mode"] == "E0" and r["admission_record_ref"] is None
    print(r["commit"], r["merge_kind"], r["disposition"], [i["failure_code"] for i in r["items"]])
PY
# nothing was published
test -z "$(git ls-remote "https://github.com/$GITHUB_REPOSITORY" refs/stegverse/main-change-receipts | grep -F "$tip" || true)"
