#!/usr/bin/env python3
from __future__ import annotations
import importlib.util, json, os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("org_kernel",ROOT/"org-kernel"/"kernel.py")
K=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(K)
GWSPEC=importlib.util.spec_from_file_location("federation_gateway_transport",ROOT/"resident-runtime"/"federation_gateway_transport.py")
GW=importlib.util.module_from_spec(GWSPEC); GWSPEC.loader.exec_module(GW)

def main():
    if os.getenv("STEGVERSE_ORG_FEDERATION_GATEWAY_URL","").strip():
        receipt=GW.resident_gateway_cycle(ROOT)
        receipt["heartbeat_reference"]=K.hb_reference()
        receipt["transport"]="SHARED_SERVICE_GATEWAY"
    else:
        results=K.consume_and_respond(ROOT)
        consumed=sum(1 for x in results if (x.get("result") or {}).get("status")=="CONSUMED")
        responses=sum(1 for x in results if x.get("response_publication"))
        receipt={
          "schema_version":"stegverse.org-federation-cycle.v1",
          "organization":K.load_registry(ROOT)["organization"],
          "heartbeat_reference":K.hb_reference(),
          "frames_seen":len(results),
          "frames_consumed":consumed,
          "responses_emitted":responses,
          "authority_effect":"NONE_CARRIER_ONLY",
          "transport":"LOCAL_SPOOL_FALLBACK"
        }
    out=ROOT/"resident-runtime"/"federation"/"latest-cycle.json"
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
    print(json.dumps(receipt,sort_keys=True))

if __name__=="__main__":
    main()
