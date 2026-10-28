#!/usr/bin/env python3
"""Universal StegVerse organization resident kernel.

Organization-neutral runtime behavior extracted from StegVerse-Labs/.github.
No GitHub, hosted scheduler, provider, or carrier grants authority.
"""
from __future__ import annotations
import base64, hashlib, importlib.util, json, os, subprocess, tempfile
# datetime is no longer called anywhere in the kernel (hb_reference has no clock
# fallback); the name is kept only so org#188's test can wrap it and assert it is never called.
from datetime import datetime, timezone  # noqa: F401
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

class HbEpochNotSupplied(ValueError):
    """hb_reference was given neither a supplied epoch nor a sample; `.refusal` carries the six fields. No clock is read."""
    def __init__(self):
        self.refusal={"disposition":"FAIL_CLOSED","failure_code":"HB_EPOCH_NOT_SUPPLIED",
          "failed_predicate":"SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH",
          "detail":"no hb_epoch was supplied and no clock is read",
          "required_evidence_or_repair":"pass epoch= as the carrier supplied it: ASCII digits with value >= 32; it is never derived from a clock",
          "retry_entrypoint":"org-kernel/kernel.py::hb_reference",
          "owning_existing_goal":"INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001",
          "next_attempt":"call again with the supplied epoch; nothing was stamped",
          "derived_from_clock":False,"consequence_committed":False}
        super().__init__("HB_EPOCH_NOT_SUPPLIED:no hb_epoch was supplied and no clock is read")

class HbEpochSampledClock(ValueError):
    """hb_reference was handed a clock sample (now_ns); `.refusal` carries the six fields.

    A sampled clock value is CLOCK, never a supplied epoch (the marker
    vocabulary of StegVerse-Labs/.github#3290: a reference with
    derived_from_clock true or a sampled_unix_ns is HB_EPOCH_INVALID). No
    reference is derived from the sample and nothing is stamped.
    """
    def __init__(self):
        self.refusal={"disposition":"FAIL_CLOSED","failure_code":"HB_EPOCH_INVALID",
          "failed_predicate":"SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH",
          "detail":"a caller-sampled clock value (now_ns) was handed to hb_reference; a sampled clock value is CLOCK, never a supplied epoch",
          "required_evidence_or_repair":"pass epoch= as the carrier supplied it: ASCII digits with value >= 32; it is never derived from a clock",
          "retry_entrypoint":"org-kernel/kernel.py::hb_reference",
          "owning_existing_goal":"INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001",
          "next_attempt":"call again with the supplied epoch and no now_ns; nothing was stamped",
          "derived_from_clock":False,"consequence_committed":False}
        super().__init__("HB_EPOCH_INVALID:a sampled clock value is CLOCK, never a supplied epoch")

def hb_reference(now_ns:int|None=None, *, epoch:int|None=None)->dict[str,Any]:
    """Build the heartbeat reference for a crossing from the supplied epoch.

    Progression is OSCILLATOR_ONLY: the epoch is a count of heartbeat periods,
    not a reading of a wall clock, and it is supplied by the carrier. The
    reference is then reproducible: the same packet at the same epoch yields
    the same frame digest (receipts are byte-deterministic).

    No epoch is derived from a clock. A caller-sampled `now_ns` is refused
    HB_EPOCH_INVALID (HbEpochSampledClock), checked before anything else, and
    an absent epoch is refused HB_EPOCH_NOT_SUPPLIED (HbEpochNotSupplied). The
    `now_ns` parameter stays only so an old caller fails closed in six fields
    instead of with a TypeError; no derived_from_clock true reference is built.
    """
    if now_ns is not None:
        raise HbEpochSampledClock()
    if epoch is None:
        raise HbEpochNotSupplied()
    if not isinstance(epoch,int) or isinstance(epoch,bool) or epoch<HB_ANCHOR_EPOCH:
        raise ValueError("epoch_precedes_hb32_anchor")
    return validate_hb_reference({"epoch":epoch,"generation":epoch,"heartbeat_id":f"HB:{epoch}",
            "phase_offset_ns":0,"frequency_hz":HB_HZ,"progression_dependency":"OSCILLATOR_ONLY",
            "derived_from_clock":False,"authority_effect":"NONE"})

def derive_channel(payload_hash:str)->dict[str,Any]:
    if not isinstance(payload_hash,str) or not payload_hash.startswith("sha256:") or len(payload_hash)!=71:
        raise ValueError("payload_hash_invalid")
    slot=int(payload_hash[7:23],16)%CHANNEL_COUNT
    return {"channel_id":f"HB:H1:P{slot}","phase_slot":slot,"phase_slot_count":CHANNEL_COUNT,
            "derivation":"PAYLOAD_SHA256_FIRST64_MOD_16","authority_effect":"NONE_CARRIER_ONLY"}

# The shared supplied-epoch rule, byte-identical to the copies in
# org-boundary/runtime/capability_ingress.py, resident-runtime/aggregate_repo_transition.py
# and resident-runtime/organization_egress_boundary.py (StegVerse-Labs/.github#3282 FINAL;
# SHARED_VALIDATOR_SHA256 in tests/test_p1_supplied_epoch_and_ledger_paths.py).
def supplied_epoch_failure(hb_epoch: Any, reference: Any = None) -> tuple[str, str] | None:
    """The shared supplied-epoch rule (SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH).

    Byte-identical in StegVerse-org/.github#185 and StegVerse-Labs/.github#3212
    and #3213. `hb_epoch` absent (None) is HB_EPOCH_NOT_SUPPLIED. Otherwise it
    must be ASCII [0-9]+ only -- an int is read as its decimal text; a bool, a
    float or anything coerced ('+33', ' 33', '3_3', '33.0') is refused -- with
    integer value >= 32 (the HB32 anchor). `reference`, the carrier frame's
    heartbeat reference when there is one, must be an object, and a
    `derived_from_clock` it carries must be exactly false. Any failure is
    HB_EPOCH_INVALID. Returns (failure_code, detail), or None when the epoch is
    supplied. No clock is read.
    """
    if reference is not None and not isinstance(reference, dict):
        return "HB_EPOCH_INVALID", "the carrier's heartbeat reference is not an object"
    if hb_epoch is None:
        return "HB_EPOCH_NOT_SUPPLIED", "no hb_epoch was supplied and no clock is read"
    if isinstance(hb_epoch, bool):
        text = None
    elif isinstance(hb_epoch, int):
        text = str(hb_epoch)
    elif isinstance(hb_epoch, str):
        text = hb_epoch
    else:
        text = None
    if text is None or not text.isascii() or not text.isdigit():
        return "HB_EPOCH_INVALID", "hb_epoch " + repr(hb_epoch) + " is not ASCII [0-9]+"
    if int(text) < 32:
        return "HB_EPOCH_INVALID", "hb_epoch " + text + " is below the HB32 anchor (32)"
    if reference is not None and "derived_from_clock" in reference \
            and reference["derived_from_clock"] is not False:
        return "HB_EPOCH_INVALID", ("the carrier's derived_from_clock is not exactly false; "
                                    "a clock-derived epoch is not a supplied one")
    if reference is not None and "sampled_unix_ns" in reference: return "HB_EPOCH_INVALID", "the carrier's heartbeat reference carries sampled_unix_ns; a sampled clock value is CLOCK, never a supplied epoch"
    if reference is not None and "derived_from_clock" not in reference: return "HB_EPOCH_PROVENANCE_UNMARKED", "the carrier's heartbeat reference carries no derived_from_clock; an unmarked clock value is laundering, and a carrier cannot self-assert CARRIED provenance"
    return None

CARRIED_PROVENANCE_KEYS=("source","head_receipt_sha")

def carrier_frame(packet:dict[str,Any], *, now_ns:int|None=None, epoch:int|None=None,
                  provenance:dict[str,Any]|None=None)->dict[str,Any]:
    # `provenance` marks a CARRIED epoch in the reference itself: source
    # "CARRIED:<origin>" and the head_receipt_sha it was read from. Additive and
    # optional; only a supplied epoch can be carried, so it is refused without one.
    if provenance is not None and (epoch is None or set(provenance)!=set(CARRIED_PROVENANCE_KEYS)
                                   or not str(provenance.get("source")).startswith("CARRIED:")):
        raise ValueError("carried_provenance_invalid")
    raw=canon(packet); payload_hash=sha(packet.get("payload",{})); ref=hb_reference(now_ns,epoch=epoch); channel=derive_channel(payload_hash)
    if provenance is not None:
        ref={**ref,**{k:provenance[k] for k in CARRIED_PROVENANCE_KEYS}}
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

#: process_boundary.py's exit codes (Data-Continuation/.github#10 semantics).
PROCESS_BOUNDARY_INPUT_FAULT_EXIT=65
PROCESS_BOUNDARY_WRITE_FAULT_EXIT=75

class BoundaryWriteFault(RuntimeError):
    """The boundary processor's own write faulted (exit 75): non-terminal, the frame stays pending."""

def dispatch(root:Path, packet:dict[str,Any], *, mesh_root:Path|None=None,
             node_state:Any|None=None, epoch:int|None=None)->dict[str,Any]:
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
            command=["python3",str(processor),"--envelope",str(envelope),"--registry",str(registry_path),"--out",str(out)]
            # An adapter whose effect is a write to node state writes it at the
            # location this node was materialized with, never under the checkout.
            if node_state is not None:
                command+=["--node-state-root",str(node_state.root)]
            completed=subprocess.run(command,cwd=root,capture_output=True,text=True,check=False)
            # The boundary's exit-code split (PB-EXIT-SPLIT): only 75, a fault in this
            # node's own write, is non-terminal -- a writer fault, never the frame's,
            # so the consuming pass leaves the frame pending with no marker and no
            # receipt. Every other non-zero exit (65, 1, an unknown code, a crash) and
            # a missing result are terminal: recorded DENY and marked, FRAME_INGEST_FAILED.
            if completed.returncode==PROCESS_BOUNDARY_WRITE_FAULT_EXIT:
                raise BoundaryWriteFault("PROCESS_BOUNDARY_WRITE_FAULT:"+completed.stderr[-512:])
            if completed.returncode!=0 or not out.is_file():
                raise ValueError("PROCESS_BOUNDARY_INPUT_FAULT:exit "+str(completed.returncode)
                                 +":endpoint_adapter_execution_failed:"+completed.stderr[-512:])
            # A result that is not a readable JSON object is the crossing's terminal
            # refusal too (PB_UNREADABLE_RESULT_NOT_SPLIT): recorded DENY and marked,
            # never retried into a second transition for the same frame.
            try:
                result=json.loads(out.read_text(encoding="utf-8"))
            except (UnicodeDecodeError,ValueError,RecursionError,MemoryError) as exc:
                raise ValueError("PROCESS_BOUNDARY_INPUT_FAULT:endpoint_adapter_result_invalid:"
                                 +type(exc).__name__) from None
            if not isinstance(result,dict):
                raise ValueError("PROCESS_BOUNDARY_INPUT_FAULT:endpoint_adapter_result_invalid:"
                                 +type(result).__name__)
            return {**result,**standing}
    if role not in {"BOUNDARY_LOCAL_DIAGNOSTIC","BOUNDARY_LOCAL_CONTROL",CAPABILITY_INGRESS_ROLE}:
        raise ValueError("endpoint_adapter_not_installed")
    # Resolved before any receipt is minted: a dispatch that cannot state how
    # processing was selected must not leave a chain implying it was consumed.
    selected=manifest_selection(root).select_processing(service,packet["payload"])
    # A work request is retained in this node's own state. Without a location
    # supplied by the materializer there is nowhere to retain it, so it is
    # refused here, before any receipt implies it was consumed. It used to fall
    # back to the repository checkout, which is not node state.
    if (role=="BOUNDARY_LOCAL_CONTROL" and node_state is None
            and (packet.get("payload") or {}).get("message_class")=="ecosystem.work.request"):
        raise ValueError("node_state_location_required_from_materializer")
    prev=None; receipts=[]
    for kind in ("INGRESS_ACCEPTED","DISPATCHED","CONSUMED","RESULT_BOUND","EGRESS_EMITTED"):
        r=receipt(kind,packet["packet_id"],service["service_id"],prev,{"payload_hash":sha(packet["payload"])})
        receipts.append(r); prev=r["receipt_id"]
    if role=="BOUNDARY_LOCAL_CONTROL":
        application_result=handle_control_message(root,packet,registry,node_state=node_state,epoch=epoch)
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
            # The mesh this node was materialized with goes to the receiving
            # operation: a capability another organization decides leaves on it.
            # The frame's epoch goes with it, so the operation's appends are at
            # the supplied epoch; without one the resolver refuses
            # HB_EPOCH_NOT_SUPPLIED with six fields and nothing is appended.
            application_result=capability_ingress(root).receive(root,service,packet,registry=registry,
                                                                mesh_root=mesh_root,hb_epoch=epoch)
        except SystemExit as refused:
            error=ValueError("capability_ingress_refused:"+str(refused))
            # A six-field refusal (the epoch rule) keeps its fields on the error.
            error.refusal=getattr(refused,"refusal",None)
            raise error from None
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
    target=required_node_state(store)
    key=node_store_module.outbox_key(frame["packet_id"])
    try:
        target.put_once(key,frame)
    except node_store_module.WriteOnceCollision:
        raise ValueError("write_once_collision")
    return Path(target.locator(key))

def ingest_frame(root:Path, frame:dict[str,Any], *, mesh_root:Path|None=None,
                 node_state:Any|None=None)->dict[str,Any]:
    packet=recover_packet(frame)
    registry=load_registry(root)
    if frame["destination_org"]!=registry["organization"]:
        return {"status":"IGNORED_NOT_ADDRESSED","packet_id":frame["packet_id"]}
    # The epoch of the frame being consumed, which recovery has validated. What
    # the answer embeds is then a function of the frame, not of this pass. A
    # frame stamped from a clock lends none (NARROW S1): its epoch is not supplied.
    ref=frame.get("heartbeat_reference") or {}
    epoch=(ref.get("epoch") if ref.get("derived_from_clock") is False and "sampled_unix_ns" not in ref
           else None)
    result=dispatch(root,packet,mesh_root=mesh_root,node_state=node_state,epoch=epoch)
    return {"status":"CONSUMED","packet":packet,"execution_result":result}

__all__=["hb_reference","derive_channel","carrier_frame","recover_packet","dispatch","persist_outbox",
         "node_standing","capability_ingress","CAPABILITY_INGRESS_ROLE","carried_standing",
         "ingest_frame","mesh_store","node_state_store","node_state_provenance",
         "resolve_federation_root","resolve_node_state_root","addressed_node_state_store",
         "record_federation_cycle","federation_cycles","required_node_state"]


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
    if str(root).startswith('git+'):
        return str(root), node_store_module.SUPPLIED
    return Path(root).expanduser().resolve(), node_store_module.SUPPLIED

def mesh_store(root:Path|str|None=None, env:dict[str,str]|None=None)->Any:
    """The shared frame medium between nodes, explicitly supplied."""
    if env is not None:
        raise ValueError("host_environment_mesh_binding_forbidden")
    resolved,provenance=resolve_federation_root(root)
    if isinstance(resolved, str) and resolved.startswith('git+'):
        repository, separator, ref = resolved[4:].partition('#')
        if not separator or not repository or not ref.startswith('refs/'):
            raise ValueError('mesh_git_locator_invalid')
        return node_store_module.GitStateStore(repository, ref)
    return PosixStateStore(resolved, provenance=provenance)

def node_state_store(root:Path)->Any:
    """One node's own markers, outbox and work intake. Expected to be ephemeral."""
    return PosixStateStore(Path(root)/"resident-runtime",
                           provenance=node_store_module.SUPPLIED)

def required_node_state(store:Any|None)->Any:
    """The node state a write goes to, which the caller must supply.

    There is no default. Each of these writes used to fall back to
    `resident-runtime/` inside the repository checkout, so a resident pass
    mutated committed space and its markers outlived the node that wrote them.
    """
    if store is None:
        raise ValueError("node_state_location_required_from_materializer")
    return store

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

FRAME_ENTRY_LIMIT_BYTES=1<<20

def read_frame_entry(target:Any, key:str)->dict[str,Any]:
    """One frames.d entry as a frame object, or ValueError naming why it is not one.

    A read error, bytes that are not UTF-8, text that is not a JSON object, an
    entry over FRAME_ENTRY_LIMIT_BYTES, or a directory named *.json is the
    entry's own fault, never the scan's (B-P36p).
    """
    try:
        bounded=getattr(target,"read_bounded",None)
        if bounded is not None:
            frame=json.loads(bounded(key,FRAME_ENTRY_LIMIT_BYTES).decode("utf-8"))
        else:
            frame=target.get(key)
            if frame is not None and len(canon(frame))>FRAME_ENTRY_LIMIT_BYTES:
                raise ValueError("frame_entry_oversized: more than "+str(FRAME_ENTRY_LIMIT_BYTES)+" bytes")
    except UnicodeDecodeError as exc:
        raise ValueError("frame_entry_not_utf8: "+str(exc)[:120])
    except json.JSONDecodeError as exc:
        raise ValueError("frame_entry_not_json: "+str(exc)[:120])
    except (RecursionError, MemoryError) as exc:
        # A deeply nested document under the size cap (F-SCAN-RECURSION) is the
        # entry's defect, never the scan's: quarantined like any unreadable entry.
        raise ValueError("frame_entry_too_deep: "+type(exc).__name__)
    except OSError as exc:
        raise ValueError("frame_entry_read_error: "+type(exc).__name__+": "+str(exc)[:120])
    if not isinstance(frame,dict):
        raise ValueError("frame_entry_not_a_json_object: "+type(frame).__name__)
    return frame

def scan_addressed_frames(organization:str, *, root:Path|None=None, store:Any|None=None,
                          seen:set[str]|None=None, unreadable:list[dict[str,Any]]|None=None)->list[dict[str,Any]]:
    """Frames in the mesh addressed to `organization` and not already consumed.

    An entry that cannot be read as a frame never stops the scan: it is
    appended to `unreadable` (its key, name, locator and reason) when the
    caller collects them, and skipped otherwise.
    """
    target=store or mesh_store(root)
    consumed=seen or set()
    out=[]
    for key in target.list_prefix(node_store_module.MESH_FRAME_PREFIX):
        if node_store_module.frame_name(key) in consumed:
            continue
        try:
            frame=read_frame_entry(target,key)
        except ValueError as exc:
            if unreadable is not None:
                unreadable.append({"key":key,"name":node_store_module.frame_name(key),
                                   "path":target.locator(key),"reason":str(exc)})
            continue
        if frame.get("destination_org")==organization:
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

def publish_packet(packet:dict[str,Any], *, root:Path|None=None, now_ns:int|None=None,
                   epoch:int|None=None, provenance:dict[str,Any]|None=None)->dict[str,Any]:
    # A supplied epoch makes the frame reproducible: the same packet at the same
    # epoch is the same frame, so publishing it again is a write-once no-op.
    frame=carrier_frame(packet,now_ns=now_ns,epoch=epoch,provenance=provenance)
    path=publish_frame(frame,root=root)
    return {"packet":packet,"frame":frame,"path":str(path)}

def consume_addressed_frames(repo_root:Path, *, mesh_root:Path|None=None, seen:set[str]|None=None,
                             node_state_root:Path|None=None, repo_ledger_root:Path|None=None,
                             org_ledger_root:Path|None=None, hb_epoch:Any=None)->list[dict[str,Any]]:
    # The same custody as consume_and_respond: a crossing consumed here is a
    # transition within the organization and is recorded before it is returned.
    if hb_epoch is not None:
        failure=supplied_epoch_failure(hb_epoch)
        if failure is not None:
            raise ValueError("cycle_hb_epoch_invalid: "+failure[0]+": "+failure[1])
        hb_epoch=int(str(hb_epoch))
    custody=crossing_custody(repo_root,repo_ledger_root=repo_ledger_root,org_ledger_root=org_ledger_root)
    registry=load_registry(repo_root)
    organization=registry["organization"]
    # Node state is optional here because only a work request needs it, and
    # dispatch refuses that one by name when none was supplied. When it is
    # supplied it is also the seen-store: a frame refused for its own defect is
    # quarantined there and not offered again (F-TYPE).
    node_state=addressed_node_state_store(node_state_root) if node_state_root is not None else None
    effective_seen=set(seen or set())
    if node_state is not None:
        effective_seen|=federation_seen_frame_names(repo_root,store=node_state)
    results=[]
    unreadable=[]
    frames=scan_addressed_frames(organization,root=mesh_root,seen=effective_seen,unreadable=unreadable)

    def refuse(item_path, frame, refused):
        marker=(quarantine_federation_frame(item_path,frame,refused,store=node_state)
                if node_state is not None else None)
        results.append({"path":item_path,"result":{"status":"REFUSED","disposition":"FAIL_CLOSED",
                        "failed_predicate":refused["failed_predicate"],"failure_code":refused["failure_code"],
                        "packet_id":frame.get("packet_id"),"quarantined":marker is not None},
                        "organization_record":None,"seen_marker":None if marker is None else str(marker)})

    for entry in unreadable:
        refuse(entry["path"],{},unreadable_entry_refusal(entry["reason"],custody))
    for item in frames:
        # The same total per-frame guard as consume_and_respond.
        try:
            kind,provenance,refused=frame_epoch_class(item["frame"],custody)
            if refused is None and kind=="CARRIED" and not ACCEPTS_CARRIED_CROSSINGS:
                refused=carried_not_accepted(custody)
            if refused is None and node_state is not None:
                refused=request_id_collision(node_state,recover_packet(item["frame"]),item["frame"],custody)
            if refused is not None:
                refuse(item["path"],item["frame"],refused)
                continue
            if kind=="CLOCK":
                try:
                    result=ingest_frame(repo_root,item["frame"],mesh_root=mesh_root,node_state=node_state)
                except ValueError as exc:
                    if any(marker in str(exc) for marker in CUSTODY_REFUSALS):
                        raise
                    result={"status":"REFUSED","disposition":"FAIL_CLOSED","failed_predicate":str(exc),
                            "packet_id":item["frame"].get("packet_id")}
                results.append({"path":item["path"],"result":{**result,"epoch_lent":None},
                                "organization_record":not_supplied_record(custody)})
                continue
            frame_epoch=(item["frame"].get("heartbeat_reference") or {}).get("epoch")
            epoch,record_provenance,frame_reference,_answer=resolve_cycle_epoch(
                hb_epoch,frame_epoch,kind,provenance,item["frame"])
            result,recorded=ingest_recorded(repo_root,item,custody,registry,mesh_root=mesh_root,
                                            node_state=node_state,epoch=epoch,provenance=record_provenance,
                                            frame_reference=frame_reference)
            results.append({"path":item["path"],"result":result,"organization_record":recorded})
        except Exception as exc:
            if isinstance(exc, ValueError) and any(marker in str(exc) for marker in CUSTODY_REFUSALS):
                raise
            if getattr(exc,"capability_ingress_refusal",False):
                # This route returns a capability crossing's refusal to its caller.
                raise
            if writer_fault(exc):
                results.append({"path":item["path"],"result":{**dispatch_io_failure(exc,custody),
                                "status":"PENDING","packet_id":item["frame"].get("packet_id")},
                                "organization_record":None})
                continue
            refuse(item["path"],item["frame"],frame_ingest_refusal(exc,custody))
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
                              root:Path|None=None, now_ns:int|None=None,
                              epoch:int|None=None)->dict[str,Any]:
    built=build_ecosystem_packets(
      origin_org=origin_org,origin_service=origin_service,organizations=organizations,standing=standing,
      message_class=message_class,subject=subject,body=body,requested_action=requested_action,
      transition_reference=transition_reference,authority_effect=authority_effect,
      communication_id=communication_id
    )
    publications=[publish_packet(packet,root=root,now_ns=now_ns,epoch=epoch) for packet in built["packets"]]
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

def resident_status(root:Path, registry:dict[str,Any]|None=None, *, epoch:int|None=None)->dict[str,Any]:
    """This node's status. Inside an answer it carries the epoch of the frame
    it answers, so answering the same frame again builds the same answer frame
    and publishing it is a write-once no-op. It used to sample the host clock
    there, which made every re-answer a different frame. Without a frame epoch
    (a local status read, never published) the sample is a live host reading
    and is labelled as derived from the clock."""
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
      "heartbeat_reference":hb_reference(epoch=epoch) if epoch is not None else None,
      "runtime_observation_claimed":False,
      # No epoch supplied: the status carries no reference and says why, as the
      # federation cycle record does (heartbeat_reference_refusal). No clock is read.
      **({} if epoch is not None else {"heartbeat_reference_refusal":resident_status_epoch_refusal()})
    }

def resident_status_epoch_refusal()->dict[str,Any]:
    """Six-field FAIL_CLOSED record for a status read given no epoch (SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH)."""
    return {"disposition":"FAIL_CLOSED","failure_code":"HB_EPOCH_NOT_SUPPLIED",
            "failed_predicate":"SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH",
            "detail":"no epoch was supplied and no clock is read",
            "required_evidence_or_repair":"supply epoch= (ecosystem_control.py status --hb-epoch) from the carrier: ASCII digits, value >= 32; it is never derived from a clock",
            "retry_entrypoint":"org-kernel/kernel.py::resident_status",
            "owning_existing_goal":"INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001",
            "next_attempt":"read the status again with the supplied epoch; the status fields above are unaffected",
            "derived_from_clock":False,"consequence_committed":False}

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
    target=required_node_state(store)
    key=node_store_module.intake_key(packet["packet_id"],communication_id)
    try:
        target.put_once(key,record)
    except node_store_module.WriteOnceCollision:
        raise ValueError("work_intake_write_once_collision")
    return {"state":record["state"],"intake_ref":target.locator(key),
            "execution_authority_inferred":False}

def handle_control_message(root:Path, packet:dict[str,Any], registry:dict[str,Any],
                           *, node_state:Any|None=None, epoch:int|None=None)->dict[str,Any]:
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
        # An answer needs the epoch of the frame it answers. A CLOCK frame lends
        # none, so the status is refused NOT_SUPPLIED rather than sampled here.
        result["monitor_status"]=(resident_status(root,registry,epoch=epoch) if epoch is not None else
                                  {"disposition":"FAIL_CLOSED","failure_code":"HB_EPOCH_NOT_SUPPLIED",
                                   "detail":"the frame lent no epoch; no clock is read for the answer"})
    elif message_class=="ecosystem.work.request":
        result["work_intake"]=persist_work_request(root,packet,store=node_state)
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

# --- Organization receipts for every crossing this node consumes ---
#: The transition class a consumed federation crossing is recorded under.
CROSSING_CONSUMED_CLASS="ORGANIZATION_FEDERATION_CROSSING_CONSUMED"
_crossing_emitters:dict[str,Any]={}

def _own_module(name:str, relative:str)->Any:
    """Load a module from this kernel's own repository, never from a caller's root."""
    own=Path(__file__).resolve().parents[1]
    key=str(own/relative)
    if key not in _crossing_emitters:
        spec=importlib.util.spec_from_file_location(name,own/relative)
        if spec is None or not (own/relative).is_file():
            raise ValueError("organization_emitter_missing:"+relative)
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        _crossing_emitters[key]=module
    return _crossing_emitters[key]

def crossing_custody(repo_root:Path, *, repo_ledger_root:Path|None, org_ledger_root:Path|None)->dict[str,Any]:
    """The organization's own emitters and the ledger stores its materializer supplied.

    Resolved before anything is consumed. Every state transition occurring
    within the organization emits an organization receipt, and a consumed
    crossing is one: consuming it and recording nothing was the gap. The
    emitters are this kernel's own repository's, so a caller's root cannot
    bring its own; the dispatch root must be this kernel's organization; and
    both ledger locations are supplied, never derived. Any of those missing is
    a refusal before mutation.
    """
    if repo_ledger_root is None or org_ledger_root is None:
        raise ValueError("ledger_location_required_from_materializer")
    own=Path(__file__).resolve().parents[1]
    emitter=_own_module("crossing_repository_ledger",".stegverse/transition-ledger/emit.py")
    organization_ledger=_own_module("crossing_organization_ledger","resident-runtime/aggregate_repo_transition.py")
    organization=load_registry(repo_root)["organization"]
    if Path(repo_root).resolve()!=own or organization!=organization_ledger.C["organization"]:
        raise ValueError("dispatch_root_is_not_this_kernels_organization")
    return {"emitter":emitter,"organization_ledger":organization_ledger,
            "repository_store":emitter.ledger_store.open_store(emitter.ledger_store.parse_locator(repo_ledger_root)),
            "organization_store":emitter.ledger_store.open_store(emitter.ledger_store.parse_locator(org_ledger_root))}

#: The transition class a crossing this boundary refused is recorded under. Its
#: own class, so a crossing first refused and later admitted is two transitions
#: rather than an admission reported as the earlier refusal.
CROSSING_REFUSED_CLASS="ORGANIZATION_FEDERATION_CROSSING_REFUSED"
#: Refusals that will not change on a retry: the crossing is refused, recorded
#: and marked. Anything else is FAIL_CLOSED: recorded, left unmarked, retried.
DETERMINISTIC_REFUSALS=("PROCESS_BOUNDARY_INPUT_FAULT","unknown_service","node_standing_refused:","standing-",
                        "PROCESSING_SELECTED_ONLY_BY_ADMITTED_PROCESSING_CAPABILITY_AND_ROUTE_ID",
                        "manifest-declares-","declared-capability-","endpoint_adapter_not_installed",
                        "endpoint-adapter-not-installed","wrong_destination_org","wrong-destination-org")
#: Refusals of custody itself. Nothing can be recorded without it, so the whole
#: pass refuses before any mutation and the frames stay in the mesh.
CUSTODY_REFUSALS=("node_state_location_required_from_materializer",
                  "ledger_location_required_from_materializer",
                  "dispatch_root_is_not_this_kernels_organization")

def refusal_disposition(reason:str)->str:
    return "DENY" if any(marker in reason for marker in DETERMINISTIC_REFUSALS) else "FAIL_CLOSED"

def record_refusal(custody:dict[str,Any], item:dict[str,Any], reason:str, disposition:str, *,
                   service:dict[str,Any]|None, epoch:int|None, provenance:dict[str,Any]|None=None,
                   frame_reference:dict[str,Any]|None=None)->dict[str,Any]:
    """Append the repository and organization receipts for a refused crossing.

    The crossing arrived, so its disposition is a transition of this
    organization, recorded like an admission. Identified by the frame, so a
    FAIL_CLOSED retried on every pass is recorded once.
    """
    frame=item["frame"]
    name=node_store_module.frame_name(str(item["path"]))
    packet_id=frame.get("packet_id")
    predecessor="sha256:"+hashlib.sha256(canon({"frame_sha256":frame.get("frame_sha256")})).hexdigest()
    successor="sha256:"+hashlib.sha256(canon({"packet_id":packet_id,"disposition":disposition,
                                                "failed_predicate":reason})).hexdigest()
    evidence={"frame_name":name,"frame_sha256":frame.get("frame_sha256"),"packet_id":packet_id,
              "destination_org":frame.get("destination_org"),
              "service_id":(service or {}).get("service_id"),
              "boundary_role":(service or {}).get("boundary_role"),
              "disposition":disposition,"failed_predicate":reason,
              "retry_entrypoint":None if disposition=="DENY" else "org-kernel/kernel.py::consume_and_respond"}
    if frame_reference is not None:
        evidence["frame_reference"]=frame_reference
    emitter=custody["emitter"]; organization_ledger=custody["organization_ledger"]
    repository_receipt=emitter.append(
        "ORGANIZATION-FEDERATION-CROSSING-"+hashlib.sha256(name.encode()).hexdigest()[:16],
        CROSSING_REFUSED_CLASS,predecessor,successor,evidence,"NONE",hb_epoch=epoch,
        hb_provenance=provenance,provenance_head_store=custody["organization_store"] if provenance else None,
        store=custody["repository_store"],idempotent_on=("frame_sha256","packet_id"))
    organization_receipt=organization_ledger.append(
        repository_receipt,"REPO_STATE_PROPAGATION",predecessor,successor,
        {"operation":CROSSING_REFUSED_CLASS,"packet_id":packet_id,
         "disposition":disposition,"failed_predicate":reason,
         **({"frame_reference":frame_reference} if frame_reference is not None else {})},
        "NONE",hb_epoch=epoch,hb_provenance=provenance,
        store=custody["organization_store"],idempotent=True)
    return {"repository_receipt_sha256":repository_receipt["receipt_sha256"],
            "organization_receipt_sha256":organization_receipt["receipt_sha256"],
            "disposition":disposition}

def ingest_recorded(repo_root:Path, item:dict[str,Any], custody:dict[str,Any], registry:dict[str,Any], *,
                    mesh_root:Path|None, node_state:Any|None, epoch:int|None,
                    provenance:dict[str,Any]|None=None,
                    frame_reference:dict[str,Any]|None=None)->tuple[dict[str,Any],dict[str,Any]|None]:
    """Ingest one frame and record its disposition, admitted or refused.

    A refusal used to leave the consuming pass by exception, recorded nowhere
    and stopping every frame behind it. A capability-address crossing still
    raises: its receiving operation records its own refusal at both levels.
    """
    destination=(item["frame"].get("destination_service") or
                 ((recover_packet(item["frame"]).get("destination") or {}).get("service")))
    service=next((svc for svc in registry["services"] if svc.get("service_id")==destination),None)
    try:
        result=ingest_frame(repo_root,item["frame"],mesh_root=mesh_root,node_state=node_state)
    except ValueError as exc:
        reason=str(exc)
        if (any(marker in reason for marker in CUSTODY_REFUSALS)
                or (service or {}).get("boundary_role")==CAPABILITY_INGRESS_ROLE):
            # Marked, so a caller's per-frame guard can tell this designed refusal
            # (recorded by the receiving operation itself) from a frame defect.
            exc.capability_ingress_refusal=(service or {}).get("boundary_role")==CAPABILITY_INGRESS_ROLE
            raise
        disposition=refusal_disposition(reason)
        recorded=record_refusal(custody,item,reason,disposition,service=service,epoch=epoch,provenance=provenance,
                                frame_reference=frame_reference)
        refused={"status":"REFUSED","disposition":disposition,"failed_predicate":reason,
                 "packet_id":item["frame"].get("packet_id")}
        if "PROCESS_BOUNDARY_INPUT_FAULT" in reason:
            # The boundary refused the frame itself (exit 65): terminal, recorded and marked.
            refused.update({"failure_code":"FRAME_INGEST_FAILED","terminal":True,
                            "required_evidence_or_repair":"the sender republishes a frame the boundary admits",
                            "retry_entrypoint":"org-kernel/kernel.py::consume_and_respond",
                            "owning_existing_goal":custody["organization_ledger"].INTR_PROTOCOL_GOAL,
                            "next_attempt":"terminal for this frame; it is recorded DENY and not offered again"})
        return refused,recorded
    return result,record_crossing(custody,item,result,service=service,epoch=epoch,provenance=provenance,
                                  frame_reference=frame_reference)

def record_crossing(custody:dict[str,Any], item:dict[str,Any], result:dict[str,Any], *,
                    service:dict[str,Any]|None, epoch:int|None, provenance:dict[str,Any]|None=None,
                    frame_reference:dict[str,Any]|None=None)->dict[str,Any]|None:
    """Append the repository and organization receipts for one consumed crossing.

    Identified by the frame, which is content addressed, so consuming the same
    frame again returns the receipts already recorded rather than minting more.
    A crossing to a capability address is not recorded here: the receiving
    operation it resolves to records both levels itself.
    """
    if result.get("status")!="CONSUMED":
        return None
    if (service or {}).get("boundary_role")==CAPABILITY_INGRESS_ROLE:
        return None
    packet=result["packet"]; execution=result["execution_result"]; frame=item["frame"]
    name=node_store_module.frame_name(str(item["path"]))
    terminal=(execution.get("reconstruction") or {}).get("terminal_receipt_id")
    predecessor="sha256:"+hashlib.sha256(canon(packet.get("payload"))).hexdigest()
    successor="sha256:"+hashlib.sha256(canon({"packet_id":packet["packet_id"],"terminal_receipt_id":terminal})).hexdigest()
    evidence={"frame_name":name,"frame_sha256":frame.get("frame_sha256"),"packet_id":packet["packet_id"],
              "origin":packet["origin"],"destination":packet["destination"],
              "service_id":execution.get("service_id"),
              "boundary_role":(service or {}).get("boundary_role"),
              "message_class":(packet.get("payload") or {}).get("message_class"),
              "processing_selection":execution.get("processing_selection"),
              "terminal_receipt_id":terminal,"disposition":"ALLOW"}
    if frame_reference is not None:
        evidence["frame_reference"]=frame_reference
    emitter=custody["emitter"]; organization_ledger=custody["organization_ledger"]
    repository_receipt=emitter.append(
        "ORGANIZATION-FEDERATION-CROSSING-"+hashlib.sha256(name.encode()).hexdigest()[:16],
        CROSSING_CONSUMED_CLASS,predecessor,successor,evidence,"NONE",hb_epoch=epoch,
        hb_provenance=provenance,provenance_head_store=custody["organization_store"] if provenance else None,
        store=custody["repository_store"],idempotent_on=("frame_sha256","packet_id"))
    organization_receipt=organization_ledger.append(
        repository_receipt,"REPO_STATE_PROPAGATION",predecessor,successor,
        {"operation":CROSSING_CONSUMED_CLASS,"packet_id":packet["packet_id"],
         "service_id":execution.get("service_id"),"disposition":"ALLOW",
         **({"frame_reference":frame_reference} if frame_reference is not None else {})},
        "NONE",hb_epoch=epoch,hb_provenance=provenance,
        store=custody["organization_store"],idempotent=True)
    return {"repository_receipt_sha256":repository_receipt["receipt_sha256"],
            "organization_receipt_sha256":organization_receipt["receipt_sha256"]}

def consume_and_respond(repo_root:Path, *, mesh_root:Path|None=None, node_state_root:Path|None=None,
                        repo_ledger_root:Path|None=None, org_ledger_root:Path|None=None,
                        seen:set[str]|None=None, now_ns:int|None=None,
                        hb_epoch:Any=None, hb_epoch_source:dict[str,Any]|None=None)->list[dict[str,Any]]:
    # A caller-sampled now_ns never replaces the answered frame's epoch: it is
    # refused HB_EPOCH_INVALID before any frame is consumed or answered (#236).
    if now_ns is not None: raise HbEpochSampledClock()
    # `hb_epoch` is the cycle's own supplied epoch (F1). When given, this
    # organization's crossing receipts are this organization's transition and are
    # stamped with it; the consumed frame's epoch is recorded only as inbound
    # provenance, in evidence.frame_reference, never as the receipt epoch. A
    # route with no such resolution (an answer frame, a governance closure) whose
    # frame epoch differs refuses HB_EPOCH_CONFLICT and writes nothing for it.
    if hb_epoch is not None:
        failure=supplied_epoch_failure(hb_epoch)
        if failure is not None:
            raise ValueError("cycle_hb_epoch_invalid: "+failure[0]+": "+failure[1])
        hb_epoch=int(str(hb_epoch))
    # Consumption markers and work intake are this node's own state, at the
    # location its materializer supplied. Resolved first, so a node without one
    # consumes nothing rather than consuming and then failing to remember it.
    node_state=addressed_node_state_store(node_state_root)
    custody=crossing_custody(repo_root,repo_ledger_root=repo_ledger_root,org_ledger_root=org_ledger_root)
    registry=load_registry(repo_root)
    organization=registry["organization"]
    durable_seen=federation_seen_frame_names(repo_root,store=node_state)
    effective_seen=set(seen or set())|durable_seen
    out=[]
    unreadable=[]
    frames=scan_addressed_frames(organization,root=mesh_root,seen=effective_seen,unreadable=unreadable)
    # An entry that is not a readable frame is quarantined by its file name with
    # the six fields, and the scan goes on to the frames behind it (B-P36p).
    for entry in unreadable:
        refused=unreadable_entry_refusal(entry["reason"],custody)
        marker=quarantine_federation_frame(entry["path"],{},refused,store=node_state)
        out.append({"path":entry["path"],"result":{"status":"REFUSED","disposition":"FAIL_CLOSED",
                    "failed_predicate":refused["failed_predicate"],"failure_code":refused["failure_code"],
                    "packet_id":None,"quarantined":True},
                    "response_publication":None,"organization_record":None,"seen_marker":str(marker)})
    for item in frames:
        # An error in this one frame -- its heartbeat reference, its digests, or
        # an adapter ingesting it -- is its own six-field refusal and a terminal
        # quarantine, and the cycle goes on to the next frame (B-P36o). A ledger
        # writer's refusal (SystemExit) is not the frame's fault: it propagates,
        # the frame stays unmarked, and the next pass completes it. Node-level
        # custody refusals still stop the cycle: no frame can proceed.
        try:
            # A frame whose epoch is not supplied (or whose CARRIED claim does not
            # verify) is refused before it is recovered or consumed, and made
            # terminal: quarantined, never offered again, nothing else written.
            kind,provenance,refused=(frame_epoch_class(item["frame"],custody) if now_ns is None
                                     else ("SUPPLIED",None,None))
            if refused is None and kind=="CARRIED" and not ACCEPTS_CARRIED_CROSSINGS:
                refused=carried_not_accepted(custody)
            if refused is not None:
                marker=quarantine_federation_frame(item["path"],item["frame"],refused,store=node_state)
                out.append({"path":item["path"],"result":{"status":"REFUSED","disposition":"FAIL_CLOSED",
                            "failed_predicate":refused["failed_predicate"],"failure_code":refused["failure_code"],
                            "packet_id":item["frame"].get("packet_id"),"quarantined":True},
                            "response_publication":None,"organization_record":None,"seen_marker":str(marker)})
                continue
            packet=recover_packet(item["frame"])
            # F-REPUB keying: a request packet id is bound to its first content. A
            # later frame reusing it with different content is refused here, before
            # anything is ledgered or answered, and is never handed the earlier answer.
            collided=request_id_collision(node_state,packet,item["frame"],custody)
            if collided is not None:
                marker=quarantine_federation_frame(item["path"],item["frame"],collided,store=node_state)
                out.append({"path":item["path"],"result":{"status":"REFUSED","disposition":"FAIL_CLOSED",
                            "failed_predicate":collided["failed_predicate"],"failure_code":collided["failure_code"],
                            "packet_id":packet["packet_id"],"quarantined":True},
                            "response_publication":None,"organization_record":None,"seen_marker":str(marker)})
                continue
            # An answer is stamped with the epoch of the frame it answers, which
            # recovery has already validated. Consuming the same frame again then
            # builds the same answer frame, and publishing it is a write-once no-op
            # rather than a second answer stamped by whatever clock this pass read.
            frame_epoch=None if now_ns is not None else (item["frame"].get("heartbeat_reference") or {}).get("epoch")
            epoch,record_provenance,frame_reference,answer_epoch=resolve_cycle_epoch(
                hb_epoch,frame_epoch,kind,provenance,item["frame"])
            if frame_reference is not None and hb_epoch_source is not None:
                # Where the cycle's own epoch came from (a committed request on a push run).
                frame_reference={**frame_reference,"cycle_epoch_source":dict(hb_epoch_source)}
            payload=packet.get("payload") or {}
            message_class=payload.get("message_class")
            service=next((svc for svc in registry["services"] if svc.get("service_id")==packet["destination"]["service"]),None)
            if kind=="CLOCK":
                # NARROW S1: consumed, lending no epoch. Dispatch runs without one;
                # recording the crossing and publishing an answer need one, so both
                # refuse NOT_SUPPLIED and nothing is written for them. The frame is
                # marked seen, so it is terminal and never blocks a later cycle.
                try:
                    result=ingest_frame(repo_root,item["frame"],mesh_root=mesh_root,node_state=node_state)
                except ValueError as exc:
                    if any(marker in str(exc) for marker in CUSTODY_REFUSALS):
                        raise
                    result={"status":"REFUSED","disposition":"FAIL_CLOSED","failed_predicate":str(exc),
                            "packet_id":item["frame"].get("packet_id")}
                result={**result,"epoch_lent":None}
                marker=mark_federation_frame_seen(repo_root,item["path"],item["frame"],result,store=node_state)
                out.append({"path":item["path"],"result":result,"response_publication":None,
                            "organization_record":not_supplied_record(custody),"seen_marker":str(marker)})
                continue
            # Recorded before anything leaves this node: no answer is published and
            # no consumption marker written for a crossing the organization has not
            # recorded. A failed append leaves the frame unmarked, so the next pass
            # offers it again and the idempotent append completes it.
            result,recorded=ingest_recorded(repo_root,item,custody,registry,mesh_root=mesh_root,
                                            node_state=node_state,epoch=epoch,provenance=record_provenance,
                                            frame_reference=frame_reference)
            if result.get("status")=="REFUSED" and result["disposition"]!="DENY":
                # FAIL_CLOSED: recorded, not marked, offered again on the next pass.
                out.append({"path":item["path"],"result":result,"response_publication":None,
                            "organization_record":recorded,"seen_marker":None})
                continue
            response_publication=None
            response=None
            if result.get("status")=="CONSUMED" and message_class in RESPONDED_REQUEST_CLASSES:
                response=build_control_response(packet,result["execution_result"])
            elif result.get("status")=="CONSUMED" and not payload.get("response_to_packet_id"):
                if service and service.get("endpoint_adapter"):
                    response=build_endpoint_response(packet,result["execution_result"])
            if response is not None:
                if frame_reference is not None:
                    # The answer names the request frame it answers, as inbound provenance.
                    response={**response,"payload":{**(response.get("payload") or {}),
                                                    "request_frame_reference":frame_reference}}
                response_publication=publish_packet(response,root=mesh_root,now_ns=now_ns,epoch=answer_epoch,
                                                    provenance=provenance if frame_reference is None else None)
            marker=mark_federation_frame_seen(repo_root,item["path"],item["frame"],result,store=node_state)
            out.append({"path":item["path"],"result":result,"response_publication":response_publication,
                        "organization_record":recorded,"seen_marker":str(marker)})
        except Exception as exc:
            # Total (F-TYPE): any exception is this frame's, except custody refusals
            # (no frame can proceed: the pass stops) and a fault writing this node's
            # own state (F-TRANSIENT-RT): an OSError, a lost compare-and-swap, a store
            # collision. Those are non-terminal: no marker, the frame stays pending,
            # and the idempotent appends consume it exactly once on the next pass. A
            # ledger writer's refusal (SystemExit) is not an Exception and propagates.
            if isinstance(exc, ValueError) and any(marker in str(exc) for marker in CUSTODY_REFUSALS):
                raise
            if writer_fault(exc):
                out.append({"path":item["path"],"result":{**dispatch_io_failure(exc,custody),
                            "status":"PENDING","packet_id":item["frame"].get("packet_id")},
                            "response_publication":None,"organization_record":None,"seen_marker":None})
                continue
            refused=frame_ingest_refusal(exc,custody)
            marker=quarantine_federation_frame(item["path"],item["frame"],refused,store=node_state)
            out.append({"path":item["path"],"result":{"status":"REFUSED","disposition":"FAIL_CLOSED",
                        "failed_predicate":refused["failed_predicate"],"failure_code":refused["failure_code"],
                        "packet_id":item["frame"].get("packet_id"),"quarantined":True},
                        "response_publication":None,"organization_record":None,"seen_marker":str(marker)})
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
                                     now_ns:int|None=None, epoch:int|None=None)->dict[str,Any]:
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
      now_ns=now_ns,epoch=epoch
    )


# --- Federation replay/dedup v1.3.1 additions ---
def federation_seen_frame_names(repo_root:Path, *, store:Any|None=None)->set[str]:
    """Which frames this node has already consumed.

    The marker records the frame's name rather than its key, so a node holding
    markers written before state was addressed does not re-consume the mesh.
    """
    target=required_node_state(store)
    names=set()
    for key in target.list_prefix(node_store_module.NODE_SEEN_PREFIX):
        try:
            value=target.get(key)
        except ValueError:
            continue
        if isinstance(value,dict) and isinstance(value.get("frame_name"),str):
            names.add(value["frame_name"])
    return names

FRAME_REFUSED_QUARANTINED="FRAME_REFUSED_QUARANTINED"

def frame_epoch_class(frame:dict[str,Any], custody:dict[str,Any])->tuple[str|None,dict[str,Any]|None,dict[str,Any]|None]:
    """Classify a consumed frame's epoch: (kind, provenance, refusal). No clock is read.

    kind is SUPPLIED (derived_from_clock false), CARRIED (false plus a source
    and head_receipt_sha that verify against this organization's current
    supplied ledger head at the same epoch), or CLOCK (flagged true, or a bare
    clock sample with no flag). A CLOCK frame is consumed but lends no epoch
    (NARROW S1): every route that needs one refuses HB_EPOCH_NOT_SUPPLIED.
    Refused -- (None, None, refusal) -- are an UNMARKED reference (no flag, no
    sample), an unverified CARRIED claim (never stripped to read as SUPPLIED),
    a flag-false reference that also carries a sample, and an invalid epoch.
    """
    ledger=custody["organization_ledger"]
    ref=frame.get("heartbeat_reference")
    epoch=ref.get("epoch") if isinstance(ref,dict) else None
    # The epoch value is checked first: a malformed or sub-anchor epoch is
    # HB_EPOCH_INVALID (absent is NOT_SUPPLIED) even on a clock frame (F-S1a),
    # and is quarantined, never raised.
    failure=supplied_epoch_failure(epoch) if isinstance(ref,dict) else supplied_epoch_failure(epoch,ref)
    predicate=ledger.HB_EPOCH_PREDICATE
    # Then the reference's coherence with that epoch, explicitly and on every
    # class, so a CLOCK frame is classified here and recover_packet never raises
    # on its reference before the CLOCK branch (B-P36o).
    if failure is None:
        incoherent=heartbeat_incoherence(ref)
        if incoherent is not None:
            failure,predicate=("HB_REFERENCE_INVALID",incoherent),"FRAME_HEARTBEAT_REFERENCE_IS_COHERENT"
    clock=failure is None and (ref.get("derived_from_clock") is True
                               or ("derived_from_clock" not in ref and "sampled_unix_ns" in ref))
    provenance=None
    if failure is None and ("source" in ref or "head_receipt_sha" in ref):
        # A self-asserted CARRIED claim is checked before CLOCK is returned (F11):
        # only a supplied epoch can be carried, so a claim on a clock reference is
        # refused, and a forged one is never consumed as a quiet CLOCK frame.
        provenance={k:ref.get(k) for k in CARRIED_PROVENANCE_KEYS}
        failure=(("CARRIED_PROVENANCE_UNVERIFIED","a CARRIED claim on a clock reference; only a supplied "
                  "epoch can be carried") if clock
                 else ledger.carried_provenance_failure(provenance,epoch,custody["organization_store"]))
    elif clock:
        return "CLOCK",None,None
    failure=failure or supplied_epoch_failure(epoch,ref)
    if failure is None:
        return ("CARRIED" if provenance else "SUPPLIED"),provenance,None
    code,detail=failure
    return None,None,{"disposition":"FAIL_CLOSED","failure_code":code,
            "failed_predicate":predicate,"detail":detail,
            "required_evidence_or_repair":("a frame carries a supplied epoch: derived_from_clock false, no "
                                           "sampled_unix_ns, ASCII digits >= "+str(HB_ANCHOR_EPOCH)
                                           +", generation and heartbeat_id equal to it; a CARRIED claim names "
                                           "this organization's current supplied head"),
            "retry_entrypoint":"org-kernel/kernel.py::consume_and_respond",
            "owning_existing_goal":ledger.INTR_PROTOCOL_GOAL,
            "next_attempt":"the sender republishes the crossing with a supplied epoch; this frame is quarantined "
                           "and not offered again"}

def heartbeat_incoherence(ref:dict[str,Any])->str|None:
    """Why a reference with a valid epoch is incoherent with it, or None. Nothing raises."""
    epoch=int(str(ref["epoch"]))
    if ref.get("generation")!=epoch: return "heartbeat_generation_mismatch: generation "+repr(ref.get("generation"))+" is not epoch "+str(epoch)
    if ref.get("heartbeat_id")!=f"HB:{epoch}": return "heartbeat_id_mismatch: heartbeat_id "+repr(ref.get("heartbeat_id"))+" is not HB:"+str(epoch)
    if ref.get("frequency_hz")!=HB_HZ: return "heartbeat_frequency_mismatch"
    if ref.get("progression_dependency")!="OSCILLATOR_ONLY": return "heartbeat_progression_not_oscillator"
    return None

HB_REFERENCE_ERRORS=("heartbeat_generation_mismatch","heartbeat_id_mismatch","heartbeat_frequency_mismatch",
                     "heartbeat_progression_not_oscillator","heartbeat_reference_invalid")
FRAME_INTEGRITY_ERRORS=("carrier_frame_hash_mismatch","packet_hash_mismatch","packet_id_mismatch",
                        "destination_org_mismatch")

def frame_ingest_refusal(exc:BaseException, custody:dict[str,Any])->dict[str,Any]:
    """Any error ingesting one frame, as a six-field refusal; the cycle continues (B-P36o).

    A frame whose heartbeat reference is incoherent, whose digests do not
    hold, or that any adapter cannot ingest used to raise out of the
    consuming pass, so every valid frame behind it waited forever.
    """
    ledger=custody["organization_ledger"]
    reason=str(exc)
    refusal=getattr(exc,"refusal",None)
    if isinstance(refusal,dict) and refusal.get("failure_code"):
        code,predicate,detail=refusal["failure_code"],refusal.get("failed_predicate") or type(exc).__name__,refusal.get("detail") or reason
    elif any(marker in reason for marker in HB_REFERENCE_ERRORS):
        code,predicate,detail="HB_REFERENCE_INVALID","FRAME_HEARTBEAT_REFERENCE_IS_COHERENT",reason
    elif "heartbeat_epoch_invalid" in reason:
        code,predicate,detail="HB_EPOCH_INVALID",ledger.HB_EPOCH_PREDICATE,reason
    elif any(marker in reason for marker in FRAME_INTEGRITY_ERRORS):
        code,predicate,detail="FRAME_INTEGRITY_INVALID","FRAME_DIGESTS_HOLD",reason
    else:
        code,predicate,detail="FRAME_INGEST_FAILED",type(exc).__name__,reason[:240]
    return {"disposition":"FAIL_CLOSED","failure_code":code,"failed_predicate":predicate,"detail":detail,
            "required_evidence_or_repair":"the sender republishes a coherent frame with a supplied epoch",
            "retry_entrypoint":"org-kernel/kernel.py::consume_and_respond",
            "owning_existing_goal":ledger.INTR_PROTOCOL_GOAL,
            "next_attempt":"on a republished frame; this one is quarantined and not offered again"}

EPOCH_RESOLUTION="SUPPLIED_CYCLE_EPOCH_STAMPS_THIS_ORGANIZATION"
#: This destination does not accept a carried crossing epoch (B-P36m, 09:00Z
#: alternative): a CARRIED frame is refused CARRIED_NOT_ACCEPTED_BY_DESTINATION,
#: whether or not the cycle supplies its own epoch. Its claim is still verified
#: first, so a forged one is CARRIED_PROVENANCE_UNVERIFIED.
ACCEPTS_CARRIED_CROSSINGS=False

def carried_not_accepted(custody:dict[str,Any])->dict[str,Any]:
    """The six-field refusal of a CARRIED frame epoch: this destination does not accept one."""
    ledger=custody["organization_ledger"]
    return {"disposition":"FAIL_CLOSED","failure_code":"CARRIED_NOT_ACCEPTED_BY_DESTINATION",
            "failed_predicate":ledger.HB_EPOCH_PREDICATE,
            "detail":"accepts_carried_crossings is false: this destination accepts a crossing only at a supplied "
                     "epoch, never a carried one",
            "required_evidence_or_repair":"the sender republishes the crossing at a supplied epoch",
            "retry_entrypoint":"resident-runtime/federation_cycle.py (--hb-epoch)",
            "owning_existing_goal":ledger.INTR_PROTOCOL_GOAL,
            "next_attempt":"the sender republishes the crossing; this frame is quarantined and not offered again"}

def resolve_cycle_epoch(hb_epoch:int|None, frame_epoch:Any, kind:str|None, provenance:dict[str,Any]|None,
                        frame:dict[str,Any])->tuple[Any,dict[str,Any]|None,dict[str,Any]|None,Any]:
    """(receipt epoch, receipt provenance, frame_reference, answer epoch). No clock is read.

    Without a cycle epoch the frame's supplied epoch is the only one, as before.
    With one (F1), everything this organization writes for the crossing -- its
    receipts and its answer -- is its own transition and takes the cycle's
    epoch, with the frame's kept as inbound provenance (frame_reference), so a
    consumed request is always answered.
    """
    if hb_epoch is None:
        return frame_epoch,provenance,None,frame_epoch
    reference={"epoch":frame_epoch,"epoch_class":kind,"frame_sha256":frame.get("frame_sha256"),
               "resolution":EPOCH_RESOLUTION,**(provenance or {})}
    return hb_epoch,None,reference,hb_epoch

REQUEST_ID_PREFIX="federation/request-ids.d/"

def request_id_collision(node_state:Any, packet:dict[str,Any], frame:dict[str,Any],
                         custody:dict[str,Any])->dict[str,Any]|None:
    """Bind a request packet id to its first content in this node's state; the six-field collision, or None.

    The same packet (same packet_sha256) at any epoch is the same request. A
    different packet under an id already bound is RESPONSE_ID_COLLISION.
    """
    key=REQUEST_ID_PREFIX+hashlib.sha256(str(packet["packet_id"]).encode()).hexdigest()+".json"
    binding={"packet_id":packet["packet_id"],"packet_sha256":frame.get("packet_sha256")}
    bound=node_state.get(key)
    if bound is None:
        try:
            node_state.put_once(key,binding)
            return None
        except node_store_module.WriteOnceCollision:
            bound=node_state.get(key)
    if bound==binding:
        return None
    ledger=custody["organization_ledger"]
    return {"disposition":"FAIL_CLOSED","failure_code":"RESPONSE_ID_COLLISION",
            "failed_predicate":"REQUEST_PACKET_ID_BINDS_ITS_FIRST_CONTENT",
            "detail":"packet "+str(packet["packet_id"])+" is bound to "+str((bound or {}).get("packet_sha256"))
                     +"; this frame carries "+str(frame.get("packet_sha256")),
            "required_evidence_or_repair":"a different request carries its own packet id",
            "retry_entrypoint":"org-kernel/kernel.py::consume_and_respond",
            "owning_existing_goal":ledger.INTR_PROTOCOL_GOAL,
            "next_attempt":"the sender republishes under a new packet id; this frame is quarantined, nothing was "
                           "ledgered or answered"}

WRITER_FAULT_MARKERS=("collision","contention","lost_comparison")

def writer_fault(exc:BaseException)->bool:
    """True for a fault writing this node's own state, which never makes a frame terminal.

    RecursionError subclasses RuntimeError but is raised by parsing content too
    deep to read (F-SCAN-RECURSION): that is the frame's defect, never a writer fault.
    """
    if isinstance(exc,(RecursionError,MemoryError)):
        return False
    if isinstance(exc,(OSError,RuntimeError,node_store_module.WriteOnceCollision)):
        return True
    return isinstance(exc,ValueError) and any(m in str(exc).lower() for m in WRITER_FAULT_MARKERS)

def dispatch_io_failure(exc:BaseException, custody:dict[str,Any])->dict[str,Any]:
    """The non-terminal six-field FRAME_DISPATCH_IO_FAILED record: no marker, the frame stays pending."""
    ledger=custody["organization_ledger"]
    return {"disposition":"FAIL_CLOSED","failure_code":"FRAME_DISPATCH_IO_FAILED","terminal":False,
            "failed_predicate":type(exc).__name__,"detail":str(exc)[:240],
            "required_evidence_or_repair":"this node's own state (ledger, node state, mesh) accepts the write",
            "retry_entrypoint":"org-kernel/kernel.py::consume_and_respond",
            "owning_existing_goal":ledger.INTR_PROTOCOL_GOAL,
            "next_attempt":"the next pass offers the frame again and the idempotent appends consume it exactly once",
            "consequence_committed":False}

def unreadable_entry_refusal(reason:str, custody:dict[str,Any])->dict[str,Any]:
    """The six-field FRAME_INGEST_FAILED refusal of a frames.d entry that is not a readable frame."""
    ledger=custody["organization_ledger"]
    return {"disposition":"FAIL_CLOSED","failure_code":"FRAME_INGEST_FAILED",
            "failed_predicate":"FRAME_ENTRY_IS_A_READABLE_JSON_OBJECT","detail":reason[:240],
            "required_evidence_or_repair":("the sender republishes the frame as a UTF-8 JSON object of at most "
                                           +str(FRAME_ENTRY_LIMIT_BYTES)+" bytes"),
            "retry_entrypoint":"org-kernel/kernel.py::consume_and_respond",
            "owning_existing_goal":ledger.INTR_PROTOCOL_GOAL,
            "next_attempt":"on a republished frame; this entry is quarantined by its file name and not offered again"}

def not_supplied_record(custody:dict[str,Any])->dict[str,Any]:
    """The six-field NOT_SUPPLIED refusal of recording a CLOCK frame's crossing; nothing is written."""
    ledger=custody["organization_ledger"]
    return {"disposition":"FAIL_CLOSED","failure_code":"HB_EPOCH_NOT_SUPPLIED",
            "failed_predicate":ledger.HB_EPOCH_PREDICATE,
            "detail":"a clock-flagged frame lends no epoch, and recording its crossing needs a supplied one",
            "required_evidence_or_repair":"the sender republishes the crossing with a supplied epoch",
            "retry_entrypoint":"org-kernel/kernel.py::consume_and_respond",
            "owning_existing_goal":ledger.INTR_PROTOCOL_GOAL,
            "next_attempt":"on a republished crossing with a supplied epoch (CLOCK_FLAGGED_FRAMES_CONSUMED_PENDING_WU_B13); "
                           "nothing was recorded","consequence_committed":False}

def quarantine_federation_frame(frame_path:str, frame:dict[str,Any], refusal:dict[str,Any], *,
                                store:Any|None=None)->Path:
    """Mark a refused frame terminal: a six-field quarantine seen-marker, once. No clock is read.

    It is the frame's seen-marker, so the frame is never offered again and
    never blocks a later cycle. Nothing else is written for it: no receipt
    can be stamped without a supplied epoch.
    """
    target=required_node_state(store)
    frame_name=node_store_module.frame_name(str(frame_path))
    marker={"schema_version":"stegverse.federation-frame-consumption.v1",
            "frame_name":frame_name,"frame_sha256":frame.get("frame_sha256"),
            "packet_id":frame.get("packet_id"),"destination_org":frame.get("destination_org"),
            "status":"REFUSED","quarantined":True,
            "failure_code":FRAME_REFUSED_QUARANTINED,"refusal_failure_code":refusal["failure_code"],
            "failed_predicate":refusal["failed_predicate"],"detail":refusal["detail"],
            "required_evidence_or_repair":refusal["required_evidence_or_repair"],
            "retry_entrypoint":refusal["retry_entrypoint"],"owning_existing_goal":refusal["owning_existing_goal"],
            "next_attempt":refusal["next_attempt"],"authority_effect":"NONE_CARRIER_ONLY"}
    key=node_store_module.seen_key(frame_name)
    try:
        target.put_once(key,marker)
    except node_store_module.WriteOnceCollision:
        raise ValueError("federation_seen_marker_collision")
    return Path(target.locator(key))

def mark_federation_frame_seen(repo_root:Path, frame_path:str, frame:dict[str,Any], result:dict[str,Any],
                               *, store:Any|None=None)->Path:
    """Record that this node consumed a frame, once and atomically."""
    target=required_node_state(store)
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
