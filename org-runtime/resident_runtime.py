#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, shutil, sys, time
from pathlib import Path
from typing import Any
ORG="StegVerse-org"; REPO=f"{ORG}/.github"; SOURCE_ROOT=Path(__file__).resolve().parents[1]; BOUNDARY=SOURCE_ROOT/"org-runtime/runtime_boundary.py"
def sha256_bytes(data:bytes)->str: return hashlib.sha256(data).hexdigest()
def canonical(value:Any)->str: return sha256_bytes(json.dumps(value,sort_keys=True,separators=(",",":")).encode())
def load(path:Path)->dict[str,Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict): raise RuntimeError(f"object required: {path}")
    return value
def root_for(raw:str|None)->Path:
    if raw: return Path(raw).expanduser().resolve()
    return (Path.home()/".stegverse/org-runtime"/ORG.lower().replace("/","-").replace(" ","-")).resolve()
def dirs(root:Path)->dict[str,Path]:
    d={"root":root,"state":root/"state","ingress":root/"spool/ingress","egress":root/"spool/egress","archive_ingress":root/"archive/ingress","archive_egress":root/"archive/egress","receipts":root/"receipts"}
    for p in d.values():
        if p!=root: p.mkdir(parents=True,exist_ok=True)
    root.mkdir(parents=True,exist_ok=True); return d
def boundary_envelope(direction:str,peer_org:str,interlock_id:str,payload_sha256:str,transition_elements_ref:str,authority_ref:str|None)->dict[str,Any]:
    body={"schema":"stegverse.organization-intr-envelope/v1","organization":ORG,"boundary_repository":REPO,"direction":direction,"peer_organization":peer_org,"interlock_id":interlock_id,"protocol":"InTr","payload_sha256":payload_sha256.lower(),"transition_elements_ref":transition_elements_ref,"authority_ref":authority_ref,"credential_authority":"TV/TVC","authority_transfer_assumed":False,"authority_effect_resolution":"DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS","hb_carrier":{"frequency_hz":100,"period_ms":10,"progression_dependency":"OSCILLATOR_ONLY","authority_effect":"NONE_CARRIER_ONLY"},"github_token_runtime_authority":"NONE"}
    return {**body,"envelope_sha256":canonical(body)}
def validate_envelope(value:dict[str,Any],direction:str)->None:
    expected={"schema":"stegverse.organization-intr-envelope/v1","organization":ORG,"boundary_repository":REPO,"direction":direction,"protocol":"InTr","credential_authority":"TV/TVC","github_token_runtime_authority":"NONE","authority_transfer_assumed":False,"authority_effect_resolution":"DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS"}
    for k,v in expected.items():
        if value.get(k)!=v: raise RuntimeError(f"envelope {k} mismatch")
    if not value.get("interlock_id") or not value.get("transition_elements_ref"): raise RuntimeError("Interlock and Transition Elements required")
    body={k:v for k,v in value.items() if k!="envelope_sha256"}
    if value.get("envelope_sha256")!=canonical(body): raise RuntimeError("envelope hash mismatch")
def activation_receipt(runtime_id:str,mode:str)->dict[str,Any]:
    body={"schema":"stegverse.organization-resident-runtime-activation-receipt/v1","organization":ORG,"owner_repository":REPO,"runtime_id":runtime_id,"mode":mode,"pid":os.getpid(),"python_executable":sys.executable,"resident_source_sha256":sha256_bytes(Path(__file__).read_bytes()),"boundary_source_sha256":sha256_bytes(BOUNDARY.read_bytes()),"credential_authority":"TV/TVC","github_token_runtime_authority":"NONE","github_actions_runtime_authority":"NONE","heartbeat_grants_execution_authority":False,"authority_transfer_assumed":False,"authority_effect_resolution":"DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS","state":"ACTIVE_RESIDENT_BOUNDARY" if mode=="SERVE" else "RESIDENT_BOUNDARY_CYCLE_OBSERVED","observed_at_unix_ns":time.time_ns()}
    return {**body,"receipt_sha256":canonical(body)}
def queue(root:Path,direction:str,peer_org:str,interlock_id:str,payload_sha256:str,transition_elements_ref:str,authority_ref:str|None)->dict[str,Any]:
    d=dirs(root); env=boundary_envelope(direction,peer_org,interlock_id,payload_sha256,transition_elements_ref,authority_ref); validate_envelope(env,direction); folder=d["ingress" if direction=="INGRESS" else "egress"]; path=folder/(env["envelope_sha256"]+".json"); path.write_text(json.dumps(env,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return {"queued":True,"path":str(path),"envelope":env}
def process(root:Path)->dict[str,Any]:
    d=dirs(root); counts={"INGRESS":0,"EGRESS":0}; receipts=[]
    for direction,key,archive_key in (("INGRESS","ingress","archive_ingress"),("EGRESS","egress","archive_egress")):
      for path in sorted(d[key].glob("*.json")):
        value=load(path); validate_envelope(value,direction)
        receipt={"schema":"stegverse.organization-intr-boundary-receipt/v1","organization":ORG,"direction":direction,"envelope_sha256":value["envelope_sha256"],"interlock_id":value["interlock_id"],"transition_elements_ref":value["transition_elements_ref"],"state":f"{direction}_OBSERVED_PENDING_TRANSITION_ELEMENT_EVALUATION","admission_decided":False,"authority_transfer_observed":False,"authority_effect_resolution":"DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS","credential_authority":"TV/TVC","github_token_runtime_authority":"NONE","observed_at_unix_ns":time.time_ns()}
        receipt["receipt_sha256"]=canonical(receipt); (d["receipts"]/(receipt["receipt_sha256"]+".json")).write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n",encoding="utf-8"); shutil.move(str(path),str(d[archive_key]/path.name)); counts[direction]+=1; receipts.append(receipt)
    return {"schema":"stegverse.organization-resident-boundary-cycle/v1","organization":ORG,"counts":counts,"receipts":receipts,"authority_effect":"NONE_CYCLE_ONLY"}
def self_test(root:Path)->dict[str,Any]:
    d=dirs(root); act=activation_receipt("self-test","ONCE"); (d["state"]/"activation.latest.json").write_text(json.dumps(act,indent=2,sort_keys=True)+"\n")
    queue(root,"INGRESS","peer-a","intr-self-test-in","0"*64,"transition-elements:self-test",None); queue(root,"EGRESS","peer-b","intr-self-test-out","f"*64,"transition-elements:self-test",None); cycle=process(root)
    valid=cycle["counts"]=={"INGRESS":1,"EGRESS":1} and all(r["admission_decided"] is False for r in cycle["receipts"])
    return {"schema":"stegverse.organization-resident-boundary-self-test/v1","organization":ORG,"valid":valid,"activation_state":act["state"],"cycle":cycle}
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--root"); sub=p.add_subparsers(dest="cmd",required=True); a=sub.add_parser("activate-once"); a.add_argument("--runtime-id",required=True); s=sub.add_parser("serve"); s.add_argument("--runtime-id",required=True); s.add_argument("--interval",type=float,default=1.0)
    for name in ("queue-ingress","queue-egress"):
      q=sub.add_parser(name); q.add_argument("--peer-org",required=True); q.add_argument("--interlock-id",required=True); q.add_argument("--payload-sha256",required=True); q.add_argument("--transition-elements-ref",required=True); q.add_argument("--authority-ref")
    sub.add_parser("cycle"); sub.add_parser("self-test"); ns=p.parse_args(); root=root_for(ns.root); d=dirs(root)
    if ns.cmd=="activate-once": out=activation_receipt(ns.runtime_id,"ONCE"); (d["state"]/"activation.latest.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    elif ns.cmd=="serve":
      out=activation_receipt(ns.runtime_id,"SERVE"); (d["state"]/"activation.latest.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n"); print(json.dumps(out,sort_keys=True),flush=True)
      while True: process(root); time.sleep(max(ns.interval,0.05))
    elif ns.cmd=="cycle": out=process(root)
    elif ns.cmd=="self-test": out=self_test(root)
    else:
      direction="INGRESS" if ns.cmd=="queue-ingress" else "EGRESS"; out=queue(root,direction,ns.peer_org,ns.interlock_id,ns.payload_sha256,ns.transition_elements_ref,ns.authority_ref)
    print(json.dumps(out,sort_keys=True)); return 0 if out.get("valid",True) else 1
if __name__=="__main__": raise SystemExit(main())
