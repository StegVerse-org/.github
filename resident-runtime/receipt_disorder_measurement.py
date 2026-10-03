#!/usr/bin/env python3
"""Measure this organization's receipt state against RE's ten disorder classes.

`Admissible-Existence/RE`'s `PO-RE-001` declares what disorder *is* -- ten
classes, each with a weight and a measurement expressed as a ratio -- and
`PO-RE-002` admits a repair as a reduction candidate only if it lowers the
score without increasing any dimension, `hidden_disorder_tolerance` being zero.

Neither obligation could be applied to anything here, because nothing measured.
This measures: for each class, the numerator and denominator the contract names,
read off the repository and organization chains.

All ten are observed. That matters, and it is why this is not a partial
surface: an unobserved dimension is exactly where hidden disorder hides, so a
reduction proven over a subset would admit a repair that fixed one dimension by
breaking an unwatched one -- the overclaim `hidden_disorder_tolerance: 0.0`
exists to refuse.

Two of the ten looked unobservable and were not:

* **stale_evidence** needs no clock and no declared freshness window. Stale
  means no longer current, and in an append-only chain that is *supersession*:
  evidence a later CORRECTION or INVALIDATION replaced, which
  `receipt_lineage_projection` already derives. A window in heartbeat epochs
  would have been a policy number invented here, and this needs none.
* **policy_or_delegation_mismatch** already has its link structure. The
  capability overlay in `org-runtime/interlock-intr.json` *is* the delegation:
  it declares who owns a capability, who binds it, which operation receives it,
  and which transport profile a peer must speak. A crossing either resolves
  through it or does not.

This measures; RE scores. `D = sum(weight_i * severity_i)` and the thresholds
live in RE's contract and `validate_re_disorder_classes.score_observation`
applies them. Carrying a copy of the formula here would be a second authority on
the score, and the stale one. So this emits severities and says whose verdict it
awaits -- the same division the lineage projection keeps, and for the same
reason.

Every class reports its numerator and denominator rather than only a ratio, so
a reader can see what was counted. A class whose denominator is zero is reported
unobserved and is left out of the severity map, because the contract's
`missing_denominator` disposition is FAIL_CLOSED and a fabricated denominator
would be worse than an absent dimension. A critical binary whose population is
empty is observed at zero: nothing to be wrong is a measurement, not a gap.

Nothing here grants authority. It counts what the chains already record.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]

MEASUREMENT_SCHEMA = "stegverse.receipt-disorder-measurement/v1"
DISORDER_CONTRACT = "Admissible-Existence/RE:data/re-disorder-classes.json"
DISORDER_SCORER = ("Admissible-Existence/RE:validators/"
                   "validate_re_disorder_classes.py::score_observation")
REDUCTION_CONTRACT = "Admissible-Existence/RE:data/re-reduction-contract.json"

#: The ten classes RE declares, named here only to address them. The weights
#: and thresholds are deliberately absent: they are RE's and this does not score.
CLASSES = (
    "missing_receipt_chain",
    "stale_evidence",
    "conflicting_evidence",
    "unreconstructable_authority",
    "unresolved_actor_identity",
    "target_or_scope_ambiguity",
    "policy_or_delegation_mismatch",
    "replay_divergence",
    "repair_without_reentry",
    "sandbox_authority_confusion",
)

#: The two RE marks critical: either at one fails closed whatever the score.
CRITICAL_BINARIES = ("repair_without_reentry", "sandbox_authority_confusion")

#: The resolution surfaces a record may declare it resolved its target through.
#:
#: Two exist and they are not interchangeable. An outbound crossing resolves a
#: *peer organization* from this organization's peer directory. An inbound
#: submission resolves a *receiving operation* from the capability overlay.
#: Measuring one against the other's fields reports disorder that is not there:
#: an ingress record carries no peer address because it addressed no peer, and
#: a record resolved through the overlay is not mis-delegated for having been.
PEER_DIRECTORY = "ORGANIZATION_FEDERATION_DIRECTORY"
CAPABILITY_OVERLAY = "CANONICAL_CONNECTOR_CAPABILITY_OVERLAY"

#: The target and scope fields each resolution surface must carry, by surface.
#:
#: A resolution through a surface neither names is itself a finding rather than
#: an exemption: it resolved a target against something nothing declares, which
#: is precisely scope ambiguity.
TARGET_SCOPE_FIELDS = {
    PEER_DIRECTORY: ("destination_organization", "destination_repository",
                     "destination_org_control_service", "transport_profile"),
    CAPABILITY_OVERLAY: ("receiving_operation", "profile_id", "operation",
                         "processing_capability", "route_id"),
}


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lineage = _module("receipt_lineage_projection",
                  "resident-runtime/receipt_lineage_projection.py")
repository_ledger = _module("repo_transition_emit", ".stegverse/transition-ledger/emit.py")
organization_ledger = _module("aggregate_repo_transition",
                              "resident-runtime/aggregate_repo_transition.py")
ledger_store = _module("ledger_store", "resident-runtime/ledger_store.py")


class MeasurementRefused(Exception):
    """A state this measurement will not report on, carrying why."""


def _evidence(receipt: Mapping[str, Any]) -> dict[str, Any]:
    evidence = receipt.get("evidence")
    return dict(evidence) if isinstance(evidence, Mapping) else {}


def _ratio(numerator: int, denominator: int, counted: str) -> dict[str, Any]:
    """A class's measurement, reported with what it counted.

    A zero denominator is reported unobserved rather than scored. The contract's
    disposition for a missing denominator is FAIL_CLOSED, so inventing one would
    be worse than leaving the dimension out.
    """
    if denominator == 0:
        return {"observed": False, "numerator": numerator, "denominator": 0,
                "counted": counted,
                "unobserved_because": "DENOMINATOR_POPULATION_IS_EMPTY"}
    return {"observed": True, "numerator": numerator, "denominator": denominator,
            "severity": round(numerator / denominator, 6), "counted": counted}


def _binary(tripped: bool, population: int, counted: str) -> dict[str, Any]:
    """A critical binary. An empty population is observed at zero, not unobserved."""
    return {"observed": True, "severity": 1.0 if tripped else 0.0,
            "population": population, "counted": counted,
            "critical_binary": True,
            "empty_population_is_an_observation_not_a_gap": population == 0}


def _store_receipts(root: Path, sha) -> dict[str, Any]:
    store = ledger_store.PosixLedgerStore(root)
    found = {}
    for key in store.list_prefix(ledger_store.RECEIPT_PREFIX):
        value = store.get(key)
        if isinstance(value, Mapping) and value.get("receipt_sha256"):
            found[value["receipt_sha256"]] = dict(value)
    return found


def _recomputes(receipt: Mapping[str, Any], sha) -> bool:
    body = dict(receipt)
    digest = body.pop("receipt_sha256", None)
    return bool(digest) and sha(body) == digest


def measure(*, repository_root: Path | None = None,
            organization_root: Path | None = None) -> dict[str, Any]:
    """Measure both chains against all ten classes.

    Both levels are required. The organization chain is where authority links
    live, so a repository-only measurement would leave
    `unreconstructable_authority` unobserved -- and this surface exists to
    observe all ten.
    """
    repo_chain = lineage.repository_chain(repository_root)
    org_chain = lineage.organization_chain(organization_root)
    if not repo_chain and not org_chain:
        raise MeasurementRefused("NO_RECEIPTS_TO_MEASURE")

    repo_root = Path(repository_root) if repository_root else repository_ledger.lr()
    org_root = (Path(organization_root) if organization_root
                else organization_ledger.ledger_root())
    repo_stored = _store_receipts(repo_root, repository_ledger.sha)
    org_stored = _store_receipts(org_root, organization_ledger.sha)

    repo_by = {r["receipt_sha256"]: r for r in repo_chain}
    reachable = set(repo_by) | {r["receipt_sha256"] for r in org_chain}
    projected = {level: lineage.project(chain) for level, chain
                 in (("REPOSITORY", repo_chain), ("ORGANIZATION", org_chain))}

    classes: dict[str, Any] = {}

    # 1. missing_receipt_chain -- references that do not resolve.
    referenced, unresolved = 0, 0
    for receipt in repo_chain:
        if receipt.get("previous_receipt_sha256"):
            referenced += 1
            if receipt["previous_receipt_sha256"] not in repo_by:
                unresolved += 1
    org_by = {r["receipt_sha256"]: r for r in org_chain}
    for receipt in org_chain:
        if receipt.get("previous_receipt_sha256"):
            referenced += 1
            if receipt["previous_receipt_sha256"] not in org_by:
                unresolved += 1
        if receipt.get("repo_receipt_sha256"):
            referenced += 1
            if receipt["repo_receipt_sha256"] not in repo_by:
                unresolved += 1
    classes["missing_receipt_chain"] = _ratio(
        unresolved, referenced,
        "receipt references across both chains that resolve to a receipt on the "
        "chain they name")

    # 2. stale_evidence -- evidence a later receipt superseded. No clock.
    superseded: set[str] = set()
    for records in projected.values():
        for record in records:
            for field in (lineage.CORRECTS_FIELD, lineage.INVALIDATES_FIELD):
                if record.get(field):
                    superseded.add(record[field])
    evidence_items = len(repo_chain) + len(org_chain)
    classes["stale_evidence"] = _ratio(
        len(superseded & reachable), evidence_items,
        "receipts superseded by a later CORRECTION or INVALIDATION, derived from "
        "lineage rather than from a clock")

    # 3. conflicting_evidence -- a receipt that does not recompute, or one the
    #    store holds that the chain's own HEAD cannot reach.
    conflicts = 0
    for receipt in repo_chain:
        if not _recomputes(receipt, repository_ledger.sha):
            conflicts += 1
    for receipt in org_chain:
        if not _recomputes(receipt, organization_ledger.sha):
            conflicts += 1
    orphans = (set(repo_stored) - set(repo_by)) | (set(org_stored) - set(org_by))
    examined = len(repo_stored) + len(org_stored)
    classes["conflicting_evidence"] = _ratio(
        conflicts + len(orphans), examined,
        "receipts in either store that recompute against their own body and are "
        "reachable from their chain's HEAD")

    # 4. unreconstructable_authority -- each organization receipt must name the
    #    repository receipt it consumed, and that receipt must be on the chain.
    missing_links = sum(
        1 for receipt in org_chain
        if not receipt.get("repo_receipt_sha256")
        or receipt["repo_receipt_sha256"] not in repo_by)
    classes["unreconstructable_authority"] = _ratio(
        missing_links, len(org_chain),
        "organization receipts whose consumed repository receipt resolves")

    # 5. unresolved_actor_identity -- an actor claim whose attestation is not proven.
    claims, unresolved_claims = 0, 0
    for receipt in repo_chain:
        evidence = _evidence(receipt)
        if evidence.get("origin_organization"):
            claims += 1
            if evidence.get("origin_attestation_state") != "PROVEN":
                unresolved_claims += 1
    classes["unresolved_actor_identity"] = _ratio(
        unresolved_claims, claims,
        "receipts claiming an origin organization whose attestation is PROVEN")

    # 6. target_or_scope_ambiguity -- a record that resolved a destination must
    #    carry it. The population is records that *performed* a resolution,
    #    marked by `destination_resolution_source`. An earlier version of this
    #    took every record that crossed a boundary, which counted a closure
    #    record as ambiguous for not repeating the destination resolution its
    #    emission already holds -- a measurement artifact reported as disorder,
    #    which is the false finding this surface exists to avoid.
    resolving = [_evidence(r) for r in repo_chain
                 if _evidence(r).get("destination_resolution_source")]
    required_fields, ambiguous = 0, 0
    for evidence in resolving:
        source = evidence.get("destination_resolution_source")
        fields = TARGET_SCOPE_FIELDS.get(source)
        if fields is None:
            # Resolved through a surface nothing declares. One unresolvable
            # link, counted rather than skipped: an undeclared resolution
            # surface is scope ambiguity, not an absence of evidence about it.
            required_fields += 1
            ambiguous += 1
            continue
        for field in fields:
            required_fields += 1
            if not evidence.get(field):
                ambiguous += 1
    classes["target_or_scope_ambiguity"] = _ratio(
        ambiguous, required_fields,
        "target and scope fields on records that resolved a target, against "
        "the fields the surface each one resolved through requires")

    # 7. policy_or_delegation_mismatch -- the capability overlay is the
    #    delegation structure, so a crossing either resolves through it or not.
    boundary = json.loads(
        (ROOT / "org-runtime/interlock-intr.json").read_text(encoding="utf-8"))
    egress = boundary.get("egress") or {}
    resolution = egress.get("peer_destination_resolution") or {}
    emitting = egress.get("emitting_operation") or {}
    declared_profile = resolution.get("destination_must_declare_this_transport_profile")
    declared_owner = emitting.get("owner_repository")
    ingress_bindings = {
        entry.get("profile_id"): entry
        for entry in ((boundary.get("ingress") or {}).get("capability_endpoint_bindings") or [])
        if isinstance(entry, dict)}
    links, mismatches = 0, 0
    for evidence in resolving:
        source = evidence.get("destination_resolution_source")
        if source == PEER_DIRECTORY:
            # An outbound crossing's delegation: it resolved through the peer
            # directory, the peer speaks the declared transport profile, and the
            # operation that emitted it is the one the overlay declares owns
            # outbound crossings.
            links += 3
            if evidence.get("transport_profile") != declared_profile:
                mismatches += 1
            if evidence.get("owner_repository") != declared_owner:
                mismatches += 1
            if not evidence.get("destination_organization"):
                mismatches += 1
        elif source == CAPABILITY_OVERLAY:
            # An inbound submission's delegation: the capability it resolved is
            # one the overlay binds, and the operation it reached is the one that
            # binding names. The overlay *is* the delegation, so a submission
            # received on an operation other than the bound one is the mismatch.
            links += 3
            binding = ingress_bindings.get(evidence.get("profile_id"))
            if binding is None:
                mismatches += 2
            else:
                if evidence.get("operation") != binding.get("operation"):
                    mismatches += 1
                if evidence.get("receiving_operation") != (
                        binding.get("receiving_operation") or {}).get("operation_id"):
                    mismatches += 1
            if not evidence.get("route_id"):
                mismatches += 1
        else:
            # Delegated through a surface nothing declares: every link on this
            # record is unresolvable against the overlay.
            links += 3
            mismatches += 3
    classes["policy_or_delegation_mismatch"] = _ratio(
        mismatches, links,
        "delegation links per resolved record, against the surface it "
        "resolved through -- the peer directory for an outbound crossing, "
        "the capability overlay binding for an inbound submission")

    # 8. replay_divergence -- the far side's recomputed chain against what came back.
    steps, divergent = 0, 0
    for receipt in repo_chain:
        evidence = _evidence(receipt)
        recomputed = evidence.get("far_side_receipt_chain_recomputed")
        if not isinstance(recomputed, list) or not recomputed:
            continue
        steps += len(recomputed)
        if evidence.get("far_side_terminal_receipt") != recomputed[-1]:
            divergent += len(recomputed)
    classes["replay_divergence"] = _ratio(
        divergent, steps,
        "far-side boundary receipt steps recomputed from emitter-held inputs that "
        "agree with the terminal receipt that came back")

    # 9. repair_without_reentry -- critical. A repaired candidate must re-cross standing.
    repaired, without_reentry = 0, 0
    for level, records in projected.items():
        chain = repo_chain if level == "REPOSITORY" else org_chain
        by_digest = {r["receipt_sha256"]: r for r in chain}
        for record in records:
            if record["event_type"] not in ("CORRECTION", "INVALIDATION"):
                continue
            repaired += 1
            evidence = _evidence(by_digest.get(record["receipt_id"], {}))
            if evidence.get("standing_reentry_observed") is not True:
                without_reentry += 1
    classes["repair_without_reentry"] = _binary(
        without_reentry > 0, repaired,
        "receipts correcting or invalidating a predecessor that record a "
        "standing re-entry")

    # 10. sandbox_authority_confusion -- critical. Nothing may assert authority.
    asserting = [r["receipt_sha256"] for r in list(repo_chain) + list(org_chain)
                 if not str(r.get("authority_effect") or "").startswith("NONE")]
    classes["sandbox_authority_confusion"] = _binary(
        bool(asserting), len(repo_chain) + len(org_chain),
        "receipts whose authority_effect is NONE-prefixed")

    unknown = sorted(set(classes) - set(CLASSES))
    if unknown:
        raise MeasurementRefused("CLASS_NOT_DECLARED_BY_THE_CONTRACT:" + ",".join(unknown))
    missing = sorted(set(CLASSES) - set(classes))
    if missing:
        raise MeasurementRefused("CLASS_NOT_MEASURED:" + ",".join(missing))

    severity = {name: row["severity"] for name, row in classes.items()
                if row.get("observed")}
    unobserved = sorted(name for name, row in classes.items() if not row.get("observed"))
    return {
        "schema": MEASUREMENT_SCHEMA,
        "disorder_contract": DISORDER_CONTRACT,
        "disorder_scorer": DISORDER_SCORER,
        "reduction_contract": REDUCTION_CONTRACT,
        "verdict_is_res_to_give_not_this_measurements": True,
        "formula_is_not_restated_here": True,
        "classes": classes,
        "severity": severity,
        "observed_dimensions": sorted(severity),
        "unobserved_dimensions": unobserved,
        "classes_declared_by_the_contract": len(CLASSES),
        "classes_observed": len(severity),
        "all_ten_observed": len(severity) == len(CLASSES),
        # The reason all ten matter rather than most of them.
        "hidden_disorder_hides_in_an_unobserved_dimension": True,
        "repository_receipts": len(repo_chain),
        "organization_receipts": len(org_chain),
        "critical_binaries": list(CRITICAL_BINARIES),
        "authority_effect": "NONE_MEASUREMENT_ONLY",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository-ledger-root", default=None)
    parser.add_argument("--organization-ledger-root", default=None)
    parser.add_argument("--severity-only", action="store_true",
                        help="emit just the severity map, for RE's scorer to read")
    parser.add_argument("--out")
    args = parser.parse_args()
    try:
        report = measure(repository_root=args.repository_ledger_root,
                         organization_root=args.organization_ledger_root)
    except MeasurementRefused as refused:
        print(json.dumps({"schema": MEASUREMENT_SCHEMA, "refused": str(refused),
                          "authority_effect": "NONE_MEASUREMENT_ONLY"},
                         indent=2, sort_keys=True))
        return 1
    rendered = json.dumps(report["severity"] if args.severity_only else report,
                          indent=2, sort_keys=True)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
