#!/usr/bin/env python3
"""Publish an already-appended organization receipt to Master Records.

Master Records is the recorder of released organization batch receipts:
downstream evidence preservation only (ORGANIZATION-ROLE-RUNTIME-REALITY-DEPLOYMENT-001).
It cannot create, admit, authorize, infer or repair a transition, it is not a
gate and not custody, and nothing in this organization awaits it. This script
runs after the organization ledger append: the transition it carries is
already real on the organization chain, and nothing here can unmake or hold it.

So a failure here is not a refusal of the organization transition. It is a
non-ALLOW for this downstream publication alone, carrying the six fields, with
`organization_transition_blocked: false`; the batch simply stays unrecorded
downstream, which is a value in its evidence state, not a blocker.
"""
import argparse,importlib.util,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("org_kernel",ROOT/"org-kernel/kernel.py")
K=importlib.util.module_from_spec(spec);spec.loader.exec_module(K)
# Destination service (MASTER-RECORDS-BULK-SEMANTIC-REMEDIATION-002): the organization transition
# ledger owns the ledger role. Legacy name "master-records.ecosystem-transition-ledger" is no longer sent.
DESTINATION_SERVICE="organization.ecosystem-transition-ledger"
RETRY_ENTRYPOINT="resident-runtime/submit_org_transition_to_master_records.py::main"
OWNING_EXISTING_GOAL="ORGANIZATION-ROLE-RUNTIME-REALITY-DEPLOYMENT-001"
#: Exit status of a downstream non-ALLOW. Distinct from argparse's 2, and never
#: read by anything that appends to the organization ledger.
NOT_RECORDED_EXIT=3
def load(p):return json.loads(Path(p).read_text())
def not_recorded(failure_code,failed_predicate,required_evidence_or_repair):
 """The six-field non-ALLOW for this downstream publication; never a transition refusal."""
 return {"status":"NOT_PUBLISHED_FOR_ORGANIZATION_RECORD","disposition":"NON_ALLOW_DOWNSTREAM_ONLY",
  "failure_code":failure_code,"failed_predicate":failed_predicate,
  "required_evidence_or_repair":required_evidence_or_repair,"retry_entrypoint":RETRY_ENTRYPOINT,
  "owning_existing_goal":OWNING_EXISTING_GOAL,
  "next_attempt":"rerun "+RETRY_ENTRYPOINT+" with the same organization receipt once the repair is supplied; a repeat publishes the same write-once frame",
  "organization_transition_blocked":False,"master_records_awaited":False,"authority_effect":"NONE"}
def attempt(a):
 if a.mesh_root is None:
  return not_recorded("MASTER_RECORDS_PUBLICATION_MESH_LOCATION_NOT_SUPPLIED","MESH_ROOT_SUPPLIED","supply --mesh-root, the mesh this node was materialized with")
 try:receipt=load(a.org_receipt)
 except (OSError,ValueError) as exc:
  return not_recorded("MASTER_RECORDS_PUBLICATION_RECEIPT_UNREADABLE","ORGANIZATION_RECEIPT_READABLE","supply a readable organization receipt JSON file ("+type(exc).__name__+")")
 if not isinstance(receipt,dict) or receipt.get("schema")!="stegverse.organization-transition-receipt/v1":
  return not_recorded("MASTER_RECORDS_PUBLICATION_RECEIPT_SCHEMA_MISMATCH","ORGANIZATION_RECEIPT_SCHEMA","supply a stegverse.organization-transition-receipt/v1")
 if receipt.get("organization")!="StegVerse-org":
  return not_recorded("MASTER_RECORDS_PUBLICATION_RECEIPT_OWNER_MISMATCH","ORGANIZATION_RECEIPT_OWNER","supply a receipt owned by StegVerse-org")
 # Only an appended receipt is released downstream: the append binds it by its own digest.
 if not isinstance(receipt.get("receipt_sha256"),str):
  return not_recorded("MASTER_RECORDS_PUBLICATION_RECEIPT_NOT_APPENDED","ORGANIZATION_LEDGER_APPEND_PRECEDES_PUBLICATION","append the transition to the organization ledger first; publish the receipt the append returned")
 try:
  relation=json.loads(a.relation_evidence_json)
  standing=load(a.standing)
 except (OSError,ValueError) as exc:
  return not_recorded("MASTER_RECORDS_PUBLICATION_INPUT_UNREADABLE","PUBLICATION_INPUTS_READABLE","supply readable --standing and --relation-evidence-json ("+type(exc).__name__+")")
 if not isinstance(standing,dict) or "predecessor" not in standing:
  return not_recorded("MASTER_RECORDS_PUBLICATION_STANDING_UNDECLARED","STANDING_DECLARES_PREDECESSOR","standing must declare the predecessor key; null is explicit genesis")
 payload={"operation":"ORGANIZATION_RECORD_ORGANIZATION_TRANSITION","organization_receipt":receipt,"predecessor_ecosystem_state_sha256":a.predecessor_ecosystem_state_sha256,"successor_ecosystem_state_sha256":a.successor_ecosystem_state_sha256,"relation_evidence":relation,"authority_transfer":False}
 try:
  packet=K.build_packet(origin_org="StegVerse-org",origin_service="stegverse-org.org-control",destination_org="master-records",destination_service=DESTINATION_SERVICE,payload=payload,standing=standing,transition_reference="ecosystem.transition.organization-record.v1",authority_effect="NONE")
  # Stamped with the epoch of the receipt it carries, so submitting the same
  # receipt again publishes the same frame -- a write-once no-op -- instead of a
  # second record request stamped by the host clock.
  published=K.publish_packet(packet,root=a.mesh_root,epoch=(receipt.get("hb_reference") or {}).get("epoch"))
 except (OSError,ValueError,KeyError,TypeError) as exc:
  return not_recorded("MASTER_RECORDS_PUBLICATION_NOT_PUBLISHED","PACKET_PUBLISHED_TO_SUPPLIED_MESH","repair the packet or mesh the kernel refused: "+str(exc)[:200])
 return {"status":"PUBLISHED_FOR_ORGANIZATION_RECORD","packet_id":packet["packet_id"],"frame_sha256":published["frame"]["frame_sha256"],"organization_transition_blocked":False,"master_records_awaited":False,"authority_effect":"NONE"}
def main():
 p=argparse.ArgumentParser();p.add_argument("--org-receipt",required=True);p.add_argument("--predecessor-ecosystem-state-sha256",required=True);p.add_argument("--successor-ecosystem-state-sha256",required=True);p.add_argument("--relation-evidence-json",default="{}")
 # Standing is declared, never derived here. The ecosystem-state digests above
 # chain this lane; the contract's own finding refuses to equate lane-local
 # chaining with cross-lane predecessor standing, so they are not reused as a
 # predecessor binding. There is no default: a silent one would be the
 # defaulting the contract forbids.
 p.add_argument("--standing",required=True,help="JSON file declaring mode, node_ref and the predecessor key")
 # The mesh this node was materialized with. Without one nothing is published,
 # and the result says so as a downstream non-ALLOW rather than a usage error.
 p.add_argument("--mesh-root",type=Path,default=None)
 a=p.parse_args()
 result=attempt(a)
 print(json.dumps(result,sort_keys=True))
 if result["status"]!="PUBLISHED_FOR_ORGANIZATION_RECORD":
  print(result["failure_code"]+": "+result["failed_predicate"]+" -- "+result["required_evidence_or_repair"],file=sys.stderr)
  return NOT_RECORDED_EXIT
 return 0
if __name__=="__main__":sys.exit(main())
