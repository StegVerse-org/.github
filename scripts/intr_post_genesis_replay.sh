#!/usr/bin/env bash
# InTr post-genesis replay (StegVerse-org/.github#162, Lane B). Run by hand (or as a CI step) after
# StegVerse-org/.github#224 and StegVerse-Labs/.github#3312 are admitted and each destination's
# intr-path-ingress.yml has run. No dispatch, no cron, no polling, no credential, no ledger write.
#
#   1. fetch: each organization's refs/stegverse/organization-ledger, anonymously (credential.helper= and no
#      auth header). A private or internal organization's ledger is not readable this way; its copy is absent and
#      its paths stay FAIL_CLOSED with retry at StegVerse-Labs/TVC#532 + #535.
#   2. replay: scripts/intr_post_genesis_replay.py reads only those local copies (no network, no clock).
#
# usage: scripts/intr_post_genesis_replay.sh <out-dir> [--require-genesis-allow] [--require-carry-allow] [--require-epoch-allow]
set -euo pipefail
out="${1:?usage: $0 <out-dir> [--require-genesis-allow]}"; shift || true
ref=refs/stegverse/organization-ledger
pub="$out/public-ledgers"; mkdir -p "$pub"
for org in StegVerse-org StegVerse-Labs SV-011 GCAT-BCAT-Engine Admissible-Existence StegGhost StegVerse-002 SV-LLM; do
  rm -rf "$pub/$org.git"; git init -q --bare "$pub/$org.git"
  if ! GIT_TERMINAL_PROMPT=0 GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null git --git-dir="$pub/$org.git" \
      -c credential.helper= -c http.https://github.com/.extraheader= \
      fetch -q --no-tags "https://github.com/$org/.github" "+$ref:$ref" 2>/dev/null; then
    rm -rf "$pub/$org.git"; echo "NOT_ANONYMOUSLY_READABLE $org (TV/TVC route: StegVerse-Labs/TVC#532 + #535)"
  else
    echo "LEDGER_TIP $org $(git --git-dir="$pub/$org.git" rev-parse "$ref")"
  fi
done
python3 scripts/intr_post_genesis_replay.py check > "$out/check.json"
python3 scripts/intr_post_genesis_replay.py replay --public-ledgers "$pub" --out "$out/replay.json" "$@"
