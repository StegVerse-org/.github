set -euo pipefail
# run in each run group's environment (a pinned group gets only its pin's exports), one process per group
cat > "$RESULTS/module_level_tests.py" <<'PY'
import ast, os, runpy, sys
from pathlib import Path
sys.path.insert(0, os.getcwd())   # as `python -` did: the checkout first, then the group's exports
ran = failed = 0
mods = sorted({a.split(".")[0] + "." + a.split(".")[1] for a in sys.argv[1:]
               if a.startswith("tests.") and a.count(".") >= 1})
for mod in mods:
    path = Path(*mod.split(".")).with_suffix(".py")
    if not path.is_file():
        continue
    names = [n.name for n in ast.parse(path.read_text()).body
             if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    if not names:
        continue
    ns = runpy.run_path(str(path), run_name="__module_level_tests__")
    for name in names:
        ran += 1
        try:
            ns[name]()
            print(f"PASS {mod}::{name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {mod}::{name}: {exc!r}")
print(f"module-level test functions: ran={ran} failed={failed}")
raise SystemExit(1 if failed else 0)
PY
python - "$RESULTS/test-set-selection.json" "$RESULTS/module_level_tests.py" <<'PY'
import json, os, subprocess, sys
sel = json.load(open(sys.argv[1]))
groups = sel.get("run_groups") or [{"id": "all", "inputs": [], "env": {}, "tests": sel["run"]["tests"]}]
worst = 0
for g in groups:
    if not g["tests"]:
        continue
    env = dict(os.environ)
    if g["inputs"]:
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env.update(g["env"])
    print(f"### run group {g['id']} inputs={','.join(g['inputs']) or '-'}", flush=True)
    worst = max(worst, subprocess.run([sys.executable, sys.argv[2], *g["tests"]], env=env).returncode)
raise SystemExit(worst)
PY
