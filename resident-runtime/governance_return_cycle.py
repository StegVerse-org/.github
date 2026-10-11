#!/usr/bin/env python3
"""Consume the frames addressed to this organization and materialize each governance return.

The federation cycle's consumption and return, without its repository-receipt
propagation (resident-runtime/federation_cycle.py runs that as a separate
transition). Every consumed crossing is recorded on both ledgers at the
locations the materializer supplies before it is answered or marked, and a
consumed governance decision is returned through
resident-runtime/governance_decision_return.py, which verifies it against this
organization's own emission record and hands it to the SDK. Nothing waits: an
absent answer is an observation, and the frames stay on the mesh, the durable
queue.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "stegverse.organization-governance-return-cycle/v1"


def _module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cycle = _module("governance_return_cycle_federation", "resident-runtime/federation_cycle.py")
K = cycle.K


def run(*, mesh_root, node_state_root):
    if mesh_root is None:
        raise SystemExit("MESH_LOCATION_REQUIRED_FROM_MATERIALIZER")
    repo_ledger_root = cycle.supplied_ledger("STEGVERSE_REPO_LEDGER_ROOT")
    org_ledger_root = cycle.supplied_ledger("STEGVERSE_ORG_LEDGER_ROOT")
    results = K.consume_and_respond(ROOT, mesh_root=mesh_root, node_state_root=node_state_root,
                                    repo_ledger_root=repo_ledger_root, org_ledger_root=org_ledger_root)
    returns = cycle.returns_for_consumed(results, mesh_root=mesh_root)
    return {
        "schema": SCHEMA,
        "organization": K.load_registry(ROOT)["organization"],
        "frames_seen": len(results),
        "frames": [{"path": str(item.get("path")),
                    "status": (item.get("result") or {}).get("status"),
                    "disposition": (item.get("result") or {}).get("disposition"),
                    "packet_id": ((item.get("result") or {}).get("packet") or {}).get("packet_id"),
                    "organization_record": item.get("organization_record")} for item in results],
        "governance_returns": returns,
        "authority_effect": "NONE_CARRIER_ONLY",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mesh-root", required=True, help="this organization's bound mesh locator")
    parser.add_argument("--node-state-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    result = run(mesh_root=args.mesh_root, node_state_root=args.node_state_root)
    text = json.dumps(result, indent=2, sort_keys=True, default=str)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(text)
    refused = [r for r in result["governance_returns"] if r.get("disposition") == "FAIL_CLOSED"]
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
