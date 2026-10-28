python -m unittest tests.test_intr_protocol_conformance tests.test_intr_protocol_conformance_merge_transfer tests.test_intr_protocol_conformance_merge_transfer_gitstore -v
python org-runtime/intr_protocol.py mesh --manifest tests/fixtures/intr-protocol/destinations/manifest.json --merge-transfer tests/fixtures/intr-protocol/merge-transfer/manifest.json > mesh.json
python - <<'PY'
import json
r = json.load(open("mesh.json"))
# 16 organizations (federation.json); 3 do not install the receiving operation (class B).
assert r["counts"] == {"ALLOW": 13, "DENY": 0, "FAIL_CLOSED": 3}, r["counts"]
for row in r["results"]:
    print(" ", row["subject"]["organization"], row["disposition"], row.get("failure_code", ""), row.get("failed_predicate", ""))
print("INTR_PROTOCOL_V1_MESH", json.dumps(r["counts"], sort_keys=True), r["report_digest"])
# Separate dimension: a main merge is a VERIFIED transfer only with a sealed, linked ledger receipt.
print("INTR_PROTOCOL_V1_MERGE_TRANSFER", json.dumps(r["merge_transfer"]["counts"], sort_keys=True))
for row in r["merge_transfer"]["results"]:
    print(" ", row["subject"]["repository"], row["subject"]["merge_commit"][:8], row["disposition"], row.get("failure_code", ""))
PY
# StegVerse-Labs and GCAT-BCAT-Engine: pinned to merge_transfer_gitstore.py verify (mode dual).
python - <<'PY'
import importlib.util, json
spec = importlib.util.spec_from_file_location("intr", "org-runtime/intr_protocol.py")
intr = importlib.util.module_from_spec(spec); spec.loader.exec_module(intr)
d = intr.merge_transfer_dimension("tests/fixtures/intr-protocol/merge-transfer-gitstore/manifest.json")
assert d["counts"] == {"ALLOW": 0, "DENY": 0, "FAIL_CLOSED": 2}, d["counts"]
print("INTR_PROTOCOL_V1_MERGE_TRANSFER_GITSTORE", json.dumps(d["counts"], sort_keys=True))
for row in d["results"]:
    print(" ", row["subject"]["repository"], row["subject"]["merge_commit"][:8], row["disposition"], row["failure_code"])
PY
