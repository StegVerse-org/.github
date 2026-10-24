python - <<'PY'
import hashlib, hmac, importlib.util, json, os, shutil, tempfile
from pathlib import Path

os.environ["STEGVERSE_ORG_FEDERATION_ROOT"] = os.environ["RUNNER_TEMP"] + "/attest-mesh"
os.environ["STEGVERSE_NODE_STATE_ROOT"] = os.environ["RUNNER_TEMP"] + "/attest-node"
ROOT = Path.cwd()

def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, relative)
    loaded = importlib.util.module_from_spec(spec); spec.loader.exec_module(loaded)
    return loaded

egress = module("egress", "resident-runtime/organization_egress_boundary.py")
disorder = module("disorder", "resident-runtime/receipt_disorder_measurement.py")
attestation = module("attestation", "org-boundary/runtime/origin_attestation.py")
kernel = egress.kernel
PEER = "StegVerse-Labs"
GENESIS = {"mode": "ESTABLISH_GENESIS", "node_ref": "ci-attestation",
           "predecessor": None}
mesh = Path(os.environ["STEGVERSE_ORG_FEDERATION_ROOT"])

# The credential authority's side of the boundary. TV/TVC's own
# functions are exercised by tests.test_origin_attestation_tvc_
# conformance, which needs a TVC checkout this CI cannot make; this
# stands in for the authority's receipt contract, not its algorithm.
KEY = b"ci-stand-in-key"
def _hmac(payload):
    d = hashlib.sha256(payload).hexdigest()
    return d, hmac.new(KEY, d.encode("ascii"), hashlib.sha256).hexdigest()
def sign(*, payload):
    d, v = _hmac(payload)
    return {"algo": "hmac-sha256", "value": v, "sha256": d}
def verify(*, payload, signature_bytes):
    carried = json.loads(signature_bytes.decode("utf-8"))
    d, v = _hmac(payload)
    if carried.get("sha256") != d:
        raise ValueError("TV signature export digest mismatch")
    return {"credential_authority": "TV/TVC",
            "operation": "TV_EXPORT_HMAC_VERIFY",
            "export_sha256": d, "signature_sha256": "artifact",
            "signature_valid": carried.get("value") == v}
AUTHORITY = {"sign": sign, "verify": verify}

peer = Path(tempfile.mkdtemp())
peer_state = Path(tempfile.mkdtemp())  # supplied node state, never a checkout
(peer / "org-boundary/registry").mkdir(parents=True)
(peer / "org-boundary/registry/services.json").write_text(json.dumps({
    "schema_version": "stegverse.org-boundary-registry.v1", "organization": PEER,
    "boundary_rule": "ALL_ORGANIZATION_INGRESS_EGRESS_GENERATED_AT_ORG_DOT_GITHUB_BOUNDARY",
    "services": [{"service_id": "stegverse-labs.org-control",
                  "repository": PEER + "/.github",
                  "boundary_role": "BOUNDARY_LOCAL_CONTROL"}]}))
(peer / "org-boundary/runtime").mkdir(parents=True)
for name in ("process_boundary.py", "manifest_selection.py", "node_standing.py"):
    shutil.copy2(ROOT / "org-boundary/runtime" / name,
                 peer / "org-boundary/runtime" / name)
(peer / "docs").mkdir(parents=True, exist_ok=True)
shutil.copy2(ROOT / "docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json",
             peer / "docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json")

emitted = egress.emit(PEER, {"message_class": "ecosystem.communication",
                             "communication_id": "ci-attestation", "body": {}},
                      standing=GENESIS, credential_authority=AUTHORITY,
                      mesh_root=mesh, hb_epoch=32)
assert emitted["disposition"] == "ALLOW", emitted.get("detail")
assert emitted["origin_attestation_state"] == "PROVEN", emitted
assert emitted["origin_is_attested_by_the_credential_authority"] is True

record = emitted["emission_record"]
assert record["attested_statement"]["packet_id"] == emitted["packet_id"]
assert record["attested_statement"]["origin_organization"] == "StegVerse-org"
# What attestation does not establish travels with every record.
assert record["proves_the_authority_signed_this_statement"] is True
assert record["proves_the_authority_authenticated_the_asker"] is False
assert record["initiator_identification_also_requires_the_bilateral_match"] is True

# The peer consumes through its own kernel into its own ledgers.

_po_spec = importlib.util.spec_from_file_location("peer_organization", "tests/peer_organization.py")

_po = importlib.util.module_from_spec(_po_spec); _po_spec.loader.exec_module(_po)

_peer_registry = json.loads((peer / "org-boundary/registry/services.json").read_text())

peer_node = _po.materialize(None, _peer_registry["organization"], _peer_registry["services"])

peer_node.consume(mesh_root=mesh, node_state_root=peer_state)
closure = egress.close(PEER, emitted["packet_id"], "ci-attestation",
                       mesh_root=mesh, hb_epoch=32)
assert closure["closed"] is True, closure.get("closure_findings")
assert closure["closure_record"]["origin_attestation_state"] == "PROVEN"
assert closure["closure_record"][
    "attestation_read_from_this_organizations_own_emission_record"] is True

# The dimension that was the entire disorder score.
out = disorder.measure()
row = out["classes"]["unresolved_actor_identity"]
assert row["observed"] is True
assert row["severity"] == 0.0, row
observed = sum(1 for c in out["classes"].values() if c["observed"])
assert observed == 10, observed
above = {k: v["severity"] for k, v in out["classes"].items() if v.get("severity")}
assert not above, above
print("ATTESTED_CROSSING=PASS", observed, "of 10 observed |",
      "unresolved_actor_identity", row["severity"], "| no class above zero")
PY
