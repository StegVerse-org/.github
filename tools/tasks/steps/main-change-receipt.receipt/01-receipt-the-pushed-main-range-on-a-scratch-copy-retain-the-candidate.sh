set -euo pipefail
# Default writer placement for #222 (decision default on StegVerse-org/.github#238): the receipt is computed
# and sealed here, read-only (dispatcher permissions contents: read), on a scratch copy; the consequence
# (an append to refs/stegverse/main-change-receipts) is a manifest-directed transition carried by
# organization-ledger-writer.yml once the organization ledger admits it from genesis
# (resident-runtime/main-change-receipt.transition.json). Nothing is published from this group.
mkdir -p "$RUNNER_TEMP/results"
test "$(git rev-parse HEAD)" = "$AFTER_SHA"
scratch="$RUNNER_TEMP/scratch.git"
git clone -q --bare "$GITHUB_WORKSPACE" "$scratch"
git --git-dir="$scratch" fetch -q "$GITHUB_WORKSPACE" "+$AFTER_SHA:refs/heads/main"
writer_sha=$(sha256sum resident-runtime/main_change_receipt.py | cut -d' ' -f1)
test "$writer_sha" = "$WRITER_SHA256"
python3 resident-runtime/main_change_receipt.py observe --root "$scratch" --repository "$GITHUB_REPOSITORY" \
  --before "$BEFORE_SHA" --after "$AFTER_SHA" --writer-ref "$AFTER_SHA" --writer-sha256 "$writer_sha" \
  --organization-ledger-writer-installed --out "$RUNNER_TEMP/results/receipts.json" > /dev/null
python3 resident-runtime/main_change_receipt.py append --root "$scratch" --receipts "$RUNNER_TEMP/results/receipts.json" \
  --out "$RUNNER_TEMP/results/append.json" > /dev/null
fresh="$RUNNER_TEMP/fresh.git"
git init -q --bare "$fresh"
git --git-dir="$fresh" fetch -q "$scratch" "+refs/stegverse/main-change-receipts:refs/stegverse/main-change-receipts"
python3 resident-runtime/main_change_receipt.py verify --root "$fresh" --receipts "$RUNNER_TEMP/results/receipts.json" \
  --out "$RUNNER_TEMP/results/verify.json"
python3 - "$RUNNER_TEMP/results/receipts.json" "$AFTER_SHA" "$RUNNER_TEMP/results/admission.json" <<'PY'
import json, sys
receipts, head = json.load(open(sys.argv[1])), sys.argv[2]
assert receipts and receipts[-1]["commit"] == head, receipts
for r in receipts:
    assert r["lowest_supported_mode"] == "E0" and r["admission_record_ref"] is None
admission = {
    "disposition": "FAIL_CLOSED",
    "failure_code": "MAIN_CHANGE_RECEIPT_ADMISSION_PENDING_GENESIS",
    "failed_predicate": "MAIN_CHANGE_RECEIPT_TRANSITION_IS_ADMITTED_FROM_ORGANIZATION_LEDGER_GENESIS",
    "required_evidence_or_repair": "the organization ledger declares its genesis and admits operation MAIN_CHANGE_RECEIPT_APPEND "
        "(resident-runtime/main-change-receipt.transition.json); organization-ledger-writer.yml then appends the retained receipts",
    "retry_entrypoint": "tools/tasks/task_catalog.json group main-change-receipt.receipt (validation-dispatcher.yml, push to main)",
    "owning_existing_goal": "StegVerse-org/.github#162 (organization ledger) / StegVerse-org/.github#166",
    "next_attempt": "the first push to main after genesis admits MAIN_CHANGE_RECEIPT_APPEND",
    "receipts": len(receipts),
    "consequence_committed": False,
}
json.dump(admission, open(sys.argv[3], "w"), indent=2, sort_keys=True)
print(json.dumps(admission, sort_keys=True))
PY
# nothing was published
tip=$(git --git-dir="$scratch" rev-parse refs/stegverse/main-change-receipts)
test -z "$(git ls-remote "https://github.com/$GITHUB_REPOSITORY" refs/stegverse/main-change-receipts | grep -F "$tip" || true)"
