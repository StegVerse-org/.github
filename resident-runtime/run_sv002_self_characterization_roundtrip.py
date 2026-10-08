#!/usr/bin/env python3
"""Submit the frozen SV002 SDK self-characterization query as a manifest-bound transition.

This builds the exact frozen SDK request (StegVerse-SDK
external_interlock_bootstrap.build_sv002_first_interlock_request), carries it as
an InTr packet through this organization's SDK self-characterization egress,
and publishes the frame on the mesh this node was materialized with. That is
the whole action.

It does not run StegVerse-002's federation cycle or this organization's: each
organization consumes when it materializes, and an unavailable receiver is
answered by the durable mesh, never by waiting. It does not search the host
for checkouts or select a transport from the environment. The StegVerse-SDK
source, the mesh and the state location are supplied, or it refuses.
GitHub Actions and other hosted CI environments are rejected as runtime
authority, and credential-bearing environments are refused.
"""
from __future__ import annotations
import argparse, importlib.util, json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOSTED_ENV = ("GITHUB_ACTIONS","CI","RENDER","VERCEL","CF_PAGES","CLOUDFLARE_WORKERS")
FORBIDDEN_CREDENTIAL_ENV = (
    "GITHUB_TOKEN","GH_TOKEN","GITHUB_PAT","GITHUB_PERSONAL_ACCESS_TOKEN",
    "ACTIONS_RUNTIME_TOKEN","ACTIONS_ID_TOKEN_REQUEST_TOKEN",
)
SDK_BOOTSTRAP = "stegverse/external_interlock_bootstrap.py"


def truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() not in {"","0","false","no"}


def load_module(name: str, path: Path):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


def refusal(failed_predicate: str, repair: str) -> dict:
    return {"schema":"stegverse.sv002-sdk-query-submission/v1",
            "disposition":"FAIL_CLOSED","failed_predicate":failed_predicate,
            "required_evidence_or_repair":repair,
            "retry_entrypoint":"resident-runtime/run_sv002_self_characterization_roundtrip.py",
            "consequence_committed":False,"authority_effect":"NONE_REFUSAL_ONLY"}


def submit(*, sdk_root: Path, mesh_root: Path, state_root: Path, authority_ref: str) -> dict:
    if not (Path(sdk_root)/SDK_BOOTSTRAP).is_file():
        return refusal("STEGVERSE_SDK_SOURCE_SUPPLIED", "supply --sdk-root containing "+SDK_BOOTSTRAP)
    boot=load_module("sv002_sdk_bootstrap",Path(sdk_root)/SDK_BOOTSTRAP)
    egress=load_module("sv002_sdk_egress",ROOT/"resident-runtime/sdk_self_characterization_egress.py")
    kernel=egress.K
    request=boot.build_sv002_first_interlock_request(authority_ref)
    packet=egress.build_packet(request)
    frame=kernel.carrier_frame(packet)
    published=kernel.publish_frame(frame,root=mesh_root)
    state=Path(state_root).expanduser().resolve(); state.mkdir(parents=True,exist_ok=True)
    for name,value in (("SDK_REQUEST.json",request),("SDK_EGRESS_PACKET.json",packet),("SDK_EGRESS_FRAME.json",frame)):
        (state/name).write_text(json.dumps(value,indent=2,sort_keys=True)+"\n")
    receipt={
        "schema":"stegverse.sv002-sdk-query-submission/v1",
        "disposition":"ALLOW",
        "experiment_id":"STEGVERSE-002-SELF-CHARACTERIZATION-001",
        "manifest_sha256":request["bindings"]["manifest_sha256"],
        "packet_id":packet["packet_id"],
        "destination":packet["destination"],
        "transport":"INTERLOCK_INTR_SUPPLIED_MESH",
        "frame_locator":str(published),
        "receiver_consumes_on_its_own_materialization":True,
        "awaits_the_receiver":False,
        "principal_execution_owner":"StegVerse-002/.github",
        "principal_repository":"StegVerse-002/micro-node-runtime",
        "cross_organization_principal_execution":False,
        "github_actions_runtime_authority":"NONE",
        "authority_effect":"NONE_SUBMISSION_ONLY",
    }
    (state/"SUBMISSION_RECEIPT.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
    return receipt


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--authority-ref",default="SDK_EXTERNAL_EVALUATOR")
    ap.add_argument("--sdk-root",type=Path,required=True)
    ap.add_argument("--mesh-root",type=Path,required=True)
    ap.add_argument("--state-root",type=Path,required=True)
    args=ap.parse_args()
    hosted=[k for k in HOSTED_ENV if truthy(os.getenv(k))]
    if hosted: raise SystemExit("hosted runtime prohibited: "+",".join(hosted))
    creds=[k for k in FORBIDDEN_CREDENTIAL_ENV if truthy(os.getenv(k))]
    if creds: raise SystemExit("credential-bearing hosted/runtime environment prohibited: "+",".join(creds))
    receipt=submit(sdk_root=args.sdk_root,mesh_root=args.mesh_root,state_root=args.state_root,
                   authority_ref=args.authority_ref)
    print(json.dumps(receipt,sort_keys=True))
    return 0 if receipt["disposition"]=="ALLOW" else 1

if __name__=="__main__":
    raise SystemExit(main())
