#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1]; ACT=ROOT/"org-runtime/activation.json"; TR=ROOT/"org-runtime/interlock-intr.json"; ORG="StegVerse-org"
def load(path:Path)->dict[str,Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict): raise SystemExit(f"object required: {path}")
    return value
def canonical(value:Any)->str: return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()
# The canonical connector registry declares a capability; this boundary declares
# where the organization receives it. A registered capability with no binding
# here resolves to nothing, which is the
# CANONICAL_ORGANIZATION_INGRESS_ENDPOINT_NOT_RESOLVED the SDK fails closed on.
# The binding is non-authorizing by construction: it says where a submission is
# received, never that it is admitted, routed or executed.
CAPABILITY_BINDING_KEY=("profile_id","profile_name","operation")
NON_AUTHORIZING_BINDING_FLAGS=("grants_routing_authority","grants_admission_authority","grants_execution_authority","environment_selected_ingress")
def capability_bindings(t:dict[str,Any])->list[dict[str,Any]]:
    bindings=(t.get("ingress") or {}).get("capability_endpoint_bindings")
    return [b for b in bindings if isinstance(b,dict)] if isinstance(bindings,list) else []
def capability_bindings_resolve(t:dict[str,Any])->bool:
    """One binding per capability, owned here, and granting nothing."""
    bindings=capability_bindings(t)
    if not bindings: return False
    keys=[tuple(str(b.get(k) or "") for k in CAPABILITY_BINDING_KEY) for b in bindings]
    if len(set(keys))!=len(keys) or any("" in key for key in keys): return False
    owner=f"{ORG}/.github"
    for b in bindings:
        receiving=b.get("receiving_operation")
        if not isinstance(receiving,dict) or receiving.get("owner_repository")!=owner: return False
        if not str(receiving.get("operation_id") or "").strip(): return False
        # No host, no environment URL. A located receiving operation would put
        # the host dependency back that the deployment declaration removes.
        if receiving.get("host_required") is not False or receiving.get("environment_url_required") is not False: return False
        if receiving.get("credential_authority")!="TV/TVC" or receiving.get("github_token_runtime_authority")!="NONE": return False
        if b.get("binding_role")!="ORGANIZATION_RECEIVING_OPERATION_RESOLUTION" or b.get("authority_effect")!="NONE_BINDING_ONLY": return False
        if any(b.get(flag) is not False for flag in NON_AUTHORIZING_BINDING_FLAGS): return False
    return True
def sdk_manifest_ingress_bound(t:dict[str,Any])->bool:
    """The capability the SDK's manifest handoff resolves on is one of them."""
    return any((b.get("profile_id"),b.get("profile_name"),b.get("operation"))==("sdk-manifest-ingress","SDK:ManifestIngress","SUBMIT_MANIFEST") for b in capability_bindings(t))
def validate()->dict[str,Any]:
    a,t=load(ACT),load(TR); h=t["heartbeat_derived_carrier"]; checks={"activation_owner":a.get("organization")==ORG and a.get("owner_repository")==f"{ORG}/.github","activation_local":a.get("activation_source_scope")=="ORG_DOT_GITHUB_ONLY","runtime_sovereign":a.get("runtime_execution_surface")=="SOVEREIGN_RESIDENT_PROCESS","transport_owner":t.get("organization")==ORG and t.get("owner_repository")==f"{ORG}/.github","all_io_here":t.get("communication_policy")=="ALL_ORGANIZATION_INGRESS_EGRESS_GENERATED_AT_ORG_DOT_GITHUB_BOUNDARY","tvtvc":a.get("credential_authority")=="TV/TVC" and t.get("credential_authority")=="TV/TVC","github_none":a.get("github_token_runtime_authority")=="NONE" and t.get("github_token_runtime_authority")=="NONE","effects_transition_derived":a.get("authority_effect_resolution")=="DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS" and t.get("authority_effect_resolution")=="DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS","hb_non_authorizing":all(h.get(k) is False for k in ("carrier_grants_admission_authority","carrier_grants_execution_authority","carrier_grants_credential_authority","carrier_grants_routing_authority","carrier_grants_transition_authority","carrier_grants_receiving_authority")),"capability_bindings_resolve":capability_bindings_resolve(t),"sdk_manifest_ingress_bound":sdk_manifest_ingress_bound(t)}; return {"schema":"stegverse.organization-boundary-validation/v1","organization":ORG,"checks":checks,"valid":all(checks.values()),"authority_effect":"NONE_VALIDATION_ONLY"}
def activation_request(runtime_id:str)->dict[str,Any]:
    body={"schema":"stegverse.organization-resident-runtime-activation-request/v1","organization":ORG,"runtime_id":runtime_id,"owner_repository":f"{ORG}/.github","state":"REQUESTED","credential_authority":"TV/TVC","request_granted_authority":False,"github_token_runtime_authority":"NONE","authority_transfer_assumed":False,"authority_effect_resolution":"DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS"}; return {**body,"request_sha256":canonical(body)}
def envelope(direction:str,peer_org:str,interlock_id:str,payload_sha256:str,transition_elements_ref:str,authority_ref:str|None)->dict[str,Any]:
    if direction not in {"INGRESS","EGRESS"}: raise SystemExit("direction")
    if len(payload_sha256)!=64: raise SystemExit("payload_sha256 must be 64 hex chars")
    body={"schema":"stegverse.organization-intr-envelope/v1","organization":ORG,"boundary_repository":f"{ORG}/.github","direction":direction,"peer_organization":peer_org,"interlock_id":interlock_id,"protocol":"InTr","payload_sha256":payload_sha256.lower(),"transition_elements_ref":transition_elements_ref,"authority_ref":authority_ref,"credential_authority":"TV/TVC","authority_transfer_assumed":False,"authority_effect_resolution":"DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS","hb_carrier":{"frequency_hz":100,"period_ms":10,"progression_dependency":"OSCILLATOR_ONLY","authority_effect":"NONE_CARRIER_ONLY"},"github_token_runtime_authority":"NONE"}; return {**body,"envelope_sha256":canonical(body)}
def main()->int:
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="cmd",required=True); sub.add_parser("validate"); a=sub.add_parser("activation-request"); a.add_argument("--runtime-id",required=True)
    for name in ("ingress","egress"):
      q=sub.add_parser(name); q.add_argument("--peer-org",required=True); q.add_argument("--interlock-id",required=True); q.add_argument("--payload-sha256",required=True); q.add_argument("--transition-elements-ref",required=True); q.add_argument("--authority-ref")
    ns=p.parse_args(); out=validate() if ns.cmd=="validate" else activation_request(ns.runtime_id) if ns.cmd=="activation-request" else envelope(ns.cmd.upper(),ns.peer_org,ns.interlock_id,ns.payload_sha256,ns.transition_elements_ref,ns.authority_ref); print(json.dumps(out,sort_keys=True)); return 0 if out.get("valid",True) else 1
if __name__=="__main__": raise SystemExit(main())
