set -euo pipefail
mkdir -p "$RUNNER_TEMP/results"
test "$(sha256sum resident-runtime/main_change_receipt.py | cut -d' ' -f1)" = 884168399f8ac54309aac86af6ab34481635de54426f635bb2229eb5073e2ebf
labs="$RUNNER_TEMP/labs.git"
git init -q --bare "$labs"
git --git-dir="$labs" fetch -q --depth=2 https://github.com/StegVerse-Labs/.github "$LABS_HEAD"
git --git-dir="$labs" fetch -q https://github.com/StegVerse-Labs/.github \
  '+refs/stegverse/organization-ledger:refs/stegverse/organization-ledger' || echo "organization ledger ref not fetched"
scratch="$RUNNER_TEMP/scratch.git"
fresh="$RUNNER_TEMP/fresh.git"
git init -q --bare "$scratch"
git init -q --bare "$fresh"
python3 resident-runtime/drift_receipt_appender.py dry-run --root "$labs" --payload "$PAYLOAD" \
  --writer-ref "$HEAD_SHA" --scratch "$scratch" --fresh "$fresh" --out "$RUNNER_TEMP/results/dry-run.json" > /dev/null
python3 - "$RUNNER_TEMP/results/dry-run.json" "$LABS_HEAD" <<'PY'
import json, sys
six = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint", "owning_existing_goal", "next_attempt")
d, head = json.load(open(sys.argv[1])), sys.argv[2]
assert not d["refusals"] and d["verify"]["disposition"] == "ALLOW" and d["replay"]["appended"] == [], d
(r,) = d["receipts"]
assert r["commit"] == head and r["main_change_receipt"]["commit"] == head, r
assert r["disposition"] == "FAIL_CLOSED" and all(r["admission"].get(k) for k in six), r
assert r["admission"]["failure_code"] == "DRIFT_RECEIPT_APPENDER_ADMISSION_PENDING_GENESIS", r
# the retained payload predates verification accounting: its receipt leads with REQUIRED_VERIFICATION_SKIPPED
assert r["first_item"]["failure_code"] == "REQUIRED_VERIFICATION_SKIPPED" and all(r["first_item"].get(k) for k in six), r
assert r["organization_ledger_effect"] == "NONE"
print("drift transition receipt", r["receipt_sha256"])
print("main-change receipt", r["main_change_receipt_sha256"], r["main_change_receipt"]["merge_kind"], [i["failure_code"] for i in r["items"]])
print("payload", r["payload"]["receipt_sha256"], "hb_epoch", r["hb_epoch"])
print("scratch tip", d["append"]["tip"])
PY
{ echo '### drift receipt appender (scratch dry run)'; echo '```json'; cat "$RUNNER_TEMP/results/dry-run.json"; echo '```'; } >> "$GITHUB_STEP_SUMMARY"
# nothing was published
for repo in StegVerse-Labs/.github StegVerse-org/.github; do
  test -z "$(git ls-remote "https://github.com/$repo" refs/stegverse/test-suite-baseline-drift)"
done
