#!/usr/bin/env python3
"""Universal StegVerse organization resident kernel.

Organization-neutral runtime behavior extracted from StegVerse-Labs/.github.
No GitHub, hosted scheduler, provider, or carrier grants authority.
"""
from __future__ import annotations
import base64, hashlib, importlib.util, json, os, subprocess, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# StegOS node state is addressed by key, not located by path. The seam lives
# beside this module so the kernel loads it without depending on a package
# layout a node may not have.
_store_spec=importlib.util.spec_from_file_location(
    "stegos_node_store", Path(__file__).resolve().parent/"node_store.py")
node_store_module=importlib.util.module_from_spec(_store_spec)
_store_spec.loader.exec_module(node_store_module)
PosixStateStore=node_store_module.PosixStateStore

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

def validate_hb_reference(ref:dict[str,Any])->dict[str,Any]:
    """A carrier frame's heartbeat reference is part of what the frame asserts.

    recover_packet verified the frame and packet digests but never the
    reference, so an incoherent or fabricated epoch rode through a validly
    signed frame unchallenged.
    """
    if not isinstance(ref,dict): raise ValueError("heartbeat_reference_invalid")
    epoch=ref.get("epoch")
    if not isinstance(epoch,int) or isinstance(epoch,bool) or epoch<HB_ANCHOR_EPOCH:
        raise ValueError("heartbeat_epoch_invalid")
    if ref.get("generation")!=epoch: raise ValueError("heartbeat_generation_mismatch")
    if ref.get("heartbeat_id")!=f"HB:{epoch}": raise ValueError("heartbeat_id_mismatch")
    if ref.get("frequency_hz")!=HB_HZ: raise ValueError("heartbeat_frequency_mismatch")
    if ref.get("progression_dependency")!="OSCILLATOR_ONLY":
        raise ValueError("heartbeat_progression_not_oscillator")
    return ref

def hb_reference(now_ns:int|None=None, *, epoch:int|None=None)->dict[str,Any]:
    """Build the heartbeat reference for a crossing.

    Progression is OSCILLATOR_ONLY: the epoch is a count of heartbeat periods,
    not a reading of a wall clock. Supply `epoch` from the carrier wherever the
    tick is available; the reference is then reproducible, so the same packet
    at the same epoch yields the same frame digest.

    Deriving the epoch from a host clock instead makes the reference depend on
    that host's clock discipline -- an NTP step moves or reverses it, and two
    nodes with skewed clocks assign different epochs to one event. A derived
    reference therefore says so and carries the sample it was derived from.
    """
    if epoch is not None:
        if now_ns is not None: raise ValueError("supply_epoch_or_sample_not_both")
        if not isinstance(epoch,int) or isinstance(epoch,bool) or epoch<HB_ANCHOR_EPOCH:
            raise ValueError("epoch_precedes_hb32_anchor")
        return validate_hb_reference({"epoch":epoch,"generation":epoch,"heartbeat_id":f"HB:{epoch}",
                "phase_offset_ns":0,"frequency_hz":HB_HZ,"progression_dependency":"OSCILLATOR_ONLY",
                "derived_from_clock":False,"authority_effect":"NONE"})
    if now_ns is None:
        now_ns=int(datetime.now(timezone.utc).timestamp()*1_000_000_000)
    if now_ns<HB_ANCHOR_UNIX_NS:
        raise ValueError("sample_precedes_hb32_anchor")
    q,phase=divmod(now_ns-HB_ANCHOR_UNIX_NS,HB_PERIOD_NS)
    epoch=HB_ANCHOR_EPOCH+q
    return validate_hb_reference({"epoch":epoch,"generation":epoch,"heartbeat_id":f"HB:{epoch}",
            "sampled_unix_ns":now_ns,"phase_offset_ns":phase,"frequency_hz":HB_HZ,
            "progression_dependency":"OSCILLATOR_ONLY","derived_from_clock":True,
            "authority_effect":"NONE"})

def derive_channel(payload_hash:str)->dict[str,Any]:
    if not isinstance(payload_hash,str) or not payload_hash.startswith("sha256:") or len(payload_hash)!=71:
        raise ValueError("payload_hash_invalid")
    slot=int(payload_hash[7:23],16)%CHANNEL_COUNT
    return {"channel_id":f"HB:H1:P{slot}","phase_slot":slot,"phase_slot_count":CHANNEL_COUNT,
            "derivation":"PAYLOAD_SHA256_FIRST64_MOD_16","authority_effect":"NONE_CARRIER_ONLY"}

def carrier_frame(packet:dict[str,Any], *, now_ns:int|None=None, epoch:int|None=None)->dict[str,Any]:
    raw=canon(packet); payload_hash=sha(packet.get("payload",{})); ref=hb_reference(now_ns,epoch=epoch); channel=derive_channel(payload_hash)
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
    validate_hb_reference(frame.get("heartbeat_reference"))
    packet=json.loads(raw)
    if packet["packet_id"]!=frame["packet_id"]: raise ValueError("packet_id_mismatch")
    if packet["destination"]["org"]!=frame["destination_org"]: raise ValueError("destination_org_mismatch")
    return packet

def receipt(kind:str, packet_id:str, subject:str, previous:str|None, detail:dict[str,Any])->dict[str,Any]:
    body={"kind":kind,"packet_id":packet_id,"subject":subject,"previous_receipt_id":previous,"detail":detail}
    rid=kind.lower()+"-"+hashlib.sha256(canon(body)).hexdigest()[:24]
    return {**body,"receipt_id":rid,"evidence_hash":sha(body)}

def manifest_selection(root:Path):
    """Load the organization's manifest-selection module from its boundary runtime.

    Processing is selected by the admitted manifest, not by the addressed row.
    The module is resolved from the dispatch root rather than from beside this
    file, for the same reason `services.json` and `process_boundary.py` are: the
    kernel is organization-neutral and runs against whichever organization root
    it is handed. A root with no selection module fails closed -- dispatching
    into a boundary that cannot say how processing was selected is exactly what
    this must not do silently.
    """
    path=root/"org-boundary/runtime/manifest_selection.py"
    if not path.is_file(): raise ValueError("org_boundary_manifest_selection_missing")
    spec=importlib.util.spec_from_file_location("manifest_selection",path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

def node_standing(root:Path):
    """Load the organization's node-standing module from its boundary runtime.

    Standing is a precondition of ingress, not a capability, so it resolves
    here rather than being something a crossing can be addressed to. Resolved
    from the dispatch root for the same reason as `manifest_selection`, and a
    root without it fails closed: a boundary that cannot validate the
    predecessor it is required to carry must not admit a crossing claiming one.
    """
    path=root/"org-boundary/runtime/node_standing.py"
    if not path.is_file(): raise ValueError("org_boundary_node_standing_missing")
    spec=importlib.util.spec_from_file_location("node_standing",path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

#: The boundary role whose dispatch resolves a bound capability's address.
#:
#: The role vocabulary is this kernel's, as `BOUNDARY_LOCAL_DIAGNOSTIC` and
#: `BOUNDARY_LOCAL_CONTROL` already are. `capability_ingress.ROLE` is that
#: module's assertion of which role it serves, and a test holds the two equal:
#: a resolver serving a role the kernel never dispatches would be unreachable
#: in exactly the way the address it resolves used to be.
CAPABILITY_INGRESS_ROLE="BOUNDARY_LOCAL_CAPABILITY_INGRESS"

def capability_ingress(root:Path):
    """Load the organization's capability-ingress module from its boundary runtime.

    A registered capability is bound to a receiving operation in the
    organization's own overlay, and that binding named a destination nothing
    could be addressed to: `dispatch` resolves `destination.service` against
    `services.json` and refuses `unknown_service` for anything absent from it.
    This resolves the address to the bound operation, from the dispatch root for
    the same reason as `manifest_selection` and `node_standing`. A root without
    it fails closed: an address that cannot resolve which capability it serves
    must not run anything.
    """
    path=root/"org-boundary/runtime/capability_ingress.py"
    if not path.is_file(): raise ValueError("org_boundary_capability_ingress_missing")
    spec=importlib.util.spec_from_file_location("capability_ingress",path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

def load_registry(source:Path|dict[str,Any])->dict[str,Any]:
    """Resolve the capability map from materialized data or an explicit checkout.

    A node that holds no repository receives the map as a document. Path-backed
    loading remains an explicit compatibility adapter for a materializer that
    chose a checkout; no host path is discovered here.
    """
    if isinstance(source,dict):
        value=source
    else:
        value=json.loads((Path(source)/"org-boundary/registry/services.json").read_text())
    if not isinstance(value,dict) or not isinstance(value.get("organization"),str):
        raise ValueError("capability_registry_invalid")
    if not isinstance(value.get("services"),list):
        raise ValueError("capability_registry_services_invalid")
    return value

def dispatch(root:Path, packet:dict[str,Any])->dict[str,Any]:
    registry=load_registry(root)
    if packet["destination"]["org"]!=registry["organization"]: raise ValueError("wrong_destination_org")
    service=next((s for s in registry["services"] if s["service_id"]==packet["destination"]["service"]),None)
    if service is None: raise ValueError("unknown_service")
    # Resolved before the role branch, because the contract covers every
    # ingress class rather than every boundary role: an INTERNAL_ENDPOINT
    # returns early below, so standing checked inside either arm would gate
    # only one of them. Refused as the contract's own disposition rather than a
    # bare error, so a caller is never left guessing which of ALLOW/DENY/
    # FAIL_CLOSED it earned.
    standing_module=node_standing(root)
    try:
        standing=standing_module.require(standing_module.load_contract(root),packet)
    except SystemExit as refused:
        raise ValueError("node_standing_refused:"+str(refused)) from None
    role=service.get("boundary_role")
    adapter=service.get("endpoint_adapter")
    if role=="INTERNAL_ENDPOINT" and adapter:
        processor=root/"org-boundary/runtime/process_boundary.py"
        if not processor.is_file(): raise ValueError("org_boundary_processor_missing")
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); envelope=td/"packet.json"; out=td/"execution.json"; registry_path=td/"registry.json"
            envelope.write_text(json.dumps(packet,indent=2,sort_keys=True)+"\n")
            registry_path.write_text(json.dumps(registry,indent=2,sort_keys=True)+"\n")
            completed=subprocess.run(["python3",str(processor),"--envelope",str(envelope),"--registry",str(registry_path),"--out",str(out)],cwd=root,capture_output=True,text=True,check=False)
            if completed.returncode!=0 or not out.is_file():
                raise ValueError("endpoint_adapter_execution_failed:"+completed.stderr[-512:])
            result=json.loads(out.read_text())
            if not isinstance(result,dict): raise ValueError("endpoint_adapter_result_invalid")
            return {**result,**standing}
    if role not in {"BOUNDARY_LOCAL_DIAGNOSTIC","BOUNDARY_LOCAL_CONTROL",CAPABILITY_INGRESS_ROLE}:
        raise ValueError("endpoint_adapter_not_installed")
    # Resolved before any receipt is minted: a dispatch that cannot state how
    # processing was selected must not leave a chain implying it was consumed.
    selected=manifest_selection(root).select_processing(service,packet["payload"])
    prev=None; receipts=[]
    for kind in ("INGRESS_ACCEPTED","DISPATCHED","CONSUMED","RESULT_BOUND","EGRESS_EMITTED"):
        r=receipt(kind,packet["packet_id"],service["service_id"],prev,{"payload_hash":sha(packet["payload"])})
        receipts.append(r); prev=r["receipt_id"]
    if role=="BOUNDARY_LOCAL_CONTROL":
        application_result=handle_control_message(root,packet,registry)
    elif role==CAPABILITY_INGRESS_ROLE:
        # The address resolves to the receiving operation the overlay binds,
        # which records its own dispositions at both ledger levels. Its refusal
        # is surfaced as this boundary's refusal rather than becoming a consumed
        # crossing with a refusal buried in its application result.
        #
        # Resolved here rather than beside the other two boundary runtimes
        # because this one gates a single role. `manifest_selection` and
        # `node_standing` gate every dispatch, so a root without them cannot
        # dispatch at all; a root that never serves a capability address is not
        # defective for having no capability resolver, and failing its control
        # dispatch over one would be a limit that is not real.
        try:
            application_result=capability_ingress(root).receive(root,service,packet,registry=registry)
        except SystemExit as refused:
            raise ValueError("capability_ingress_refused:"+str(refused)) from None
    else:
        application_result={"echo":packet["payload"]}
    return {"schema_version":SCHEMA,"organization":registry["organization"],"packet_id":packet["packet_id"],
            "service_id":service["service_id"],"consumed":True,"application_result":application_result,
            "authority_effect":packet["transition"]["authority_effect"],
            **selected,**standing,"receipts":receipts,
            "reconstruction":{"same_execution_required":True,"status":"RECONSTRUCTED","terminal_receipt_id":prev}}

def persist_outbox(root:Path, frame:dict[str,Any], *, store:Any|None=None)->Path:
    """Record a published frame in this node's outbox.

    The write is atomic and write-once by key; it used to be a bare
    `write_text`, so a reader could observe a partial frame.
    """
    target=store or node_state_store(root)
    key=node_store_module.outbox_key(frame["packet_id"])
    try:
        target.put_once(key,frame)
    except node_store_module.WriteOnceCollision:
        raise ValueError("write_once_collision")
    return Path(target.locator(key))

def ingest_frame(root:Path, frame:dict[str,Any])->dict[str,Any]:
    packet=recover_packet(frame)
    registry=load_registry(root)
    if frame["destination_org"]!=registry["organization"]:
        return {"status":"IGNORED_NOT_ADDRESSED","packet_id":frame["packet_id"]}
    result=dispatch(root,packet)
    return {"status":"CONSUMED","packet":packet,"execution_result":result}

__all__=["hb_reference","derive_channel","carrier_frame","recover_packet","dispatch","persist_outbox",
         "node_standing","capability_ingress","CAPABILITY_INGRESS_ROLE","carried_standing",
         "ingest_frame","mesh_store","node_state_store","node_state_provenance",
         "resolve_federation_root","resolve_node_state_root","addressed_node_state_store",
         "record_federation_cycle","federation_cycles"]


# --- Federation mesh v1.1 additions ---
def federation_root(root:Path|str)->Path:
    return resolve_federation_root(root)[0]

def resolve_federation_root(root:Path|str|None)->tuple[Path,str]:
    """Return the mesh location supplied by the node materializer.

    StegOS does not derive mesh identity from environment variables, a home
    directory, a checkout, or any other host property. A materializer either
    supplies the mesh location or the node fails closed.
    """
    if root is None:
        raise ValueError("mesh_location_required_from_materializer")
    return Path(root).expanduser().resolve(), node_store_module.SUPPLIED

def mesh_store(root:Path|str|None=None, env:dict[str,str]|None=None)->Any:
    """The shared frame medium between nodes, explicitly supplied."""
    if env is not None:
        raise ValueError("host_environment_mesh_binding_forbidden")
    resolved,provenance=resolve_federation_root(root)
    return PosixStateStore(resolved, provenance=provenance)

def node_state_store(root:Path)->Any:
    """One node's own markers, outbox and work intake. Expected to be ephemeral."""
    return PosixStateStore(Path(root)/"resident-runtime",
                           provenance=node_store_module.SUPPLIED)

def node_state_provenance(root:Path|str|None=None, env:dict[str,str]|None=None)->dict[str,Any]:
    """What this node's supplied mesh state depends on."""
    store=mesh_store(root,env)
    return {"schema_version":"stegverse.stegos-node-state-provenance/v1",
            "mesh_locator":str(store.root),"mesh_provenance":store.provenance,
            "mesh_portable":store.portable,"store_kind":store.kind,
            "authority_effect":"NONE_REPORT_ONLY"}

def publish_frame(frame:dict[str,Any], *, root:Path|None=None, store:Any|None=None)->Path:
    """Publish a frame to the mesh, addressed by what it carries."""
    target=store or mesh_store(root)
    key=node_store_module.frame_key(frame)
    try:
        target.put_once(key,frame)
    except node_store_module.WriteOnceCollision:
        raise ValueError("federation_frame_write_once_collision")
    return Path(target.locator(key))

def scan_addressed_frames(organization:str, *, root:Path|None=None, store:Any|None=None,
                          seen:set[str]|None=None)->list[dict[str,Any]]:
    """Frames in the mesh addressed to `organization` and not already consumed."""
    target=store or mesh_store(root)
    consumed=seen or set()
    out=[]
    for key in target.list_prefix(node_store_module.MESH_FRAME_PREFIX):
        if node_store_module.frame_name(key) in consumed:
            continue
        frame=target.get(key)
        if frame is not None and frame.get("destination_org")==organization:
            out.append({"key":key,"name":node_store_module.frame_name(key),
                        "path":target.locator(key),"frame":frame})
    return out

def carried_standing(request_packet:dict[str,Any])->dict[str,Any]:
    """Carry a request's standing onto its response, unchanged and marked as carried.

    A response is not a new chain position. Deriving a successor binding here
    would mean computing the owner's `successor_predecessor_binding` locally,
    and `local_second_predecessor_semantics_permitted` is false, so the only
    truthful options are to carry the request's standing forward or to refuse.
    It is carried, and flagged, so nothing downstream reads a restatement as an
    advanced generation.
    """
    declared=request_packet.get("standing")
    if not isinstance(declared,dict): raise ValueError("response_requires_request_standing")
    return {**declared,"standing_carried_forward_from_request":True}

def build_packet(*, origin_org:str, origin_service:str, destination_org:str, destination_service:str,
                 payload:dict[str,Any], standing:dict[str,Any], transition_reference:str="federation.v1",
                 authority_effect:str="NONE", packet_id:str|None=None)->dict[str,Any]:
    """Build an ingress packet. `standing` is required and has no default.

    Every ingress class the contract covers requires canonical node standing,
    so a packet that does not declare it cannot cross. A default here would be
    exactly the silent fallback the contract forbids, so there is none: a
    caller states its chain position or it does not get a packet.
    """
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
      "standing":standing,
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


# --- Ecosystem-wide communication v1.2 additions ---
def organization_slug(organization:str)->str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in organization).strip("-")

def build_ecosystem_packets(*, origin_org:str, origin_service:str, organizations:list[str], standing:dict[str,Any],
                            message_class:str, subject:str, body:dict[str,Any],
                            requested_action:str|None=None, transition_reference:str="ecosystem.communication.v1",
                            authority_effect:str="NONE", communication_id:str|None=None)->dict[str,Any]:
    ordered=sorted(dict.fromkeys(organizations))
    if not ordered:
        raise ValueError("organizations_required")
    comm_id=communication_id or "ecosystem-"+hashlib.sha256(canon({
        "origin_org":origin_org,"origin_service":origin_service,"organizations":ordered,
        "message_class":message_class,"subject":subject,"body":body,
        "requested_action":requested_action,"transition_reference":transition_reference
    })).hexdigest()[:24]
    packets=[]
    for org in ordered:
        service=organization_slug(org)+".org-control"
        payload={
          "communication_id":comm_id,
          "message_class":message_class,
          "subject":subject,
          "body":body,
          "requested_action":requested_action,
          "audience":"ECOSYSTEM",
          "target_organization":org,
          "target_count":len(ordered)
        }
        packet=build_packet(
          origin_org=origin_org,
          origin_service=origin_service,
          destination_org=org,
          destination_service=service,
          payload=payload,
          standing=standing,
          transition_reference=transition_reference,
          authority_effect=authority_effect,
          packet_id=comm_id+":"+organization_slug(org)
        )
        packets.append(packet)
    return {"communication_id":comm_id,"organization_count":len(ordered),"packets":packets}

def publish_ecosystem_message(*, origin_org:str, origin_service:str, organizations:list[str], standing:dict[str,Any],
                              message_class:str, subject:str, body:dict[str,Any],
                              requested_action:str|None=None, transition_reference:str="ecosystem.communication.v1",
                              authority_effect:str="NONE", communication_id:str|None=None,
                              root:Path|None=None, now_ns:int|None=None)->dict[str,Any]:
    built=build_ecosystem_packets(
      origin_org=origin_org,origin_service=origin_service,organizations=organizations,standing=standing,
      message_class=message_class,subject=subject,body=body,requested_action=requested_action,
      transition_reference=transition_reference,authority_effect=authority_effect,
      communication_id=communication_id
    )
    publications=[publish_packet(packet,root=root,now_ns=now_ns) for packet in built["packets"]]
    return {"communication_id":built["communication_id"],"organization_count":built["organization_count"],
            "published_count":len(publications),"publications":publications}

def aggregate_ecosystem_results(communication_id:str, results_by_org:dict[str,list[dict[str,Any]]])->dict[str,Any]:
    rows=[]
    for org,items in sorted(results_by_org.items()):
        matched=[]
        for item in items:
            result=item.get("result") or {}
            packet=result.get("packet") or {}
            payload=packet.get("payload") or {}
            if payload.get("communication_id")==communication_id:
                matched.append(item)
        status="CONSUMED" if any((x.get("result") or {}).get("status")=="CONSUMED" for x in matched) else "NOT_OBSERVED"
        terminal=None
        for x in matched:
            er=(x.get("result") or {}).get("execution_result") or {}
            terminal=(er.get("reconstruction") or {}).get("terminal_receipt_id") or terminal
        rows.append({"organization":org,"status":status,"terminal_receipt_id":terminal})
    consumed=sum(1 for row in rows if row["status"]=="CONSUMED")
    return {"communication_id":communication_id,"organization_count":len(rows),
            "consumed_count":consumed,"pending_count":len(rows)-consumed,
            "complete":consumed==len(rows) and len(rows)>0,"organizations":rows}


# --- Ecosystem control/response v1.3 additions ---
def load_federation_directory(root:Path)->dict[str,Any]:
    path=root/"org-boundary/registry/federation.json"
    value=json.loads(path.read_text())
    if value.get("denominator")!=len(value.get("organizations") or []):
        raise ValueError("federation_directory_denominator_mismatch")
    return value

def resident_status(root:Path, registry:dict[str,Any]|None=None)->dict[str,Any]:
    reg=registry or load_registry(root)
    activation_path=root/"resident-runtime/activation-manifest.json"
    activation=json.loads(activation_path.read_text()) if activation_path.exists() else {}
    kernel=(activation.get("kernel") or {})
    return {
      "organization":reg["organization"],
      "kernel_version":kernel.get("version"),
      "activation_state":activation.get("state"),
      "registered_service_count":len(reg.get("services") or []),
      "registered_services":[s.get("service_id") for s in reg.get("services") or []],
      "org_control_service":organization_slug(reg["organization"])+".org-control",
      "heartbeat_reference":hb_reference(),
      "runtime_observation_claimed":False
    }

def persist_work_request(root:Path, packet:dict[str,Any], *, store:Any|None=None)->dict[str,Any]:
    payload=packet.get("payload") or {}
    communication_id=payload.get("communication_id")
    record={
      "schema_version":"stegverse.ecosystem-work-intake.v1",
      "communication_id":communication_id,
      "packet_id":packet["packet_id"],
      "origin":packet["origin"],
      "destination":packet["destination"],
      "requested_action":payload.get("requested_action"),
      "body":payload.get("body"),
      "transition":packet["transition"],
      "state":"QUEUED_FOR_LOCAL_ADMISSION_EVALUATION",
      "execution_authority_inferred":False,
      "carrier_grants_execution_authority":False
    }
    target=store or node_state_store(root)
    key=node_store_module.intake_key(packet["packet_id"],communication_id)
    try:
        target.put_once(key,record)
    except node_store_module.WriteOnceCollision:
        raise ValueError("work_intake_write_once_collision")
    return {"state":record["state"],"intake_ref":target.locator(key),
            "execution_authority_inferred":False}

def handle_control_message(root:Path, packet:dict[str,Any], registry:dict[str,Any])->dict[str,Any]:
    payload=packet.get("payload") or {}
    message_class=payload.get("message_class")
    result={
      "message_received":True,
      "message_class":message_class,
      "communication_id":payload.get("communication_id"),
      "requested_action":payload.get("requested_action"),
      "execution_authority_inferred":False,
      "execution_authority_effect":packet["transition"]["authority_effect"]
    }
    if message_class=="ecosystem.monitor.request":
        result["monitor_status"]=resident_status(root,registry)
    elif message_class=="ecosystem.work.request":
        result["work_intake"]=persist_work_request(root,packet)
    elif message_class=="ecosystem.communication":
        result["communication_acknowledged"]=True
    elif message_class in {"ecosystem.monitor.response","ecosystem.work.ack","ecosystem.communication.ack"}:
        result["response_acknowledged"]=True
    return result

#: The request classes this boundary answers, and the acknowledgement each is
#: answered with. A crossing declaring anything else is consumed and receipted
#: and never answered, so its closure is not pending -- it is unreachable. The
#: mapping is named here because three surfaces read it: the responder that
#: decides whether to answer, the response builder that labels the answer, and
#: the egress boundary that refuses a crossing it can see will never close.
RESPONDED_REQUEST_CLASSES = {
    "ecosystem.monitor.request": "ecosystem.monitor.response",
    "ecosystem.work.request": "ecosystem.work.ack",
    "ecosystem.communication": "ecosystem.communication.ack",
}


def response_message_class(request_class:str|None)->str:
    return RESPONDED_REQUEST_CLASSES.get(request_class or "","ecosystem.communication.ack")

def build_control_response(request_packet:dict[str,Any], execution_result:dict[str,Any])->dict[str,Any]:
    req_payload=request_packet.get("payload") or {}
    origin_org=request_packet["origin"]["org"]
    local_org=request_packet["destination"]["org"]
    cls=response_message_class(req_payload.get("message_class"))
    payload={
      "communication_id":req_payload.get("communication_id"),
      "message_class":cls,
      "subject":"response:"+str(req_payload.get("subject") or ""),
      "body":{
        "request_packet_id":request_packet["packet_id"],
        "responding_organization":local_org,
        "application_result":execution_result.get("application_result"),
        "receipt_terminal":(execution_result.get("reconstruction") or {}).get("terminal_receipt_id")
      },
      "requested_action":None,
      "audience":"ORIGIN",
      "target_organization":origin_org,
      "target_count":1
    }
    return build_packet(
      origin_org=local_org,
      origin_service=organization_slug(local_org)+".org-control",
      destination_org=origin_org,
      destination_service=organization_slug(origin_org)+".org-control",
      payload=payload,
      standing=carried_standing(request_packet),
      transition_reference=str((request_packet.get("transition") or {}).get("reference") or "ecosystem.communication.v1")+".response",
      authority_effect="NONE",
      packet_id=str(req_payload.get("communication_id"))+":response:"+organization_slug(local_org)
    )

def build_endpoint_response(request_packet:dict[str,Any], execution_result:dict[str,Any])->dict[str,Any]:
    payload={
      "schema":"stegverse.org-endpoint-response/v1",
      "response_to_packet_id":request_packet["packet_id"],
      "request_manifest_sha256":((request_packet.get("payload") or {}).get("request") or {}).get("bindings",{}).get("manifest_sha256"),
      "execution_result":execution_result,
      "authority_transfer":False
    }
    return build_packet(
      origin_org=request_packet["destination"]["org"],
      origin_service=request_packet["destination"]["service"],
      destination_org=request_packet["origin"]["org"],
      destination_service=request_packet["origin"]["service"],
      payload=payload,
      standing=carried_standing(request_packet),
      transition_reference=str((request_packet.get("transition") or {}).get("reference") or "endpoint")+".response",
      authority_effect="NONE_RESPONSE_ONLY",
      packet_id=request_packet["packet_id"]+":response"
    )

def consume_and_respond(repo_root:Path, *, mesh_root:Path|None=None, seen:set[str]|None=None,
                        now_ns:int|None=None)->list[dict[str,Any]]:
    registry=load_registry(repo_root)
    organization=registry["organization"]
    durable_seen=federation_seen_frame_names(repo_root)
    effective_seen=set(seen or set())|durable_seen
    out=[]
    for item in scan_addressed_frames(organization,root=mesh_root,seen=effective_seen):
        packet=recover_packet(item["frame"])
        payload=packet.get("payload") or {}
        message_class=payload.get("message_class")
        result=ingest_frame(repo_root,item["frame"])
        response_publication=None
        if result.get("status")=="CONSUMED" and message_class in RESPONDED_REQUEST_CLASSES:
            response=build_control_response(packet,result["execution_result"])
            response_publication=publish_packet(response,root=mesh_root,now_ns=now_ns)
        elif result.get("status")=="CONSUMED" and not payload.get("response_to_packet_id"):
            service=next((svc for svc in registry["services"] if svc.get("service_id")==packet["destination"]["service"]),None)
            if service and service.get("endpoint_adapter"):
                response=build_endpoint_response(packet,result["execution_result"])
                response_publication=publish_packet(response,root=mesh_root,now_ns=now_ns)
        marker=mark_federation_frame_seen(repo_root,item["path"],item["frame"],result)
        out.append({"path":item["path"],"result":result,"response_publication":response_publication,"seen_marker":str(marker)})
    return out

def collect_ecosystem_responses(origin_org:str, communication_id:str, *, mesh_root:Path|None=None)->dict[str,Any]:
    responses=[]
    for item in scan_addressed_frames(origin_org,root=mesh_root):
        packet=recover_packet(item["frame"])
        payload=packet.get("payload") or {}
        if payload.get("communication_id")!=communication_id:
            continue
        if payload.get("message_class") not in {
            "ecosystem.monitor.response","ecosystem.work.ack","ecosystem.communication.ack"}:
            continue
        body=payload.get("body") or {}
        responses.append({
          "organization":body.get("responding_organization") or packet["origin"]["org"],
          "message_class":payload.get("message_class"),
          "request_packet_id":body.get("request_packet_id"),
          "application_result":body.get("application_result"),
          "receipt_terminal":body.get("receipt_terminal"),
          "response_packet_id":packet["packet_id"],
          "frame_sha256":item["frame"].get("frame_sha256")
        })
    dedup={}
    for row in responses:
        dedup[row["organization"]]=row
    rows=[dedup[k] for k in sorted(dedup)]
    return {
      "communication_id":communication_id,
      "response_count":len(rows),
      "organizations":rows
    }

def publish_ecosystem_from_directory(repo_root:Path, *, message_class:str, subject:str, body:dict[str,Any],
                                     requested_action:str|None=None, authority_effect:str="NONE",
                                     communication_id:str|None=None, mesh_root:Path|None=None,
                                     now_ns:int|None=None)->dict[str,Any]:
    registry=load_registry(repo_root)
    directory=load_federation_directory(repo_root)
    organizations=[row["organization"] for row in directory["organizations"]]
    origin=registry["organization"]
    return publish_ecosystem_message(
      origin_org=origin,
      origin_service=organization_slug(origin)+".org-control",
      organizations=organizations,
      message_class=message_class,
      subject=subject,
      body=body,
      requested_action=requested_action,
      authority_effect=authority_effect,
      communication_id=communication_id,
      root=mesh_root,
      now_ns=now_ns
    )


# --- Federation replay/dedup v1.3.1 additions ---
def federation_seen_frame_names(repo_root:Path, *, store:Any|None=None)->set[str]:
    """Which frames this node has already consumed.

    The marker records the frame's name rather than its key, so a node holding
    markers written before state was addressed does not re-consume the mesh.
    """
    target=store or node_state_store(repo_root)
    names=set()
    for key in target.list_prefix(node_store_module.NODE_SEEN_PREFIX):
        try:
            value=target.get(key)
        except ValueError:
            continue
        if isinstance(value,dict) and isinstance(value.get("frame_name"),str):
            names.add(value["frame_name"])
    return names

def mark_federation_frame_seen(repo_root:Path, frame_path:str, frame:dict[str,Any], result:dict[str,Any],
                               *, store:Any|None=None)->Path:
    """Record that this node consumed a frame, once and atomically."""
    target=store or node_state_store(repo_root)
    frame_name=node_store_module.frame_name(str(frame_path))
    marker={
      "schema_version":"stegverse.federation-frame-consumption.v1",
      "frame_name":frame_name,
      "frame_sha256":frame.get("frame_sha256"),
      "packet_id":frame.get("packet_id"),
      "destination_org":frame.get("destination_org"),
      "status":result.get("status"),
      "authority_effect":"NONE_CARRIER_ONLY"
    }
    key=node_store_module.seen_key(frame_name)
    try:
        target.put_once(key,marker)
    except node_store_module.WriteOnceCollision:
        raise ValueError("federation_seen_marker_collision")
    return Path(target.locator(key))

# --- Resident cycle records, addressed rather than located ---
def resolve_node_state_root(root:Path|str|None)->tuple[Path,str]:
    """Return the node-state location supplied by the materializer."""
    if root is None:
        raise ValueError("node_state_location_required_from_materializer")
    return Path(root).expanduser().resolve(), node_store_module.SUPPLIED

def addressed_node_state_store(root:Path|str|None=None, env:dict[str,str]|None=None)->Any:
    """This node's state at the location supplied by its materializer."""
    if env is not None:
        raise ValueError("host_environment_node_state_binding_forbidden")
    resolved,provenance=resolve_node_state_root(root)
    return PosixStateStore(resolved, provenance=provenance)

def record_federation_cycle(receipt:dict[str,Any], *, root:Path|None=None,
                            store:Any|None=None, env:dict[str,str]|None=None)->Path:
    """Record one resident cycle in this node's own state.

    The cycle receipt is this node's report of one pass. It was written to
    `resident-runtime/federation/latest-cycle.json` inside the repository
    checkout, so running the resident runtime mutated committed space and kept
    only the most recent pass -- the rest were overwritten and gone. It is now
    addressed by what it reported, in a node state root that is resolved rather
    than assumed, and every pass is kept.
    """
    target=store or addressed_node_state_store(root,env)
    key=node_store_module.cycle_key(receipt)
    target.put_once(key,receipt)
    return Path(target.locator(key))

def federation_cycles(*, root:Path|None=None, store:Any|None=None,
                      env:dict[str,str]|None=None)->list[dict[str,Any]]:
    """Every cycle this node recorded, in reproducible key order."""
    target=store or addressed_node_state_store(root,env)
    out=[]
    for key in target.list_prefix(node_store_module.NODE_CYCLE_PREFIX):
        value=target.get(key)
        if isinstance(value,dict):
            out.append(value)
    return out
