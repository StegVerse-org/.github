set -euo pipefail
python3 -m unittest tests.test_intr_path_tvc_read -v
# real state: no TVC read receipt is landed, so the other organization's half is FAIL_CLOSED with retry at TVC
python3 resident-runtime/intr_path_ingress.py end-to-end-via-tvc \
  --path-id 'SV-011->StegVerse-org:intr-destination' --communication-id 'intr-path-v1:SV-011->StegVerse-org' \
  --out "$RUNNER_TEMP/pair.json" > /dev/null || true
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); six=("failure_code","failed_predicate","required_evidence_or_repair","retry_entrypoint","owning_existing_goal","next_attempt"); assert r["disposition"] != "ALLOW", r; assert all(r.get(f) for f in six), r; print("INTR_PATH_PAIR_REAL_STATE", r["disposition"], r["failure_code"], r["retry_entrypoint"][:60])' "$RUNNER_TEMP/pair.json"
