#!/usr/bin/env python3
"""Run the frozen SV002 SDK self-characterization query through sovereign org runtimes.

This is a same-host/cross-org orchestration bridge. It never executes the
StegVerse-002 principal directly. It builds the exact frozen SDK request,
publishes it through the StegVerse-org boundary, invokes the StegVerse-002
organization federation cycle, then invokes the StegVerse-org response cycle.

If an HTTPS federation gateway is configured, the normal gateway path is used.
Otherwise the canonical same-host federation spool is used. GitHub Actions and
other hosted CI/runtime environments are rejected.
"""
from __future__ import annotations

import argparse, importlib.util, json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOSTED_ENV = ("GITHUB_ACTIONS","CI","RENDER","VERCEL","CF_PAGES","CLOUDFLARE_WORKERS")
FORBIDDEN_CREDENTIAL_ENV = (
    "GITHUB_TOKEN","GH_TOKEN","GITHUB_PAT","GITHUB_PERSONAL_ACCESS_TOKEN",
    "ACTIONS_RUNTIME_TOKEN","ACTIONS_ID_TOKEN_REQUEST_TOKEN",
)

def truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() not in {"","0","false","no"}

def candidates(env_name: str, org: str, repo: str) -> list[Path]:
    out=[]
    if os.getenv(env_name):
        out.append(Path(os.environ[env_name]).expanduser())
    home=Path.home()
    out += [
        home/".stegverse"/"repos"/org/repo,
        Path("/var/lib/stegverse/source")/org/repo,
        Path("/srv/stegverse/repos")/org/repo,
        Path("/opt/stegverse/repos")/org/repo,
    ]
    return [p.resolve() for p in out]

def resolve_repo(env_name: str, org: str, repo: str, required: tuple[str,...]) -> Path:
    for root in candidates(env_name,org,repo):
        if root.is_dir() and all((root/x).is_file() for x in required):
            return root
    raise RuntimeError(f"required local repository not materialized: {org}/{repo}")

def load_module(name: str, path: Path):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

def run_cycle(root: Path) -> dict:
    p=subprocess.run(
        [sys.executable,str(root/"resident-runtime/federation_cycle.py")],
        cwd=root,capture_output=True,text=True,check=False,env=dict(os.environ),timeout=2100,
    )
    if p.returncode != 0:
        raise RuntimeError(f"federation cycle failed for {root}: {p.stderr[-2000:]}")
    for line in reversed(p.stdout.splitlines()):
        try:
            v=json.loads(line)
            if isinstance(v,dict): return v
        except Exception:
            pass
    raise RuntimeError(f"federation cycle emitted no JSON: {root}")

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--authority-ref",default="SDK_EXTERNAL_EVALUATOR")
    ap.add_argument("--state-root",type=Path,default=Path.home()/".stegverse"/"sv002-sdk-query")
    args=ap.parse_args()

    hosted=[k for k in HOSTED_ENV if truthy(os.getenv(k))]
    if hosted: raise SystemExit("hosted runtime prohibited: "+",".join(hosted))
    creds=[k for k in FORBIDDEN_CREDENTIAL_ENV if truthy(os.getenv(k))]
    if creds: raise SystemExit("credential-bearing hosted/runtime environment prohibited: "+",".join(creds))

    sdk=resolve_repo(
        "STEGVERSE_SDK_SOURCE_ROOT","StegVerse-org","StegVerse-SDK",
        ("stegverse/external_interlock_bootstrap.py",)
    )
    target=resolve_repo(
        "STEGVERSE_SV002_ORG_ROOT","StegVerse-002",".github",
        ("resident-runtime/federation_cycle.py","resident-runtime/self_characterization_surface.py")
    )
    principal=resolve_repo(
        "STEGVERSE_MICRO_NODE_RUNTIME_ROOT","StegVerse-002","micro-node-runtime",
        ("tools/run_self_characterization_principal.py",
         "experiments/self-characterization-001/EXPERIMENT_CONTRACT.v0.3.json")
    )
    os.environ["STEGVERSE_MICRO_NODE_RUNTIME_ROOT"]=str(principal)

    boot=load_module("sv002_sdk_bootstrap",sdk/"stegverse/external_interlock_bootstrap.py")
    egress=load_module("sv002_sdk_egress",ROOT/"resident-runtime/sdk_self_characterization_egress.py")
    kernel=load_module("sv002_source_kernel",ROOT/"org-kernel/kernel.py")
    gateway=load_module("sv002_source_gateway",ROOT/"resident-runtime/federation_gateway_transport.py")

    state=args.state_root.expanduser().resolve(); state.mkdir(parents=True,exist_ok=True)
    request=boot.build_sv002_first_interlock_request(args.authority_ref)
    request_path=state/"SDK_REQUEST.json"
    request_path.write_text(json.dumps(request,indent=2,sort_keys=True)+"\n")

    packet=egress.build_packet(request)
    frame=kernel.carrier_frame(packet)
    packet_path=state/"SDK_EGRESS_PACKET.json"
    frame_path=state/"SDK_EGRESS_FRAME.json"
    packet_path.write_text(json.dumps(packet,indent=2,sort_keys=True)+"\n")
    frame_path.write_text(json.dumps(frame,indent=2,sort_keys=True)+"\n")

    if os.getenv("STEGVERSE_ORG_FEDERATION_GATEWAY_URL","").strip():
        submitted=gateway.submit_frame(frame)
        transport="SHARED_SERVICE_GATEWAY"
    else:
        spool_path=kernel.publish_frame(frame)
        submitted={"state":"PENDING","path":str(spool_path)}
        transport="LOCAL_SPOOL_FALLBACK"

    target_cycle=run_cycle(target)
    source_cycle=run_cycle(ROOT)

    receipt={
        "schema":"stegverse.sv002-sdk-query-roundtrip/v1",
        "experiment_id":"STEGVERSE-002-SELF-CHARACTERIZATION-001",
        "manifest_sha256":request["bindings"]["manifest_sha256"],
        "packet_id":packet["packet_id"],
        "transport":transport,
        "submission_state":submitted.get("state"),
        "target_cycle":target_cycle,
        "source_cycle":source_cycle,
        "principal_execution_owner":"StegVerse-002/.github",
        "principal_repository":"StegVerse-002/micro-node-runtime",
        "cross_organization_principal_execution":False,
        "github_actions_runtime_authority":"NONE",
        "authority_effect":"NONE_ORCHESTRATION_ONLY",
    }
    out=state/"ROUNDTRIP_RECEIPT.json"
    out.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
    print(json.dumps(receipt,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
