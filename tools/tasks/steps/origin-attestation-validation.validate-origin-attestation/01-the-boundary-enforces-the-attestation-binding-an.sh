python org-runtime/runtime_boundary.py validate > boundary.json
python - <<'PY'
import json
x = json.load(open("boundary.json"))
assert x["valid"] is True, x["checks"]
assert x["checks"]["origin_attestation_is_bound"] is True
print("ORIGIN_ATTESTATION_BOUND=PASS", len(x["checks"]), "checks")
PY
