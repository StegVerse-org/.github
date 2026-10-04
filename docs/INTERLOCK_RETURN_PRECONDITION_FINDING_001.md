# Finding 001 — the interlock return is gated on the wrong ledger

    document_id:      INTERLOCK-RETURN-PRECONDITION-FINDING-001
    status:           RECORDED_FOR_THE_OWNING_SURFACE
    authority_effect: NONE_FINDING_ONLY
    owner_of_the_fix: StegVerse-org/StegVerse-SDK
    raised_from:      StegVerse-org/.github

## The finding

`stegverse/post_return_evidence.py::build_pending_interlock_return` refuses to
build an interlock return at all unless the run it is handed reports:

    master_records_custody_status == "RECORDED"

That makes an **organization-level return** wait on **ecosystem-level
custody**. This organization's own ledger contract says it does not.

## The evidence, from the surface that owns it

`.stegverse/transition-ledger/org-contract.json`:

    replay_rule: ORGANIZATION_REPLAY_MUST_REQUIRE_ONLY_VERIFIED_REPO_RECEIPTS
                 _AND_ORG_RECEIPTS_NOT_ECOSYSTEM_REPLAY
    propagation_gates_organization_runtime_reality: false
    propagation_target:                            master-records/.github
    propagation_role:    RELEASED_ORGANIZATION_BATCH_RECEIPT_RECORDER
    always_on_receiver_required:                   false
    runtime_reality_authority:                     Organization
    ledger_root_is_organization_runtime_reality_locus: true

Four of those are the finding on their own. Master Records is the
**propagation target** and the **batch receipt recorder** — where organization
transitions go afterwards as observed reality and custody. It is explicitly
**not** a gate: `propagation_gates_organization_runtime_reality` is false, and
`always_on_receiver_required` is false, so Master Records being unreachable is
declared not to block this organization's runtime reality. The replay rule says
the same thing from the replay side.

## Why it matters, stated narrowly

This is not a claim that Master Records is the wrong custody authority. It is
the right one, and the authority split in
`StegVerse-Labs/.github` says so: *Master Records: observed reality, custody,
reconstruction.*

The finding is about **gating**. A return describes a transition that occurred
within an organization, and the evidence for that transition is the
organization receipt this boundary already writes on every crossing —
`organization_scope_rule` requires one for every state transition occurring
within the organization. Requiring ecosystem custody before that return can be
constructed inverts the layering: it makes the slower, broader authority a
precondition of the narrower, faster one, which is the opposite of how the
contract arranges them.

It also has a practical consequence worth naming. With that gate in place the
return leg cannot be exercised at all until custody closes, so a capability
that is written and tested reads as unbuilt. Relocating the precondition to
org receipts would let the return be exercised against evidence that already
exists, without weakening what custody means.

## What this document does not do

It does not change the SDK, which owns the gate and its own contract process.
It does not assert that org receipts are *sufficient* evidence for a return —
only that the contract makes them the organization-level locus and makes
ecosystem custody a propagation target rather than a precondition. Whether the
return additionally wants custody as *recorded context* rather than as a
*refusal condition* is the owning surface's design call.

It creates no route, runtime, credential, node, ingress, authority, deployment,
release or Task Registry entry.

## What this organization holds

`tests/test_organization_role_runtime_reality_deployment.py` asserts the
contract fields above, including the replay rule, which nothing had been
holding. That case exists so this contradiction is never resolved by weakening
the position here rather than correcting it where it lives.
