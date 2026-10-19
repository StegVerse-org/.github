#!/usr/bin/env python3
"""StegVerse-org resident executor: one federation cycle per materialization.

Each invocation is one ephemeral materialization of this organization's node:
it runs the canonical federation cycle once over the mesh and node state it
was given, records what it did in that node state, and exits. Nothing loops,
polls, or waits for a receiver; frames that arrive later are consumed by a
later materialization (DURABLE_QUEUE_OR_EVENT_EPHEMERAL_MATERIALIZATION).
GitHub Actions and other hosted CI environments are rejected as runtime
authority.

The frozen SV002 SDK query is no longer run from here. It is a manifest-bound
submission (resident-runtime/run_sv002_self_characterization_roundtrip.py),
invoked as its own action.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HOSTED=("GITHUB_ACTIONS","CI","RENDER","VERCEL","CF_PAGES","CLOUDFLARE_WORKERS")

def truthy(v):
    return str(v or "").strip().lower() not in {"","0","false","no"}

def atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name("."+path.name+".tmp")
    temp.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    os.replace(temp,path)

def run_json(cmd, timeout):
    p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,check=False,env=dict(os.environ),timeout=timeout)
    payload=None
    for line in reversed(p.stdout.splitlines()):
        try:
            v=json.loads(line)
            if isinstance(v,dict):
                payload=v
                break
        except Exception:
            pass
    return p,payload

def cycle(mesh_root, node_state_root, hb_epoch=None):
    script=ROOT/"resident-runtime"/"federation_cycle.py"
    # The cycle takes a supplied epoch and refuses without one; the executor
    # passes on what its materializer supplied and reads none from a clock.
    epoch=[] if hb_epoch is None else ["--hb-epoch",hb_epoch]
    p,result=run_json([sys.executable,str(script),"--mesh-root",str(mesh_root),"--node-state-root",str(node_state_root),*epoch],120)
    if p.returncode!=0:
        # A refused cycle prints its six-field refusal; it is carried, not just stderr.
        raise RuntimeError("federation cycle failed: "+(json.dumps(result,sort_keys=True) if result else p.stderr[-1024:]))
    return result

# The cycle records each attempted transition with its own disposition and
# exits 0 once it has recorded them. Its exit code says the cycle ran, not that
# what it attempted was allowed, so the executor reads the dispositions.
CHILD_TRANSITIONS=("consumption","repository_propagation")
NOT_ALLOWED=("DENY","FAIL_CLOSED")

def failed_transitions(fed):
    """Every transition the cycle recorded as DENY or FAIL_CLOSED, with its predicate."""
    if not isinstance(fed,dict):
        return [{"transition":"federation_cycle","disposition":"FAIL_CLOSED",
                 "failed_predicate":"FEDERATION_CYCLE_RECEIPT_ABSENT"}]
    rows=[(name,fed.get(name)) for name in CHILD_TRANSITIONS]
    rows+=[("governance_return",item) for item in (fed.get("governance_returns") or [])]
    failed=[]
    for name,value in rows:
        if isinstance(value,dict) and value.get("disposition") in NOT_ALLOWED:
            failed.append({"transition":name,"disposition":value["disposition"],
                           "failed_predicate":value.get("failed_predicate"),
                           "retry_entrypoint":value.get("retry_entrypoint")})
    return failed

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--mesh-root",type=Path,required=True)
    ap.add_argument("--node-state-root",type=Path,required=True)
    ap.add_argument("--hb-epoch",default=None,help="supplied heartbeat epoch, passed to the federation cycle")
    a=ap.parse_args()
    bad=[k for k in HOSTED if truthy(os.getenv(k))]
    if bad:
        raise SystemExit("hosted runtime prohibited: "+",".join(bad))
    error=None
    try:
        fed=cycle(a.mesh_root,a.node_state_root,a.hb_epoch)
    except Exception as exc:
        fed=None
        error=str(exc)
    failed=[] if error is not None else failed_transitions(fed)
    allowed=error is None and not failed
    state={
        "schema":"stegverse.organization-resident-executor/v2",
        "organization":"StegVerse-org",
        "observed_at":datetime.now(timezone.utc).isoformat(),
        "materialization":"ONE_CYCLE_PER_INVOCATION",
        "disposition":"ALLOW" if allowed else "FAIL_CLOSED",
        "failed_predicate":(None if allowed else
                            "FEDERATION_CYCLE_FAILED" if error is not None else
                            "FEDERATION_CYCLE_TRANSITION_NOT_ALLOWED"),
        "failed_transitions":failed,
        "federation_cycle":fed,
        "error":error,
        "retry_entrypoint":None if allowed else (
            "resident-runtime/resident_executor.py" if error is not None else
            failed[0]["retry_entrypoint"] or "resident-runtime/resident_executor.py"),
        "github_actions_runtime_authority":"NONE",
        "authority_effect":"NONE_EXECUTOR_ONLY",
    }
    # Recorded in the node state this materialization was given, not the checkout.
    atomic_json(Path(a.node_state_root)/"resident-runtime"/"resident-executor.latest.json",state)
    print(json.dumps(state,sort_keys=True),flush=True)
    return 0 if state["disposition"]=="ALLOW" else 2

if __name__=="__main__":
    raise SystemExit(main())
