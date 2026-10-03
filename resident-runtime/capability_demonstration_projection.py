#!/usr/bin/env python3
"""A capability is mapped by having been demonstrated, not by having been listed.

The capability map was going to be enumerated: a service per peer, written down
in this organization's directory. `peer_capability_resolution` already records
why that is weak -- `peer_declares_its_capability_services_in_the_peer_directory`
is false, because this organization writing down what its peers serve is a
declaration none of them made.

ST-022 settles the other half. Capability profiles are declared "with the
mechanism already used for services in an organization service registry, raised
from service to participant", and then:

    A profile enables capability. It does not decide admissibility --
    admissibility resolves at the binding moment, per transition.

So the owner surface already separates the two things an enumerated map would
have conflated. A profile is an intention. A transition is an occurrence. This
projection derives the second, which nothing recorded, from evidence every
crossing already writes.

Nothing is declared here and nothing is stored. The repository ledger is read,
from HEAD backwards, every receipt verified against its own body, and what comes
out is the set of capabilities that have actually been exercised with a receipt
to cite.

Two kinds of demonstration exist, because the evidence differs:

* `RECEIVED_HERE` -- a submission resolved a capability through this
  organization's own overlay and this organization's receiving operation
  dispositioned it. The capability and the operation are both in the receipt.
* `SERVED_BY_A_PEER_ADDRESS` -- an outbound crossing addressed a peer's
  capability address and closed. A closure requires the far side's receipt chain
  to recompute from inputs this organization already held, so a verified closure
  is evidence that *something at that address ran this packet and minted the
  chain this packet determines*. That is a real demonstration of service, and it
  is the thing `peer_serves_this_capability_is_proven_here: false` says cannot
  be established at resolution time. It can be established at closure.

Joined against the profiles this organization declares, three states fall out,
and the middle one is the ecosystem's own defect class made countable:

    DECLARED_AND_DEMONSTRATED        a working capability
    DECLARED_NOT_YET_DEMONSTRATED    a declaration nothing has exercised
    DEMONSTRATED_AND_NOT_DECLARED    served without being declared

What this must never be read as:

* **A demonstration is not a grant.** ST-022's ceiling rule makes effective
  capability an intersection of a profile with every ancestor ceiling and the
  jurisdiction set, and a parent may only ever narrow. Evidence that a
  capability ran cannot widen a profile past a ceiling, and this projection
  grants nothing.
* **Admissibility is still per transition.** A capability appearing here does
  not admit the next crossing; the boundary resolves that each time.
* **Absence is not refutation.** A capability nothing has exercised is absent
  from this map, which says only that no demonstration exists. It does not say
  the capability is unsupported, and reading it that way would make an unrun
  experiment look like a missing capability.
* **It does not say who.** A closure proves the address served the capability.
  It does not prove which organization that address belongs to -- origin is
  asserted and `credential_authority` is TV/TVC. The map is keyed by address
  for that reason, with the organization recorded as the one this organization
  addressed rather than one the far side proved.

So the ecosystem validates its own capability surface with every experiment that
leaves a receipt, and the map is a ratchet of positive evidence rather than a
survey.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = ROOT / "org-runtime/interlock-intr.json"

PROJECTION_SCHEMA = "stegverse.capability-demonstration-projection/v1"

#: The owner surface for how a participant's capability profile is declared.
PROFILE_DECLARATION_AUTHORITY = (
    "StegVerse-Labs/repo-standards:standards/ST-022_KV_PARTICIPANT.standard.md")

#: The two resolution surfaces a record may have resolved its target through.
#: Named identically to the disorder measurement, which measures each record
#: against the surface it resolved through for the same reason.
PEER_DIRECTORY = "ORGANIZATION_FEDERATION_DIRECTORY"
CAPABILITY_OVERLAY = "CANONICAL_CONNECTOR_CAPABILITY_OVERLAY"

RECEIVED_HERE = "RECEIVED_HERE"
SERVED_BY_A_PEER_ADDRESS = "SERVED_BY_A_PEER_ADDRESS"

DECLARED_AND_DEMONSTRATED = "DECLARED_AND_DEMONSTRATED"
DECLARED_NOT_YET_DEMONSTRATED = "DECLARED_NOT_YET_DEMONSTRATED"
DEMONSTRATED_AND_NOT_DECLARED = "DEMONSTRATED_AND_NOT_DECLARED"

ALLOW = "ALLOW"


class DemonstrationRefused(SystemExit):
    """A projection that cannot stand on verified evidence refuses."""


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lineage = _module("receipt_lineage_projection",
                  "resident-runtime/receipt_lineage_projection.py")


def _evidence(receipt: Mapping[str, Any]) -> dict[str, Any]:
    evidence = receipt.get("evidence")
    return dict(evidence) if isinstance(evidence, Mapping) else {}


def boundary(root: Path | None = None) -> dict[str, Any]:
    path = (Path(root) / "org-runtime/interlock-intr.json") if root else BOUNDARY
    return json.loads(path.read_text(encoding="utf-8"))


def declared_profiles(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """The capability profiles this organization declares, by profile id.

    The overlay is the authority on what this organization intends to serve.
    Only this organization's own profiles are readable here: a peer's profile is
    the peer's to declare, and nothing in this repository can read it.
    """
    declared = (boundary(root).get("ingress") or {}).get(
        "capability_endpoint_bindings") or []
    return {entry["profile_id"]: entry for entry in declared
            if isinstance(entry, Mapping) and entry.get("profile_id")}


def emissions(chain: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Emission records by packet id, which is what a closure cites.

    A closure names the packet it answers and nothing about the capability; the
    capability is on the emission. Without the emission a closure cannot say
    which capability was served, so it is not a demonstration of one.
    """
    found = {}
    for receipt in chain:
        evidence = _evidence(receipt)
        packet_id = evidence.get("packet_id")
        if packet_id and evidence.get("destination_resolution_source") == PEER_DIRECTORY:
            found[packet_id] = evidence
    return found


def received_here(chain: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Capabilities a submission exercised on one of this organization's operations.

    Keyed on a record naming both a receiving operation and the capability
    profile it serves, which is what an admitted submission and a refused one
    have in common. Keying on `destination_resolution_source` instead would
    have found admissions only, because a refusal resolves no destination and
    correctly does not claim to -- and a map of admissions alone presents a
    capability that only ever refuses as one nothing has ever exercised.

    Both dispositions are carried. A refusal is evidence that the capability was
    exercised and that this operation dispositioned it, which is a different
    fact from a submission that completed, and the two are counted separately
    rather than summed.
    """
    out = []
    for receipt in chain:
        evidence = _evidence(receipt)
        capability = evidence.get("profile_id")
        operation = evidence.get("receiving_operation")
        if not capability or not operation:
            continue
        out.append({
            "demonstration": RECEIVED_HERE,
            "capability_profile_id": capability,
            "capability_operation": evidence.get("operation"),
            "receiving_operation_id": operation,
            # On an admission these are what the organization resolved; on a
            # refusal, what the submission declared. Both are the submitter's
            # capability either way, under the name the record gives it.
            "processing_capability": evidence.get("processing_capability")
                or evidence.get("submitted_processing_capability"),
            "route_id": evidence.get("route_id") or evidence.get("submitted_route_id"),
            "internal_surface": (evidence.get("crossing") or {}).get("resolved_service_id"),
            "resolved_through": evidence.get("destination_resolution_source"),
            "disposition": receipt.get("transition_class"),
            "evidence_receipt_sha256": receipt.get("receipt_sha256"),
            "evidence_transition_id": receipt.get("transition_id"),
            # The address the submission arrived at is not in this record. It is
            # resolvable from the overlay, but resolving it here would put a
            # declaration inside a demonstration.
            "arrival_address_is_evidenced": False,
        })
    return out


def served_by_a_peer_address(chain: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Capability addresses a verified closure shows were served.

    Only a verified closure counts. A closure with findings is a crossing whose
    far-side chain did not recompute, which is evidence that the address did
    *not* mint the chain this packet determines -- the opposite of a
    demonstration -- and it is carried as an unserved attempt rather than
    dropped.
    """
    by_packet = emissions(chain)
    out = []
    for receipt in chain:
        evidence = _evidence(receipt)
        packet_id = evidence.get("request_packet_id")
        if not packet_id:
            continue
        emission = by_packet.get(packet_id)
        if emission is None:
            continue
        capability = emission.get("destination_capability_profile_id")
        if not capability:
            # A control crossing, not a capability one. It demonstrates the
            # peer's control service, which no profile declares and which this
            # map does not invent one for.
            continue
        verified = evidence.get("verified_the_far_side_terminal_receipt_recomputes")
        out.append({
            "demonstration": SERVED_BY_A_PEER_ADDRESS,
            "capability_profile_id": capability,
            "address": emission.get("far_side_service_id"),
            "addressed_organization": emission.get("destination_organization"),
            "transport_profile": emission.get("transport_profile"),
            "served": verified is True,
            "far_side_terminal_receipt_recomputed":
                evidence.get("far_side_terminal_receipt_recomputed"),
            "closure_findings": evidence.get("closure_findings") or [],
            "disposition": receipt.get("transition_class"),
            "evidence_receipt_sha256": receipt.get("receipt_sha256"),
            "emission_packet_id": packet_id,
            # What a recomputed chain establishes, carried with the entry so an
            # address in this map is never read as an identified organization.
            "proves_the_address_ran_this_packet": verified is True,
            "proves_which_organization_the_address_belongs_to": False,
        })
    return out


def _state(declared: bool, demonstrated: bool) -> str:
    if declared and demonstrated:
        return DECLARED_AND_DEMONSTRATED
    if declared:
        return DECLARED_NOT_YET_DEMONSTRATED
    return DEMONSTRATED_AND_NOT_DECLARED


REFUSED_SUFFIX = "_REFUSED"


def _refused(row: Mapping[str, Any]) -> bool:
    return str(row.get("disposition") or "").endswith(REFUSED_SUFFIX)


def map_of_this_organization(chain: list[Mapping[str, Any]],
                             root: Path | None = None) -> dict[str, Any]:
    """Declared against demonstrated, for the capabilities this organization owns."""
    inbound = received_here(chain)
    profiles = declared_profiles(root)
    admitted = {row["capability_profile_id"] for row in inbound if not _refused(row)}
    rows = []
    for capability in sorted(set(profiles) | {row["capability_profile_id"] for row in inbound}):
        cited = [row for row in inbound if row["capability_profile_id"] == capability]
        declared = capability in profiles
        demonstrated = capability in admitted
        rows.append({
            "capability_profile_id": capability,
            "declared": declared,
            "declared_profile_name": (profiles.get(capability) or {}).get("profile_name"),
            "declared_receiving_operation":
                ((profiles.get(capability) or {}).get("receiving_operation")
                 or {}).get("operation_id"),
            "demonstrated": demonstrated,
            # Exercised and demonstrated are different facts, and the state
            # lattice cannot carry both: a capability that refuses every
            # submission is not demonstrated, but it is being tested, and a
            # capability nothing has ever submitted to is not. Collapsing them
            # would make an untried declaration and a failing one read alike.
            "exercised": bool(cited),
            "state": _state(declared, demonstrated),
            "admitted_demonstration_count": len([row for row in cited if not _refused(row)]),
            "refused_demonstration_count": len([row for row in cited if _refused(row)]),
            "evidence_receipts": [row["evidence_receipt_sha256"] for row in cited],
        })
    return {"organization": "StegVerse-org", "capabilities": rows}


def map_of_peer_addresses(chain: list[Mapping[str, Any]]) -> dict[str, Any]:
    """What peer addresses have been shown to serve, with no declared side.

    There is no declared column here, and inventing one is the thing this
    replaces. A peer's profile is the peer's to declare and nothing in this
    repository can read it, so a peer address appears only once a closure has
    shown it served something.
    """
    outbound = served_by_a_peer_address(chain)
    addresses = {}
    for row in outbound:
        key = (row["address"], row["capability_profile_id"])
        entry = addresses.setdefault(key, {
            "address": row["address"],
            "capability_profile_id": row["capability_profile_id"],
            "addressed_organization": row["addressed_organization"],
            "declared_profile_readable_here": False,
            "served_demonstration_count": 0,
            "unserved_attempt_count": 0,
            "evidence_receipts": [],
        })
        entry["served_demonstration_count" if row["served"] else "unserved_attempt_count"] += 1
        entry["evidence_receipts"].append(row["evidence_receipt_sha256"])
    return {"addresses": [addresses[key] for key in sorted(addresses)]}


def projection(*, ledger_root: Path | None = None,
               root: Path | None = None) -> dict[str, Any]:
    """The whole map, with what it is and is not stated alongside it.

    `ledger_root` is where the receipts are -- a ledger is addressed, not
    located, so it resolves from the environment unless one is given.
    `root` is this repository, which is where the declared profiles are. They
    are different roots and were briefly one: reading the overlay out of a
    ledger directory would have produced an empty declared side and made every
    demonstrated capability read as undeclared.
    """
    try:
        chain = lineage.repository_chain(ledger_root)
    except (lineage.LineageRefused, SystemExit) as refused:
        # The lineage projection refuses a chain that does not verify, and that
        # refusal is the stronger disposition: a capability map built on a chain
        # whose receipts do not recompute would cite evidence that is not there.
        raise DemonstrationRefused(
            "PROJECTION_STANDS_ON_A_VERIFIED_CHAIN:" + str(refused)) from None
    this = map_of_this_organization(chain, root)
    peers = map_of_peer_addresses(chain)
    inbound = received_here(chain)
    outbound = served_by_a_peer_address(chain)
    return {
        "schema": PROJECTION_SCHEMA,
        "organization": this["organization"],
        "owner_repository": "StegVerse-org/.github",
        "receipts_read": len(chain),
        "this_organization": this,
        "peer_addresses": peers,
        "demonstration_count": len(inbound) + len(outbound),
        "profile_declaration_authority": PROFILE_DECLARATION_AUTHORITY,
        # ST-022's own line, carried so a reader of this map applies it.
        "a_profile_enables_capability_it_does_not_decide_admissibility": True,
        "admissibility_resolves_per_transition_not_from_this_projection": True,
        # ST-022's ceiling rule: evidence cannot widen a profile.
        "demonstration_is_evidence_not_a_grant": True,
        "effective_capability_is_an_intersection_with_every_ancestor_ceiling": True,
        # The epistemic limit that keeps this from being read as a survey.
        "absence_of_a_demonstration_is_not_evidence_of_absent_capability": True,
        "map_is_a_ratchet_of_positive_evidence": True,
        # The attestation gap, in the one place it lands on this map.
        "a_peer_address_is_not_an_identified_organization": True,
        "origin_attestation_state": "NOT_PROVEN",
        "credential_authority": "TV/TVC",
        "nothing_is_declared_or_stored_by_this_projection": True,
        "authority_effect": "NONE_PROJECTION_ONLY",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository-ledger-root", default=None)
    parser.add_argument("--out")
    args = parser.parse_args()
    result = projection(ledger_root=Path(args.repository_ledger_root)
                        if args.repository_ledger_root else None)
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
