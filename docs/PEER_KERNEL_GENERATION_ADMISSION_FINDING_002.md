# Finding 002 — two peers declare a kernel gate they do not run

    document_id:      PEER-KERNEL-GENERATION-ADMISSION-FINDING-002
    status:           RECORDED_FOR_THE_OWNING_ORGANIZATIONS
    authority_effect: NONE_FINDING_ONLY
    owners_of_the_fix: StegVerse-Labs, Admissible-Existence
    raised_from:      StegVerse-org/.github
    supersedes_nothing: true
    answered_by:      PEER-KERNEL-GENERATION-ADMISSION-MIGRATION-002

## The finding

`StegVerse-Labs` and `Admissible-Existence` each declare, in their own
`org-boundary/registry/federation.json` and in ours:

    kernel_required: 1.3.0
    transport_profile: stegverse.intr.org-boundary.v1

Both run a kernel that does not gate on canonical node standing. A packet
declaring an arbitrary origin and **no standing at all** is admitted and
receipted by each of them:

    Admissible-Existence   CONSUMED   <- no standing required
    StegVerse-Labs         CONSUMED   <- no standing required

The same packet is refused at this organization's boundary, fail-closed:

    node_standing_refused:node-standing-fail_closed:
      claimed-standing-not-provable:no-standing-declared

## Stated at the strength the evidence supports

This is an **admission** gap, not an execution one. The consuming kernel's own
application result says so:

    "consumed": true,
    "application_result": {
      "message_received": true,
      "execution_authority_inferred": false,
      "execution_authority_effect": "NONE"
    },
    "authority_effect": "NONE"

So this is not "anyone can make these organizations do something". Nothing is
executed and no authority is conferred. What happens is narrower and still
worth recording: **a full receipt chain is minted for a crossing whose origin
was never established.** The probe's declared origin was the string
`Anyone-At-All`, and it appears in the receipted packet as the origin.

That matters because `origin` is caller-written, and this ecosystem's own
contract says a caller-editable classification does not establish identity --
`CALLER_EDITABLE_CLASSIFICATION_DOES_NOT_ESTABLISH_IDENTITY`. The standing gate
is what converts a written origin into an admitted one. Without it, the
receipts are real and what they attest to is thinner than a reader of the chain
would reasonably assume.

## The asymmetry, which is why this is not urgent for us

Inbound to this organization, the gate holds and is held by a case:
`tests/test_node_standing_ingress.py::test_the_crossing_lane_refuses_an_envelope_with_no_standing`.
Our `build_packet` additionally makes `standing` a required keyword, so a
standing-less packet cannot be constructed here at all.

Outbound, every packet this organization emits carries standing, so crossings
to these peers are well-formed; they are simply not checked on arrival. The
risk therefore sits with the receiving organizations and with anyone reading
their chains, not with this one.

## What this organization already records

`resolve_destination` carries `destination_kernel_required` into the resolution
record and compares it to nothing, and since
`fix/peer-kernel-generation-not-proven` the record says so rather than implying
otherwise:

    destination_kernel_generation_is_proven_here: false
    destination_kernel_required_is_checked_at_resolution: false
    declared_kernel_version_does_not_establish_the_enforcement_it_implies: true

This finding is the concrete instance those fields were written for. They
predicted that a declared version would not establish the enforcement it
implies; here are two organizations where it does not.

## What this document does not do

It does not change either organization's kernel. Neither profile repository can
be written from the session that raised this -- both are named `.github`, and a
repository whose name begins with `.` cannot be attached here, so read is the
ceiling.

The gate itself now exists as an applicable artifact, recorded separately in
`docs/PEER_KERNEL_GENERATION_ADMISSION_MIGRATION_002.md`: two patches that
apply cleanly to both current heads, bring each peer to disposition parity with
this organization, and pass each peer's own test suite unchanged except by the
patch. The ceiling above is unmoved -- a recorded patch is not an applied one,
and applying it remains the owning organization's act.

It does not assert that the older kernel is broken for its own purposes. It
runs, it consumes, it mints a correct receipt chain, and it declines to infer
execution authority. What it does not do is the thing `kernel_required: 1.3.0`
says it does.

It does not propose that this organization check a peer's kernel generation at
resolution time. A local assertion about a remote kernel would be the same
defect relocated. The claim belongs to the party that can prove it, which is
the peer, at its own ingress surface.

## Reproduction

With `StegVerse-Labs/.github` and `Admissible-Existence/.github` cloned beside
this repository, load each peer's **own** kernel against its **own** tree --
loading this organization's kernel against a peer tree tests the wrong thing
and will fail for an unrelated reason (`org_boundary_node_standing_missing`,
because the peer does not carry the module this kernel requires):

    k = <peer kernel>.build_packet(
            origin_org="Anyone-At-All", origin_service="anyone.org-control",
            destination_org=<peer>, destination_service=<peer org-control>,
            payload={"probe": "unstanding"})
    <peer kernel>.publish_packet(k, root=mesh)
    <peer kernel>.consume_and_respond(<peer root>, mesh_root=mesh)

Offer the same packet to this organization's kernel to see the refusal.
