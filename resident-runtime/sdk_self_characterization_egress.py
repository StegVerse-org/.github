#!/usr/bin/env python3
"""Bind a manifest-declared external-organization interaction to StegVerse-org egress.

This surface used to carry exactly one question. Seven module-level constants --
`EXPERIMENT_ID`, `OPERATION`, `OBJECTIVE`, `SOURCE`, `TARGET_ENTITY`,
`TARGET_ORG`, `TARGET_SERVICE` -- plus a hardcoded transition reference and
packet-id prefix meant the egress runtime *was* the StegVerse-002
self-characterization query. A second question could not be asked without
editing this file, which is processing selected by something other than the
admitted manifest: the defect
`SDK-GENERIC-MANIFEST-ECOSYSTEM-INVARIANT-005` exists to remove.

The manifest contract is owned by `StegVerse-org/StegVerse-SDK`, so the
generalization landed there first. Its
`stegverse.external_organization.interaction_manifest.v2` declares everything
this runtime used to supply: the far side's organization and service, the
transition referenced, the packet-id prefix, and the generation's place in its
chain. Writing those requirements here first would have defined a second
contract on an SDK-owned schema -- the parallel authority the task's own text
prohibits -- so this module validates what the SDK declares and refuses what it
cannot resolve. It does not re-implement the owner's semantics; it refuses to
consume what it was not given.

Two contracts are consumed, selected by the schema the manifest declares, and
neither defaults into the other:

* `…interaction_manifest.v2` -- the generic contract. Every identity is read
  from the manifest. An omitted declaration is refused, never completed against
  a constant.
* `…interaction_manifest.v1` -- the finished first generation. Its four
  undeclared values are projected here, explicitly and only for that schema,
  because the interaction is complete and its recorded evidence must stay
  re-derivable. It is not a degraded form of v2 and is never widened into one.

Each generation remains a frozen one-shot. Nothing here holds a standing query:
a standing coupling is what the least-stable-micronode policy denies, and the
stability preference runs toward `ONE_SHOT_OPERATION`. What replaces editing
this runtime is augment-and-repeat -- review a generation's result, augment the
manifest, freeze it as the next generation, which declares the predecessor
digest, the digest of the result that was reviewed, and the heartbeat epoch at
which it was observed. Order comes from that oscillator count, not a clock.

Nothing here grants authority. The request carries `authority_transfer: false`
and resolves its effect from applicable transition elements.
"""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, os, re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("org_kernel",ROOT/"org-kernel"/"kernel.py")
K=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(K)
GWSPEC=importlib.util.spec_from_file_location("federation_gateway_transport",ROOT/"resident-runtime"/"federation_gateway_transport.py")
GW=importlib.util.module_from_spec(GWSPEC); GWSPEC.loader.exec_module(GW)

GENERIC_MANIFEST="stegverse.external_organization.interaction_manifest.v2"
FIRST_GENERATION_MANIFEST="stegverse.external_organization.interaction_manifest.v1"

# Properties of the interaction contract itself rather than of any one
# interaction, so these stay fixed: a request that mints its own InTr receipt or
# claims delivery is not this contract regardless of what it declares.
REQUEST_ENVELOPE={
  "schema_version":"stegverse.external_organization.interlock_request.v1",
  "request_class":"EXTERNAL_ORGANIZATION_INTERACTION",
  "transport":"InTr",
  "authority_transfer":False,
  "sdk_mints_intr_receipt":False,
  "sdk_claims_delivery":False,
  "authority_effect_resolution":"DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS",
}

NON_PRESCRIPTIVE=("prescribe_self_ontology","prescribe_formalism","prescribe_transition_elements",
                  "prescribe_external_followup","prescribe_admissible_existence_connection")
HEX64=re.compile(r"^[0-9a-f]{64}$")

# The four values the finished first generation never declared. This projection
# exists for one schema and one completed interaction. It is not a default: a v2
# manifest that omits any of them is refused, and no other schema reaches here.
FIRST_GENERATION_PROJECTION={
  "target_organization":"StegVerse-002",
  "target_service":"stegverse-002.self-characterization",
  "transition_reference":"sv002.self-characterization.request.v0.2",
  "packet_id_prefix":"sv002-self-char-",
}

def canon(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def digest(v): return hashlib.sha256(canon(v)).hexdigest()

def declared(mapping,key,where):
    """Read a declared non-empty string, or refuse. Nothing is defaulted."""
    value=mapping.get(key) if isinstance(mapping,dict) else None
    if not isinstance(value,str) or not value.strip():
        raise ValueError(f"{where}.{key} must be declared")
    return value.strip()

def validate_chain(manifest):
    """Verify this generation's declared place in its chain of predecessors.

    The owner computes the binding; this refuses to consume one that does not
    hold. `predecessor` must be present as a key either way -- an absent key is
    an unstated chain position, and reading it as a first generation would be
    the defaulting this module refuses everywhere else.
    """
    generation=manifest.get("generation")
    if not isinstance(generation,int) or isinstance(generation,bool) or generation<1:
        raise ValueError("manifest.generation must be an integer of at least 1")
    if "predecessor" not in manifest:
        raise ValueError("manifest.predecessor must be declared, as null for a first generation")
    predecessor=manifest["predecessor"]
    if generation==1:
        if predecessor is not None:
            raise ValueError("a first generation declares no predecessor")
        return
    if not isinstance(predecessor,dict):
        raise ValueError("a generation beyond the first declares the predecessor it continues")
    if predecessor.get("generation")!=generation-1:
        raise ValueError("manifest.predecessor.generation must be this generation less one")
    for key in ("manifest_sha256","result_sha256"):
        value=predecessor.get(key)
        if not isinstance(value,str) or not HEX64.match(value):
            raise ValueError(f"manifest.predecessor.{key} must be a sha256 digest")
    epoch=predecessor.get("heartbeat_epoch")
    if not isinstance(epoch,int) or isinstance(epoch,bool) or epoch<K.HB_ANCHOR_EPOCH:
        # Order is an oscillator count, never a clock reading, so an epoch below
        # this heartbeat's anchor is not an earlier observation -- it is no
        # observation this heartbeat can place.
        raise ValueError("manifest.predecessor.heartbeat_epoch must be an HB epoch at or after the anchor")

def transport_declaration(manifest):
    """Resolve the far side and transport naming this manifest's schema declares.

    The generic schema declares all four. The finished first generation declared
    none of them, so they are projected for that schema alone and the result
    says which contract it came from, because a caller reading this cannot
    otherwise tell a declaration from a projection.
    """
    schema=manifest.get("schema")
    if schema==GENERIC_MANIFEST:
        target=manifest.get("target")
        if not isinstance(target,dict): raise ValueError("manifest.target must be declared")
        return {"contract":"MANIFEST_DECLARED",
                "target_organization":declared(target,"organization","manifest.target"),
                "target_service":declared(target,"service","manifest.target"),
                "transition_reference":declared(manifest,"transition_reference","manifest"),
                "packet_id_prefix":declared(manifest,"packet_id_prefix","manifest")}
    if schema==FIRST_GENERATION_MANIFEST:
        return {"contract":"FIRST_GENERATION_PROJECTED",**FIRST_GENERATION_PROJECTION}
    raise ValueError(f"unsupported manifest schema: {schema!r}")

def validate_request(req):
    for k,v in REQUEST_ENVELOPE.items():
        if req.get(k)!=v: raise ValueError(f"{k} mismatch")
    if not str(req.get("authority_ref") or "").strip(): raise ValueError("authority_ref required")
    payload=req.get("payload") or {}; manifest=payload.get("manifest")
    if not isinstance(manifest,dict): raise ValueError("manifest required")

    for key in ("manifest_id","experiment_id","operation","objective"):
        declared(manifest,key,"manifest")
    source=manifest.get("source_organization")
    if not isinstance(source,dict): raise ValueError("manifest.source_organization must be declared")
    declared(source,"organization_id","manifest.source_organization")
    target=manifest.get("target")
    if not isinstance(target,dict): raise ValueError("manifest.target must be declared")
    declared(target,"entity_id","manifest.target")

    # The operation the request names and the operation the manifest declares
    # are the same operation, or the request is carrying something the manifest
    # did not ask for.
    if req.get("operation")!=manifest["operation"]:
        raise ValueError("request operation does not match the manifest declaration")

    policy=manifest.get("knowledge_policy") or {}
    for key in NON_PRESCRIPTIVE:
        if policy.get(key) is not False: raise ValueError("knowledge policy became prescriptive")

    transport=transport_declaration(manifest)
    if transport["contract"]=="MANIFEST_DECLARED":
        validate_chain(manifest)

    body=dict(manifest); claimed=str(body.pop("manifest_sha256",""))
    if claimed!=digest(body): raise ValueError("manifest hash mismatch")

    bindings=req.get("bindings") or {}
    required={
      "experiment_id":manifest["experiment_id"],
      "source_organization_id":source["organization_id"],
      "target_entity_id":target["entity_id"],
      "manifest_id":manifest["manifest_id"],
      "manifest_sha256":manifest["manifest_sha256"],
    }
    for k,v in required.items():
        if bindings.get(k)!=v: raise ValueError(f"bindings.{k} mismatch")
    return manifest,transport

def packet_standing(manifest):
    """Derive the envelope's standing from the manifest's own declared chain position.

    The manifest already carries `generation` and `predecessor`, and
    `validate_request` has already held them to the owner's rule. Re-declaring
    a chain position beside it would create a second place to say where this
    generation sits, and the two could then disagree. Deriving it means they
    agree by construction, and the boundary's own agreement check then has
    something true to confirm rather than two independent claims to reconcile.
    """
    generation=manifest.get("generation"); predecessor=manifest.get("predecessor")
    mode="ESTABLISH_GENESIS" if generation==1 and predecessor is None else "VERIFY_EXISTING"
    return {"mode":mode,
            "node_ref":manifest["source_organization"]["organization_id"],
            "generation":generation,
            "predecessor":predecessor}

def build_packet(req):
    manifest,transport=validate_request(req)
    return K.build_packet(
      standing=packet_standing(manifest),
      origin_org="StegVerse-org",
      origin_service="stegverse-org.stegverse-sdk",
      destination_org=transport["target_organization"],
      destination_service=transport["target_service"],
      payload={"request":req},
      transition_reference=transport["transition_reference"],
      authority_effect="NONE_REQUEST_ONLY",
      packet_id=transport["packet_id_prefix"]+manifest["manifest_sha256"][:24],
    )

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--request",type=Path,required=True); ap.add_argument("--packet-out",type=Path,required=True); ap.add_argument("--frame-out",type=Path); ap.add_argument("--submit",action="store_true")
    a=ap.parse_args(); req=json.loads(a.request.read_text())
    manifest,transport=validate_request(req)
    packet=build_packet(req); frame=K.carrier_frame(packet)
    a.packet_out.parent.mkdir(parents=True,exist_ok=True); a.packet_out.write_text(json.dumps(packet,indent=2,sort_keys=True)+"\n")
    if a.frame_out:
        a.frame_out.parent.mkdir(parents=True,exist_ok=True); a.frame_out.write_text(json.dumps(frame,indent=2,sort_keys=True)+"\n")
    submit_result=None
    transport_kind=None
    if a.submit:
        if os.getenv("STEGVERSE_ORG_FEDERATION_GATEWAY_URL","").strip():
            submit_result=GW.submit_frame(frame)
            transport_kind="SHARED_SERVICE_GATEWAY"
        else:
            path=K.publish_frame(frame)
            submit_result={"state":"PENDING","path":str(path)}
            transport_kind="LOCAL_SPOOL_FALLBACK"
    predecessor=manifest.get("predecessor")
    print(json.dumps({"status":"PASS","packet_id":packet["packet_id"],"destination":packet["destination"],
        "experiment_id":manifest["experiment_id"],
        "manifest_contract":transport["contract"],
        "generation":manifest.get("generation"),
        "predecessor_manifest_sha256":(predecessor or {}).get("manifest_sha256"),
        "manifest_sha256":req["bindings"]["manifest_sha256"],"submitted":bool(a.submit),
        "gateway_state":submit_result.get("state") if isinstance(submit_result,dict) else None,
        "transport":transport_kind,
        "submission_ref":submit_result.get("path") if isinstance(submit_result,dict) else None},sort_keys=True))
if __name__=="__main__": raise SystemExit(main())
