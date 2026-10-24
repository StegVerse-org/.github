set -euo pipefail
python - "$RESULTS/test-set-args.txt" <<'PY'
import ast, runpy, sys
from pathlib import Path
ran = failed = 0
mods = sorted({a.split(".")[0] + "." + a.split(".")[1] for a in Path(sys.argv[1]).read_text().split()
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
