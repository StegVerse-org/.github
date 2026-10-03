# Receipt Disorder Measurement Mirror Handoff

**Repository:** `StegVerse-org/.github`
**Module:** `resident-runtime/receipt_disorder_measurement.py`
**Target contracts:** `Admissible-Existence/RE:data/re-disorder-classes.json`, `…/re-reduction-contract.json`
**Status:** ALL_TEN_CLASSES_OBSERVED

## Why all ten, and not most of them

`PO-RE-001` declares what disorder is: ten classes, each with a weight and a
measurement expressed as a ratio. `PO-RE-002` admits a repair as a reduction
candidate only if it lowers the score **and** increases no dimension —
`hidden_disorder_tolerance` is `0.0`, and "no previously zero dimension
increases above zero".

That is why a partial measurement is not a smaller version of this surface but
a different and worse thing. An **unobserved dimension is exactly where hidden
disorder hides**: a reduction proven over four of ten classes would admit a
repair that fixed one dimension by breaking an unwatched one, which is the
overclaim `hidden_disorder_tolerance: 0.0` exists to refuse.

So all ten are observed. Nine of them currently read zero; that is a result, not
a reason to have measured fewer.

## Two classes that looked unobservable and were not

An earlier reading of this called `stale_evidence` and
`policy_or_delegation_mismatch` unobservable. Both were wrong, and neither needs
a number invented here.

* **`stale_evidence`** needs no clock and no declared freshness window. Stale
  means *no longer current*, and in an append-only chain that is
  **supersession**: evidence a later `CORRECTION` or `INVALIDATION` replaced,
  which `receipt_lineage_projection` already derives. A window expressed in
  heartbeat epochs would have been a policy value chosen here rather than
  declared by the organization, and this needs none.
* **`policy_or_delegation_mismatch`** already has its link structure. The
  capability overlay in `org-runtime/interlock-intr.json` *is* the delegation —
  it declares who owns a capability, who binds it, which operation receives it
  and which transport profile a peer must speak. A crossing either resolves
  through it or does not.

## What each class counts

| Class | Numerator over denominator |
| --- | --- |
| `missing_receipt_chain` | receipt references across both chains that fail to resolve on the chain they name |
| `stale_evidence` | receipts superseded by a later `CORRECTION` or `INVALIDATION` |
| `conflicting_evidence` | receipts that fail to recompute against their own body, or that a store holds and the chain's HEAD cannot reach |
| `unreconstructable_authority` | organization receipts whose consumed repository receipt does not resolve |
| `unresolved_actor_identity` | origin claims whose attestation is not `PROVEN` |
| `target_or_scope_ambiguity` | absent target or scope fields on records that resolved a destination |
| `policy_or_delegation_mismatch` | delegation links disagreeing with the capability overlay |
| `replay_divergence` | far-side boundary receipt steps whose recomputed terminal disagrees with what came back |
| `repair_without_reentry` | *critical binary* — a repaired candidate recording no standing re-entry |
| `sandbox_authority_confusion` | *critical binary* — a receipt whose `authority_effect` is not `NONE`-prefixed |

Both levels are required. The organization chain is where authority links live,
so a repository-only measurement would leave `unreconstructable_authority`
unobserved — and this surface exists to observe all ten.

Every class reports its numerator and denominator rather than only a ratio, so
a reader can see what was counted. A zero denominator is reported **unobserved**
and left out of the severity map, because the contract's `missing_denominator`
disposition is `FAIL_CLOSED` and a fabricated denominator would be worse than an
absent dimension. A critical binary with an empty population is observed at
zero: nothing to be wrong is a measurement, not a gap.

## This measures; RE scores

`D = sum(weight_i * severity_i)` and the thresholds live in RE's contract, and
`validate_re_disorder_classes.score_observation` applies them — callable since
`Admissible-Existence/RE` #6 precisely so an observer need not carry a copy.
Carrying the formula here would be a second authority on the score, and the
stale one.

A test asserts the absence: no declared weight or threshold value appears in
this module's source.

## Measured, on a real chain

A real inter-organization crossing — emitted, closed, and one refused:

```text
missing_receipt_chain            0.0        0/7
stale_evidence                   0.0        0/6
conflicting_evidence             0.0        0/6
unreconstructable_authority      0.0        0/3
unresolved_actor_identity        1.0        3/3
target_or_scope_ambiguity        0.0        0/4
policy_or_delegation_mismatch    0.0        0/3
replay_divergence                0.0        0/5
repair_without_reentry           0.0        population 0
sandbox_authority_confusion      0.0        population 6

RE scores it: 0.08 | CONVERGED_CANDIDATE | lower bound: false
```

**The whole score is one dimension.** `unresolved_actor_identity` is `1.0`
because every inter-organization crossing's origin is asserted by its sender and
verified by nothing. The attestation gap is now a measured quantity rather than
a prose caveat, and it is the only disorder this ecosystem's receipt state
currently carries. `replay_divergence` is `0.0` because the egress closure
recomputes the far side's chain rather than trusting it.

`lower bound: false` is the part that matters. With all ten observed, the score
is a measurement rather than an understatement.

## One false finding, caught before it was reported

The first version of this measurement scored `target_or_scope_ambiguity` at
`0.375` and `policy_or_delegation_mismatch` at `0.333`. Neither was real. The
population was every record that crossed a boundary, which counted a **closure**
record as ambiguous for not repeating the destination resolution its **emission**
record already holds. A measurement artifact, about to be reported as ecosystem
disorder.

The population is now records that actually performed a resolution, marked by
`destination_resolution_source`, and a test asserts that a closure record is not
counted as an ambiguous target. Recorded because a measurement surface that
produces false findings is worse than none: it would have sent a repair after a
defect that did not exist.

## Validation

```text
tests.test_receipt_disorder_measurement        15 tests OK
  all ten declared classes are measured
  why all ten rather than most
  every class reports what it counted
  an unattested origin is measured at one
  the far-side reconstruction measures no replay divergence
  a closure record is not counted as an ambiguous target
  a receipt that does not recompute is conflicting evidence
  an orphaned receipt is conflicting evidence
  a receipt asserting authority trips the critical binary
  a repair population that is empty is observed at zero
  stale evidence is supersession rather than a clock
  the formula is not restated here
  the severity map is what RE's scorer consumes
  the measurement grants nothing
  measuring nothing is refused

full per-file sweep                            24 of 25
actionlint on the new workflow                 clean
```

The one sweep failure is `test_sdk_manifest_crossing_fidelity`, which fails
identically on `main` because this container holds a newer SDK than its workflow
pins.

The CI step, extracted verbatim and run locally:

```text
DISORDER_MEASURED_ALL_TEN=PASS 10 of 10 | unattested origin: 1.0
```

## What this does not do

It does not score, and it does not judge. It does not prove a reduction:
`PO-RE-002` needs a *before* and an *after* around a repair, and there is no
remediation lane yet to produce one. What this provides is the *before* — the
first honest baseline, with every dimension observed, so that when a repair
happens the reduction can be proven without hidden disorder.

Nothing here grants authority. `authority_effect` is `NONE_MEASUREMENT_ONLY`,
and all five RE obligations remain `tested_not_proven`.

## Correction: two resolution surfaces, not one

Two classes measured every record that resolved a target against the fields an
*outbound* crossing carries. That was right while an outbound crossing was the
only resolution in any ledger. It is not right in general, and it became wrong
in practice the moment a bound capability got an address, because an inbound
submission then resolves a target too — and resolves a different kind of one.

An outbound crossing resolves a **peer organization** from this organization's
peer directory. An inbound submission resolves a **receiving operation** from
the capability overlay. Measured against the peer directory's fields, every
manifest submission scored:

```text
target_or_scope_ambiguity      1.0    no destination_organization, no peer address
policy_or_delegation_mismatch  1.0    resolution_source is the overlay, not the directory
```

Both false. The ingress record carries no peer address because it addressed no
peer, and a record resolved through the overlay is not mis-delegated for having
been resolved through the overlay — the overlay *is* the delegation structure
this class measures against.

The fix measures each record against the surface it declares it resolved
through. `TARGET_SCOPE_FIELDS` is now keyed by resolution surface, and the
delegation links differ by surface: for an outbound crossing, directory
resolution and the declared transport profile and owning repository; for an
inbound submission, that the capability is one the overlay binds and that the
operation reached is the one that binding names. A resolution through a surface
nothing declares is counted as a finding rather than skipped — it resolved a
target against something undeclared, which is what scope ambiguity is.

Coverage grew rather than narrowed, which is the point: narrowing the population
to outbound crossings would have removed the false finding by leaving the inbound
lane unmeasured, and an unmeasured dimension is where `hidden_disorder_tolerance:
0.0` says disorder hides.

Measured over a ledger holding both lanes — an outbound crossing emitted and
closed, and a peer's manifest submission received at the capability address:

```text
target_or_scope_ambiguity      0.0    0/9    (4 peer fields + 5 overlay fields)
policy_or_delegation_mismatch  0.0    0/6    (3 links + 3 links)
unresolved_actor_identity      1.0    2/2
all seven others               0.0
observed                       10 of 10
```

Recorded for the same reason the first false finding was: a measurement surface
that produces false findings is worse than none, because it sends a repair after
a defect that does not exist.
