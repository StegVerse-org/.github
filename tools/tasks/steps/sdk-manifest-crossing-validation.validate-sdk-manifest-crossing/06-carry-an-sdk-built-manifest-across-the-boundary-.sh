python - <<'PY'
import hashlib, importlib.util, json
from pathlib import Path

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

builder = load("build", "tests/fixtures/sdk_manifest_fixture_build.py")
bridge = load("crossing", "resident-runtime/sdk_manifest_crossing.py")

manifest = builder.rebuild()["governance-to-boundary-diagnostic"]
# An ingress manifest declares no chain position, so the crossing is
# given one. There is no default: a crossing with no standing fails
# closed at the boundary.
standing = json.loads(Path("tests/fixtures/crossing-standing-genesis.json").read_text())
registry = json.loads(Path("org-boundary/registry/services.json").read_text())
result = bridge.cross(manifest, registry=registry, standing=standing,
                      packet_id="ci-sdk-built-manifest-crossing")
assert result["crossing_completed"] is True, result
assert result["consumed"] is True
assert result["reconstruction"] == "RECONSTRUCTED"
assert result["receipts"] == ["INGRESS_ACCEPTED", "DISPATCHED", "CONSUMED",
                              "RESULT_BOUND", "EGRESS_EMITTED"]
assert result["authority_effect"] == "NONE"
# The governance processor binds the request the manifest carries,
# so the far side is bound to the manifest by that request's digest.
assert result["resolved_service_id"] == "stegverse-org.governance", result
far = result["egress"]["payload"]["execution_result"]["application_result"]
request = manifest["extensions"]["stegverse_governance_request"]
canon = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
assert far["governance_request_sha256"] == hashlib.sha256(canon).hexdigest(), \
    "a different governance request arrived"
# StegCore is a StegVerse-Labs repository: the request is bound for
# StegVerse-Labs to decide, never decided here.
assert far["decision_state"] == "REQUESTED_OF_DECIDING_ORGANIZATION", far
assert far["deciding_organization"] == "StegVerse-Labs", far
print("SDK_MANIFEST_CROSSES_ORGANIZATION_BOUNDARY=PASS")
print(result["terminal_receipt_id"])
PY
