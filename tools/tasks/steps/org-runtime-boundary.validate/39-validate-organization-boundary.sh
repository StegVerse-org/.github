python org-runtime/runtime_boundary.py validate | tee /tmp/org-boundary.json
python -c 'import json; x=json.load(open("/tmp/org-boundary.json")); assert x["valid"] is True; assert x["authority_effect"]=="NONE_VALIDATION_ONLY"'
