# Migration 002 — the gate Finding 002 reported, built and proven

    document_id:        PEER-KERNEL-GENERATION-ADMISSION-MIGRATION-002
    status:             ONE_PEER_APPLIED_ONE_PEER_AWAITING_ITS_ORGANIZATION
    authority_effect:   NONE_MIGRATION_ARTIFACT_ONLY
    answers:            PEER-KERNEL-GENERATION-ADMISSION-FINDING-002
    owners_of_the_fix:  StegVerse-Labs, Admissible-Existence
    raised_from:        StegVerse-org/.github
    not_applied_here:   true

    applied:            StegVerse-Labs/.github, default branch, commit
                          5f14de9ac686b0b6b4f77ece31087a0e980b537b,
                          kernel_version 1.3.2, NODE_STANDING_GATE_PASS
    awaiting:           Admissible-Existence/.github, kernel_version 1.3.1,
                          no gate

## What this adds to Finding 002

Finding 002 recorded that `StegVerse-Labs` and `Admissible-Existence` each
declare `kernel_required: 1.3.0` and run a kernel with no standing gate, and it
said plainly that it did not change either kernel, because neither repository
can be written from the session that raised it.

The gate now exists and is proven. One of the two owners has applied it:
`StegVerse-Labs/.github` carries it on its default branch at commit `5f14de9`,
reporting `kernel_version: 1.3.2`, with `NODE_STANDING_GATE_PASS` in its own
suite. `Admissible-Existence/.github` has not, and its patch is recorded below.

So this document no longer describes a uniformly unapplied migration, and the
earlier blanket claim that no peer's default branch runs the gate is now false.
It was asserted here and echoed by this repository's own workflow, which is the
defect this migration exists to fix pointed back at the record keeping it: a
declared limit that had stopped being real. The status block above states it
per peer, because that is the only form of the claim that can stay true.

## The artifacts

    docs/migrations/admissible-existence.node-standing-gate.patch

It touches four files, `org-kernel/kernel.py`,
`org-kernel/tests/test_kernel.py`, `org-kernel/kernel-manifest.json` and
`resident-runtime/submit_org_transition_to_master_records.py`, and no others.
The fourth is the subject of the section after next.

`docs/migrations/stegverse-labs.node-standing-gate.patch` has been removed. Its
target applied it, so it no longer applies to `StegVerse-Labs` main and a patch
that cannot apply to the tree it names is the artifact this record exists to
keep from rotting. What it did is in this repository's history and, applied, in
that organization's.

The manifest hunk is why this revision exists. Before it, a peer that applied
the gate and a peer that had not both reported `kernel_version: 1.3.1`, so
`kernel_required` could not tell the two generations apart -- a declared limit
that was not real. The gated generation is **1.3.2**: 1.3.1 plus the standing
gate. It is not 1.4.0, because this migration installs the gate and not parity
with this organization's 46-function kernel, and a number claiming parity would
be the same defect one layer up.

Each depends on two files copied verbatim from this repository, which is their
canonical source. They are copied rather than vendored into the patch so the
peer carries the canonical module instead of a fork of it:

    org-boundary/runtime/node_standing.py
      sha256 a24b7d2cc546fa57e4467e55d075e717249e20c2624b4299b36dca08f307ac8e

    docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json
      sha256 398c794b3d1c617787a5cf1edd59d3420584800aec01f718b9e9611f5f9b7bab

One further dependency is assumed already present in the peer rather than
carried, and is named here so the assumption is not implicit:

    org-boundary/registry/services.json
      present in Admissible-Existence/.github at the head below; the patch
      reads the peer's own service registry and must not replace it

Verified against:

    Admissible-Existence/.github  b57204ab0e7ee8f285dd9ea944fc37ec7cc7abc9
    StegVerse-org/.github         0e6f9c33af88e1e74dd88e515bbd12b46b4c483c

Applied at, and measured on, StegVerse-Labs' own default branch rather than a
scratch clone:

    StegVerse-Labs/.github        5f14de9ac686b0b6b4f77ece31087a0e980b537b

## What each patch does

    1. node_standing(root) loads the peer's own boundary module from the
       dispatch root, failing closed when the root does not carry it.
    2. dispatch() resolves standing before the boundary-role branch, and
       refuses with the contract's own disposition rather than a bare error.
    3. the resolved standing travels on the dispatch result.
    4. build_packet() takes `standing` as a required keyword with no default.
    5. build_ecosystem_packets, publish_ecosystem_message and
       publish_ecosystem_from_directory thread it through.
    6. carried_standing() carries a request's standing onto its response,
       marked as carried, because a response is not a new crossing.

Admissible-Existence's kernel also has the `INTERNAL_ENDPOINT` arm, which
returns early. Standing is resolved before the role branch for that reason: a
check inside either arm would gate only one of them. Its early return carries
the resolved standing too.

## The caller the signature change breaks

Step 4 above makes `standing` a required keyword on `build_packet()`. That is
the point of it -- a default would be the defaulting the contract forbids --
but a required keyword breaks every existing caller, and the kernel is not the
only caller. Both owners carry one outside `org-kernel/`, at the same path,
with the same shape:

    resident-runtime/submit_org_transition_to_master_records.py

Measured at `StegVerse-Labs` 78f902c and `Admissible-Existence` b57204a before
either applied anything: each calls `K.build_packet(...)` without `standing`.
With the gate applied and that caller untouched, the script dies:

    TypeError: build_packet() missing 1 required keyword-only argument: 'standing'

No test and no workflow in either peer exercises that path, so CI stays green
over a dead live script. That is this migration's own defect class one layer
down -- the gate is enforced where a test looks and unenforced where one does
not -- and the earlier revisions of this record did not mention it. The patch
recorded above now carries the fix, so the applier gets it in the same apply
rather than discovering it in production.

The fix is a port, not a new design: this repository's copy of the same script
already solved it, and the patched peer copy differs from it only in the two
organization identifiers. Standing is declared through a required `--standing`
file and never derived. The ecosystem-state digests the script already carries
chain its own lane, and the contract's finding refuses to equate lane-local
chaining with cross-lane predecessor standing, so they are not reused as a
predecessor binding. The `predecessor` key must be present explicitly, because
`null` is genesis stated and an absent key is genesis assumed:

    missing --standing        error: the following arguments are required: --standing
    standing without the key  standing must declare the predecessor key;
                              null is explicit genesis

`StegVerse-Labs` found this while applying the migration and fixed it in the
same branch, which is why its applied state is sound. It is recorded here so
the next applier does not have to find it again.

## Dispositions, before and after

Probing each organization's **own** kernel against its **own** tree, with the
origin string `Anyone-At-All`:

    packet                     before                  after
    no standing at all         CONSUMED, 5 receipts    build refused
    standing declared empty    cannot be built         fail-closed refusal
    valid genesis standing     cannot be built         CONSUMED, 5 receipts

The same three dispositions, run against this organization's kernel, are
identical after the patch:

    no standing at all      build_packet() missing 1 required keyword-only
                            argument: 'standing'
    standing declared empty node_standing_refused:node-standing-fail_closed:
                            claimed-standing-not-provable:no-mode-declared
    valid genesis standing  CONSUMED

Parity with this organization is the target, and parity is what the patches
reach. They do not make the peer stricter than the organization that raised the
finding.

## What the gate does not do, stated as the result states it

A crossing whose origin string is `Anyone-At-All` and whose standing is a valid
genesis declaration is admitted, here and after the patch there. The gate makes
a crossing provable by node chain; it does not validate a caller-written origin.
The admitted result says so in its own fields rather than leaving a reader of
the chain to assume otherwise, and both patches assert these values:

    caller_editable_origin_established_identity      false
    structural_standing_only                         true
    structural_standing_is_authenticated_standing    false
    standing_authority_effect                        NONE_STANDING_ONLY

So Finding 002's narrowing holds after the migration: the receipt chain becomes
one whose standing was checked, not one whose origin was authenticated. An
authenticated crossing remains deferred, with the external InTr boundary, to
tests 5 and 6.

## Proof

`Admissible-Existence`: the patch applied to a fresh clone of the head named
above, the two canonical files copied in, and its **own** test suite run
unchanged except by the patch:

    Admissible-Existence  PASS
                          NODE_STANDING_GATE_PASS
                          kernel_version 1.3.2
                          dispatch without standing refused
                            node_standing_refused:node-standing-fail_closed:
                            claimed-standing-not-provable:no-standing-declared
                          resident-runtime caller requires --standing

`StegVerse-Labs`: no longer a scratch-clone measurement. Its default branch at
5f14de9ac686b0b6b4f77ece31087a0e980b537b, checked out and run as it stands:

    StegVerse-Labs        PASS
                          FEDERATION_PASS
                          ECOSYSTEM_BROADCAST_PASS
                          ECOSYSTEM_CONTROL_RESPONSE_PASS
                          ECOSYSTEM_DEDUP_PASS
                          NODE_STANDING_GATE_PASS
                          kernel_version 1.3.2
                          34 kernel functions
                          resident-runtime caller requires --standing

The five pre-existing Labs proofs include the fourteen-node fanout, the
monitor request-and-response roll-up, the work-intake admission queue and the
durable dedup proof. The gate does not cost any of them. `NODE_STANDING_GATE_PASS`
is added by the patch and is the regression that holds the gate: it proves a
standing-less packet cannot be constructed, that a hand-forged envelope which
skips the constructor is refused fail-closed, and that the admitted crossing
carries the disposition fields above.

Each patch updates the peer's synthetic test roots to carry the standing
surfaces rather than stubbing them out. A test root that admits a crossing the
real root would refuse proves nothing about the real root.

## Why this is not applied from here

Both repositories are named `.github`. A repository whose name begins with `.`
cannot be attached to the session that produced this, and the git proxy will
not issue a credential for a repository the session has not attached, so push
is refused in both directions. Read is the ceiling, exactly as Finding 002
recorded.

That ceiling is on this session, not on the migration. `StegVerse-Labs` was
migrated by starting a session with that repository selected, which is the
procedure below and is now a measured path rather than a proposed one.

Applying it needs a session started with the target repository selected. The
steps, from that session's checkout root:

    git apply <this repo>/docs/migrations/<org>.node-standing-gate.patch
    cp <this repo>/org-boundary/runtime/node_standing.py \
       org-boundary/runtime/node_standing.py
    mkdir -p docs && cp <this repo>/docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json docs/
    python3 org-kernel/tests/test_kernel.py

Measured on a fresh clone of the remaining head, following exactly those four
steps: `NODE_STANDING_GATE_PASS`, exit 0, and a standing-less dispatch refused
`node_standing_refused:node-standing-fail_closed:claimed-standing-not-provable:
no-standing-declared`. Skipping either copy step produces a kernel that cannot
run, which is what the applier must not do and what
`tests/test_peer_migration_artifacts.py` now holds the record to.

A fifth step is no longer needed for the caller: the patch carries that fix.
What the applier must still do is check for *other* out-of-kernel callers of
`build_packet()` in its own tree, because the one named above is the one both
owners happened to share and not a guarantee that no peer has another:

    git grep -n 'build_packet' -- . ':!org-kernel'

## Boundary

    This document does not change any peer kernel. StegVerse-Labs' own
      session did, in its own repository.
    A patch recorded here is not an applied patch.
    A passing peer test suite in a scratch clone is not that organization's CI.
      The StegVerse-Labs measurement above is its default branch, which is
      that organization's tree but still not a run of its CI.
    Standing admitted is not origin authenticated.
    One peer's default branch runs the gate and one does not, so no blanket
      claim about "the peers" is available here. Stating it per peer is not a
      formatting preference; the blanket form was false the moment the first
      one applied.
    kernel_required stays 1.3.0 and is not raised by this document. Raising it
      to 1.3.2 would refuse Admissible-Existence, which still reports 1.3.1, so
      the honest moment to raise it is after the second owner applies this --
      not before, and not silently. A denominator that excludes a peer because
      the ecosystem has not finished migrating it is an unreachable closure
      dressed as a limit.
    1.3.2 is the gate, not generation parity. Twelve kernel functions present
      in StegVerse-org remain absent from a migrated peer: addressed_node_state_store,
      build_endpoint_response, capability_ingress, federation_cycles,
      manifest_selection, mesh_store, node_state_provenance, node_state_store,
      record_federation_cycle, resolve_federation_root, resolve_node_state_root
      and validate_hb_reference. Closing those is a separate migration.
