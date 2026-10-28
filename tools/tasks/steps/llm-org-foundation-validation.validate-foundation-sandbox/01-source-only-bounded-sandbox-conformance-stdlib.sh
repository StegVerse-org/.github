python - <<'PY'
import runpy
tests = runpy.run_path("tests/test_llm_org_foundation_validation.py")
names = sorted(name for name in tests if name.startswith("test_") and callable(tests[name]))
assert len(names) >= 5
for name in names:
    tests[name]()
    print("PASS", name)
PY
