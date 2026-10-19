#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, json, os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("org_kernel",ROOT/"org-kernel"/"kernel.py")
K=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(K)
LSSPEC=importlib.util.spec_from_file_location("ledger_store",ROOT/"resident-runtime"/"ledger_store.py")
LS=importlib.util.module_from_spec(LSSPEC); LSSPEC.loader.exec_module(LS)
# Repositories in this organization append their own transitions to their own
# ledgers. `organization_scope_rule` is that every transition occurring within
# the organization emits an organization receipt, so carrying them up is part of
# the resident cycle rather than something a person runs by hand. It is
# intra-organization: no boundary is crossed and no InTr is involved.
PRSPEC=importlib.util.spec_from_file_location("propagate_repository_receipts",ROOT/"resident-runtime"/"propagate_repository_receipts.py")
PR=importlib.util.module_from_spec(PRSPEC); PRSPEC.loader.exec_module(PR)

def returns_for_consumed(results, *, mesh_root, hb_epoch=None):
    """Materialize the governance return for each decision consumed in this cycle.

    The consumed answer is the event; nothing waits for it. The return operation
    and the SDK admission it imports load only when such an answer is consumed.
    """
    answers=[item for item in results
             if (item.get("result") or {}).get("status")=="CONSUMED"
             and str((((item["result"].get("packet") or {}).get("payload")) or {}).get("communication_id") or "").startswith("governance:")]
    if not answers:
        return []
    module=None
    mesh=K.mesh_store(mesh_root)
    out=[]
    for item in answers:
        # Without a cycle epoch the closure is stamped with the supplied epoch of the answer frame it observes,
        # as the kernel stamps an answer with the epoch of the frame it answers:
        # consuming the same answer again (a fresh node state, a further run)
        # then returns the closure already recorded instead of minting another.
        frame=mesh.get(K.node_store_module.MESH_FRAME_PREFIX+K.node_store_module.frame_name(str(item["path"])))
        reference=(frame or {}).get("heartbeat_reference") or {}
        if "epoch_lent" in item["result"] or K.supplied_epoch_failure(reference.get("epoch"),reference) is not None:
            # A consumed CLOCK answer lends no epoch (NARROW S1), and an unmarked or
            # clock-flagged reference is not a supplied one: the closure is never
            # stamped from it (F10). It refuses NOT_SUPPLIED and nothing is appended.
            out.append(clock_answer_refusal(item["result"]["packet"]))
            continue
        if module is None:
            spec=importlib.util.spec_from_file_location("governance_decision_return",ROOT/"resident-runtime"/"governance_decision_return.py")
            module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        # F1: the closure is this organization's transition. In a cycle with its own
        # supplied epoch it is stamped with that epoch (K.EPOCH_RESOLUTION), never
        # with the deciding organization's; the answer frame is named by its packet.
        returned=module.return_on_consumption(item["result"]["packet"], mesh_root=mesh_root,
                                              hb_epoch=reference.get("epoch") if hb_epoch is None else hb_epoch)
        if returned is not None:
            out.append({key:returned.get(key) for key in (
              "disposition","trigger","decision_returned","governance_disposition","governance_failed_predicate","failed_predicate",
              "governance_request_packet_id","governance_communication_id","response_packet_id",
              "closure_transition_class","closure_organization_receipt_sha256",
              "deciding_organization_receipt_sha256","retry_entrypoint")})
    return out

def clock_answer_refusal(packet):
    """The six-field NOT_SUPPLIED refusal of returning a decision whose answer frame lent no epoch."""
    payload=packet.get("payload") or {}
    return {"disposition":"FAIL_CLOSED","trigger":"DECISION_FRAME_CONSUMED","decision_returned":False,
            "failure_code":"HB_EPOCH_NOT_SUPPLIED",
            "failed_predicate":PR.organization_ledger.HB_EPOCH_PREDICATE,
            "required_evidence_or_repair":"the deciding organization republishes its answer with a supplied epoch",
            "retry_entrypoint":"resident-runtime/governance_decision_return.py::return_on_consumption",
            "owning_existing_goal":PR.organization_ledger.INTR_PROTOCOL_GOAL,
            "next_attempt":"on a republished answer with a supplied epoch; the clock-stamped one is consumed and "
                           "nothing was appended for it",
            "governance_request_packet_id":(payload.get("body") or {}).get("request_packet_id"),
            "governance_communication_id":payload.get("communication_id"),
            "response_packet_id":packet.get("packet_id")}

def ledger_location_refusal(*, retry_entrypoint):
    """The consumption's own six-field disposition when the kernel refused custody for
    want of a ledger location. Shared with resident-runtime/governance_return_cycle.py,
    which consumes through the same kernel call."""
    return {"disposition":"FAIL_CLOSED",
            "failure_code":PR.organization_ledger.LOCATION_FAILURE_CODE,
            "failed_predicate":"LEDGER_LOCATION_REQUIRED_FROM_MATERIALIZER",
            "required_evidence_or_repair":"supply STEGVERSE_REPO_LEDGER_ROOT and STEGVERSE_ORG_LEDGER_ROOT",
            "retry_entrypoint":retry_entrypoint,
            "owning_existing_goal":PR.organization_ledger.LOCATION_OWNING_GOAL,
            "next_attempt":PR.organization_ledger.location_next_attempt("STEGVERSE_REPO_LEDGER_ROOT and STEGVERSE_ORG_LEDGER_ROOT"),
            "consequence_committed":False}

def mesh_location_refusal(*, retry_entrypoint):
    """The same six fields when no mesh location was supplied: the carrier is the
    declared one, and nothing in the host environment selects another."""
    return {"disposition":"FAIL_CLOSED",
            "failure_code":"MESH_LOCATION_NOT_SUPPLIED",
            "failed_predicate":"MESH_LOCATION_REQUIRED_FROM_MATERIALIZER",
            "required_evidence_or_repair":"supply --mesh-root as the bound mesh locator (resident-runtime/mesh_locator_binding.py)",
            "retry_entrypoint":retry_entrypoint,
            "owning_existing_goal":PR.organization_ledger.LOCATION_OWNING_GOAL,
            "next_attempt":PR.organization_ledger.location_next_attempt("the mesh locator"),
            "consequence_committed":False}

def supplied_ledger(variable):
    """A ledger location as this organization's materializer supplies it, or None.

    The same interface the repository and organization emitters read. The
    kernel never reads it; the cycle passes what it was given explicitly.
    """
    value=os.environ.get(variable)
    return LS.parse_locator(value) if value else None

CLI_ENTRYPOINT="resident-runtime/federation_cycle.py (--hb-epoch)"

def epoch_refused(hb_epoch):
    """The six-field refusal of a supplied epoch, by the organization writer's rule, or None."""
    refusal=PR.organization_ledger.epoch_refusal(hb_epoch)
    return None if refusal is None else {**refusal,"retry_entrypoint":CLI_ENTRYPOINT}

def main(*, mesh_root:Path|None=None, node_state_root:Path|None=None,
         repo_ledger_root:Path|None=None, org_ledger_root:Path|None=None, hb_epoch=None):
    if node_state_root is None:
        raise SystemExit("NODE_STATE_LOCATION_REQUIRED_FROM_MATERIALIZER")
    # The carrier is the declared one: kernel frames over the mesh this node
    # was materialized with. Nothing in the host environment selects another.
    if mesh_root is None:
        raise SystemExit("MESH_LOCATION_REQUIRED_FROM_MATERIALIZER")
    # The epoch is supplied and checked as typed after the locations, before anything is
    # read or written, and the cycle record is stamped with it. It used to be accepted
    # and then ignored: every cycle was stamped from the host clock. An absent
    # one is HB_EPOCH_NOT_SUPPLIED; a refused write beats a clock-stamped record.
    refused=epoch_refused(hb_epoch)
    if refused is not None:
        raise PR.organization_ledger.OrgLedgerEpochRefused(refused)
    hb_epoch=int(str(hb_epoch))
    repo_ledger_root=repo_ledger_root or supplied_ledger("STEGVERSE_REPO_LEDGER_ROOT")
    org_ledger_root=org_ledger_root or supplied_ledger("STEGVERSE_ORG_LEDGER_ROOT")
    # Consuming a crossing is a transition within the organization, so it is
    # recorded on both ledgers before it is answered or marked. Without both
    # locations nothing is consumed: the frames stay in the mesh, which is the
    # durable queue, and the cycle says why rather than aborting.
    consumption={"disposition":"ALLOW"}
    try:
        results=K.consume_and_respond(ROOT, mesh_root=mesh_root, node_state_root=node_state_root,
                                      repo_ledger_root=repo_ledger_root, org_ledger_root=org_ledger_root,
                                      hb_epoch=hb_epoch)
    except ValueError as exc:
        if "ledger_location_required_from_materializer" not in str(exc):
            raise
        results=[]
        consumption=ledger_location_refusal(retry_entrypoint="resident-runtime/federation_cycle.py::main")
    # A frame the kernel refused without a DENY is recorded but left unmarked for
    # the next pass; the consumption did not complete for it and is not ALLOW.
    # A DENY is the frame's governed outcome, recorded and marked like any other.
    failed_frames=[{"path":str(x.get("path")),
                    "packet_id":(x.get("result") or {}).get("packet_id"),
                    "disposition":(x.get("result") or {}).get("disposition"),
                    "failed_predicate":(x.get("result") or {}).get("failed_predicate")}
                   for x in results if (x.get("result") or {}).get("status")=="REFUSED"
                   and (x.get("result") or {}).get("disposition")!="DENY"]
    if consumption.get("disposition")=="ALLOW" and failed_frames:
        consumption={"disposition":"FAIL_CLOSED",
                     "failed_predicate":"FEDERATION_FRAME_CONSUMPTION_NOT_COMPLETED",
                     "failed_frames":failed_frames,
                     "retry_entrypoint":"resident-runtime/federation_cycle.py::main",
                     "consequence_committed":False}
    consumed=sum(1 for x in results if (x.get("result") or {}).get("status")=="CONSUMED")
    responses=sum(1 for x in results if x.get("response_publication"))
    governance_returns=returns_for_consumed(results, mesh_root=mesh_root, hb_epoch=hb_epoch)
    receipt={
      "schema_version":"stegverse.org-federation-cycle.v1",
      "organization":K.load_registry(ROOT)["organization"],
      "heartbeat_reference":K.hb_reference(epoch=hb_epoch),
      "frames_seen":len(results),
      "frames_consumed":consumed,
      "frames_denied":sum(1 for x in results if (x.get("result") or {}).get("status")=="REFUSED"
                          and (x.get("result") or {}).get("disposition")=="DENY"),
      "consumption":consumption,
      "organization_receipts_recorded":sum(1 for x in results if x.get("organization_record")),
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
        propagation=PR.propagate_all(hb_epoch=hb_epoch)
    except PR.organization_ledger.OrgLedgerEpochRefused as exc:
        receipt["repository_propagation"]={**exc.refusal,
          "consequence_committed":False,
          "crossed_an_organization_boundary":False,
          "interlock_intr_involved":False}
    except PR.organization_ledger.LedgerLocationRequired as exc:
        receipt["repository_propagation"]={
          "disposition":"FAIL_CLOSED",
          "failure_code":PR.organization_ledger.LOCATION_FAILURE_CODE,
          "failed_predicate":exc.failed_predicate,
          "required_evidence_or_repair":"supply "+exc.variable,
          "retry_entrypoint":"resident-runtime/propagate_repository_receipts.py::propagate_all",
          "owning_existing_goal":PR.organization_ledger.LOCATION_OWNING_GOAL,
          "next_attempt":PR.organization_ledger.location_next_attempt(exc.variable),
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

def cli():
    ap=argparse.ArgumentParser()
    ap.add_argument("--mesh-root", type=Path, default=None)
    ap.add_argument("--node-state-root", type=Path, required=True)
    ap.add_argument("--hb-epoch", default=None, help="supplied carrier heartbeat epoch (never sampled)")
    args=ap.parse_args()
    try:
        main(mesh_root=args.mesh_root,node_state_root=args.node_state_root,hb_epoch=args.hb_epoch)
    except PR.organization_ledger.OrgLedgerEpochRefused as exc:
        print(json.dumps(exc.refusal,sort_keys=True)); raise SystemExit(1)
    return 0

if __name__=="__main__":
    import importlib.util as _writer_util
    _writer_spec = _writer_util.spec_from_file_location("writer_cli", Path(__file__).resolve().parent / "writer_cli.py")
    _writer = _writer_util.module_from_spec(_writer_spec); _writer_spec.loader.exec_module(_writer)
    raise SystemExit(_writer.run(cli, "resident-runtime/federation_cycle.py (--hb-epoch)"))
