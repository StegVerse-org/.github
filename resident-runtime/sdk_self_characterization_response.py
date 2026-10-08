#!/usr/bin/env python3
"""Persist the exact StegVerse-002 self-characterization response for SDK consumption."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXPERIMENT_ID="STEGVERSE-002-SELF-CHARACTERIZATION-001"
# The response record is this node's own state. It was written under the
# repository checkout with a bare write_text; it is now written once, atomically,
# at the node-state location the materializer supplied.
_nspec=importlib.util.spec_from_file_location("node_store",ROOT/"org-kernel/node_store.py")
node_store=importlib.util.module_from_spec(_nspec); _nspec.loader.exec_module(node_store)
RESPONSE_PREFIX="self-characterization/responses/"

def canon(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--envelope",type=Path,required=True); ap.add_argument("--out",type=Path,required=True); ap.add_argument("--node-state-root",type=Path,default=None); a=ap.parse_args()
    packet=json.loads(a.envelope.read_text())
    if (packet.get("destination") or {}).get("org")!="StegVerse-org" or (packet.get("destination") or {}).get("service")!="stegverse-org.stegverse-sdk":
        raise SystemExit("wrong-sdk-response-destination")
    if (packet.get("origin") or {}).get("org")!="StegVerse-002" or (packet.get("origin") or {}).get("service")!="stegverse-002.self-characterization":
        raise SystemExit("wrong-sdk-response-origin")
    payload=packet.get("payload") or {}
    if payload.get("schema")!="stegverse.org-endpoint-response/v1" or not payload.get("response_to_packet_id"):
        raise SystemExit("response-schema-mismatch")
    manifest_sha=str(payload.get("request_manifest_sha256") or "")
    if len(manifest_sha)!=64 or any(c not in "0123456789abcdef" for c in manifest_sha):
        raise SystemExit("manifest-binding-invalid")
    execution=payload.get("execution_result")
    if not isinstance(execution,dict) or execution.get("service_id")!="stegverse-002.self-characterization":
        raise SystemExit("execution-result-binding-invalid")
    record={
      "schema":"stegverse.sdk-self-characterization-response/v1",
      "experiment_id":EXPERIMENT_ID,
      "response_packet_id":packet.get("packet_id"),
      "response_to_packet_id":payload.get("response_to_packet_id"),
      "manifest_sha256":manifest_sha,
      "execution_result":execution,
      "authority_transfer":False,
    }
    record["record_sha256"]=hashlib.sha256(canon(record)).hexdigest()
    # Validated first, so a packet that is not this response is refused by name
    # whether or not node state was supplied.
    if a.node_state_root is None:
        raise SystemExit("node_state_location_required_from_materializer")
    store=node_store.PosixStateStore(a.node_state_root)
    key=RESPONSE_PREFIX+manifest_sha+".json"
    try:
        store.put_once(key,record)
    except node_store.WriteOnceCollision:
        raise SystemExit("sdk-response-write-once-collision")
    dest=store.locator(key)
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps({"state":"RESPONSE_PERSISTED","response_ref":str(dest),"record_sha256":record["record_sha256"]},indent=2,sort_keys=True)+"\n")
    print(json.dumps({"state":"RESPONSE_PERSISTED","response_ref":str(dest)},sort_keys=True))
    return 0
if __name__=="__main__": raise SystemExit(main())
