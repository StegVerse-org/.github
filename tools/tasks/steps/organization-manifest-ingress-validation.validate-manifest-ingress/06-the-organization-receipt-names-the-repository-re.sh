python - <<'PY'
import json, os
from pathlib import Path

def receipts(variable, schema):
    return [json.loads(p.read_text()) for p in Path(os.environ[variable]).rglob("*.json")
            if json.loads(p.read_text()).get("schema") == schema]

repository, = receipts("STEGVERSE_REPO_LEDGER_ROOT",
                       "stegverse.repo-transition-receipt/v1")
organization, = receipts("STEGVERSE_ORG_LEDGER_ROOT",
                         "stegverse.organization-transition-receipt/v1")
# The three fields that read null while one writer stood in for both levels.
assert organization["source_receipt_schema"] == "stegverse.repo-transition-receipt/v1"
assert organization["source_repository"] == "StegVerse-org/.github"
assert organization["repo_receipt_sha256"] == repository["receipt_sha256"]
assert organization["repo_transition_id"] == repository["transition_id"]
assert organization["org_transition_class"] == "REPO_STATE_PROPAGATION"
assert repository["transition_class"] == "ORGANIZATION_SDK_MANIFEST_INGRESS"
print("ORGANIZATION_CONSUMES_A_REPOSITORY_RECEIPT=PASS", repository["transition_id"])
PY
