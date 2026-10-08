#!/usr/bin/env python3
"""Organization-local projection of the canonical federation directory.

The federation directory has one canonical source. Every organization's
`org-boundary/registry/federation.json` is a projection of it: the canonical
entries unchanged, plus the exact source they were projected from. A projection
is read locally, so no crossing waits on a remote directory, and it is updated
only by re-projecting from the canonical source. A local addition is drift, not
a peer: an organization absent from the canonical directory is added there.

Projection grants no routing, admission or transition authority.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[2]
PROJECTION_PATH=ROOT/"org-boundary/registry/federation.json"
CANONICAL_REPOSITORY="StegVerse-Labs/.github"
CANONICAL_PATH="org-boundary/registry/federation.json"
RULE="CANONICAL_ENTRIES_UNCHANGED_LOCAL_ADDITIONS_PROHIBITED_UPDATE_BY_REPROJECTION"

def canon(v:Any)->bytes: return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def sha(v:Any)->str: return "sha256:"+hashlib.sha256(v if isinstance(v,(bytes,bytearray)) else canon(v)).hexdigest()

def directory_body(directory:dict[str,Any])->dict[str,Any]:
    """The canonical part of a directory: everything except projection provenance."""
    return {k:v for k,v in directory.items() if k!="projection"}

def project(canonical_bytes:bytes, *, source_commit:str, source_repository:str=CANONICAL_REPOSITORY,
            source_path:str=CANONICAL_PATH)->dict[str,Any]:
    canonical=json.loads(canonical_bytes)
    if "projection" in canonical: raise SystemExit("canonical directory must not itself be a projection")
    if canonical.get("denominator")!=len(canonical.get("organizations") or []):
        raise SystemExit("federation_directory_denominator_mismatch")
    return {**canonical,"projection":{
        "source_repository":source_repository,"source_path":source_path,"source_commit":source_commit,
        "source_sha256":sha(bytes(canonical_bytes)),"entries_sha256":sha(canonical),
        "rule":RULE,"authority_effect":"NONE_PROJECTION_ONLY"}}

def verify(projection:dict[str,Any], canonical_bytes:bytes|None=None)->dict[str,Any]:
    meta=projection.get("projection")
    if not isinstance(meta,dict): raise SystemExit("federation directory is not a declared projection")
    body=directory_body(projection)
    checks={"rule":meta.get("rule")==RULE,
            "entries_unchanged_since_projection":meta.get("entries_sha256")==sha(body),
            "denominator":body.get("denominator")==len(body.get("organizations") or [])}
    if canonical_bytes is not None:
        checks["matches_canonical"]=body==json.loads(canonical_bytes) and meta.get("source_sha256")==sha(bytes(canonical_bytes))
    return {"schema":"stegverse.federation-projection-verification/v1","checks":checks,"valid":all(checks.values()),
            "source_commit":meta.get("source_commit"),"authority_effect":"NONE_VALIDATION_ONLY"}

def main()->int:
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="cmd",required=True)
    v=sub.add_parser("verify"); v.add_argument("--canonical")
    r=sub.add_parser("reproject"); r.add_argument("--canonical",required=True); r.add_argument("--source-commit",required=True)
    ns=p.parse_args()
    if ns.cmd=="reproject":
        PROJECTION_PATH.write_text(json.dumps(project(Path(ns.canonical).read_bytes(),source_commit=ns.source_commit),indent=2,ensure_ascii=False)+"\n")
    out=verify(json.loads(PROJECTION_PATH.read_text()),Path(ns.canonical).read_bytes() if ns.canonical else None)
    print(json.dumps(out,sort_keys=True)); return 0 if out["valid"] else 1

if __name__=="__main__": raise SystemExit(main())
