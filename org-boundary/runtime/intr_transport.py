#!/usr/bin/env python3
import hashlib, json, uuid
PROFILE="stegverse.intr.org-boundary.v1"
def _canon(v): return json.dumps(v,sort_keys=True,separators=(",",":")).encode()
def build_ingress(origin,destination,payload,carrier_reference,transition_reference,authority_effect="NONE",packet_id=None):
 return {"schema_version":PROFILE,"packet_id":packet_id or str(uuid.uuid4()),"direction":"INGRESS","origin":origin,"destination":destination,"carrier":{"kind":"HB_DERIVED","reference":carrier_reference},"intr_profile":PROFILE,"transition":{"reference":transition_reference,"authority_effect":authority_effect,"conditions":[]},"payload":payload,"evidence":{"ingress_receipt":None,"dispatch_receipt":None,"consumption_receipt":None,"egress_receipt":None,"reconstruction_reference":None}}
def build_egress(ingress,execution_result):
 payload={"request_packet_id":ingress["packet_id"],"execution_result":execution_result}
 return {"schema_version":PROFILE,"packet_id":ingress["packet_id"]+":egress","direction":"EGRESS","origin":ingress["destination"],"destination":ingress["origin"],"carrier":{"kind":ingress["carrier"]["kind"],"reference":ingress["carrier"]["reference"],"observed_at":_now()},"intr_profile":ingress["intr_profile"],"transition":{"reference":ingress["transition"]["reference"],"authority_effect":ingress["transition"]["authority_effect"],"conditions":ingress["transition"].get("conditions",[])},"payload":payload,"evidence":{"ingress_receipt":execution_result["receipts"][0]["receipt_id"],"dispatch_receipt":execution_result["receipts"][1]["receipt_id"],"consumption_receipt":execution_result["receipts"][2]["receipt_id"],"egress_receipt":execution_result["receipts"][-1]["receipt_id"],"reconstruction_reference":execution_result["reconstruction"]["terminal_receipt_id"]},"payload_hash":hashlib.sha256(_canon(payload)).hexdigest()}
def validate_org_crossing(envelope,expected_direction):
 """Reject an envelope the boundary cannot consume, at the boundary.

 process_boundary.py reads origin and destination as {"org","service"} objects.
 Checking only that the keys are present let a malformed endpoint through here
 and surfaced it as a TypeError deep inside execution, so the shape is part of
 the crossing contract and is enforced where the crossing is validated.
 """
 if envelope.get("direction")!=expected_direction: raise ValueError("wrong-direction")
 for key in ("packet_id","origin","destination","carrier","intr_profile","transition","payload","evidence"):
  if key not in envelope: raise ValueError("missing-"+key)
 if envelope.get("intr_profile")!=PROFILE: raise ValueError("wrong-intr-profile")
 for key in ("origin","destination"):
  endpoint=envelope[key]
  if not isinstance(endpoint,dict): raise ValueError(key+"-must-be-an-object")
  for field in ("org","service"):
   if not isinstance(endpoint.get(field),str) or not endpoint[field].strip():
    raise ValueError(key+"-missing-"+field)
 return True
