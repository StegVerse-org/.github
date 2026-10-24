python org-runtime/runtime_boundary.py validate > boundary.json
python - <<'PY'
import json
report = json.load(open("boundary.json"))
assert report["valid"] is True, report["checks"]
assert report["checks"]["capability_addresses_resolve"] is True
assert report["checks"]["peer_capability_addresses_derive"] is True
print("INTR_DESTINATION_ADDRESS_ENFORCED=PASS", len(report["checks"]), "checks")
PY
