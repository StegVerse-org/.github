python - <<'PY'
import json
from pathlib import Path
from stegverse.connector_capability_overlay import resolve_organization_ingress
from stegverse.manifest_builder import build_manifest
from stegverse.manifest_state_transition_runtime import execute_manifest

boundary = json.loads(Path('org-runtime/interlock-intr.json').read_text())
resolution = resolve_organization_ingress(
    boundary, profile_id='sdk-manifest-ingress',
    profile_name='SDK:ManifestIngress', operation='SUBMIT_MANIFEST')
assert resolution['owner_repository'] == 'StegVerse-org/.github'
assert resolution['resolution_source'] == 'ORG_DOT_GITHUB_INTERLOCK_INTR_BOUNDARY'
assert resolution['authority_effect'] == 'NONE_BINDING_ONLY'
assert resolution['environment_inputs'] == []

manifest = build_manifest(
    data={'binding': 'ci'}, source_framework='organization-boundary-ci',
    source_output_id='organization-ingress-capability-binding-ci',
    processor_request={'candidate': {'action': 'inspect'}, 'judgment': {},
                       'signal': {}, 'execution': {}, 'capability': {},
                       'continuity': {}, 'approval': {},
                       'permission_present': False},
    created_at='2026-10-03T00:00:00Z')

unresolved = execute_manifest(manifest)
assert unresolved['failure_code'] == 'CANONICAL_ORGANIZATION_INGRESS_ENDPOINT_NOT_RESOLVED'

resolved = execute_manifest(manifest, boundary)
assert resolved['disposition'] == 'ALLOW'
assert resolved['state'] == 'MANIFESTED_FOR_INTERLOCK_INTR_HANDOFF'
assert resolved['destination_resolution_source'] == 'CANONICAL_CONNECTOR_CAPABILITY_OVERLAY'
# A named destination is not a reached one.
for unobserved in ('intr_admission_observed', 'far_side_transition_observed',
                   'organization_receipt_observed', 'consequence_committed',
                   'receiver_contacted'):
    assert resolved[unobserved] is False, unobserved
print('ORGANIZATION_INGRESS_CAPABILITY_BINDING=PASS')
PY
