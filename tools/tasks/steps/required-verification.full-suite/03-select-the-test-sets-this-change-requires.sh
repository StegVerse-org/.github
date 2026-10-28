set -euo pipefail
python "$LABS/scripts/test_set_selection.py" select --root . --manifest .stegverse/test-sets.json \
  --spec .stegverse/test-set-spec.json --base "$BASE_SHA" --head HEAD --pr-head "$HEAD_SHA" \
  --retry-entrypoint "$WORKFLOW_REF" --owning-goal "StegVerse-org/.github#166 ENTERPRISE-HOST-PROVIDER-ERADICATION-001" \
  --out "$RESULTS/test-set-selection.json" --args-out "$RESULTS/test-set-args.txt" || true
test -s "$RESULTS/test-set-selection.json"
test -f "$RESULTS/test-set-args.txt"
