set -euo pipefail
python3 -m unittest tests.test_intr_path_public_ledger_read -v
# Anonymous read (no credential, no auth header) of each inbound row's source ledger. A private or internal
# source is not readable this way; its copy is absent and the verifier stays on the TV/TVC route (FAIL_CLOSED).
pub="$RUNNER_TEMP/public-ledgers"
bash tools/tasks/intr_public_ledgers.sh "$pub"
# Dry run on a scratch copy of this ledger: consume, verify, then end to end per row. Not ledgered, not authentic.
scratch="$RUNNER_TEMP/scratch.git"; git init -q --bare "$scratch"
echo "$(git rev-parse --path-format=absolute --git-common-dir)/objects" > "$scratch/objects/info/alternates"
git --git-dir="$scratch" update-ref "$LEDGER_REF" "$(git rev-parse "$LEDGER_REF")"
namespace=$(python3 -c 'import json; print(json.load(open(".stegverse/transition-ledger/contract.json"))["repository_ledger_location"]["namespace"])')
export STEGVERSE_ORG_LEDGER_ROOT="git+$scratch#$LEDGER_REF" STEGVERSE_REPO_LEDGER_ROOT="git+$scratch#$LEDGER_REF:$namespace"
export STEGVERSE_INTR_PUBLIC_LEDGERS="$pub"
python3 resident-runtime/intr_path_ingress.py consume --out "$RUNNER_TEMP/dry-consume.json" > /dev/null || true
python3 resident-runtime/intr_path_ingress.py verify --out "$RUNNER_TEMP/dry-verify.json" > /dev/null || true
python3 - "$RUNNER_TEMP" "$pub" <<'PY'
import json, subprocess, sys
tmp, pub = sys.argv[1], sys.argv[2]
six = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
       "owning_existing_goal", "next_attempt")
rows = json.load(open(".stegverse/intr-path-transfer/inbound.json"))["transfers"] if __import__("os").path.isfile(".stegverse/intr-path-transfer/inbound.json") else []
for name in ("dry-consume", "dry-verify"):
    for r in (json.load(open(tmp + "/" + name + ".json")) if rows else []):
        assert r["disposition"] in ("ALLOW", "DENY", "FAIL_CLOSED"), r
        assert r["disposition"] == "ALLOW" or all(r.get(f) for f in six), r
for row in rows:
    out = tmp + "/dry-e2e.json"
    subprocess.run(["python3", "resident-runtime/intr_path_ingress.py", "end-to-end-via-tvc", "--path-id", row["path_id"],
                    "--communication-id", row["communication_id"], "--public-ledgers", pub, "--out", out],
                   stdout=subprocess.DEVNULL, check=False)
    r = json.load(open(out))
    assert r["disposition"] in ("ALLOW", "DENY", "FAIL_CLOSED"), r
    assert r["disposition"] == "ALLOW" or all(r.get(f) for f in six), r
    print("INTR_PATH_E0_DRY_RUN", row["path_id"], r["disposition"], r.get("path"), r.get("failure_code"))
PY
