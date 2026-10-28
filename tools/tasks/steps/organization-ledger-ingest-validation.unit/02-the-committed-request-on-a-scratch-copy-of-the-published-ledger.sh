# Read-only against the published ref: it is fetched anonymously into a scratch
# bare repository, the committed request is admitted and appended there, and the
# scratch copy is read back. Nothing is pushed; the published ref is unchanged.
set -euo pipefail
python resident-runtime/organization_ledger_ingest.py read
python resident-runtime/organization_ledger_ingest.py admit-sealed --ledger-repository "$GITHUB_REPOSITORY"
scratch="$RUNNER_TEMP/ingest-scratch.git"
git init -q --bare "$scratch"
git --git-dir="$scratch" fetch -q "https://github.com/$GITHUB_REPOSITORY" "+refs/stegverse/organization-ledger:refs/stegverse/organization-ledger"
STEGVERSE_ORG_LEDGER_ROOT="git+$scratch#refs/stegverse/organization-ledger" \
  python resident-runtime/organization_ledger_ingest.py append-sealed --ledger-repository "$GITHUB_REPOSITORY"
python resident-runtime/organization_ledger_ingest.py readback-sealed --location "git+$scratch#refs/stegverse/organization-ledger"
