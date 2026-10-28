python - <<'PY'
import hashlib, json
m = json.load(open("resident-runtime/resident-runtime-convergence-manifest.json"))
for role, entry in m["baseline"]["files"].items():
    data = open(entry["path"], "rb").read()
    state = "AT_PIN" if hashlib.sha256(data).hexdigest() == entry["sha256"] else "MOVED_SINCE_PIN"
    print(f"{role} {entry['path']} {state}")
PY
