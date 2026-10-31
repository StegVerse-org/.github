set -euo pipefail
python3 resident-runtime/intr_path_transfer.py verify --out "$RUNNER_TEMP/results/real-state.json" > /dev/null
python3 - <<'PY'
import json, os
from pathlib import Path
state = json.loads((Path(os.environ["RUNNER_TEMP"]) / "results/real-state.json").read_text())
own = [p for p in state["paths"] if p["path_id"].startswith("StegVerse-org->")]
assert own, "no source paths examined"
assert all(p["halves"]["source"] in ("ALLOW", "FAIL_CLOSED") for p in own), own
print("INTR_PATH_REAL_STATE", json.dumps(state["counts"]))
PY
