#!/usr/bin/env python3
"""Release one verified organization receipt batch to Master Records as downstream evidence.

Master Records is the recorder of released organization batch receipts:
downstream evidence preservation only (ORGANIZATION-ROLE-RUNTIME-REALITY-DEPLOYMENT-001).
It cannot create, admit, authorize, infer or repair a transition, it is not a
gate and not custody, and nothing in this organization awaits it. This script
runs after the organization ledger append: the transitions it carries are
already real on the organization chain, and nothing here can unmake or hold them.

The release predecessor is a verified organization receipt-chain segment. The
receipts are supplied in chain order (a single receipt is a batch of one); each
must be this organization's receipt with a matching self-digest, and each must
link to the one before it by `previous_receipt_sha256`. A segment that does not
verify is refused before any packet is built.

So a failure here is not a refusal of the organization transition. It is a DENY
of this downstream release alone, carrying failure_code, failed_predicate,
required_evidence_or_repair, retry_entrypoint, owning_existing_goal and
next_attempt, with `organization_transition_blocked: false`; the batch simply
stays unrecorded downstream, which is a value in its evidence state, not a blocker.
"""
import argparse,importlib.util,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("org_kernel",ROOT/"org-kernel/kernel.py")
K=importlib.util.module_from_spec(spec);spec.loader.exec_module(K)
_agg=importlib.util.spec_from_file_location("org_ledger_for_release",ROOT/"resident-runtime/aggregate_repo_transition.py")
AGG=importlib.util.module_from_spec(_agg);_agg.loader.exec_module(AGG)
ORGANIZATION="StegVerse-org"
ORIGIN_SERVICE="stegverse-org.org-control"
DESTINATION_ORG="master-records"
# Destination service (MASTER-RECORDS-BULK-SEMANTIC-REMEDIATION-002): the organization transition
# ledger owns the ledger role. Legacy name "master-records.ecosystem-transition-ledger" is no longer sent.
DESTINATION_SERVICE="organization.ecosystem-transition-ledger"
TRANSITION_REFERENCE="ecosystem.transition.organization-record.v1"
RECORDER_ROLE="RELEASED_ORGANIZATION_BATCH_RECEIPT_RECORDER"
RELEASE_PREDECESSOR="VERIFIED_ORGANIZATION_RECEIPT_CHAIN_SEGMENT"
ORG_RECEIPT_SCHEMA="stegverse.organization-transition-receipt/v1"
RETRY_ENTRYPOINT="resident-runtime/submit_org_transition_to_master_records.py::main"
OWNING_EXISTING_GOAL="ORGANIZATION-ROLE-RUNTIME-REALITY-DEPLOYMENT-001"
#: Exit status of a downstream DENY. Distinct from argparse's 2, and never
#: read by anything that appends to the organization ledger.
NOT_RECORDED_EXIT=3
# failed_predicate -> (failure_code, required_evidence_or_repair)
REFUSALS={
 "MESH_ROOT_SUPPLIED":("MASTER_RECORDS_RELEASE_MESH_LOCATION_NOT_SUPPLIED","supply --mesh-root, the mesh this node was materialized with"),
 "PUBLICATION_INPUTS_READABLE":("MASTER_RECORDS_RELEASE_INPUT_UNREADABLE","supply readable --org-receipt, --standing and --relation-evidence-json JSON"),
 "RELEASED_BATCH_IS_NOT_EMPTY":("MASTER_RECORDS_RELEASE_BATCH_EMPTY","supply at least one organization receipt with --org-receipt"),
 "ORGANIZATION_RECEIPT_SCHEMA_MATCHES":("MASTER_RECORDS_RELEASE_RECEIPT_SCHEMA_MISMATCH","release only "+ORG_RECEIPT_SCHEMA+" receipts"),
 "ORGANIZATION_RECEIPT_OWNER_MATCHES":("MASTER_RECORDS_RELEASE_RECEIPT_OWNER_MISMATCH","release only receipts emitted by "+ORGANIZATION+"'s own ledger"),
 "ORGANIZATION_RECEIPT_SELF_DIGEST_MATCHES":("MASTER_RECORDS_RELEASE_RECEIPT_DIGEST_MISMATCH","supply the receipt bytes exactly as appended to the organization ledger; only an appended receipt is released"),
 "ORGANIZATION_RECEIPT_CHAIN_SEGMENT_IS_CONTIGUOUS":("MASTER_RECORDS_RELEASE_SEGMENT_NOT_CONTIGUOUS","supply a contiguous segment in chain order: each receipt's previous_receipt_sha256 names the receipt before it"),
 "STANDING_DECLARES_PREDECESSOR":("MASTER_RECORDS_RELEASE_STANDING_UNDECLARED","standing must declare the predecessor key; null is explicit genesis"),
 "PACKET_PUBLISHED_TO_SUPPLIED_MESH":("MASTER_RECORDS_RELEASE_NOT_PUBLISHED","repair the packet or mesh the kernel refused"),
}
class ReleaseRefused(Exception):
 """A DENY of this downstream release; never a refusal of the organization transition."""
 def __init__(self,predicate,detail):
  failure_code,repair=REFUSALS[predicate]
  self.refusal={"status":"NOT_PUBLISHED_FOR_ORGANIZATION_RECORD","disposition":"DENY","scope":"DOWNSTREAM_RELEASE_ONLY",
   "failure_code":failure_code,"failed_predicate":predicate,"required_evidence_or_repair":repair,
   "retry_entrypoint":RETRY_ENTRYPOINT,"owning_existing_goal":OWNING_EXISTING_GOAL,
   "next_attempt":"rerun "+RETRY_ENTRYPOINT+" with the same receipt-chain segment once the repair is supplied; a repeat publishes the same write-once frame",
   "detail":detail[:240],"organization_transition_blocked":False,"master_records_awaited":False,
   "gates_organization_runtime_reality":False,"authority_effect":"NONE"}
  super().__init__(failure_code)
def load(p):return json.loads(Path(p).read_text())
def verify_released_segment(receipts):
 """Verify a receipt-chain segment this organization releases; return its batch summary."""
 if isinstance(receipts,dict):receipts=[receipts]
 if not receipts:raise ReleaseRefused("RELEASED_BATCH_IS_NOT_EMPTY","released batch is empty")
 previous=None
 for i,receipt in enumerate(receipts):
  if not isinstance(receipt,dict) or receipt.get("schema")!=ORG_RECEIPT_SCHEMA:raise ReleaseRefused("ORGANIZATION_RECEIPT_SCHEMA_MATCHES",f"organization receipt schema mismatch at {i}")
  if receipt.get("organization")!=ORGANIZATION:raise ReleaseRefused("ORGANIZATION_RECEIPT_OWNER_MATCHES",f"organization receipt owner mismatch at {i}")
  body={k:v for k,v in receipt.items() if k!="receipt_sha256"}
  if receipt.get("receipt_sha256")!=AGG.sha(body):raise ReleaseRefused("ORGANIZATION_RECEIPT_SELF_DIGEST_MATCHES",f"organization receipt digest mismatch at {i}")
  if i and receipt.get("previous_receipt_sha256")!=previous:raise ReleaseRefused("ORGANIZATION_RECEIPT_CHAIN_SEGMENT_IS_CONTIGUOUS",f"organization receipt at {i} does not link to the receipt before it")
  previous=receipt["receipt_sha256"]
 return {"release_predecessor":RELEASE_PREDECESSOR,"verified_by":ORGANIZATION,"receipt_count":len(receipts),
  "segment_base_previous_receipt_sha256":receipts[0].get("previous_receipt_sha256"),
  "segment_first_receipt_sha256":receipts[0]["receipt_sha256"],"segment_head_receipt_sha256":receipts[-1]["receipt_sha256"],
  "receipts":list(receipts)}
def build_released_batch_packet(receipts,predecessor_ecosystem_state_sha256,successor_ecosystem_state_sha256,relation_evidence,standing):
 batch=verify_released_segment(receipts)
 # Standing is declared, never derived here. The ecosystem-state digests chain
 # this lane; the contract's own finding refuses to equate lane-local chaining
 # with cross-lane predecessor standing, so they are not reused as a
 # predecessor binding. There is no default: a silent one would be the
 # defaulting the contract forbids.
 if not isinstance(standing,dict) or "predecessor" not in standing:raise ReleaseRefused("STANDING_DECLARES_PREDECESSOR","standing must declare the predecessor key")
 payload={"operation":"RECORD_RELEASED_ORGANIZATION_BATCH","recorder_role":RECORDER_ROLE,"released_batch":batch,
  "predecessor_ecosystem_state_sha256":predecessor_ecosystem_state_sha256,"successor_ecosystem_state_sha256":successor_ecosystem_state_sha256,
  "relation_evidence":relation_evidence,"authority_transfer":False,"gates_organization_runtime_reality":False,"awaited_by_organization":False}
 return K.build_packet(origin_org=ORGANIZATION,origin_service=ORIGIN_SERVICE,destination_org=DESTINATION_ORG,destination_service=DESTINATION_SERVICE,payload=payload,standing=standing,transition_reference=TRANSITION_REFERENCE,authority_effect="NONE")
def release(a):
 if a.mesh_root is None:raise ReleaseRefused("MESH_ROOT_SUPPLIED","no --mesh-root")
 try:
  receipts=[load(p) for p in a.org_receipt]
  relation=json.loads(a.relation_evidence_json)
  standing=load(a.standing)
 except (OSError,ValueError) as exc:raise ReleaseRefused("PUBLICATION_INPUTS_READABLE",type(exc).__name__+": "+str(exc))
 packet=build_released_batch_packet(receipts,a.predecessor_ecosystem_state_sha256,a.successor_ecosystem_state_sha256,relation,standing)
 # Stamped with the epoch of the segment's head receipt, so releasing the same
 # segment again publishes the same frame -- a write-once no-op -- instead of a
 # second record request stamped by the host clock. Publication is
 # fire-and-forget evidence: no answer is requested and nothing waits for it.
 try:published=K.publish_packet(packet,root=a.mesh_root,epoch=(receipts[-1].get("hb_reference") or {}).get("epoch"))
 except (OSError,ValueError,KeyError,TypeError) as exc:raise ReleaseRefused("PACKET_PUBLISHED_TO_SUPPLIED_MESH",str(exc))
 return {"status":"PUBLISHED_FOR_ORGANIZATION_RECORD","disposition":"ALLOW","packet_id":packet["packet_id"],"receipt_count":len(receipts),
  "frame_sha256":published["frame"]["frame_sha256"],"organization_transition_blocked":False,"master_records_awaited":False,
  "gates_organization_runtime_reality":False,"authority_effect":"NONE"}
def main():
 p=argparse.ArgumentParser()
 p.add_argument("--org-receipt",required=True,action="append",help="an organization receipt of the released segment; repeat in chain order")
 p.add_argument("--predecessor-ecosystem-state-sha256",required=True);p.add_argument("--successor-ecosystem-state-sha256",required=True)
 p.add_argument("--relation-evidence-json",default="{}")
 p.add_argument("--standing",required=True,help="JSON file declaring mode, node_ref and the predecessor key")
 # The mesh this node was materialized with. Without one nothing is published,
 # and the result says so as a downstream DENY rather than a usage error.
 p.add_argument("--mesh-root",type=Path,default=None)
 a=p.parse_args()
 try:result=release(a)
 except ReleaseRefused as refused:result=refused.refusal
 print(json.dumps(result,sort_keys=True))
 if result["disposition"]!="ALLOW":
  print(result["failure_code"]+": "+result["failed_predicate"]+" -- "+result["required_evidence_or_repair"],file=sys.stderr)
  return NOT_RECORDED_EXIT
 return 0
if __name__=="__main__":sys.exit(main())
