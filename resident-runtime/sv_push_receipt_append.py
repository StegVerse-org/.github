#!/usr/bin/env python3
"""``sv_push_receipt`` -- append one push-range receipt to the organization ledger.

Port of the StegVerse-Labs/.github#3424 operation to this organization's own writer
(StegVerse-org/.github#167; Coordination ruling: a push receipt belongs on the ledger of the organization that owns
the pushed repository, and each organization keeps its own ledger). Lane B owns this writer.

``resident-runtime/sv_push_receipt.py`` (the pushing session's producer) emits a sealed
``stegverse.sv_push_receipt.v1`` for a push it just made: repository, ref, old_sha, new_sha, pusher_session,
pushed_commits and a supplied hb_epoch. It never appends. It becomes a ledger receipt only when this writer operation
appends it to refs/stegverse/organization-ledger (BRANCH_WRITER_IS_DERIVED_FROM_THE_PUSH_RECEIPT_CHAIN).

Layout, the two levels every receipt of this ledger has (nothing new in the ledger format):
  * repository receipt (``stegverse.repo-transition-receipt/v1``): ``$.evidence`` IS the push receipt, byte-for-value,
    self-identified by ``$.evidence.schema``. ``transition_class`` SV_PUSH_RECEIPT_APPEND.
  * organization receipt (``stegverse.organization-transition-receipt/v1``): ``boundary_evidence.operation ==
    "sv_push_receipt"``, ``repo_receipt_sha256`` naming the repository receipt kept at ``source-receipts/<hex>.json``.

One receipt per push range. The range is (repository, ref, old_sha, new_sha). Its transition id is derived from that
range alone (not from the receipt bytes, the pusher or the epoch), so a second receipt for a range the ledger already
holds is refused as a duplicate (FAIL_CLOSED SV_PUSH_RECEIPT_RANGE_ALREADY_RECORDED, nothing appended), whether it is
byte-identical or differs in any field. The lookup and both appends run under the writer workflow's
ORGANIZATION_LEDGER_LOCK (concurrency group organization-ledger); the ledger store's own compare-on-HEAD transaction
backs each append, and the ref moves only by the workflow's fast-forward publish.

Admission, all before any write:
  * the evidence is one object whose schema is stegverse.sv_push_receipt.v1 and which passes the producer's own
    ``sv_push_receipt.receipt_problem`` (closed field set, 40-hex shas, pushed_commits ending at new_sha, supplied epoch,
    seal over the canonical body);
  * time is supplied only: the append epoch (an integer from the committed request) and the receipt's hb_epoch must both
    pass this writer's supplied_epoch_failure (resident-runtime/aggregate_repo_transition.py, the rule shared with
    organization_egress_boundary.py, source sha256 7f36f0e6...) and be equal. Absent, null, "", "null" or
    UNKNOWN_NOT_AUTHENTICALLY_OBSERVED -> FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED; any other malformed or unequal value ->
    DENY HB_EPOCH_MISMATCH. A stored receipt must carry a supplied (not clock-derived) epoch.

The verifier is clock-free and network-free: it reads the request, the receipt and the declared ledger store only.
Every refusal is a six-field FAIL_CLOSED with consequence_committed false. Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]

OPERATION_ID = "sv_push_receipt"
TRANSITION_CLASS = "SV_PUSH_RECEIPT_APPEND"
PROFILE_ID = "org-ledger-writer"
PUSH_RECEIPT_SCHEMA_ID = "stegverse.sv_push_receipt.v1"
RESULT_SCHEMA = "stegverse.org-sv-push-receipt-append-result/v1"
READBACK_SCHEMA = "stegverse.org-sv-push-receipt-readback/v1"
OWNING_GOAL = "StegVerse-org/.github#163 (BRANCH_WRITER_IS_DERIVED_FROM_THE_PUSH_RECEIPT_CHAIN)"
RETRY = "resident-runtime/sv_push_receipt_append.py::append_push_receipt"
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
EPOCH_MISMATCH = "HB_EPOCH_MISMATCH"
EPOCH_SOURCE_PREDICATE = "ADMISSION_HB_EPOCH_IS_A_SUPPLIED_EPOCH"
EPOCH_TIE_PREDICATE = "PUSH_RECEIPT_HB_EPOCH_EQUALS_APPEND_HB_EPOCH"
UNKNOWN_SENTINEL = "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"
UNOBSERVED_EPOCH_VALUES = ("", "null", UNKNOWN_SENTINEL)
RANGE_FIELDS = ("repository", "ref", "old_sha", "new_sha")


def _module(name: str, relative: str):
    if name in sys.modules:
        return sys.modules[name]
    runtime = str(ROOT / "resident-runtime")
    if runtime not in sys.path:
        sys.path.insert(0, runtime)
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# The same two-level writers the main-merge transfer appends through (intr_destination_ingress.py is not edited): the
# repository ledger (.stegverse/transition-ledger/emit.py) and the organization ledger
# (resident-runtime/aggregate_repo_transition.py) on resident-runtime/ledger_store.py.
ingress = _module("intr_destination_ingress_sv_push", "resident-runtime/intr_destination_ingress.py")
producer = _module("sv_push_receipt_producer_for_append", "resident-runtime/sv_push_receipt.py")
sha = ingress.sha
# The shared supplied-epoch rule: this writer's copy, pinned by the sha256 of its source (the digest
# resident-runtime/intr_hop.py pins for the egress boundary's byte-identical copy).
SHARED_RULE_SHA256 = "7f36f0e697cadc91acd27af121eee3fc460b887ec67cfa258727bfccec0ca5f8"
epoch_rule = ingress.organization_ledger.supplied_epoch_failure
KERNEL_RULE_SHA256 = hashlib.sha256(inspect.getsource(epoch_rule).encode("utf-8")).hexdigest()


def refusal(code: str, predicate: str, repair: str, next_attempt: str, **detail: Any) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "operation": OPERATION_ID, "disposition": "FAIL_CLOSED",
            "failure_code": code, "failed_predicate": predicate, "required_evidence_or_repair": repair,
            "retry_entrypoint": RETRY, "owning_existing_goal": OWNING_GOAL, "next_attempt": next_attempt,
            "consequence_committed": False, "authority_effect": "NONE_REFUSAL_ONLY", **detail}


def range_key(receipt: Mapping[str, Any]) -> dict[str, str]:
    return {name: receipt[name] for name in RANGE_FIELDS}


def range_id(receipt: Mapping[str, Any]) -> str:
    """The hex that names a push range: sha256 of the canonical (repository, ref, old_sha, new_sha)."""
    return hashlib.sha256(json.dumps(range_key(receipt), sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def transition_id(receipt: Mapping[str, Any]) -> str:
    return TRANSITION_CLASS + ":" + range_id(receipt)


def push_payload(receipt: Any) -> dict[str, Any] | None:
    """None when `receipt` is a complete, sealed, self-identified sv-push-receipt.v1; otherwise the refusal."""
    if not isinstance(receipt, dict) or receipt.get("schema") != PUSH_RECEIPT_SCHEMA_ID:
        return refusal("LEDGER_EVIDENCE_NOT_A_PUSH_RECEIPT", "ORGANIZATION_LEDGER_EVIDENCE_IS_A_SELF_IDENTIFYING_PUSH_RECEIPT",
                       "supply the push receipt exactly as resident-runtime/sv_push_receipt.py emit wrote it; its $.schema is "
                       + PUSH_RECEIPT_SCHEMA_ID, "commit the ingest request again with the emitted receipt; nothing was written")
    problem = producer.receipt_problem(receipt)
    if problem is not None:
        return refusal("SV_PUSH_RECEIPT_MALFORMED", "PUSH_RECEIPT_PASSES_THE_PRODUCERS_OWN_SHAPE_AND_SEAL_CHECK",
                       "an unaltered " + PUSH_RECEIPT_SCHEMA_ID + " receipt: closed field set, 40-hex shas, pushed_commits ending "
                       "at new_sha, a supplied hb_epoch and a result_sha256 over its canonical body (the check that failed: "
                       + problem + ")", "commit the ingest request again with the emitted receipt; nothing was written",
                       problem=problem)
    return None


def _unobserved_value(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value in UNOBSERVED_EPOCH_VALUES)


def _unobserved(detail: str, **extra: Any) -> dict[str, Any]:
    return refusal("HB_EPOCH_SOURCE_UNOBSERVED", EPOCH_SOURCE_PREDICATE,
                   "supply the append epoch as an integer in the committed request and carry the same supplied epoch in the push "
                   "receipt; both must pass resident-runtime/aggregate_repo_transition.py::supplied_epoch_failure (SHARED_RULE_SHA256 " + SHARED_RULE_SHA256 + ")",
                   "after a supplied epoch is observed on both; nothing was written", detail=detail,
                   shared_rule_sha256=SHARED_RULE_SHA256, **extra)


def _mismatch(detail: str, **extra: Any) -> dict[str, Any]:
    out = refusal(EPOCH_MISMATCH, EPOCH_TIE_PREDICATE,
                  "append the receipt at the epoch it carries: the request's hb_epoch (an int) equals $.evidence.hb_epoch "
                  "(ASCII digits), both passing resident-runtime/aggregate_repo_transition.py::supplied_epoch_failure",
                  "commit the ingest request again with the receipt's own supplied epoch; nothing was written",
                  detail=detail, shared_rule_sha256=SHARED_RULE_SHA256, **extra)
    out["disposition"] = "DENY"
    return out


def _epoch_refusal(receipt: Mapping[str, Any], hb_epoch: Any) -> dict[str, Any] | None:
    if KERNEL_RULE_SHA256 != SHARED_RULE_SHA256:
        return _unobserved("resident-runtime/aggregate_repo_transition.py::supplied_epoch_failure is not the pinned shared rule",
                           kernel_rule_sha256=KERNEL_RULE_SHA256)
    mine = receipt.get("hb_epoch")
    for side, value in (("append epoch", hb_epoch), ("push receipt hb_epoch", mine)):
        if _unobserved_value(value):
            return _unobserved(side + " is absent, null, '', 'null' or " + UNKNOWN_SENTINEL, side=side, value=repr(value))
    bad = epoch_rule(hb_epoch)
    if bad is not None or type(hb_epoch) is not int:
        return _mismatch("append epoch " + repr(hb_epoch) + ": " + (bad[0] + ": " + bad[1] if bad else "not an int"),
                         hb_epoch=repr(hb_epoch), receipt_hb_epoch=repr(mine))
    bad = epoch_rule(mine)
    if bad is not None or not isinstance(mine, str):
        return _mismatch("push receipt hb_epoch " + repr(mine) + ": " + (bad[0] + ": " + bad[1] if bad else "not ASCII text"),
                         hb_epoch=hb_epoch, receipt_hb_epoch=repr(mine))
    if int(mine) != hb_epoch:
        return _mismatch("the receipt's epoch differs from the append epoch", hb_epoch=hb_epoch, receipt_hb_epoch=mine)
    return None


def _self_verifies(doc: Any) -> bool:
    return isinstance(doc, dict) and doc.get("receipt_sha256") == sha({k: v for k, v in doc.items() if k != "receipt_sha256"})


def _stored_epoch_refusal(row: Any, hb_epoch: int) -> dict[str, Any] | None:
    if not _self_verifies(row):
        return _unobserved("a stored receipt does not verify against its body")
    hb = row.get("hb_reference")
    ep = hb.get("epoch") if isinstance(hb, dict) else None
    if type(ep) is not int or epoch_rule(ep, hb) is not None or hb.get("derived_from_clock") is not False:
        return _unobserved("a stored hb_reference.epoch is not a supplied int epoch", receipt_sha256=row.get("receipt_sha256"))
    if ep != hb_epoch:
        out = refusal(EPOCH_MISMATCH, EPOCH_TIE_PREDICATE, "the stored receipt carries another epoch than this append",
                      "none; the recorded receipt stands", receipt_sha256=row.get("receipt_sha256"), stored_epoch=ep, hb_epoch=hb_epoch)
        out["disposition"] = "DENY"
        return out
    return None


def _duplicate(receipt: Mapping[str, Any], prior: Mapping[str, Any]) -> dict[str, Any]:
    recorded = prior.get("evidence") if isinstance(prior.get("evidence"), dict) else {}
    return refusal("SV_PUSH_RECEIPT_RANGE_ALREADY_RECORDED", "ONE_PUSH_RECEIPT_PER_REPOSITORY_REF_OLD_NEW_RANGE",
                   "the ledger already holds a receipt for " + receipt["repository"] + " " + receipt["ref"] + " "
                   + receipt["old_sha"][:12] + ".." + receipt["new_sha"][:12]
                   + "; a second receipt for the same range is a duplicate and is not minted, identical or not",
                   "none for this range: the recorded receipt is the evidence; a receipt for a different range (another old_sha or "
                   "new_sha) may be appended; nothing was written",
                   appended=False, range=range_key(receipt), range_id=range_id(receipt),
                   recorded_repository_receipt_sha256=prior.get("receipt_sha256"),
                   recorded_push_receipt_sha256=recorded.get("result_sha256"),
                   submitted_push_receipt_sha256=receipt.get("result_sha256"),
                   byte_identical_to_recorded=bool(recorded) and recorded == dict(receipt))


def _append_one(receipt: Mapping[str, Any], hb_epoch: int, predecessor: str, successor: str,
                boundary: Mapping[str, Any]) -> dict[str, Any]:
    """Both levels. The range lookup comes first and a recorded range is refused with nothing written, so a range is
    never minted twice. Returns the pair, or the duplicate refusal."""
    repository, organization = ingress.repository_ledger, ingress.organization_ledger
    tid = transition_id(receipt)
    store = repository.ledger_store.open_store(repository.lr())
    prior = ingress._ledger_write(repository.recorded, store, store.get(repository.ledger_store.HEAD_KEY), tid,
                                  TRANSITION_CLASS)
    if prior is not None:
        return _duplicate(receipt, prior)
    repository_receipt = ingress._ledger_write(repository.append, tid, TRANSITION_CLASS, predecessor, successor,
                                               dict(receipt), "NONE", hb_epoch=hb_epoch, idempotent_on=())
    # The organization receipt takes the repository receipt's epoch, as the main-merge transfer's does.
    organization_receipt = ingress._ledger_write(
        organization.append, repository_receipt, "REPO_STATE_PROPAGATION", predecessor, successor, dict(boundary),
        "NONE", hb_epoch=repository_receipt["hb_reference"]["epoch"], idempotent=True)
    return {"repository_receipt": repository_receipt, "organization_receipt": organization_receipt}


def append_push_receipt(receipt: Any, *, hb_epoch: Any) -> dict[str, Any]:
    """Append `receipt` as the repository receipt's $.evidence and aggregate it into the organization ledger, once per range."""
    bad = push_payload(receipt)
    if bad is None:
        bad = _epoch_refusal(receipt, hb_epoch)
    if bad is not None:
        return bad
    payload_sha256 = sha(receipt)
    successor = sha({"operation": OPERATION_ID, "push_receipt_sha256": payload_sha256, "range": range_key(receipt),
                     "pusher_session": receipt["pusher_session"], "pushed_commits": len(receipt["pushed_commits"])})
    boundary = {"operation": OPERATION_ID, "profile_id": PROFILE_ID, "repository": receipt["repository"], "ref": receipt["ref"],
                "old_sha": receipt["old_sha"], "new_sha": receipt["new_sha"], "range_id": range_id(receipt),
                "push_receipt_sha256": payload_sha256, "push_result_sha256": receipt["result_sha256"]}
    try:
        ingress.repository_ledger.lr()
        ingress.organization_ledger.ledger_root()
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - every resolver refusal is reported, none is retried
        return refusal("ORGANIZATION_LEDGER_LOCATION_UNRESOLVED", "WRITER_LEDGER_LOCATIONS_ARE_SUPPLIED",
                       "supply the repository and organization ledger locations the writer workflow declares",
                       "after the ledger locations resolve; nothing was written", detail=f"{type(exc).__name__}: {exc}")
    try:
        appended = _append_one(receipt, hb_epoch, payload_sha256, successor, boundary)
    except (ValueError, SystemExit) as exc:
        return refusal("ORGANIZATION_LEDGER_APPEND_REFUSED", "PUSH_RECEIPT_APPEND_COMPLETES_AT_BOTH_LEVELS",
                       "repair the refusal the ledger reported; the writer publishes only when both receipts exist",
                       "after the ledger refusal is repaired", detail=f"{type(exc).__name__}: {getattr(exc, 'code', None) or exc}")
    if appended.get("disposition") == "FAIL_CLOSED":
        return appended
    repository = appended["repository_receipt"]
    organization = appended["organization_receipt"]
    for row in (repository, organization):
        bad = _stored_epoch_refusal(row, hb_epoch)
        if bad is not None:
            bad["consequence_committed"] = "LOCAL_ONLY_NOT_PUBLISHED"  # the writer workflow pushes nothing after a refusal
            return bad
    store_mod = ingress.repository_ledger.ledger_store
    return {
        "schema": RESULT_SCHEMA, "operation": OPERATION_ID, "disposition": "ALLOW", "transition_class": TRANSITION_CLASS,
        "appended": True, "range": range_key(receipt), "range_id": range_id(receipt),
        "push_receipt_sha256": payload_sha256, "push_result_sha256": receipt["result_sha256"],
        "repository_receipt_sha256": repository["receipt_sha256"],
        "organization_receipt_sha256": organization["receipt_sha256"],
        "organization_receipt_key": store_mod.receipt_key(organization["receipt_sha256"]),
        "repository_receipt_source_key": store_mod.source_key(repository["receipt_sha256"]),
        "hb_epoch": repository["hb_reference"]["epoch"],
        "organization_receipt_preserves_repository_receipt": organization.get("repo_receipt_sha256") == repository["receipt_sha256"],
        "consequence_committed": True, "authority_effect": "NONE",
    }


def admit_push_receipt(receipt: Any, *, hb_epoch: Any) -> dict[str, Any]:
    """The admission checks alone (shape, seal, supplied epoch and its tie). Reads no ledger and writes nothing, so the
    PR-facing check can run it on a committed request without appending."""
    bad = push_payload(receipt)
    if bad is None:
        bad = _epoch_refusal(receipt, hb_epoch)
    if bad is not None:
        return bad
    return {"schema": RESULT_SCHEMA, "operation": OPERATION_ID, "disposition": "ALLOW", "admitted": True, "writes": False,
            "range": range_key(receipt), "range_id": range_id(receipt), "transition_id": transition_id(receipt),
            "hb_epoch": hb_epoch, "push_result_sha256": receipt["result_sha256"], "authority_effect": "NONE_ADMISSION_ONLY"}


def bind_push_receipt(location: str, result: Mapping[str, Any]) -> dict[str, Any]:
    """Read the appended pair back from `location` (a fresh fetch of the ref): sealed, in place, linked, self-identified,
    and the only receipt on the repository chain for its range."""
    store_mod = ingress.repository_ledger.ledger_store
    store = store_mod.open_store(store_mod.parse_locator(location))
    org_sha = result.get("organization_receipt_sha256")
    repo_sha = result.get("repository_receipt_sha256")
    org = store.get(store_mod.receipt_key(org_sha)) if isinstance(org_sha, str) else None
    repo = store.get(store_mod.source_key(repo_sha)) if isinstance(repo_sha, str) else None
    evidence = repo.get("evidence") if isinstance(repo, dict) else None
    try:
        # The repository receipts live in the repository subtree of the same ref: repository-ledger/<ledger repository>.
        repo_store = store_mod.open_store(location + ":repository-ledger/" + repo["repository"])
        in_range = [r for r in ingress.repository_ledger.chain(repo_store, repo_store.get(store_mod.HEAD_KEY))
                    if r.get("transition_class") == TRANSITION_CLASS and isinstance(evidence, dict)
                    and r.get("transition_id") == transition_id(evidence)]
    except Exception:  # noqa: BLE001 - an unreadable chain is a failed check below
        in_range = []
    checks = {
        "organization_receipt_sealed": _self_verifies(org) and org.get("receipt_sha256") == org_sha,
        "repository_receipt_sealed_beside_it": _self_verifies(repo) and repo.get("receipt_sha256") == repo_sha,
        "organization_receipt_names_repository_receipt": isinstance(org, dict) and org.get("repo_receipt_sha256") == repo_sha,
        "operation_is_sv_push_receipt": isinstance(org, dict) and (org.get("boundary_evidence") or {}).get("operation") == OPERATION_ID,
        "evidence_is_a_valid_push_receipt": isinstance(evidence, dict) and push_payload(evidence) is None,
        "evidence_is_the_appended_receipt": isinstance(evidence, dict) and sha(evidence) == result.get("push_receipt_sha256"),
        "exactly_one_receipt_for_the_range": len(in_range) == 1,
        "epoch_supplied_not_clock": all(isinstance(r, dict) and (r.get("hb_reference") or {}).get("derived_from_clock") is False
                                        for r in (org, repo)),
    }
    if not all(checks.values()):
        failed = sorted(k for k, v in checks.items() if not v)
        return {"schema": READBACK_SCHEMA, "disposition": "FAIL_CLOSED", "failure_code": "SV_PUSH_RECEIPT_READBACK_FAILED",
                "failed_predicate": failed[0].upper(), "required_evidence_or_repair": "the fresh fetch must hold the sealed pair: "
                + ", ".join(failed), "retry_entrypoint": "resident-runtime/sv_push_receipt_append.py::bind_push_receipt",
                "owning_existing_goal": OWNING_GOAL, "next_attempt": "after a fresh fetch of the published ref",
                "checks": checks, "readback_writes": False, "authority_effect": "NONE_READBACK_ONLY"}
    return {"schema": READBACK_SCHEMA, "disposition": "ALLOW", "location": location, "checks": checks,
            "organization_receipt_sha256": org_sha, "repository_receipt_sha256": repo_sha,
            "readback_writes": False, "authority_effect": "NONE_READBACK_ONLY"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("append")
    a.add_argument("--push-receipt", type=Path, required=True, help="the producer's sv-push-receipt.v1 JSON file")
    a.add_argument("--hb-epoch", required=True, help="supplied epoch, ASCII digits >= 32; never from a clock")
    a.add_argument("--out", type=Path, default=None)
    m = sub.add_parser("admit", help="the admission checks alone; reads no ledger and writes nothing")
    m.add_argument("--push-receipt", type=Path, required=True)
    m.add_argument("--hb-epoch", required=True)
    m.add_argument("--out", type=Path, default=None)
    r = sub.add_parser("readback")
    r.add_argument("--location", required=True)
    r.add_argument("--result", type=Path, required=True)
    r.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    if args.cmd in ("append", "admit"):
        epoch = int(args.hb_epoch) if re.fullmatch(r"[0-9]+", args.hb_epoch or "") else args.hb_epoch
        try:
            receipt = json.loads(args.push_receipt.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            out = refusal("LEDGER_EVIDENCE_NOT_A_PUSH_RECEIPT", "ORGANIZATION_LEDGER_EVIDENCE_IS_A_SELF_IDENTIFYING_PUSH_RECEIPT",
                          "supply the producer's receipt as one JSON object", "after a readable receipt is supplied; nothing was written",
                          detail=f"{type(exc).__name__}: {exc}")
        else:
            out = (append_push_receipt if args.cmd == "append" else admit_push_receipt)(receipt, hb_epoch=epoch)
    else:
        out = bind_push_receipt(args.location, json.loads(args.result.read_text(encoding="utf-8")))
    text = json.dumps(out, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(json.dumps(out, sort_keys=True))
    return 0 if out.get("disposition") == "ALLOW" else 1


if __name__ == "__main__":
    sys.exit(main())
