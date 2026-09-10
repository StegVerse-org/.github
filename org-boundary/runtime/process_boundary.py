#!/usr/bin/env python3
import argparse, hashlib, json, subprocess, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
KINDS=["INGRESS_ACCEPTED","DISPATCHED","CONSUMED","RESULT_BOUND","EGRESS_EMITTED"]
def canon(v): return json.dumps(v,sort_keys=True,separators=(",",":")).encode()
def hid(prefix,v): return prefix+"-"+hashlib.sha256(canon(v)).hexdigest()[:24]
def load(path): return json.loads(Path(path).read_text())

def resolve_adapter(svc):
    adapter=svc.get("endpoint_adapter")
    if not adapter:
        raise SystemExit("endpoint-adapter-not-installed")
    candidate=Path(str(adapter))
    if not candidate.is_absolute():
        candidate=ROOT/candidate
    candidate=candidate.resolve()
    root=ROOT.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise SystemExit("endpoint-adapter-outside-organization-root")
    if not candidate.is_file():
        raise SystemExit("endpoint-adapter-not-found")
    return candidate

def endpoint_result(env,svc,envelope_path):
    role=svc.get("boundary_role")
    if role=="INTERNAL_ENDPOINT":
        adapter=resolve_adapter(svc)
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"endpoint-response.json"
            completed=subprocess.run(
                ["python3",str(adapter),"--envelope",str(Path(envelope_path).resolve()),"--out",str(out)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode!=0 or not out.is_file():
                raise SystemExit("endpoint-adapter-execution-failed")
            result=load(out)
            if not isinstance(result,dict):
                raise SystemExit("endpoint-adapter-result-invalid")
            return result
    if role=="BOUNDARY_LOCAL_DIAGNOSTIC":
        return {"echo":env["payload"]}
    raise SystemExit("endpoint-adapter-not-installed")
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--envelope",required=True); ap.add_argument("--registry",default="org-boundary/registry/services.json"); ap.add_argument("--out",required=True); a=ap.parse_args()
 env=load(a.envelope); reg=load(a.registry)
 req=["schema_version","packet_id","direction","origin","destination","carrier","intr_profile","transition","payload","evidence"]; miss=[k for k in req if k not in env]
 if miss: raise SystemExit("missing:"+",".join(miss))
 if env["destination"]["org"]!=reg["organization"]: raise SystemExit("wrong-destination-org")
 svc=next((s for s in reg["services"] if s["service_id"]==env["destination"]["service"]),None)
 if not svc: raise SystemExit("unknown-service")
 base={"packet_id":env["packet_id"],"service_id":svc["service_id"],"payload_hash":hashlib.sha256(canon(env["payload"])).hexdigest()}
 receipts=[]; prev=None
 for kind in KINDS:
  subject={**base,"kind":kind,"previous_receipt_id":prev}; rid=hid(kind.lower(),subject); receipts.append({"kind":kind,"receipt_id":rid,"subject":svc["service_id"],"evidence_hash":hashlib.sha256(canon(subject)).hexdigest(),"previous_receipt_id":prev}); prev=rid
 application_result=endpoint_result(env,svc,a.envelope)
 result={"schema_version":reg["organization"].lower().replace(" ","-")+".boundary-execution.v1","packet_id":env["packet_id"],"organization":reg["organization"],"service_id":svc["service_id"],"consumed":True,"application_result":application_result,"authority_effect":env["transition"]["authority_effect"],"receipts":receipts,"reconstruction":{"same_execution_required":True,"status":"RECONSTRUCTED","terminal_receipt_id":prev}}
 Path(a.out).parent.mkdir(parents=True,exist_ok=True); Path(a.out).write_text(json.dumps(result,indent=2,sort_keys=True)+"\n"); print(json.dumps({"status":"PASS","terminal_receipt_id":prev}))
if __name__=="__main__": main()
