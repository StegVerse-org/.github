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
if [ "$INGEST_OPERATION" = "sv_check_receipt" ]; then
  # Appended once per receipt, only by the writer's push-time job; the PR-facing check admits the committed receipt
  # (pins, schema, supplied epoch, declared command, stage-gate binding) and appends nothing.
  gate_args=()
  if [ -f "$RUNNER_TEMP/ingest/evaluation-subject.json" ]; then gate_args+=(--subject "$RUNNER_TEMP/ingest/evaluation-subject.json"); fi
  if [ -f "$RUNNER_TEMP/ingest/base-state-readback.json" ]; then gate_args+=(--readback "$RUNNER_TEMP/ingest/base-state-readback.json"); fi
  python resident-runtime/sv_check_receipt_append.py admit --check-receipt "$RUNNER_TEMP/ingest/check-receipt.json" \
    --hb-epoch "$HB_EPOCH" --ledger-repository "$GITHUB_REPOSITORY" "${gate_args[@]}"
  exit 0
fi
if [ "$INGEST_OPERATION" = "sv_change_admit" ]; then
  # Recorded once per change, only by the writer's push-time job; the PR-facing check admits the committed request
  # (shape, owning ledger, NATIVE successor, supplied epoch, P1 pins) and appends nothing, so it cannot go red once the
  # writer has recorded the change.
  python resident-runtime/sv_change_admit_append.py admit --predecessor "$RUNNER_TEMP/ingest/predecessor.json" \
    --successor "$RUNNER_TEMP/ingest/successor.json" --admission "$RUNNER_TEMP/ingest/admission.json" --hb-epoch "$HB_EPOCH"
  exit 0
fi
python resident-runtime/organization_ledger_ingest.py admit-sealed --ledger-repository "$GITHUB_REPOSITORY"
scratch="$RUNNER_TEMP/ingest-scratch.git"
git init -q --bare "$scratch"
git --git-dir="$scratch" fetch -q "https://github.com/$GITHUB_REPOSITORY" "+refs/stegverse/organization-ledger:refs/stegverse/organization-ledger"
STEGVERSE_ORG_LEDGER_ROOT="git+$scratch#refs/stegverse/organization-ledger" \
  python resident-runtime/organization_ledger_ingest.py append-sealed --ledger-repository "$GITHUB_REPOSITORY"
python resident-runtime/organization_ledger_ingest.py readback-sealed --location "git+$scratch#refs/stegverse/organization-ledger"
