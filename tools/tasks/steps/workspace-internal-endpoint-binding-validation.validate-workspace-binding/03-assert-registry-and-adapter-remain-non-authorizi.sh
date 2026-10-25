python - <<'PY'
import json
from pathlib import Path

registry = json.loads(Path('org-boundary/registry/services.json').read_text())
service = next(s for s in registry['services'] if s['service_id'] == 'stegverse-org.workspace-resource-consumer')
assert service['boundary_role'] == 'INTERNAL_ENDPOINT'
assert service['endpoint_adapter'] == 'resident-runtime/workspace_resource_consumer_adapter.py'
assert service['repository'] == 'StegVerse-org/StegVerse-SDK'
text = Path(service['endpoint_adapter']).read_text()
assert 'authority_transfer' in text and 'False' in text
assert 'intr_receipt_minted_by_adapter' in text
print('WORKSPACE_INTERNAL_ENDPOINT_BINDING=PASS')
PY
