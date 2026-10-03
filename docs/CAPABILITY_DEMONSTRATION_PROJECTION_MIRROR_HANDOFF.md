# Capability Demonstration Projection Mirror Handoff

**Repository:** `StegVerse-org/.github`
**Projection:** `resident-runtime/capability_demonstration_projection.py`
**Profile declaration authority:** `StegVerse-Labs/repo-standards:standards/ST-022_KV_PARTICIPANT.standard.md`
**Status:** DEMONSTRATED_SIDE_DERIVED_DECLARED_SIDE_OWNED_BY_ST_022

## The map was going to be enumerated, and should not be

The capability map's next step looked like a list: a service per peer, written
into this organization's directory, so an outbound manifest could be addressed
to a peer's receiving operation. `peer_capability_resolution` already records
why that is weak —
`peer_declares_its_capability_services_in_the_peer_directory: false`. This
organization writing down what its peers serve is a declaration none of them
made, and it is the same defect class as every other one corrected here: a
declaration nothing enforces.

## ST-022 already separates intention from occurrence

The owner surface settles the declared half, and it does so by reusing what is
already here:

> Capabilities are declared with the mechanism already used for services in an
> organization service registry, raised from service to participant:
> `boundary_role`, `profile_status`, and an `accepts[]` list of admitted message
> classes. **A profile enables capability. It does not decide admissibility —
> admissibility resolves at the binding moment, per transition.**

So a profile is an *intention*, and admissibility is an *occurrence* resolved
per transition. Nothing was deriving the second. Every crossing already writes
the evidence for it, and nothing read it back.

This projection reads it back. It declares nothing, stores nothing, and the
repository ledger is read from HEAD backwards with every receipt verified
against its own body — the same walk `receipt_lineage_projection` performs,
reused rather than reimplemented.

## Two kinds of demonstration, because the evidence differs

| | evidence | what it establishes |
| --- | --- | --- |
| `RECEIVED_HERE` | a receipt naming a receiving operation and the capability profile it serves | this organization's operation dispositioned a submission under that capability |
| `SERVED_BY_A_PEER_ADDRESS` | a verified closure joined to its emission | something at that address ran this packet and minted the chain this packet determines |

The second one matters more than it looks. A closure requires the far side's
receipt chain to **recompute** from inputs this organization already held, so a
verified closure is real evidence of service. It is exactly what
`peer_serves_this_capability_is_proven_here: false` says cannot be established
at resolution time — and it can be established at closure. Resolution cannot
prove a peer serves a capability. A closure can.

## Declared against demonstrated

```text
DECLARED_AND_DEMONSTRATED      a working capability
DECLARED_NOT_YET_DEMONSTRATED  a declaration nothing has exercised
DEMONSTRATED_AND_NOT_DECLARED  served without being declared
```

The middle cell is this ecosystem's own defect class, counted automatically from
whatever has been run. It is why the map is worth having beyond routing: every
experiment that leaves a receipt moves a capability out of that cell, and a
declaration that never moves is visible as such without anyone auditing for it.

`exercised` is carried separately from `demonstrated`, because the state lattice
cannot hold both. A capability that refuses every submission is not
demonstrated, but it *is* being tested; a capability nothing has ever submitted
to is not. Collapsing them would make an untried declaration and a failing one
read alike.

## One upstream gap this needed, and closed

A refused submission recorded no capability. `refusal_record` deliberately
carries "nothing an admitted crossing would have produced", which is right for
the resolved service and the receipt chain — but it also omitted which
capability's receiving operation refused and what the submission declared it
wanted. Without those, **a capability that only ever refuses is
indistinguishable from one nothing has ever exercised.**

The refusal now carries `profile_id`, `operation`,
`submitted_processing_capability` and `submitted_route_id`. Neither is something
the admitted crossing produced: the first is a constant of the operation, the
second is the submitter's own declaration. A submission that declared nothing
records nulls rather than omitting the field, because "declared nothing" and "we
did not record it" are different facts.

`destination_resolution_source` is deliberately **not** on a refusal. A refusal
resolved no destination, and marking it as a record that did would put it in the
disorder measurement's `resolving` population and have it measured for target
and scope fields it correctly lacks — the false finding that measurement already
had once.

So the projection keys on a record naming both a receiving operation and a
capability profile, which admissions and refusals have in common, rather than on
the resolution source, which only admissions carry.

## What this must never be read as

* **A demonstration is not a grant.** ST-022's ceiling rule makes effective
  capability `own_profile ∩ ceiling(parent) ∩ … ∩ jurisdiction_set`, and a
  parent may only ever narrow. Evidence that a capability ran cannot widen a
  profile past a ceiling. This projection's `authority_effect` is
  `NONE_PROJECTION_ONLY`.
* **Admissibility is still per transition.** A capability on this map does not
  admit the next crossing.
* **Absence is not refutation.** A capability nothing has exercised is absent,
  which says only that no demonstration exists — not that the capability is
  unsupported. The map is a **ratchet of positive evidence**, not a survey, and
  reading it as one would make an unrun experiment look like a missing
  capability.
* **It does not say who.** A closure proves the address served the capability,
  not which organization that address belongs to. Origin is asserted and
  `credential_authority` is TV/TVC, so peer entries are keyed by **address**,
  with the organization recorded as the one this organization addressed rather
  than one the far side proved.

## The demo surface

The map is produced by CI from the demonstrations that run actually performs,
and uploaded as an artifact. It is never a committed snapshot: a file in the
tree would read as current while the ledger moved on, which is the staleness
defect this repository has already hit twice. A ledger is addressed, not
located, so the map is derived where the receipts are.

```text
CAPABILITY_MAP_DERIVED_FROM_DEMONSTRATIONS=PASS 2 demonstrations
  own   sdk-manifest-ingress                 DECLARED_AND_DEMONSTRATED   exercised, 1 admitted
  peer  stegverse-labs.sdk-manifest-ingress  served 1   declared_profile_readable_here false
```

## Verified

```text
tests.test_capability_demonstration_projection   18 OK
tests.test_organization_manifest_ingress         23 OK
org-runtime/runtime_boundary.py validate         valid, 15/15
actionlint                                       clean
```

Both CI steps extracted verbatim and run locally.

## What this does not close

`SVORG-CAPABILITY-MAP-DISCOVERY-001` asks how the capability map **reaches a
node that holds no repository**, and its activation condition — whether the
capability map and the ST-022 KV participant spec are one spec — is an owner
decision that has not been made. That is distribution, and it is untouched here.
This is derivation: where the map's content comes from. The two are separable,
and deriving the content does not decide how it travels.

Nothing here grants authority.
