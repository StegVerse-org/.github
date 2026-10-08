#!/usr/bin/env python3
import argparse,importlib.util,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("org_kernel",ROOT/"org-kernel/kernel.py")
K=importlib.util.module_from_spec(spec);spec.loader.exec_module(K)
# Destination service (MASTER-RECORDS-BULK-SEMANTIC-REMEDIATION-002): the organization transition
# ledger owns the ledger role. Legacy name "master-records.ecosystem-transition-ledger" is no longer sent.
DESTINATION_SERVICE="organization.ecosystem-transition-ledger"
def load(p):return json.loads(Path(p).read_text())
def main():
 p=argparse.ArgumentParser();p.add_argument("--org-receipt",required=True);p.add_argument("--predecessor-ecosystem-state-sha256",required=True);p.add_argument("--successor-ecosystem-state-sha256",required=True);p.add_argument("--relation-evidence-json",default="{}")
 # Standing is declared, never derived here. The ecosystem-state digests above
 # chain this lane; the contract's own finding refuses to equate lane-local
 # chaining with cross-lane predecessor standing, so they are not reused as a
 # predecessor binding. There is no default: a silent one would be the
 # defaulting the contract forbids.
 p.add_argument("--standing",required=True,help="JSON file declaring mode, node_ref and the predecessor key")
 a=p.parse_args()
 receipt=load(a.org_receipt)
 if receipt.get("schema")!="stegverse.organization-transition-receipt/v1":raise SystemExit("organization receipt schema mismatch")
 if receipt.get("organization")!="StegVerse-org":raise SystemExit("organization receipt owner mismatch")
 payload={"operation":"ORGANIZATION_RECORD_ORGANIZATION_TRANSITION","organization_receipt":receipt,"predecessor_ecosystem_state_sha256":a.predecessor_ecosystem_state_sha256,"successor_ecosystem_state_sha256":a.successor_ecosystem_state_sha256,"relation_evidence":json.loads(a.relation_evidence_json),"authority_transfer":False}
 standing=load(a.standing)
 if not isinstance(standing,dict) or "predecessor" not in standing:raise SystemExit("standing must declare the predecessor key; null is explicit genesis")
 packet=K.build_packet(origin_org="StegVerse-org",origin_service="stegverse-org.org-control",destination_org="master-records",destination_service=DESTINATION_SERVICE,payload=payload,standing=standing,transition_reference="ecosystem.transition.organization-record.v1",authority_effect="NONE")
 published=K.publish_packet(packet)
 print(json.dumps({"status":"PUBLISHED_FOR_ORGANIZATION_RECORD","packet_id":packet["packet_id"],"frame_sha256":published["frame"]["frame_sha256"],"authority_effect":"NONE"},sort_keys=True))
if __name__=="__main__":main()
