# Read-only against the published ref: it is fetched anonymously into a scratch
# bare repository, the committed request is admitted and appended there, and the
# scratch copy is read back. Nothing is pushed; the published ref is unchanged.
set -euo pipefail
envfile="$RUNNER_TEMP/ingest.env"
python resident-runtime/organization_ledger_ingest.py read --materialize "$RUNNER_TEMP/ingest" --github-env "$envfile"
. "$envfile"
if [ "$INGEST_OPERATION" = "sv_push_receipt" ]; then
  # A push receipt is appended once per range, only by the writer's push-time job; the PR-facing check admits the
  # committed receipt (shape, seal, supplied epoch) and appends nothing, so it cannot go red once the writer has
  # recorded the range.
  python resident-runtime/sv_push_receipt_append.py admit --push-receipt "$RUNNER_TEMP/ingest/push-receipt.json" \
    --hb-epoch "$HB_EPOCH"
  exit 0
fi
python resident-runtime/organization_ledger_ingest.py admit-sealed --ledger-repository "$GITHUB_REPOSITORY"
scratch="$RUNNER_TEMP/ingest-scratch.git"
git init -q --bare "$scratch"
git --git-dir="$scratch" fetch -q "https://github.com/$GITHUB_REPOSITORY" "+refs/stegverse/organization-ledger:refs/stegverse/organization-ledger"
STEGVERSE_ORG_LEDGER_ROOT="git+$scratch#refs/stegverse/organization-ledger" \
  python resident-runtime/organization_ledger_ingest.py append-sealed --ledger-repository "$GITHUB_REPOSITORY"
python resident-runtime/organization_ledger_ingest.py readback-sealed --location "git+$scratch#refs/stegverse/organization-ledger"
