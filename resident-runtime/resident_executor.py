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

def cycle(mesh_root, node_state_root):
    script=ROOT/"resident-runtime"/"federation_cycle.py"
    p,result=run_json([sys.executable,str(script),"--mesh-root",str(mesh_root),"--node-state-root",str(node_state_root)],120)
    if p.returncode!=0:
        raise RuntimeError("federation cycle failed: "+p.stderr[-1024:])
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--mesh-root",type=Path,required=True)
    ap.add_argument("--node-state-root",type=Path,required=True)
    a=ap.parse_args()
    bad=[k for k in HOSTED if truthy(os.getenv(k))]
    if bad:
        raise SystemExit("hosted runtime prohibited: "+",".join(bad))
    error=None
    try:
        fed=cycle(a.mesh_root,a.node_state_root)
    except Exception as exc:
        fed=None
        error=str(exc)
    state={
        "schema":"stegverse.organization-resident-executor/v2",
        "organization":"StegVerse-org",
        "observed_at":datetime.now(timezone.utc).isoformat(),
        "materialization":"ONE_CYCLE_PER_INVOCATION",
        "disposition":"ALLOW" if error is None else "FAIL_CLOSED",
        "federation_cycle":fed,
        "error":error,
        "retry_entrypoint":None if error is None else "resident-runtime/resident_executor.py",
        "github_actions_runtime_authority":"NONE",
        "authority_effect":"NONE_EXECUTOR_ONLY",
    }
    # Recorded in the node state this materialization was given, not the checkout.
    atomic_json(Path(a.node_state_root)/"resident-runtime"/"resident-executor.latest.json",state)
    print(json.dumps(state,sort_keys=True),flush=True)
    return 0 if error is None else 2

if __name__=="__main__":
    raise SystemExit(main())
