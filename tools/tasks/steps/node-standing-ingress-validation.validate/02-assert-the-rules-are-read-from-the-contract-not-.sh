set -eu
python - <<'PY'
from pathlib import Path
source = Path('org-boundary/runtime/node_standing.py').read_text(encoding='utf-8')
# A second copy of the owner's field set here would violate
# local_second_predecessor_semantics_permitted: false. It is read off
# the contract, so the literal names must not appear as a local tuple.
assert 'predecessor_fields' in source
assert '"generation", "manifest_sha256", "result_sha256", "heartbeat_epoch"' not in source
assert 'CANONICAL_NODE_INGRESS_CONTRACT_001.json' in source
for marker in ('predecessor-key-absent', 'standing_agrees_with_carried_manifest',
               'attestation_owner_state', 'declared_predecessor_lineage_recomputed',
               'caller_editable_origin_established_identity'):
    assert marker in source, marker

kernel = Path('org-kernel/kernel.py').read_text(encoding='utf-8')
# Standing must resolve above the role branch, or only one dispatch
# arm is gated and the other is the bypass.
standing_at = kernel.index('standing_module=node_standing(root)')
role_at = kernel.index('role=service.get("boundary_role")')
assert standing_at < role_at, 'standing must resolve before the role branch'
# No default standing anywhere: a silent default is the defaulting the
# contract exists to prevent.
assert 'standing:dict[str,Any]' in kernel
assert 'standing=None' not in kernel and 'standing={}' not in kernel
# Every separately invocable ingress surface must be gated, not just
# the kernel. process_boundary.py is run directly as a subprocess by
# the SDK manifest crossing, so a kernel-only gate leaves the
# external lane open.
boundary = Path('org-boundary/runtime/process_boundary.py').read_text(encoding='utf-8')
assert 'node_standing.require(' in boundary, 'the crossing surface must resolve standing'
assert boundary.index('node_standing.require(') < boundary.index('selection.select_processing('), \
    'standing must resolve before processing is selected'

crossing = Path('resident-runtime/sdk_manifest_crossing.py').read_text(encoding='utf-8')
assert 'CROSSING_REQUIRES_DECLARED_STANDING' in crossing
assert '"standing": standing' in crossing, 'the envelope must carry the declaration'
print('NODE_STANDING_CONTRACT_IS_THE_AUTHORITY=PASS')
print('EVERY_INGRESS_SURFACE_GATED=PASS')
PY
