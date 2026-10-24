#!/usr/bin/env bash
# Lane B (session lane-b-91117956, StegVerse-org/.github#162): anonymous InTr mesh destination + ledger receipt read
# for ONE organization. Safe to re-run; reads only; never writes any ledger ref on GitHub; no dispatch.
# SKAP invariant: the SKAP Vault inside KV is the only PII and credential store for every user, the ecosystem's
# own included. These reads need and hold no credential, token or TVC receipt: anonymous https only.
# usage: read_org.sh <org>      output: /workspace/laneB/reads/out/<org>.json
set -uo pipefail
ORG=${1:?usage: read_org.sh <org>}
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false SSH_ASKPASS=/bin/false HOME=/tmp/anonhome
unset GH_TOKEN GITHUB_TOKEN GH_ENTERPRISE_TOKEN GIT_CREDENTIAL_HELPER
mkdir -p "$HOME"
HERE=$(cd "$(dirname "$0")" && pwd); C=$HERE/cache; OUT=$HERE/out; ANON=/workspace/laneB/lab1024/anon
REF=refs/stegverse/organization-ledger; T=60
ORGS16="StegVerse-org StegVerse-Labs StegGhost GCAT-BCAT-Engine AaCT-E AdmittedCode ECAT-ICAT-Formal master-records Triad-Test formalism-tests Data-Continuation Admissible-Existence StegVerse-002 Infrastructure-Continuity-Ventures SV-011 SV-LLM"
mkdir -p "$C/main" "$C/lsr" "$OUT" "$ANON"
G="git -c credential.helper= -c core.askPass=/bin/false"
url() { echo "https://github.com/$1/.github"; }
bare() { [ -d "$1" ] || git init -q --bare "$1"; }

# ledger ref (as specified by the coordinator) into the lab1024 anonymous mirror; ls-remote result cached per org
ledger() { local o=$1; bare "$ANON/$o.git"
  timeout $T git ls-remote "$(url $o)" refs/heads/main $REF > "$C/lsr/$o.txt" 2>"$C/lsr/$o.err"; echo $? > "$C/lsr/$o.rc"
  if grep -q "$REF" "$C/lsr/$o.txt"; then
    timeout $T $G --git-dir="$ANON/$o.git" fetch -q "$(url $o)" "+$REF:$REF" 2>>"$C/lsr/$o.err" || echo "fetch_failed" >> "$C/lsr/$o.err"
  else git --git-dir="$ANON/$o.git" update-ref -d $REF 2>/dev/null || true; fi   # local mirror only; never remote
}
# main snapshot (depth 1) extracted to cache/main/<org>@<sha>
mainsnap() { local o=$1 d="$C/$1.git"; bare "$d"
  timeout $T $G --git-dir="$d" fetch -q --depth 1 "$(url $o)" +refs/heads/main:refs/remotes/anon/main 2>/dev/null || return 1
  local s; s=$(git --git-dir="$d" rev-parse refs/remotes/anon/main); local w="$C/main/$o@$s"
  [ -d "$w" ] || { mkdir -p "$w.tmp" && git --git-dir="$d" archive "$s" | tar -x -C "$w.tmp" && mv "$w.tmp" "$w"; }
  ln -sfn "$w" "$C/main/$o"; }

# target org + every peer's ledger ref (parallel; private orgs fail fast), plus the three main snapshots needed
for o in $ORGS16; do ledger "$o" & done; [[ " $ORGS16 " == *" $ORG "* ]] || ledger "$ORG" &
mainsnap StegVerse-org & mainsnap StegVerse-Labs & [ "$ORG" = StegVerse-org ] || [ "$ORG" = StegVerse-Labs ] || mainsnap "$ORG" &
wait
python3 "$HERE/read_org.py" "$ORG" "$C" "$ANON" "$OUT/$ORG.json"
