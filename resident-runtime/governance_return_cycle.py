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


RETRY_ENTRYPOINT = "resident-runtime/governance_return_cycle.py::run"


def _refused(refusal):
    """A cycle that consumed nothing for want of custody: the frames stay on the mesh,
    and the run says why with the six fields of a non-ALLOW rather than aborting."""
    return {"schema": SCHEMA, "organization": K.load_registry(ROOT)["organization"], **refusal,
            "frames_seen": 0, "frames": [], "governance_returns": [],
            "authority_effect": "NONE_REFUSAL_ONLY"}


def run(*, mesh_root, node_state_root, hb_epoch=None, hb_epoch_source=None):
    if mesh_root is None:
        return _refused(cycle.mesh_location_refusal(retry_entrypoint=RETRY_ENTRYPOINT))
    # A cycle without a supplied epoch consumes nothing (§Q): it refuses
    # NOT_SUPPLIED before the mesh is read, so every frame stays pending on the
    # mesh, with no quarantine and no seen-marker, for a cycle that has one.
    refused = cycle.epoch_refused(hb_epoch)
    if refused is not None:
        return _refused({**refused, "retry_entrypoint": RETRY_ENTRYPOINT, "consequence_committed": False})
    repo_ledger_root = cycle.supplied_ledger("STEGVERSE_REPO_LEDGER_ROOT")
    org_ledger_root = cycle.supplied_ledger("STEGVERSE_ORG_LEDGER_ROOT")
    try:
        results = K.consume_and_respond(ROOT, mesh_root=mesh_root, node_state_root=node_state_root,
                                        repo_ledger_root=repo_ledger_root, org_ledger_root=org_ledger_root,
                                        hb_epoch=int(str(hb_epoch)), hb_epoch_source=hb_epoch_source)
    except ValueError as exc:
        if "ledger_location_required_from_materializer" not in str(exc):
            raise
        return _refused(cycle.ledger_location_refusal(retry_entrypoint=RETRY_ENTRYPOINT))
    returns = cycle.returns_for_consumed(results, mesh_root=mesh_root, hb_epoch=int(str(hb_epoch)))
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
    parser.add_argument("--hb-epoch", default=None,
                        help="the supplied heartbeat epoch (ASCII digits >= 32); without one nothing is consumed")
    parser.add_argument("--hb-epoch-source-json", default=None,
                        help="where the epoch came from (source COMMITTED_REQUEST and the request digest); recorded")
    args = parser.parse_args(argv)
    source = json.loads(args.hb_epoch_source_json) if args.hb_epoch_source_json else None
    result = run(mesh_root=args.mesh_root, node_state_root=args.node_state_root, hb_epoch=args.hb_epoch,
                 hb_epoch_source=source)
    text = json.dumps(result, indent=2, sort_keys=True, default=str)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(text)
    refused = [r for r in result["governance_returns"] if r.get("disposition") == "FAIL_CLOSED"]
    return 1 if refused or result.get("disposition") == "FAIL_CLOSED" else 0


if __name__ == "__main__":
    sys.exit(main())
