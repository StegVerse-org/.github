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
 # Supplied, never derived from the host: see aggregate_repo_transition.ledger_root.
 raise ValueError("ledger_location_required_from_materializer: STEGVERSE_REPO_LEDGER_ROOT")
# A transition occurring in this repository emits its receipt here. An
# in-process caller needs the same append the CLI performs, with the same lock
# and the same HEAD publication -- a second implementation of this would be a
# second writer to one store, which is the fork this lock exists to prevent.
def recorded(target,head,transition_id,transition_class):
 """The receipt this chain already holds for a transition, walking back from `head`."""
 cursor=(head or {}).get("receipt_sha256")
 while cursor:
  receipt=target.get(ledger_store.receipt_key(cursor))
  if receipt is None:return None
  if receipt.get("transition_id")==transition_id and receipt.get("transition_class")==transition_class:return receipt
  cursor=receipt.get("previous_receipt_sha256")
 return None
def append(transition_id,transition_class,predecessor_state_sha256,successor_state_sha256,evidence=None,authority_effect="NONE",hb_epoch=None,store=None,idempotent_on=None):
 """Append one repository transition receipt through the substrate transaction.

 With `idempotent_on` (a tuple of evidence keys, possibly empty) a transition
 the chain already records is returned rather than minted again. Identity is
 the transition id and class; the predecessor state and the named evidence
 fields must also match, or the call refuses with `ledger_receipt_collision`
 rather than calling a different transition a replay. The lookup reads the
 chain at the HEAD the append compares against, so a writer that lands the
 same transition first makes this attempt lose the comparison, re-read, and
 return that writer's receipt.
 """
 target=store or ledger_store.PosixLedgerStore(lr());target.initialize()
 for _attempt in range(128):
  expected_head=target.get(ledger_store.HEAD_KEY)
  prev=(expected_head or {}).get("receipt_sha256")
  if idempotent_on is not None:
   prior=recorded(target,expected_head,transition_id,transition_class)
   if prior is not None:
    mine=evidence if evidence is not None else {}
    if prior.get("predecessor_state_sha256")!=predecessor_state_sha256 or any(
       (prior.get("evidence") or {}).get(k)!=mine.get(k) for k in idempotent_on):
     raise ValueError("ledger_receipt_collision")
    return prior
  b={"schema":"stegverse.repo-transition-receipt/v1","repository":C["repository"],"transition_id":transition_id,"transition_class":transition_class,"predecessor_state_sha256":predecessor_state_sha256,"successor_state_sha256":successor_state_sha256,"evidence":evidence if evidence is not None else {},"authority_effect":authority_effect,"hb_reference":kernel.hb_reference(epoch=hb_epoch) if hb_epoch is not None else kernel.hb_reference(),"previous_receipt_sha256":prev}
  dg=sha(b);r={**b,"receipt_sha256":dg};key=ledger_store.receipt_key(dg)
  new_head={"repository":C["repository"],"receipt_sha256":dg,"receipt_path":target.locator(key)}
  if target.append_transaction(key,r,expected_head,new_head):
   return r
 raise SystemExit("REPO_LEDGER_APPEND_CONTENTION_EXHAUSTED")

def main():
 p=argparse.ArgumentParser();p.add_argument("--transition-id",required=True);p.add_argument("--transition-class",required=True);p.add_argument("--predecessor-state-sha256",required=True);p.add_argument("--successor-state-sha256",required=True);p.add_argument("--evidence-json",default="{}");p.add_argument("--authority-effect",default="NONE");p.add_argument("--hb-epoch",type=int,default=None,help="heartbeat epoch; derived from the host clock, and marked as derived, when absent");a=p.parse_args()
 print(json.dumps(append(a.transition_id,a.transition_class,a.predecessor_state_sha256,a.successor_state_sha256,json.loads(a.evidence_json),a.authority_effect,a.hb_epoch),sort_keys=True))
if __name__=="__main__":main()
