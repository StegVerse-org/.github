set -euo pipefail
python3 resident-runtime/test_suite_baseline_refresh.py check
test "$(sha256sum resident-runtime/main_change_receipt.py | cut -d' ' -f1)" = "$WRITER_SHA256"
git config --global user.name ci
git config --global user.email ci@stegverse.invalid
LABS="$RUNNER_TEMP/labs-tool"
RESULTS="$RUNNER_TEMP/results"
mkdir -p "$RESULTS"
printf 'LABS=%s\nRESULTS=%s\nSTEGVERSE_LABS_ROOT=%s\n' "$LABS" "$RESULTS" "$LABS" >> "$GITHUB_ENV"
python3 resident-runtime/pinned_labs.py fetch --dest "$LABS"
git -c 'http.https://github.com/.extraheader=' fetch --no-tags --quiet origin \
  '+refs/stegverse/organization-ledger:refs/stegverse/organization-ledger'
# pinned: the runner's system jsonschema 4.10.3 equates a nested true with 1 in enum/const
python -m pip install "jsonschema==4.26.0"
