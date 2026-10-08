#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("org_kernel",ROOT/"org-kernel"/"kernel.py")
K=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(K)
# Repositories in this organization append their own transitions to their own
# ledgers. `organization_scope_rule` is that every transition occurring within
# the organization emits an organization receipt, so carrying them up is part of
# the resident cycle rather than something a person runs by hand. It is
# intra-organization: no boundary is crossed and no InTr is involved.
PRSPEC=importlib.util.spec_from_file_location("propagate_repository_receipts",ROOT/"resident-runtime"/"propagate_repository_receipts.py")
PR=importlib.util.module_from_spec(PRSPEC); PRSPEC.loader.exec_module(PR)

def returns_for_consumed(results, *, mesh_root):
    """Materialize the governance return for each decision consumed in this cycle.

    The consumed answer is the event; nothing waits for it. The return operation
    and the SDK admission it imports load only when such an answer is consumed.
    """
    answers=[item["result"]["packet"] for item in results
             if (item.get("result") or {}).get("status")=="CONSUMED"
             and str((((item["result"].get("packet") or {}).get("payload")) or {}).get("communication_id") or "").startswith("governance:")]
    if not answers:
        return []
    spec=importlib.util.spec_from_file_location("governance_decision_return",ROOT/"resident-runtime"/"governance_decision_return.py")
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    out=[]
    for packet in answers:
        returned=module.return_on_consumption(packet, mesh_root=mesh_root)
        if returned is not None:
            out.append({key:returned.get(key) for key in (
              "disposition","trigger","decision_returned","governance_disposition","failed_predicate",
              "governance_request_packet_id","governance_communication_id","response_packet_id",
              "closure_transition_class","retry_entrypoint")})
    return out

def main(*, mesh_root:Path|None=None, node_state_root:Path|None=None):
    if node_state_root is None:
        raise SystemExit("NODE_STATE_LOCATION_REQUIRED_FROM_MATERIALIZER")
    # The carrier is the declared one: kernel frames over the mesh this node
    # was materialized with. Nothing in the host environment selects another.
    if mesh_root is None:
        raise SystemExit("MESH_LOCATION_REQUIRED_FROM_MATERIALIZER")
    results=K.consume_and_respond(ROOT, mesh_root=mesh_root)
    consumed=sum(1 for x in results if (x.get("result") or {}).get("status")=="CONSUMED")
    responses=sum(1 for x in results if x.get("response_publication"))
    governance_returns=returns_for_consumed(results, mesh_root=mesh_root)
    receipt={
      "schema_version":"stegverse.org-federation-cycle.v1",
      "organization":K.load_registry(ROOT)["organization"],
      "heartbeat_reference":K.hb_reference(),
      "frames_seen":len(results),
      "frames_consumed":consumed,
      "responses_emitted":responses,
      "authority_effect":"NONE_CARRIER_ONLY",
      "transport":"INTERLOCK_INTR_SUPPLIED_MESH"
    }
    if governance_returns:
        receipt["governance_returns"]=governance_returns
    # Propagated after the frames are handled, so a cycle that failed to consume
    # does not report having carried receipts it never reached.
    # Propagation is its own attempted transition. Without a supplied
    # repository ledger location it fails closed here and says so; the frames
    # above were already handled and are not undone or withheld by it.
    try:
        propagation=PR.propagate_all()
    except PR.organization_ledger.LedgerLocationRequired as exc:
        receipt["repository_propagation"]={
          "disposition":"FAIL_CLOSED",
          "failed_predicate":exc.failed_predicate,
          "required_evidence_or_repair":"supply "+exc.variable,
          "retry_entrypoint":"resident-runtime/propagate_repository_receipts.py::propagate_all",
          "consequence_committed":False,
          "crossed_an_organization_boundary":False,
          "interlock_intr_involved":False,
        }
    else:
        receipt["repository_propagation"]={
          "disposition":"ALLOW",
          "repositories_declared":propagation["repositories_declared"],
          "repositories_present":propagation["repositories_present"],
          "receipts_propagated":propagation["receipts_propagated"],
          "receipts_already_carried":propagation["receipts_already_carried"],
          "crossed_an_organization_boundary":False,
          "interlock_intr_involved":False,
        }
    # Recorded in this node's own state, through the seam that already owns
    # where node state lives. It was written into the repository checkout, which
    # made a run mutate committed space and kept only the most recent pass.
    # The cycle is addressed by what it reported, so the locator is returned to
    # the caller rather than written back into the document it addresses.
    recorded=K.record_federation_cycle(receipt, root=node_state_root)
    print(json.dumps({**receipt,"recorded_at":str(recorded)},sort_keys=True))
    return receipt

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--mesh-root", type=Path, default=None)
    ap.add_argument("--node-state-root", type=Path, required=True)
    args=ap.parse_args()
    main(mesh_root=args.mesh_root,node_state_root=args.node_state_root)
