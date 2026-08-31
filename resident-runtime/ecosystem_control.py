#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, json, os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("org_kernel",ROOT/"org-kernel"/"kernel.py")
K=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(K)
GWSPEC=importlib.util.spec_from_file_location("federation_gateway_transport",ROOT/"resident-runtime"/"federation_gateway_transport.py")
GW=importlib.util.module_from_spec(GWSPEC); GWSPEC.loader.exec_module(GW)

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    for name,cls in (("send-monitor","ecosystem.monitor.request"),("send-work","ecosystem.work.request"),("send-message","ecosystem.communication")):
        p=sub.add_parser(name)
        p.add_argument("--subject",required=True)
        p.add_argument("--body-json",required=True)
        p.add_argument("--requested-action")
        p.add_argument("--communication-id")
        p.set_defaults(message_class=cls)
    p=sub.add_parser("collect")
    p.add_argument("--communication-id",required=True)
    sub.add_parser("status")
    args=ap.parse_args()
    reg=K.load_registry(ROOT)
    org=reg["organization"]
    if args.cmd=="status":
        print(json.dumps(K.resident_status(ROOT),indent=2,sort_keys=True))
        return
    if args.cmd=="collect":
        if os.getenv("STEGVERSE_ORG_FEDERATION_GATEWAY_URL","").strip():
            result=GW.collect_local_responses(ROOT,args.communication_id)
        else:
            result=K.collect_ecosystem_responses(org,args.communication_id)
        print(json.dumps(result,indent=2,sort_keys=True))
        return
    body=json.loads(args.body_json)
    if os.getenv("STEGVERSE_ORG_FEDERATION_GATEWAY_URL","").strip():
        out=GW.publish_ecosystem_via_gateway(
            repo_root=ROOT,
            message_class=args.message_class,
            subject=args.subject,
            body=body,
            requested_action=args.requested_action,
            communication_id=args.communication_id
        )
    else:
        out=K.publish_ecosystem_from_directory(
            ROOT,
            message_class=args.message_class,
            subject=args.subject,
            body=body,
            requested_action=args.requested_action,
            communication_id=args.communication_id
        )
    print(json.dumps({
      "status":"PUBLISHED",
      "organization":org,
      "communication_id":out["communication_id"],
      "published_count":out["published_count"]
    },indent=2,sort_keys=True))

if __name__=="__main__":
    main()
