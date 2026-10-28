#!/usr/bin/env bash
# Anonymous read of each inbound row's source-organization ledger (E0, no credential).
#
# usage: tools/tasks/intr_public_ledgers.sh <dir>
#
# For every source organization named in .stegverse/intr-path-transfer/inbound.json,
# fetch https://github.com/<org>/.github $LEDGER_REF into <dir>/<org>.git with no
# credential helper and no auth header. A private or internal source is not readable
# this way: its copy is removed and the reader stays on the TV/TVC route, where
# resident-runtime/intr_path_ingress.py answers FAIL_CLOSED until a TVC read receipt
# verifies. Writes nothing but <dir>. The verifier that consumes <dir>
# (STEGVERSE_INTR_PUBLIC_LEDGERS) is clock-free and network-free; this fetch is the
# only network step and it is read-only.
#
# One reader for both lifecycles: catalog group intr-path-public-ledger-read.validate
# (validation dispatcher) and, once its owner adds the one step proposed on #238, the
# organization ledger writer's path-ingress job.
set -euo pipefail
pub="${1:?usage: intr_public_ledgers.sh <dir>}"
: "${LEDGER_REF:?LEDGER_REF is the organization ledger ref}"
mkdir -p "$pub"
[ -f .stegverse/intr-path-transfer/inbound.json ] || exit 0
for org in $(python3 -c 'import json; print(" ".join(sorted({r["path_id"].split("->")[0] for r in json.load(open(".stegverse/intr-path-transfer/inbound.json"))["transfers"]})))'); do
  git init -q --bare "$pub/$org.git"
  if ! GIT_TERMINAL_PROMPT=0 git --git-dir="$pub/$org.git" -c credential.helper= -c http.https://github.com/.extraheader= \
      fetch -q --no-tags "https://github.com/$org/.github" "+$LEDGER_REF:$LEDGER_REF"; then
    rm -rf "$pub/$org.git"; echo "NOT_ANONYMOUSLY_READABLE $org (TV/TVC route applies; FAIL_CLOSED until a TVC read receipt verifies)"
  fi
done
