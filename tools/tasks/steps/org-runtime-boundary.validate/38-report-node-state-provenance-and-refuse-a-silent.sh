python - <<'PY'
import importlib.util, json
spec = importlib.util.spec_from_file_location("kernel", "org-kernel/kernel.py")
kernel = importlib.util.module_from_spec(spec); spec.loader.exec_module(kernel)
supplied = kernel.node_state_provenance("/tmp/ci-stegos-mesh")
assert supplied["mesh_provenance"] == "SUPPLIED"
assert supplied["mesh_portable"] is True
assert supplied["authority_effect"] == "NONE_REPORT_ONLY"
try:
    kernel.node_state_provenance()
    raise AssertionError("host-derived mesh unexpectedly admitted")
except ValueError as exc:
    assert "mesh_location_required_from_materializer" in str(exc)
print(json.dumps(supplied, sort_keys=True))
print("STEGOS_NODE_STATE_PROVENANCE_REPORTED=PASS")
PY
