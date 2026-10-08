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
* **The far side's receipt is reconstructed, not carried.** This claim was
  retracted after it shipped. The first version of this operation said the far
  side's chain could not be verified here, and the validator *enforced* that — a
  declared limit that is not real. A boundary receipt id is
  `kind-sha256(canon({kind, packet_id, subject, previous_receipt_id,
  detail}))[:24]`, and every input is something this organization already
  holds: the packet id it minted, the service id it resolved from its own
  directory, and the digest of its own payload. So the terminal id that comes
  back is **recomputed and compared**, and a response that does not recompute
  did not come from a boundary that ran this packet. It is the same move
  `organization_manifest_ingress.reconstruct_closures` already makes inbound.

  Reconstruction proves a boundary ran this packet and minted the chain this
  packet determines. It does **not** prove which organization that boundary
  belongs to, and it does not prove the far side persisted the chain on its own
  ledger. Those are the bilateral match, which needs the far side's chain
  readable and is not available at closure.

  A closure also requires **this organization's own emission record**, read off
  its own chain: that is the local half of the bilateral match, and a crossing
  with no emission receipt here is one this organization has no record of
  making, so it cannot be closed.

The validator refuses a declaration claiming otherwise. An
`origin_attestation_state` other than `NOT_PROVEN`,
`origin_is_verified_by_this_boundary` true,
`reconstruction_proves_who_the_far_side_is` true or
`reconstruction_proves_the_far_side_persisted_its_chain` true each fail
`egress_emitting_operation_bound` — and so now does declaring
`far_side_receipt_reconstructed_here` **false**, because understating what the
chain establishes is as wrong as overstating it.

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

## What identifies the initiator, and where a credential is still needed

Not a field. The **matching pair** does: a forged origin cannot produce one,
because the claimed initiator's own ledger would hold no
`ORGANIZATION_EGRESS_EMITTED` receipt binding that packet id. Identification is
by chain, not by credential, and `origin_attestation_state` is a disclaimer that
no credential was presented rather than the thing that establishes who sent it.

The match is available in two places and not in a third:

* **At closure, emitter side** — reconstruction, above. Needs no counterparty
  cooperation and runs today.
* **At audit, bilaterally** — both chains readable, each binding the same packet
  id and payload digest.
* **Not at ingress.** The receiving organization would have to read the claimed
  initiator's ledger synchronously, and a ledger is addressed, not located: the
  propagation sweep found 1 of 18 declared repositories present on that node.
  So the far side admits structurally and a forgery is caught afterwards.

That is sufficient while admission confers nothing — `authority_effect` is
`NONE` on every surface and nothing executes on the strength of a frame. It
stops being sufficient at the first irreversible consequence, which is **writing an
organization record to Master Records**: discovering afterwards that a frame was forged is
a far worse position than refusing it at the door.

So TV/TVC attestation is **not** a prerequisite for inter-organization
transport. It is required before that organization record is written. TVC (`StegVerse-Labs/TVC`) is an
authority and evidence provider for scoped execution tokens and receipt-bound
admissibility evidence, and holds certificate root key custody; which of its
surfaces issues an organization-level signing authority — as opposed to a
runtime-package execution token — is a design decision for the repository
owner and is not taken here.

## Receipt lineage for reversibility, and why it is smaller than it looked

`Admissible-Existence/RE`'s lineage contract requires `receipt_id`,
`event_type`, `predecessor_id`, `payload_hash` and `sequence`. A real egress
chain fed to RE's own `validate_re_lineage.evaluate` returns `FAIL_CLOSED` as
stored, and `LINEAGE_RECONSTRUCTABLE` once projected:

```text
real egress chain   : EGRESS_EMITTED, EGRESS_CLOSED, EGRESS_REFUSED
derived event_types : ORIGINAL, SUPPLEMENT, SUPPLEMENT
RE lineage verdict  : LINEAGE_RECONSTRUCTABLE
raw receipts        : FAIL_CLOSED
```

Both missing fields are **derivable**, so no receipt schema changes and no
repository that writes receipts is touched. `ORIGINAL` is the receipt with no
predecessor — the first receipt of a chain, which is exactly what RE requires
a new process to mark. Every ordinary append that adds to the chain without
superseding anything is a `SUPPLEMENT`. `sequence` is chain position. All three
come from `previous_receipt_sha256`, which every receipt already carries.

Only `CORRECTION` and `INVALIDATION` carry information the chain does not
already hold, because they *reference* a prior receipt they supersede or void.
Those are additive optional fields appearing only on a transition that actually
does it, not a rewrite of the receipt shape.

Nothing here grants authority. It records a crossing that occurred and the
disposition it reached.

## A carried requirement is not a verified one

`federation.json` declares `kernel_required` for every peer. `resolve_destination`
read it, carried it into the record as `destination_kernel_required`, and
**checked nothing**. `transport_profile`, beside it in the same row, is refused
on mismatch. So one field in the row was enforced and the other only looked
like it was.

This was found while confirming whether `Admissible-Existence` is wired for
InTr. It is: a crossing resolves to `admissible-existence.org-control`, emits,
and is CONSUMED by that organization's own kernel with the full five-receipt
chain. What the crossing also showed is why the unchecked field matters.

```text
StegVerse-org/.github        org-kernel/kernel.py   779 lines   kernel_version 1.3.1
Admissible-Existence/.github org-kernel/kernel.py   499 lines   kernel_version 1.3.1
```

Both declare `1.3.1`. The 779-line kernel resolves `node_standing` and
`manifest_selection` before admitting anything and records
`node_standing_disposition` and `processing_selection` on every dispatch. The
499-line kernel references neither, and the crossing's execution result carries
neither field. Same declared version, materially different enforcement.

So a declared kernel version does not establish the enforcement it implies, and
a peer's generation is not readable from here at resolution time — the same
shape as `peer_serves_this_capability_is_proven_here: false`. The record now
says so rather than letting a carried requirement read as a checked one:

```text
destination_kernel_required                           carried from the directory
destination_kernel_required_is_checked_at_resolution  false
destination_kernel_generation_is_proven_here           false
declared_kernel_version_does_not_establish_the_enforcement_it_implies  true
```

A peer below its declared requirement is **not** refused, and a test asserts
that — recorded because it is true, not because it is desirable. Gating a
crossing on a peer's kernel generation would need that generation readable,
which it is not. Establishing it is the peer's to do, and bringing a peer's
kernel forward is a migration in that organization under ST-020 and ST-014,
not something this directory can assert by carrying a number.

## An unreachable closure is not a pending one

Found while confirming whether `StegVerse-Labs` is wired for InTr. It is, and
more completely than the probe that found this suggested: a crossing resolves to
`stegverse-labs.org-control`, emits, is CONSUMED by that organization's own
kernel with the full five-receipt chain, that kernel publishes a response, and
`close` observes it, reconstructs the far-side terminal receipt, matches it and
records `ORGANIZATION_EGRESS_CLOSED`. All three request classes the profile
answers close end to end against the real tree.

The first probe did not, and the reason was the probe's own payload:

```text
payload {"probe": "intr-wiring"}

emit    ALLOW      frame published, standing carried
peer    CONSUMED   five receipts, terminal receipt minted
close   PENDING    forever
```

`consume_and_respond` answers only the request classes the transport profile
names, and `close` correlates an answer by `communication_id`, which `emit` read
from the payload and from nowhere else. A payload declaring neither is published,
consumed and receipted — and never answered. So the crossing was not pending,
which is a crossing still in flight. Its closure was **unreachable**, which
`PENDING` cannot express, and `emit` returned `ALLOW` for it.

Every caller already passed both fields. The precondition was honoured by
convention and checked by nothing, which is the same shape as the unchecked
`kernel_required` above — except this one is readable in this organization's own
payload rather than in a peer's tree, so it is refused rather than recorded:

```text
PAYLOAD_DECLARES_A_REQUEST_CLASS_THE_BOUNDARY_ANSWERS          DENY
PAYLOAD_CARRIES_THE_COMMUNICATION_ID_CLOSURE_CORRELATES_ON     DENY
```

The answering set had been a literal in the responder and, separately, the keys
of the response-class mapping. It is now named once, as
`org-kernel/kernel.py::RESPONDED_REQUEST_CLASSES`, and the boundary document's
`closable_crossing_precondition` is validated against the kernel's own set
rather than restating it, so the declaration cannot drift from the code.

What the refusal does not establish: the set is **this** organization's
responder's, and a peer's is not readable from here. The refusal therefore rests
on the shared transport profile, which both sides declare, and the declaration
says so:

```text
responded_request_classes_are_this_organizations_responders  true
peer_responded_request_classes_are_readable_here             false
```

A peer that answered a class this profile does not name would have its crossing
refused here. That is the fail-closed direction, and it is preferred to the
alternative this section replaces: reporting ALLOW for a crossing that could
never complete.

Nothing here grants authority.
