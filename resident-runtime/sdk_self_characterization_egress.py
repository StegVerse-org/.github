#!/usr/bin/env python3
"""Bind the frozen StegVerse SDK self-characterization request to StegVerse-org egress."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("org_kernel",ROOT/"org-kernel"/"kernel.py")
K=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(K)
GWSPEC=importlib.util.spec_from_file_location("federation_gateway_transport",ROOT/"resident-runtime"/"federation_gateway_transport.py")
GW=importlib.util.module_from_spec(GWSPEC); GWSPEC.loader.exec_module(GW)

EXPERIMENT_ID="STEGVERSE-002-SELF-CHARACTERIZATION-001"
OPERATION="REQUEST_SELF_CHARACTERIZATION"
OBJECTIVE="Determine what constitutes the entity identified as StegVerse-002 and produce a representation sufficient for another system to evaluate and reconstruct your conclusion."
SOURCE="StegVerse-SDK-Evaluator"
TARGET_ENTITY="StegVerse-002"
TARGET_ORG="StegVerse-002"
TARGET_SERVICE="stegverse-002.self-characterization"

def canon(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def digest(v): return hashlib.sha256(canon(v)).hexdigest()

def validate_request(req):
    expected={
      "schema_version":"stegverse.external_organization.interlock_request.v1",
      "request_class":"EXTERNAL_ORGANIZATION_INTERACTION",
      "operation":OPERATION,
      "transport":"InTr",
      "authority_transfer":False,
      "sdk_mints_intr_receipt":False,
      "sdk_claims_delivery":False,
      "authority_effect_resolution":"DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS",
    }
    for k,v in expected.items():
        if req.get(k)!=v: raise ValueError(f"{k} mismatch")
    if not str(req.get("authority_ref") or "").strip(): raise ValueError("authority_ref required")
    payload=req.get("payload") or {}; manifest=payload.get("manifest")
    if not isinstance(manifest,dict): raise ValueError("manifest required")
    if manifest.get("experiment_id")!=EXPERIMENT_ID or manifest.get("operation")!=OPERATION or manifest.get("objective")!=OBJECTIVE:
        raise ValueError("frozen experiment binding mismatch")
    if (manifest.get("source_organization") or {}).get("organization_id")!=SOURCE: raise ValueError("source mismatch")
    if (manifest.get("target") or {}).get("entity_id")!=TARGET_ENTITY: raise ValueError("target mismatch")
    policy=manifest.get("knowledge_policy") or {}
    for key in ("prescribe_self_ontology","prescribe_formalism","prescribe_transition_elements","prescribe_external_followup","prescribe_admissible_existence_connection"):
        if policy.get(key) is not False: raise ValueError("knowledge policy became prescriptive")
    body=dict(manifest); claimed=str(body.pop("manifest_sha256",""))
    if claimed!=digest(body): raise ValueError("manifest hash mismatch")
    bindings=req.get("bindings") or {}
    required={
      "experiment_id":EXPERIMENT_ID,
      "source_organization_id":SOURCE,
      "target_entity_id":TARGET_ENTITY,
      "manifest_id":manifest.get("manifest_id"),
      "manifest_sha256":manifest.get("manifest_sha256"),
    }
    for k,v in required.items():
        if bindings.get(k)!=v: raise ValueError(f"bindings.{k} mismatch")
    return manifest

def build_packet(req):
    manifest=validate_request(req)
    return K.build_packet(
      origin_org="StegVerse-org",
      origin_service="stegverse-org.stegverse-sdk",
      destination_org=TARGET_ORG,
      destination_service=TARGET_SERVICE,
      payload={"request":req},
      transition_reference="sv002.self-characterization.request.v0.2",
      authority_effect="NONE_REQUEST_ONLY",
      packet_id="sv002-self-char-"+manifest["manifest_sha256"][:24],
    )

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--request",type=Path,required=True); ap.add_argument("--packet-out",type=Path,required=True); ap.add_argument("--frame-out",type=Path); ap.add_argument("--submit",action="store_true")
    a=ap.parse_args(); req=json.loads(a.request.read_text()); packet=build_packet(req); frame=K.carrier_frame(packet)
    a.packet_out.parent.mkdir(parents=True,exist_ok=True); a.packet_out.write_text(json.dumps(packet,indent=2,sort_keys=True)+"\n")
    if a.frame_out:
        a.frame_out.parent.mkdir(parents=True,exist_ok=True); a.frame_out.write_text(json.dumps(frame,indent=2,sort_keys=True)+"\n")
    submit_result=GW.submit_frame(frame) if a.submit else None
    print(json.dumps({"status":"PASS","packet_id":packet["packet_id"],"destination":packet["destination"],"manifest_sha256":req["bindings"]["manifest_sha256"],"submitted":bool(a.submit),"gateway_state":submit_result.get("state") if isinstance(submit_result,dict) else None},sort_keys=True))
if __name__=="__main__": raise SystemExit(main())
