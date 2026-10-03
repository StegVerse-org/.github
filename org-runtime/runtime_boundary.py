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
# Egress is not receiving a registered capability, so it resolves an emitting
# operation rather than a capability binding: one operation, owned here, that
# publishes to a peer the organization's own directory declares. Before this the
# egress section carried only `interlock_required` and `intr_required`, so the
# outbound half of the boundary was declared to exist and bound to nothing.
EGRESS_EMITTING_OPERATION_ID="ORGANIZATION_INTER_ORG_EGRESS"
EGRESS_NON_AUTHORIZING_FLAGS=NON_AUTHORIZING_BINDING_FLAGS
def egress_emitting_operation(t:dict[str,Any])->dict[str,Any]:
    operation=(t.get("egress") or {}).get("emitting_operation")
    return operation if isinstance(operation,dict) else {}
def egress_emitting_operation_bound(t:dict[str,Any])->bool:
    """One emitting operation, owned here, granting nothing, and attesting nothing it cannot.

    The same shape the receiving operation is held to, plus what an outbound
    crossing may and may not claim. It must not claim the origin on a frame was
    verified here -- nothing verifies that. It must claim the far side's chain
    is reconstructed here, because it is, and it must not claim that
    reconstruction establishes who the far side is or that the far side
    persisted its own chain. Those are the bilateral match, which needs the far
    side's chain readable.
    """
    operation=egress_emitting_operation(t)
    if not operation: return False
    if operation.get("owner_repository")!=f"{ORG}/.github": return False
    if operation.get("operation_id")!=EGRESS_EMITTING_OPERATION_ID: return False
    if not str(operation.get("emission") or "").strip(): return False
    if not str(operation.get("closure") or "").strip(): return False
    if operation.get("transport")!="INTERLOCK_INTR": return False
    # No host, no environment URL -- the same rule the receiving operation keeps.
    if operation.get("host_required") is not False or operation.get("environment_url_required") is not False: return False
    if operation.get("credential_authority")!="TV/TVC" or operation.get("github_token_runtime_authority")!="NONE": return False
    if operation.get("binding_role")!="ORGANIZATION_EMITTING_OPERATION_RESOLUTION" or operation.get("authority_effect")!="NONE_BINDING_ONLY": return False
    if any(operation.get(flag) is not False for flag in EGRESS_NON_AUTHORIZING_FLAGS): return False
    if operation.get("every_disposition_is_receipted") is not True: return False
    if operation.get("origin_attestation_state")!="NOT_PROVEN": return False
    if operation.get("origin_is_verified_by_this_boundary") is not False: return False
    # Reconstruction is required, not forbidden. The first version of this
    # check enforced that the far side's chain could NOT be reconstructed here,
    # which declared a limit that is not real: a boundary receipt id derives
    # from the packet id, the service id and the payload digest, all of which
    # the emitter holds. What must stay false are the two things reconstruction
    # genuinely does not establish.
    if operation.get("far_side_receipt_reconstructed_here") is not True: return False
    if operation.get("far_side_chain_recomputed_from_emitter_held_inputs") is not True: return False
    if operation.get("reconstruction_proves_who_the_far_side_is") is not False: return False
    if operation.get("reconstruction_proves_the_far_side_persisted_its_chain") is not False: return False
    if operation.get("closure_requires_this_organizations_own_emission_record") is not True: return False
    return True
def egress_destinations_resolve_from_the_directory(t:dict[str,Any])->bool:
    """Destinations come from the organization's own peer directory, not a caller."""
    resolution=(t.get("egress") or {}).get("peer_destination_resolution")
    if not isinstance(resolution,dict): return False
    if resolution.get("source")!="ORGANIZATION_FEDERATION_DIRECTORY": return False
    if resolution.get("directory")!="org-boundary/registry/federation.json": return False
    if resolution.get("resolved_from_caller_argument") is not False: return False
    return resolution.get("destination_must_declare_this_transport_profile")=="stegverse.intr.org-boundary.v1"
REGISTRY=ROOT/"org-boundary/registry/services.json"
CAPABILITY_INGRESS_ROLE="BOUNDARY_LOCAL_CAPABILITY_INGRESS"
def capability_addresses_resolve(t:dict[str,Any])->bool:
    """Every bound capability is reachable, which is what binding one implies.

    `capability_endpoint_binding_rule` resolved a receiving operation and
    stopped there. `dispatch` resolves `destination.service` against the service
    registry and refuses `unknown_service` for anything absent from it, so a
    binding whose operation had no registered address named a destination
    transport could not reach -- the declaration was real and the reachability
    it implied was not. This is `capability_address_rule`, enforced: the
    addressed service exists, carries the role whose dispatch resolves a
    capability, agrees with the binding on which capability arrives there, and
    names an operation module that is present in this repository.
    """
    if (t.get("ingress") or {}).get("capability_address_rule")!=\
       "A_BOUND_RECEIVING_OPERATION_IS_ADDRESSABLE_IN_THE_SERVICE_REGISTRY_OR_IT_IS_UNREACHABLE": return False
    bindings=capability_bindings(t)
    if not bindings: return False
    rows={r.get("service_id"):r for r in load(REGISTRY).get("services",[]) if isinstance(r,dict)}
    for b in bindings:
        receiving=b.get("receiving_operation")
        if not isinstance(receiving,dict): return False
        row=rows.get(receiving.get("addressed_service"))
        if row is None: return False
        if row.get("boundary_role")!=CAPABILITY_INGRESS_ROLE: return False
        if receiving.get("addressed_service_boundary_role")!=CAPABILITY_INGRESS_ROLE: return False
        if row.get("capability_profile_id")!=b.get("profile_id"): return False
        if receiving.get("address_is_resolvable_from_the_service_registry") is not True: return False
        # The address selects no processor, and must not read as one that did.
        if receiving.get("selects_processing_at_the_capability_address") is not False: return False
        if row.get("selects_processing_at_this_address") is not False: return False
        if row.get("address_grants_admission_authority") is not False: return False
        operation=receiving.get("operation")
        if not isinstance(operation,str) or not (ROOT/operation).is_file(): return False
        resolution=receiving.get("address_resolution")
        if not isinstance(resolution,str) or not (ROOT/resolution.split("::",1)[0]).is_file(): return False
    return True
def peer_capability_addresses_derive(t:dict[str,Any])->bool:
    """A peer's capability address is derived, and what that does not prove is said.

    Enumerating a service per peer would be this organization writing down what
    its peers serve, which is a declaration none of them made. Deriving it is
    honest only while the record says so: the form is the organization's own and
    the same one this organization answers at, and it is not evidence that a
    given peer installed the receiving operation. Claiming otherwise is the
    overclaim; declaring the derivation unusable would be the limit that is not
    real.
    """
    r=(t.get("egress") or {}).get("peer_capability_resolution")
    if not isinstance(r,dict): return False
    if r.get("address_form")!="ORGANIZATION_SLUG_DOT_CAPABILITY_PROFILE_ID": return False
    if r.get("capability_must_be_declared_in_this_organizations_overlay") is not True: return False
    if r.get("derivation_is_the_same_one_this_organization_answers_at") is not True: return False
    if r.get("peer_serves_this_capability_is_proven_here") is not False: return False
    if r.get("peer_declares_its_capability_services_in_the_peer_directory") is not False: return False
    if r.get("unserved_capability_address_is_observable_as_an_unclosed_crossing") is not True: return False
    if r.get("default_without_a_declared_capability")!="ORG_CONTROL_SERVICE": return False
    # The address it says it is proven on must actually be served here.
    proven=r.get("proven_on_this_organization")
    rows={row.get("service_id") for row in load(REGISTRY).get("services",[]) if isinstance(row,dict)}
    return isinstance(proven,str) and proven in rows
ATTESTATION_MODULE=ROOT/"org-boundary/runtime/origin_attestation.py"
def origin_attestation_is_bound(t:dict[str,Any])->bool:
    """Origin is attested by the credential authority, and the limit is declared.

    `origin_attestation_state` read NOT_PROVEN on every inter-organization
    record, and RE measured that single dimension as the whole disorder score.
    The settled specification's section 4 says TV/TVC already holds the
    primitive, so this holds the binding to it: the declared authority and its
    two operations, a statement the receiver reconstructs rather than one that
    travels beside its own signature, no key material and no verification
    algorithm here, and an unreachable authority refused rather than passed.

    What attestation does not establish is required to be declared too. It
    proves the authority signed the statement; it does not prove the authority
    authenticated the asker, and claiming otherwise would be the overclaim this
    check exists to refuse.
    """
    a=(t.get("egress") or {}).get("origin_attestation")
    if not isinstance(a,dict): return False
    if a.get("credential_authority")!="TV/TVC": return False
    if a.get("sign_operation")!="TV_EXPORT_HMAC_SIGN": return False
    if a.get("verify_operation")!="TV_EXPORT_HMAC_VERIFY": return False
    if a.get("signature_algorithm")!="hmac-sha256": return False
    if a.get("statement_fields")!=["origin_organization","destination_organization",
                                   "destination_service","packet_id","payload_sha256",
                                   "transport_profile"]: return False
    for required in ("statement_reconstructed_by_the_receiver_from_the_packet",
                     "signature_travels_inside_the_packet",
                     "authority_is_asked_to_sign_then_asked_to_verify",
                     "unreachable_authority_is_a_hold_not_a_pass",
                     "offered_attestation_that_failed_refuses_the_emission",
                     "proves_the_authority_signed_the_statement",
                     "initiator_identification_also_requires_the_bilateral_match"):
        if a.get(required) is not True: return False
    for forbidden in ("statement_travels_beside_its_signature","boundary_holds_key_material",
                      "verification_algorithm_implemented_here",
                      "proves_the_authority_authenticated_the_asker"):
        if a.get(forbidden) is not False: return False
    # The disposition for a crossing that offers no attestation is declared
    # rather than implicit: every peer is unattested today, and whether that
    # stays admitted is the owner's policy, not this boundary's silence.
    if a.get("unattested_crossing_disposition")!="ADMITTED_AND_RECORDED_AS_UNATTESTED": return False
    if a.get("requiring_attestation_is_an_owner_policy_decision_not_made_here") is not True: return False
    binding=a.get("statement_binding")
    if not isinstance(binding,str) or not (ROOT/binding.split("::",1)[0]).is_file(): return False
    # No second implementation of the credential authority's algorithm lives
    # here. A repository that could verify a signature itself would be a second
    # credential authority, which the TV/TVC split exists to prevent.
    source=ATTESTATION_MODULE.read_text(encoding="utf-8")
    return not any(token in source for token in ("import hmac","hmac.new","hashlib.sha256"))
def sdk_manifest_ingress_bound(t:dict[str,Any])->bool:
    """The capability the SDK's manifest handoff resolves on is one of them."""
    return any((b.get("profile_id"),b.get("profile_name"),b.get("operation"))==("sdk-manifest-ingress","SDK:ManifestIngress","SUBMIT_MANIFEST") for b in capability_bindings(t))
def validate()->dict[str,Any]:
    a,t=load(ACT),load(TR); h=t["heartbeat_derived_carrier"]; checks={"activation_owner":a.get("organization")==ORG and a.get("owner_repository")==f"{ORG}/.github","activation_local":a.get("activation_source_scope")=="ORG_DOT_GITHUB_ONLY","runtime_sovereign":a.get("runtime_execution_surface")=="SOVEREIGN_RESIDENT_PROCESS","transport_owner":t.get("organization")==ORG and t.get("owner_repository")==f"{ORG}/.github","all_io_here":t.get("communication_policy")=="ALL_ORGANIZATION_INGRESS_EGRESS_GENERATED_AT_ORG_DOT_GITHUB_BOUNDARY","tvtvc":a.get("credential_authority")=="TV/TVC" and t.get("credential_authority")=="TV/TVC","github_none":a.get("github_token_runtime_authority")=="NONE" and t.get("github_token_runtime_authority")=="NONE","effects_transition_derived":a.get("authority_effect_resolution")=="DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS" and t.get("authority_effect_resolution")=="DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS","hb_non_authorizing":all(h.get(k) is False for k in ("carrier_grants_admission_authority","carrier_grants_execution_authority","carrier_grants_credential_authority","carrier_grants_routing_authority","carrier_grants_transition_authority","carrier_grants_receiving_authority")),"capability_bindings_resolve":capability_bindings_resolve(t),"sdk_manifest_ingress_bound":sdk_manifest_ingress_bound(t),"egress_emitting_operation_bound":egress_emitting_operation_bound(t),"egress_destinations_resolve_from_the_directory":egress_destinations_resolve_from_the_directory(t),"capability_addresses_resolve":capability_addresses_resolve(t),"peer_capability_addresses_derive":peer_capability_addresses_derive(t),"origin_attestation_is_bound":origin_attestation_is_bound(t)}; return {"schema":"stegverse.organization-boundary-validation/v1","organization":ORG,"checks":checks,"valid":all(checks.values()),"authority_effect":"NONE_VALIDATION_ONLY"}
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
