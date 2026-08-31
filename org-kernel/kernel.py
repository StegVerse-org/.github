#!/usr/bin/env python3
"""Universal StegVerse organization resident kernel.

Organization-neutral runtime behavior extracted from StegVerse-Labs/.github.
No GitHub, hosted scheduler, provider, or carrier grants authority.
"""
from __future__ import annotations
import base64, hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HB_ANCHOR_EPOCH=32
HB_ANCHOR_UNIX_NS=1_787_511_600_000_000_000
HB_PERIOD_NS=10_000_000
HB_HZ=100
CHANNEL_COUNT=16
SCHEMA="stegverse.org-resident-kernel/v1"
CARRIER_SCHEMA="stegverse.org-resident-kernel.carrier/v1"
PACKET_SCHEMA="stegverse.intr.org-boundary.v1"

def canon(v:Any)->bytes:
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()

def sha(v:Any)->str:
    raw=v if isinstance(v,(bytes,bytearray)) else canon(v)
    return "sha256:"+hashlib.sha256(bytes(raw)).hexdigest()

def hb_reference(now_ns:int|None=None)->dict[str,Any]:
    if now_ns is None:
        now_ns=int(datetime.now(timezone.utc).timestamp()*1_000_000_000)
    if now_ns<HB_ANCHOR_UNIX_NS:
        raise ValueError("sample_precedes_hb32_anchor")
    q,phase=divmod(now_ns-HB_ANCHOR_UNIX_NS,HB_PERIOD_NS)
    epoch=HB_ANCHOR_EPOCH+q
    return {"epoch":epoch,"generation":epoch,"heartbeat_id":f"HB:{epoch}","sampled_unix_ns":now_ns,
            "phase_offset_ns":phase,"frequency_hz":HB_HZ,"progression_dependency":"OSCILLATOR_ONLY",
            "authority_effect":"NONE"}

def derive_channel(payload_hash:str)->dict[str,Any]:
    if not isinstance(payload_hash,str) or not payload_hash.startswith("sha256:") or len(payload_hash)!=71:
        raise ValueError("payload_hash_invalid")
    slot=int(payload_hash[7:23],16)%CHANNEL_COUNT
    return {"channel_id":f"HB:H1:P{slot}","phase_slot":slot,"phase_slot_count":CHANNEL_COUNT,
            "derivation":"PAYLOAD_SHA256_FIRST64_MOD_16","authority_effect":"NONE_CARRIER_ONLY"}

def carrier_frame(packet:dict[str,Any], *, now_ns:int|None=None)->dict[str,Any]:
    raw=canon(packet); payload_hash=sha(packet.get("payload",{})); ref=hb_reference(now_ns); channel=derive_channel(payload_hash)
    body={"schema":CARRIER_SCHEMA,"packet_id":packet["packet_id"],"packet_sha256":sha(raw),
          "packet_base64":base64.b64encode(raw).decode("ascii"),"heartbeat_reference":ref,
          "channel":channel,"origin_org":packet["origin"]["org"],"destination_org":packet["destination"]["org"],
          "intr_profile":packet["intr_profile"],"authority_effect":"NONE_CARRIER_ONLY"}
    return {**body,"frame_sha256":sha(body)}

def recover_packet(frame:dict[str,Any])->dict[str,Any]:
    body=dict(frame); claimed=body.pop("frame_sha256",None)
    if claimed!=sha(body): raise ValueError("carrier_frame_hash_mismatch")
    raw=base64.b64decode(frame["packet_base64"].encode("ascii"),validate=True)
    if sha(raw)!=frame["packet_sha256"]: raise ValueError("packet_hash_mismatch")
    packet=json.loads(raw)
    if packet["packet_id"]!=frame["packet_id"]: raise ValueError("packet_id_mismatch")
    if packet["destination"]["org"]!=frame["destination_org"]: raise ValueError("destination_org_mismatch")
    return packet

def receipt(kind:str, packet_id:str, subject:str, previous:str|None, detail:dict[str,Any])->dict[str,Any]:
    body={"kind":kind,"packet_id":packet_id,"subject":subject,"previous_receipt_id":previous,"detail":detail}
    rid=kind.lower()+"-"+hashlib.sha256(canon(body)).hexdigest()[:24]
    return {**body,"receipt_id":rid,"evidence_hash":sha(body)}

def load_registry(root:Path)->dict[str,Any]:
    return json.loads((root/"org-boundary/registry/services.json").read_text())

def dispatch(root:Path, packet:dict[str,Any])->dict[str,Any]:
    registry=load_registry(root)
    if packet["destination"]["org"]!=registry["organization"]: raise ValueError("wrong_destination_org")
    service=next((s for s in registry["services"] if s["service_id"]==packet["destination"]["service"]),None)
    if service is None: raise ValueError("unknown_service")
    if service.get("boundary_role")!="BOUNDARY_LOCAL_DIAGNOSTIC":
        raise ValueError("endpoint_adapter_not_installed")
    prev=None; receipts=[]
    for kind in ("INGRESS_ACCEPTED","DISPATCHED","CONSUMED","RESULT_BOUND","EGRESS_EMITTED"):
        r=receipt(kind,packet["packet_id"],service["service_id"],prev,{"payload_hash":sha(packet["payload"])})
        receipts.append(r); prev=r["receipt_id"]
    return {"schema_version":SCHEMA,"organization":registry["organization"],"packet_id":packet["packet_id"],
            "service_id":service["service_id"],"consumed":True,"application_result":{"echo":packet["payload"]},
            "authority_effect":packet["transition"]["authority_effect"],"receipts":receipts,
            "reconstruction":{"same_execution_required":True,"status":"RECONSTRUCTED","terminal_receipt_id":prev}}

def persist_outbox(root:Path, frame:dict[str,Any])->Path:
    out=root/"resident-runtime/federation/outbox"; out.mkdir(parents=True,exist_ok=True)
    path=out/(hashlib.sha256(frame["packet_id"].encode()).hexdigest()+".json")
    if path.exists():
        if json.loads(path.read_text())!=frame: raise ValueError("write_once_collision")
        return path
    path.write_text(json.dumps(frame,indent=2,sort_keys=True)+"\n")
    return path

def ingest_frame(root:Path, frame:dict[str,Any])->dict[str,Any]:
    packet=recover_packet(frame)
    registry=load_registry(root)
    if frame["destination_org"]!=registry["organization"]:
        return {"status":"IGNORED_NOT_ADDRESSED","packet_id":frame["packet_id"]}
    result=dispatch(root,packet)
    return {"status":"CONSUMED","packet":packet,"execution_result":result}

__all__=["hb_reference","derive_channel","carrier_frame","recover_packet","dispatch","persist_outbox","ingest_frame"]


# --- Federation mesh v1.1 additions ---
FEDERATION_ROOT_ENV="STEGVERSE_ORG_FEDERATION_ROOT"

def federation_root(env:dict[str,str]|None=None)->Path:
    values=os.environ if env is None else env
    override=values.get(FEDERATION_ROOT_ENV)
    if override:
        return Path(override).expanduser().resolve()
    base=Path(values.get("XDG_STATE_HOME",str(Path.home()/".local"/"state")))
    return (base/"stegverse"/"org-federation").resolve()

def publish_frame(frame:dict[str,Any], *, root:Path|None=None)->Path:
    mesh=(root or federation_root()).resolve()
    frames=mesh/"frames.d"
    frames.mkdir(parents=True,exist_ok=True)
    frame_id=hashlib.sha256((frame["packet_id"]+"|"+frame["frame_sha256"]).encode()).hexdigest()
    path=frames/(frame_id+".json")
    if path.exists():
        existing=json.loads(path.read_text())
        if existing!=frame:
            raise ValueError("federation_frame_write_once_collision")
        return path
    path.write_text(json.dumps(frame,indent=2,sort_keys=True)+"\n")
    return path

def scan_addressed_frames(organization:str, *, root:Path|None=None, seen:set[str]|None=None)->list[dict[str,Any]]:
    mesh=(root or federation_root()).resolve()
    frames=mesh/"frames.d"
    if not frames.exists():
        return []
    consumed=seen or set()
    out=[]
    for path in sorted(frames.glob("*.json")):
        if path.name in consumed:
            continue
        frame=json.loads(path.read_text())
        if frame.get("destination_org")==organization:
            out.append({"path":str(path),"frame":frame})
    return out

def build_packet(*, origin_org:str, origin_service:str, destination_org:str, destination_service:str,
                 payload:dict[str,Any], transition_reference:str="federation.v1",
                 authority_effect:str="NONE", packet_id:str|None=None)->dict[str,Any]:
    pid=packet_id or "pkt-"+hashlib.sha256(canon({
        "origin_org":origin_org,"origin_service":origin_service,"destination_org":destination_org,
        "destination_service":destination_service,"payload":payload,"transition_reference":transition_reference
    })).hexdigest()[:24]
    return {
      "schema_version":PACKET_SCHEMA,
      "packet_id":pid,
      "direction":"INGRESS",
      "origin":{"org":origin_org,"service":origin_service},
      "destination":{"org":destination_org,"service":destination_service},
      "carrier":{"kind":"HB_DERIVED","reference":"org-federation"},
      "intr_profile":"stegverse.intr.org-boundary.v1",
      "transition":{"reference":transition_reference,"authority_effect":authority_effect,"conditions":[]},
      "payload":payload,
      "evidence":{"ingress_receipt":None,"dispatch_receipt":None,"consumption_receipt":None,"egress_receipt":None,"reconstruction_reference":None}
    }

def publish_packet(packet:dict[str,Any], *, root:Path|None=None, now_ns:int|None=None)->dict[str,Any]:
    frame=carrier_frame(packet,now_ns=now_ns)
    path=publish_frame(frame,root=root)
    return {"packet":packet,"frame":frame,"path":str(path)}

def consume_addressed_frames(repo_root:Path, *, mesh_root:Path|None=None, seen:set[str]|None=None)->list[dict[str,Any]]:
    registry=load_registry(repo_root)
    organization=registry["organization"]
    results=[]
    for item in scan_addressed_frames(organization,root=mesh_root,seen=seen):
        result=ingest_frame(repo_root,item["frame"])
        results.append({"path":item["path"],"result":result})
    return results
