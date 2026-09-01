#!/usr/bin/env python3
import argparse,importlib.util,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("org_kernel",ROOT/"org-kernel/kernel.py")
K=importlib.util.module_from_spec(spec);spec.loader.exec_module(K)
def load(p):return json.loads(Path(p).read_text())
def main():
 p=argparse.ArgumentParser();p.add_argument("--org-receipt",required=True);p.add_argument("--predecessor-ecosystem-state-sha256",required=True);p.add_argument("--successor-ecosystem-state-sha256",required=True);p.add_argument("--relation-evidence-json",default="{}");a=p.parse_args()
 receipt=load(a.org_receipt)
 if receipt.get("schema")!="stegverse.organization-transition-receipt/v1":raise SystemExit("organization receipt schema mismatch")
 if receipt.get("organization")!="StegVerse-org":raise SystemExit("organization receipt owner mismatch")
 payload={"operation":"CUSTODY_ORGANIZATION_TRANSITION","organization_receipt":receipt,"predecessor_ecosystem_state_sha256":a.predecessor_ecosystem_state_sha256,"successor_ecosystem_state_sha256":a.successor_ecosystem_state_sha256,"relation_evidence":json.loads(a.relation_evidence_json),"authority_transfer":False}
 packet=K.build_packet(origin_org="StegVerse-org",origin_service="stegverse-org.org-control",destination_org="master-records",destination_service="master-records.ecosystem-transition-ledger",payload=payload,transition_reference="ecosystem.transition.custody.v1",authority_effect="NONE")
 published=K.publish_packet(packet)
 print(json.dumps({"status":"PUBLISHED_FOR_CUSTODY","packet_id":packet["packet_id"],"frame_sha256":published["frame"]["frame_sha256"],"authority_effect":"NONE"},sort_keys=True))
if __name__=="__main__":main()
