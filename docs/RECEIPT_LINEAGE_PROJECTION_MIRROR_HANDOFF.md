# Receipt Lineage Projection Mirror Handoff

**Repository:** `StegVerse-org/.github`
**Module:** `resident-runtime/receipt_lineage_projection.py`
**Target contract:** `Admissible-Existence/RE:data/re-lineage-contract.json`
**Status:** LINEAGE_DERIVED_NOT_STORED

## What this is for

Reversing from a current state to a historical one is RE's formalism, and
`PO-RE-004` is the obligation that makes it possible: receipt lineage must
remain reconstructable, append-only, with corrections that do not erase their
predecessors. Its contract asks each record for `receipt_id`, `event_type`,
`predecessor_id`, `payload_hash` and `sequence`.

A StegVerse receipt carries three of those under its own names and neither of
the other two. Fed to RE's own `validate_re_lineage.evaluate` as stored, a real
chain returns `FAIL_CLOSED`.

## Both missing fields are derivable

This was the finding that made the work small. Nothing is stored and no
repository that writes receipts changes:

```text
ORIGINAL      the receipt with no predecessor -- the first receipt of the chain
SUPPLEMENT    an ordinary append: adds to the chain without superseding anything
CORRECTION    the receipt names a prior receipt it corrects
INVALIDATION  the receipt names a prior receipt it voids
```

`sequence` is chain position. All of it comes from `previous_receipt_sha256`,
which every receipt already carries.

Marking the first receipt is the whole of what a new process has to do, which is
what RE requires and what nothing in StegVerse was doing. Every transition this
ecosystem currently emits is an `ORIGINAL` followed by `SUPPLEMENT`s, and that
is the correct reading of them: none of them supersedes another.

Only `CORRECTION` and `INVALIDATION` carry information the chain does not
already hold, because they *reference* a prior receipt. Those are two additive,
optional evidence fields — `corrects_receipt_sha256` and
`invalidates_receipt_sha256` — that appear only on a transition that actually
does it. **Nothing writes them yet.** The projection reflects them when
something does, and that path is tested rather than assumed.

## A projection, not a migration

The ledger is read-only here and unchanged by the projection. A receipt is
committed evidence and the shape it was minted in is part of what it is, which
is the same reason `tools/check_re_obligation_evidence.py` normalises RE's own
receipts for comparison rather than rewriting them.

Order is the chain's own, walked from HEAD backwards and reversed. A directory
listing would present receipts in whatever order the filesystem offers, and
`orphaned_or_reordered_history_fails_closed`.

Every receipt is verified against its own body before it is projected. That is
this ecosystem's own integrity rule rather than RE's: a projection built on a
receipt whose digest does not recompute would be presenting a lineage that does
not hold.

## RE judges; this does not

The rules about what makes a lineage reconstructable live in RE's contract and
its validator enforces them. Restating them here would be a second authority on
that shape, and the stale one — the defect corrected in `Admissible-Existence/RE`
#5, where a committed receipt disagreed with the validator it named.

So the projection produces records faithfully and reports
`verdict_is_res_to_give_not_this_projections`. It declares its own output shape,
`PROJECTED_FIELDS`, which is a different thing from restating RE's judgment.

**`Admissible-Existence/RE` is private**, so a cross-organization
`actions/checkout` here would need a credential secret, and
`github_token_runtime_authority` is `NONE`. Each repository therefore asserts
what it owns:

| Repository | Asserts |
| --- | --- |
| `StegVerse-org/.github` | the projection — the derivation, the shape, faithfulness, that nothing is stored, that the ledger is unchanged |
| `Admissible-Existence/RE` | the verdict — a projected chain run through RE's own `validate_re_lineage.evaluate` |

Neither restates the other's rules, and no credential is introduced.

## Verification

Run in this session against `Admissible-Existence/RE` at
`e9086cf8dd95c1f1b070c6432cbf2f45f9268e34`, both repositories present:

```text
REPOSITORY    3 records | {'ORIGINAL': 1, 'SUPPLEMENT': 2} | RE: LINEAGE_RECONSTRUCTABLE
ORGANIZATION  3 records | {'ORIGINAL': 1, 'SUPPLEMENT': 2} | RE: LINEAGE_RECONSTRUCTABLE
raw receipts, no projection                                | RE: FAIL_CLOSED
```

The chain projected is a real inter-organization crossing —
`ORGANIZATION_EGRESS_EMITTED`, `ORGANIZATION_EGRESS_CLOSED`,
`ORGANIZATION_EGRESS_REFUSED` — not a synthetic fixture.

```text
tests.test_receipt_lineage_projection                 17 tests OK
org-runtime/runtime_boundary.py validate              valid: true, 13/13
actionlint on the new workflow                        clean
```

Both CI steps extracted verbatim from the workflow and run locally:

```text
LINEAGE_PROJECTION=REPOSITORY=PASS 3 records {'ORIGINAL': 1, 'SUPPLEMENT': 2}
LINEAGE_PROJECTION=ORGANIZATION=PASS 3 records {'ORIGINAL': 1, 'SUPPLEMENT': 2}
```

## One defect this surfaced

The two ledger levels name their state fields differently: a repository receipt
carries `successor_state_sha256`, an organization receipt carries
`successor_org_state_sha256`. Projecting only the repository spelling silently
produced a null `payload_hash`, and the organization level returned
`FAIL_CLOSED` from RE while the repository level passed. The projection now
reads the field the level actually uses, and a test asserts both spellings
rather than one assumed form.

Worth recording because it is the kind of thing only a cross-level projection
finds: both chains were internally valid and neither level's own tests could
have caught it.

## Authority boundaries

Nothing here grants authority. RE's own contract states it —
`lineage_reconstruction_creates_authority: false` — and a projection of a chain
is not a transition on it. `authority_effect` is `NONE_PROJECTION_ONLY`.

All five RE obligations remain `tested_not_proven`. Reconstructable lineage is
not a proof of reversibility; it is the precondition `PO-RE-004` states, and
`PO-RE-002`'s reduction and `PO-RE-003`'s standing re-entry remain separate
obligations this does not touch.
