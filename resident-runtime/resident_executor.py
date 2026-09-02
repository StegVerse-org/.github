#!/usr/bin/env python3
"""Persistent StegVerse organization resident executor.

Continuously runs the canonical federation cycle. On StegVerse-org, it can also
consume the one-shot frozen SV002 SDK query request exactly once. GitHub Actions
and other hosted CI environments are rejected as runtime authority.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HOSTED=("GITHUB_ACTIONS","CI","RENDER","VERCEL","CF_PAGES","CLOUDFLARE_WORKERS")
STATE=ROOT/"resident-runtime"/"state"
SV002_TASK=ROOT/"resident-runtime"/"control"/"sv002-sdk-query.request.json"
SV002_RECEIPT=STATE/"sv002-sdk-query.execution.latest.json"
HEARTBEAT=STATE/"resident-executor.latest.json"

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

def consume_sv002_once():
    if not SV002_TASK.is_file():
        return None
    task=json.loads(SV002_TASK.read_text(encoding="utf-8"))
    if task.get("state")!="REQUESTED":
        return None
    if SV002_RECEIPT.is_file():
        prior=json.loads(SV002_RECEIPT.read_text(encoding="utf-8"))
        if prior.get("task_id")==task.get("task_id") and prior.get("terminal") is True:
            return prior
    script=ROOT/"resident-runtime"/"run_sv002_self_characterization_roundtrip.py"
    if not script.is_file():
        raise RuntimeError("SV002 roundtrip runtime missing")
    p,result=run_json([sys.executable,str(script),"--authority-ref",task["authority_ref"]],2200)
    receipt={
        "schema":"stegverse.resident-one-shot-execution/v1",
        "task_id":task["task_id"],
        "attempted_at":datetime.now(timezone.utc).isoformat(),
        "returncode":p.returncode,
        "result":result,
        "stdout_tail":p.stdout[-8192:],
        "stderr_tail":p.stderr[-8192:],
        "terminal":bool(p.returncode==0 and isinstance(result,dict)),
        "github_actions_runtime_authority":"NONE",
        "authority_effect":"NONE_EXECUTOR_ONLY",
    }
    atomic_json(SV002_RECEIPT,receipt)
    return receipt

def cycle():
    script=ROOT/"resident-runtime"/"federation_cycle.py"
    p,result=run_json([sys.executable,str(script)],120)
    if p.returncode!=0:
        raise RuntimeError("federation cycle failed: "+p.stderr[-1024:])
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--once",action="store_true")
    ap.add_argument("--poll-seconds",type=float,default=1.0)
    a=ap.parse_args()
    bad=[k for k in HOSTED if truthy(os.getenv(k))]
    if bad:
        raise SystemExit("hosted runtime prohibited: "+",".join(bad))
    iteration=0
    while True:
        iteration+=1
        sv002=None
        error=None
        try:
            sv002=consume_sv002_once()
            fed=cycle()
        except Exception as exc:
            fed=None
            error=str(exc)
        state={
            "schema":"stegverse.organization-resident-executor/v1",
            "organization":"StegVerse-org",
            "observed_at":datetime.now(timezone.utc).isoformat(),
            "iteration":iteration,
            "state":"RUNNING" if error is None else "DEGRADED",
            "federation_cycle":fed,
            "sv002_one_shot":sv002,
            "error":error,
            "persistent":not a.once,
            "github_actions_runtime_authority":"NONE",
            "authority_effect":"NONE_EXECUTOR_ONLY",
        }
        atomic_json(HEARTBEAT,state)
        print(json.dumps(state,sort_keys=True),flush=True)
        if a.once:
            return 0 if error is None else 2
        time.sleep(max(0.25,a.poll_seconds))

if __name__=="__main__":
    raise SystemExit(main())
