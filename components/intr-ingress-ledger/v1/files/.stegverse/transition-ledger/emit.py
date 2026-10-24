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
 # A git+<repository>#<ref>[:namespace] locator is the designated durable root.
 # A plain path stays a filesystem root. With neither supplied, the host state
 # directory remains the local root callers already resolved.
 if o:return ledger_store.parse_locator(o)
 return (Path(os.getenv("XDG_STATE_HOME",str(Path.home()/".local/state")))/"stegverse/repo-ledgers"/C["repository"]).resolve()
# A transition occurring in this repository emits its receipt here. An
# in-process caller needs the same append the CLI performs, with the same lock
# and the same HEAD publication -- a second implementation of this would be a
# second writer to one store, which is the fork this lock exists to prevent.
def recorded(target,head,transition_id,transition_class):
 """The receipt this chain already holds for a transition, walking back from `head`."""
 found=None
 cursor=(head or {}).get("receipt_sha256") if isinstance(head,dict) else None
 while cursor:
  receipt=target.get(ledger_store.receipt_key(cursor))
  if receipt is None: return found
  if found is None and receipt.get("transition_id")==transition_id and receipt.get("transition_class")==transition_class: found=receipt
  cursor=receipt.get("previous_receipt_sha256")
 return found
_ABSENT=object()
def append(transition_id,transition_class,predecessor_state_sha256,successor_state_sha256,evidence=None,authority_effect="NONE",hb_epoch=None,idempotent_on=None):
 """Append one repository transition receipt and publish HEAD atomically.

 With `idempotent_on` (a tuple of evidence keys) a transition the chain already
 records is returned rather than minted again. Identity is the transition id
 and class. An exact retry must also carry the same predecessor state,
 successor state, authority effect and named evidence fields, or the call
 refuses with `ledger_receipt_collision`. The heartbeat reference is not
 compared: a retry legitimately arrives at another epoch.
 """
 store=ledger_store.open_store(lr());store.initialize()
 with store.exclusive():
  head=store.get(ledger_store.HEAD_KEY);prev=(head or {}).get("receipt_sha256")
  if idempotent_on is not None:
   prior=recorded(store,head,transition_id,transition_class)
   if prior is not None:
    mine=evidence if isinstance(evidence,dict) else {}; theirs=prior.get("evidence") if isinstance(prior.get("evidence"),dict) else {}
    if (prior.get("predecessor_state_sha256")!=predecessor_state_sha256
        or prior.get("successor_state_sha256")!=successor_state_sha256
        or prior.get("authority_effect")!=authority_effect
        or any(theirs.get(k,_ABSENT)!=mine.get(k,_ABSENT) for k in idempotent_on)):
     raise ValueError("ledger_receipt_collision")
    return prior
  b={"schema":"stegverse.repo-transition-receipt/v1","repository":C["repository"],"transition_id":transition_id,"transition_class":transition_class,"predecessor_state_sha256":predecessor_state_sha256,"successor_state_sha256":successor_state_sha256,"evidence":evidence if evidence is not None else {},"authority_effect":authority_effect,"hb_reference":kernel.hb_reference(epoch=hb_epoch) if hb_epoch is not None else kernel.hb_reference(),"previous_receipt_sha256":prev};dg=sha(b);r={**b,"receipt_sha256":dg};key=ledger_store.receipt_key(dg)
  existing=store.get(key)
  if existing is not None and existing!=r:raise SystemExit("receipt collision")
  if existing is None:store.put(key,r)
  store.put(ledger_store.HEAD_KEY,{"repository":C["repository"],"receipt_sha256":dg,"receipt_path":store.locator(key)})
 return r
def main():
 p=argparse.ArgumentParser();p.add_argument("--transition-id",required=True);p.add_argument("--transition-class",required=True);p.add_argument("--predecessor-state-sha256",required=True);p.add_argument("--successor-state-sha256",required=True);p.add_argument("--evidence-json",default="{}");p.add_argument("--authority-effect",default="NONE");p.add_argument("--hb-epoch",type=int,default=None,help="heartbeat epoch; derived from the host clock, and marked as derived, when absent");a=p.parse_args()
 print(json.dumps(append(a.transition_id,a.transition_class,a.predecessor_state_sha256,a.successor_state_sha256,json.loads(a.evidence_json),a.authority_effect,a.hb_epoch),sort_keys=True))
if __name__=="__main__":main()
