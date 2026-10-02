#!/usr/bin/env python3
import argparse,hashlib,importlib.util,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];C=json.loads((ROOT/".stegverse/transition-ledger/contract.json").read_text())
# The heartbeat is the ecosystem's time base; the kernel owns its derivation so
# a receipt and a carrier frame cannot disagree about what an epoch is.
_spec=importlib.util.spec_from_file_location("kernel",ROOT/"org-kernel/kernel.py")
kernel=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(kernel)
# The repository ledger published HEAD with no lock and no atomic replacement,
# so two concurrent appends read one HEAD, bound receipts to the same
# predecessor, and the later HEAD write silently won -- forking the chain and
# orphaning a receipt. The organization ledger above it serializes its append;
# this one addresses the same store so it does too.
_sspec=importlib.util.spec_from_file_location("ledger_store",ROOT/"resident-runtime/ledger_store.py")
ledger_store=importlib.util.module_from_spec(_sspec);_sspec.loader.exec_module(ledger_store)
def canon(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def sha(v):return "sha256:"+hashlib.sha256(v if isinstance(v,(bytes,bytearray)) else canon(v)).hexdigest()
def lr():
 o=os.getenv("STEGVERSE_REPO_LEDGER_ROOT")
 if o:return Path(o).expanduser().resolve()
 return (Path(os.getenv("XDG_STATE_HOME",str(Path.home()/".local/state")))/"stegverse/repo-ledgers"/C["repository"]).resolve()
def main():
 p=argparse.ArgumentParser();p.add_argument("--transition-id",required=True);p.add_argument("--transition-class",required=True);p.add_argument("--predecessor-state-sha256",required=True);p.add_argument("--successor-state-sha256",required=True);p.add_argument("--evidence-json",default="{}");p.add_argument("--authority-effect",default="NONE");p.add_argument("--hb-epoch",type=int,default=None,help="heartbeat epoch; derived from the host clock, and marked as derived, when absent");a=p.parse_args()
 store=ledger_store.PosixLedgerStore(lr());store.initialize()
 with store.exclusive():
  head=store.get(ledger_store.HEAD_KEY);prev=(head or {}).get("receipt_sha256")
  b={"schema":"stegverse.repo-transition-receipt/v1","repository":C["repository"],"transition_id":a.transition_id,"transition_class":a.transition_class,"predecessor_state_sha256":a.predecessor_state_sha256,"successor_state_sha256":a.successor_state_sha256,"evidence":json.loads(a.evidence_json),"authority_effect":a.authority_effect,"hb_reference":kernel.hb_reference(epoch=a.hb_epoch) if a.hb_epoch is not None else kernel.hb_reference(),"previous_receipt_sha256":prev};dg=sha(b);r={**b,"receipt_sha256":dg};key=ledger_store.receipt_key(dg)
  existing=store.get(key)
  if existing is not None and existing!=r:raise SystemExit("receipt collision")
  if existing is None:store.put(key,r)
  store.put(ledger_store.HEAD_KEY,{"repository":C["repository"],"receipt_sha256":dg,"receipt_path":store.locator(key)})
 print(json.dumps(r,sort_keys=True))
if __name__=="__main__":main()
