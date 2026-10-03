#!/usr/bin/env python3
import importlib.util, json, shutil, tempfile
from pathlib import Path
spec=importlib.util.spec_from_file_location("kernel","org-kernel/kernel.py"); k=importlib.util.module_from_spec(spec); spec.loader.exec_module(k)
with tempfile.TemporaryDirectory() as td:
 root=Path(td); (root/"org-boundary/registry").mkdir(parents=True); (root/"org-boundary/runtime").mkdir(parents=True)
 reg={"organization":"Kernel-Test","services":[{"service_id":"kernel-test.boundary-diagnostic","repository":"Kernel-Test/.github","boundary_role":"BOUNDARY_LOCAL_DIAGNOSTIC"}]}
 (root/"org-boundary/registry/services.json").write_text(json.dumps(reg))
 # A root that dispatches carries a boundary runtime beside its registry: a
 # boundary that cannot state how processing was selected fails closed instead.
 shutil.copy2("org-boundary/runtime/manifest_selection.py",root/"org-boundary/runtime/manifest_selection.py")
 shutil.copy2("org-boundary/runtime/node_standing.py",root/"org-boundary/runtime/node_standing.py")
 (root/"docs").mkdir(parents=True,exist_ok=True)
 shutil.copy2("docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json",root/"docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json")
 packet={"schema_version":"stegverse.intr.org-boundary.v1","packet_id":"kernel-test-001","direction":"INGRESS",
 "origin":{"org":"Peer","service":"peer.boundary-diagnostic"},"destination":{"org":"Kernel-Test","service":"kernel-test.boundary-diagnostic"},
 "carrier":{"kind":"HB_DERIVED","reference":"canonical"},"intr_profile":"stegverse.intr.org-boundary.v1",
 "transition":{"reference":"diagnostic","authority_effect":"NONE"},"payload":{"probe":"ping"},
 "standing":{"mode":"ESTABLISH_GENESIS","node_ref":"kernel-test-node","predecessor":None},
 "evidence":{"ingress_receipt":None,"dispatch_receipt":None,"consumption_receipt":None,"egress_receipt":None,"reconstruction_reference":None}}
 frame=k.carrier_frame(packet,now_ns=k.HB_ANCHOR_UNIX_NS+1_000_000_000)
 recovered=k.recover_packet(frame); assert recovered==packet
 out=k.ingest_frame(root,frame); assert out["status"]=="CONSUMED"; assert out["execution_result"]["reconstruction"]["status"]=="RECONSTRUCTED"
 assert [x["kind"] for x in out["execution_result"]["receipts"]]==["INGRESS_ACCEPTED","DISPATCHED","CONSUMED","RESULT_BOUND","EGRESS_EMITTED"]
 # A diagnostic is the processor, so nothing selected one, and the result says
 # so rather than leaving a declaration looking like one that was processed.
 assert out["execution_result"]["processing_selection"]=="BOUNDARY_LOCAL_NO_PROCESSOR_SELECTED"
 assert out["execution_result"]["declared_capability_processed"] is False
 print("PASS")
