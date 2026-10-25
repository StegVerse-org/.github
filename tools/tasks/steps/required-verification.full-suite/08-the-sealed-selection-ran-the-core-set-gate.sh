set -euo pipefail
# Folded from the needs-aggregator job 'required-verification' of #222's required-verification.yml. In the
# dispatcher each catalog group is its own check, so this gate holds this group only: it runs only when every
# earlier step of this group succeeded (no if:), and it requires the sealed selection that ran the core set for
# this pull request's exact commits. path-scope is its own catalog group and check.
python3 resident-runtime/required_verification.py gate --needs '{"full-suite": {"result": "success"}}' \
  --selection "$(cat "$RESULTS/selection-summary.json")" \
  --pr-head "$HEAD_SHA" --base-sha "$BASE_SHA" --require full-suite \
  --retry-entrypoint "$WORKFLOW_REF" \
  --out "$RESULTS/gate.json"
