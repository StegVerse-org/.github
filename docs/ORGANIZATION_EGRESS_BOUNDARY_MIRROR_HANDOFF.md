# Organization Egress Boundary Mirror Handoff

**Repository:** `StegVerse-org/.github`
**Operation:** `ORGANIZATION_INTER_ORG_EGRESS`
**Boundary document:** `org-runtime/interlock-intr.json` → `egress.emitting_operation`
**Status:** OUTBOUND_CROSSING_RECORDED_ORIGIN_UNATTESTED

## Inter-organization transport already worked

This is the finding that set the scope. A two-organization round trip completes
today with no new transport:

```text
StegVerse-org  →  build_packet(destination_org=Peer)  →  publish_packet  →  mesh
Peer           →  consume_and_respond(peer_root)      →  CONSUMED, response published
StegVerse-org  →  collect_ecosystem_responses         →  1 response, far-side terminal receipt
```

The federation mesh is the substrate, frames are content addressed, and
`org-boundary/registry/federation.json` already declares fourteen peer
organizations with their repositories, org-control services and the
`stegverse.intr.org-boundary.v1` transport profile. Nothing was missing from the
mechanism.

## What was missing was the record

`publish_packet` appends to no ledger and `collect_ecosystem_responses` only
reads the mesh. So leaving the organization — the most consequential transition
in the ecosystem — emitted **no receipt at all**, while
`organization_scope_rule` is that every state transition occurring within the
organization emits an organization receipt. The three inbound boundaries were
corrected to record every arrival under its disposition; this is the outbound
one, which was never built.

The boundary document said as much. Its `egress` section carried only
`interlock_required`, `intr_required`, `direction` and `standing_resolution` —
the outbound half was declared to exist and bound to nothing, so a reader could
not say which operation leaves the organization.

## Two transitions, not one

An outbound crossing is two dispositions separated in time, and either can be
refused on its own:

```text
emit    CROSS_AN_ORGANIZATION_BOUNDARY_OUTBOUND
        ORGANIZATION_EGRESS_EMITTED          ALLOW
        ORGANIZATION_EGRESS_REFUSED          DENY

close   OBSERVE_THE_FAR_SIDE_CLOSURE_OF_AN_OUTBOUND_CROSSING
        ORGANIZATION_EGRESS_CLOSED           ALLOW
        ORGANIZATION_EGRESS_CLOSURE_REFUSED  DENY
```

Both are recorded at both levels — the repository ledger first, the organization
ledger consuming that receipt as `REPO_STATE_PROPAGATION` — because a crossing
is not an exception to the layering `preserves_repo_receipt` requires.

The emission record is appended **after** the frame is published, because the
record is of an emission and carries the frame's digest. Minting it first would
be a receipt claiming a crossing that had not happened.

## An absence is not a transition

`close` returns `PENDING` and writes nothing when no response is in the mesh.
Nothing crossed the boundary, so there is no arrival to dispose of, and a chain
that appended a refusal on every poll would record the polling rather than the
crossing. A response that *is* present and does not verify is a crossing with
disposition DENY, recorded under its own class.

This is the line the `state_changed` correction drew, applied here: the
disposition of an action that occurred at the boundary is a transition; the
absence of an event is not.

## Destinations resolve from the organization's own directory

`resolve_destination` reads `org-boundary/registry/federation.json`. An
organization absent from it is refused, and so is one whose declared
`transport_profile` is not the profile this boundary speaks. A destination taken
from a caller's argument alone would let the caller name its own peer — the same
error as letting a caller name its own organization at ingress.

## What an outbound crossing does not prove

Recorded, not hidden, in every record and in the declaration:

* **The origin is asserted, not attested.** The frame says it came from this
  organization and nothing verifies that. Any writer of the shared mesh can
  publish a frame claiming any origin. Intra-organization this was tolerable;
  across a boundary it is the whole trust question, and it is the same rule as
  `caller_editable_ingress_source_field: FORBIDDEN_AS_AUTHORITATIVE_EVIDENCE`
  one level up. `origin_attestation_state` stays `NOT_PROVEN`,
  `origin_is_verified_by_this_boundary` is false, and `credential_authority`
  names TV/TVC as the authority that would change it.
* **The far side's receipt is carried, not verified.** Its terminal receipt id
  comes back in the response and this organization does not hold its ledger, so
  the chain cannot be reconstructed here. What *is* checked is listed beside
  what is not: that the response answers the packet that was emitted, comes
  from the organization that was resolved, carries an acknowledgement class, and
  carries a terminal receipt at all.

The validator refuses a declaration claiming otherwise:
`origin_attestation_state` other than `NOT_PROVEN`,
`origin_is_verified_by_this_boundary` true, or
`far_side_receipt_reconstructed_here` true each fail
`egress_emitting_operation_bound`.

## The declaration is enforced

Adding `egress.emitting_operation` to the boundary document without checking it
would be the declare-without-enforce defect this ecosystem exists to catch, so
`org-runtime/runtime_boundary.py` gained two checks, bringing its total to 13:

```text
egress_emitting_operation_bound
egress_destinations_resolve_from_the_directory
```

They hold the emitting operation to the same shape as the receiving operation —
owned here, no host, no environment URL, TV/TVC credential authority, no GitHub
token runtime authority, granting nothing — plus the two claims above. Each
check is asserted to **refuse** a bad declaration, not only to pass the good
one.

## Validation

```text
tests.test_organization_egress_boundary                23 tests OK
  an emitted crossing is recorded at both levels
  the organization consumes the repository receipt it did not author
  the record says a boundary was crossed
  the destination comes from this organization's own peer directory
  the record carries digests rather than the payload
  an undeclared peer is refused and recorded
  a refusal is never recorded as a crossing that left
  a refused crossing publishes no frame
  a peer speaking another transport profile is refused
  an absence is not recorded as anything
  the full round trip closes and is recorded
  the emission and the closure are two transitions on one chain
  a response answering another packet refuses the closure
  the closure record does not claim the far-side receipt was verified
  every record states the origin is asserted and not attested
  + 8 boundary-document checks, each asserted to refuse

org-runtime/runtime_boundary.py validate              valid: true, 13/13 checks
tests.test_organization_ingress_capability_binding    OK
tests.test_organization_role_runtime_reality_deployment OK
tests.test_intr_org_crossing                          OK
tests.test_organization_manifest_ingress              OK
tests.test_organization_repository_propagation        OK
actionlint on the new workflow                        clean
```

Both new CI steps were extracted verbatim from the workflow and run locally:

```text
EGRESS_EMITTING_OPERATION_BOUND=PASS 13 checks
INTER_ORG_ROUND_TRIP_ON_ONE_CHAIN=PASS 3 transitions
```

The round-trip step asserts the chain end to end:
`ORGANIZATION_EGRESS_EMITTED → ORGANIZATION_EGRESS_CLOSED →
ORGANIZATION_EGRESS_REFUSED` with dispositions `ALLOW ALLOW DENY`, every record
carrying an intended action and no record carrying `state_changed`, and the
organization chain carrying one consumed repository receipt per transition.

Both ledger roots are redirected per test and per CI step. The ledgers are
durable sovereign state and a run appending into either default location would
be writing runtime reality from a test.

## Next, and why it is next

**TV/TVC origin attestation.** This is now the only thing standing between a
recorded crossing and a *trusted* one, and it is no longer a vague step 5: the
egress record has the field, the validator refuses a false claim about it, and
the declaration names TV/TVC as the authority. The shape of the work is a
signature over the emitted packet produced under TVC authority, carried on the
frame, and verified at the receiving organization's ingress before it admits —
which turns `origin_attestation_state` from `NOT_PROVEN` into a verified
recognition and lets `origin_is_verified_by_this_boundary` become true on both
sides.

TVC (`StegVerse-Labs/TVC`) is an authority and evidence provider for scoped
execution tokens and receipt-bound admissibility evidence, and holds certificate
root key custody. Which of its surfaces issues an organization-level signing
authority — as opposed to a runtime-package execution token — is a design
decision for the repository owner and is not taken here.

**Receipt lineage for reversibility.** `Admissible-Existence/RE`'s lineage
contract requires `receipt_id`, `event_type`, `predecessor_id`, `payload_hash`
and `sequence`. A real eight-receipt StegVerse chain fed to RE's own
`validate_re_lineage.evaluate` returns `FAIL_CLOSED`, and
`LINEAGE_RECONSTRUCTABLE` through a field adapter supplying exactly two things:
`sequence`, which is derivable from chain position, and `event_type`
(`ORIGINAL / CORRECTION / INVALIDATION / SUPPLEMENT`), which is **not** —
nothing in a StegVerse receipt says that one transition corrects or invalidates
another. Inter-organization crossings are the chains most likely to need
reversing, so this is a prerequisite for the remediation lane rather than a
cleanup.

Nothing here grants authority. It records a crossing that occurred and the
disposition it reached.
