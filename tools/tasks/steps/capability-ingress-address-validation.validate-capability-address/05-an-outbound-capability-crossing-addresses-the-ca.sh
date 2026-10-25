python - <<'PY'
import importlib.util

spec = importlib.util.spec_from_file_location(
    "egress", "resident-runtime/organization_egress_boundary.py")
egress = importlib.util.module_from_spec(spec); spec.loader.exec_module(egress)

control = egress.resolve_destination("StegVerse-Labs")
assert control["destination_service"] == control["destination_org_control_service"]
assert control["destination_capability_profile_id"] is None

capability = egress.resolve_destination("StegVerse-Labs",
                                        capability="sdk-manifest-ingress")
assert capability["destination_service"] == "stegverse-labs.sdk-manifest-ingress"
assert capability["destination_service"] != capability["destination_org_control_service"]
# The derivation is the one this organization itself answers at.
assert egress.peer_capability_service(
    "StegVerse-org", "sdk-manifest-ingress") == "stegverse-org.sdk-manifest-ingress"
# And what it does not prove is recorded rather than implied.
assert capability["peer_serves_this_capability_is_proven_here"] is False
assert capability["destination_capability_declared_by_the_peer_directory"] is False

try:
    egress.resolve_destination("StegVerse-Labs", capability="not-declared-anywhere")
except egress.EgressRefused as refused:
    assert refused.failed_predicate == "CAPABILITY_IS_DECLARED_IN_THIS_ORGANIZATIONS_OVERLAY"
else:
    raise AssertionError("an undeclared capability was not refused")
print("PEER_CAPABILITY_ADDRESS=PASS", capability["destination_service"])
PY
