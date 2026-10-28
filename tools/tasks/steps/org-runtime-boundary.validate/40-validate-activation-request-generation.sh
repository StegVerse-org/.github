python org-runtime/runtime_boundary.py activation-request --runtime-id validation-resident | tee /tmp/activation.json
python -c 'import json; x=json.load(open("/tmp/activation.json")); assert x["state"]=="REQUESTED"; assert x["request_granted_authority"] is False; assert x["github_token_runtime_authority"]=="NONE"'
