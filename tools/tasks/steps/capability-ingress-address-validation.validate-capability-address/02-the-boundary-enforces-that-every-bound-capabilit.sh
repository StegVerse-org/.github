python org-runtime/runtime_boundary.py validate > boundary.json
python - <<'PY'
import json
x = json.load(open("boundary.json"))
assert x["valid"] is True, x["checks"]
assert x["checks"]["capability_addresses_resolve"] is True
assert x["checks"]["peer_capability_addresses_derive"] is True
print("CAPABILITY_ADDRESS_ENFORCED=PASS", len(x["checks"]), "checks")
PY
