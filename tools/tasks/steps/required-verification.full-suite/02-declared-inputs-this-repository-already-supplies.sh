set -euo pipefail
# The organization ledger ref, fetched anonymously as intr-path-transfer-validation.yml does.
git -c 'http.https://github.com/.extraheader=' fetch --no-tags --quiet origin \
  '+refs/stegverse/organization-ledger:refs/stegverse/organization-ledger'
# jsonschema: only the agreement oracle (tests/test_stdlib_json_schema_agreement.py). Every schema check
# validates with the pinned stdlib validator (STEGVERSE_LABS_ROOT, sha256-checked above).
# pinned: the runner's system jsonschema 4.10.3 equates a nested true with 1 in enum/const
python -m pip install "jsonschema==4.26.0"
