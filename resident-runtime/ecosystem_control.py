#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("org_kernel",ROOT/"org-kernel"/"kernel.py")
K=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(K)

def main():
    ap=argparse.ArgumentParser()
    # The mesh this node was materialized with. Sending and collecting use the
    # declared carrier over it; the kernel refuses when it is not supplied.
    ap.add_argument("--mesh-root",type=Path,default=None)
    sub=ap.add_subparsers(dest="cmd",required=True)
    for name,cls in (("send-monitor","ecosystem.monitor.request"),("send-work","ecosystem.work.request"),("send-message","ecosystem.communication")):
        p=sub.add_parser(name)
        p.add_argument("--subject",required=True)
        p.add_argument("--body-json",required=True)
        p.add_argument("--requested-action")
        p.add_argument("--communication-id")
        # The node standing every packet carries. Ingress refuses a packet
        # without one, so it is required here rather than defaulted.
        p.add_argument("--standing",type=Path,required=True)
        p.set_defaults(message_class=cls)
    p=sub.add_parser("collect")
    p.add_argument("--communication-id",required=True)
    p=sub.add_parser("status")
    # As supplied by the carrier; checked by the shared rule. Absent, the status
    # carries heartbeat_reference null and a six-field refusal. No clock is read.
    p.add_argument("--hb-epoch",type=str,default=None)
    args=ap.parse_args()
    reg=K.load_registry(ROOT)
    org=reg["organization"]
    if args.cmd=="status":
        epoch=None
        if args.hb_epoch is not None:
            ispec=importlib.util.spec_from_file_location("capability_ingress_status_epoch",ROOT/"org-boundary/runtime/capability_ingress.py")
            rule=importlib.util.module_from_spec(ispec); ispec.loader.exec_module(rule)
            failure=rule.supplied_epoch_failure(args.hb_epoch)
            if failure is not None:
                print(json.dumps({**K.resident_status_epoch_refusal(),"failure_code":failure[0],"detail":failure[1]},indent=2,sort_keys=True))
                raise SystemExit(1)
            epoch=int(args.hb_epoch)
        print(json.dumps(K.resident_status(ROOT,epoch=epoch),indent=2,sort_keys=True))
        return
    if args.cmd=="collect":
        result=K.collect_ecosystem_responses(org,args.communication_id,mesh_root=args.mesh_root)
        print(json.dumps(result,indent=2,sort_keys=True))
        return
    body=json.loads(args.body_json)
    directory=K.load_federation_directory(ROOT)
    out=K.publish_ecosystem_message(
        origin_org=org,
        origin_service=K.organization_slug(org)+".org-control",
        organizations=[row["organization"] for row in directory["organizations"]],
        standing=json.loads(args.standing.read_text(encoding="utf-8")),
        message_class=args.message_class,
        subject=args.subject,
        body=body,
        requested_action=args.requested_action,
        communication_id=args.communication_id,
        root=args.mesh_root
    )
    print(json.dumps({
      "status":"PUBLISHED",
      "organization":org,
      "communication_id":out["communication_id"],
      "published_count":out["published_count"]
    },indent=2,sort_keys=True))

if __name__=="__main__":
    main()
