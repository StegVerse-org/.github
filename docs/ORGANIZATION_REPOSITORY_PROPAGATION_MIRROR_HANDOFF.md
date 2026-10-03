# Organization Repository Propagation Mirror Handoff

Updated: 2026-10-03
Organization: `StegVerse-org`
Repository: `.github`
Goal Task ID: `SVORG-STEGOS-PORTABILITY-001`
Predecessor handoffs: `docs/ORGANIZATION_MANIFEST_INGRESS_MIRROR_HANDOFF.md`, `StegVerse-org/LLM-adapter:docs/PRE_PROTOCOL_RECEIPT_FINDING_MIRROR_HANDOFF.md`
Status: `WIRED INTO THE RESIDENT CYCLE / INTRA-ORGANIZATION / NO INTERLOCK-INTR INVOLVED`

## What was missing

`organization_scope_rule` is that every state transition occurring within the organization emits an organization receipt. Repositories in this organization append their own transitions to their own ledgers — the LLM-adapter records a node's arrival at its ingress boundary — and nothing carried those receipts up. The organization's record began at its own boundary, so the whole front half of the path was absent from it.

## It is not a crossing, and it never needed Interlock/InTr

This was mis-stated earlier in the work and is worth recording plainly: `StegVerse-org/LLM-adapter` and `StegVerse-org/.github` are both inside `StegVerse-org`. There is no organization boundary between them. Interlock/InTr is the *inter-organization* transport; the hop that needs it is organization to `propagation_target: master-records/.github`.

Three things made this available already and none of them is transport:

1. `aggregate_repo_transition.py` already exposed `--repo-receipt`.
2. `verify_source` already admits any `repository` inside this organization, binding the receipt by its own digest.
3. A ledger is addressed, not located. `ledger_store` exists so a chain is reachable by key on whatever substrate holds it; on one node the repository and organization ledgers are sibling addresses under one state home.

What was missing was only the step that walks a repository's chain and hands the receipts over.

## Order and exactly-once are the whole job

```text
resident-runtime/propagate_repository_receipts.py
  declared_repositories()   read off org-boundary/registry/services.json
  repository_chain(root)    HEAD backwards, reversed, each receipt verified
  already_propagated(org)   the repo_receipt_sha256 values the org chain carries
  append(..., REPO_STATE_PROPAGATION, ...)   in repository chain order
```

* **Order.** Receipts are propagated in repository chain order, so the organization's record of a repository cannot imply a sequence the repository never had.
* **Verification.** Each receipt's claimed digest is checked against the digest of its body before it is carried. An unverifiable receipt stops the walk: unverified evidence on the organization chain is worse than none.
* **Exactly once.** Already-propagated receipts are skipped by reading what the organization chain already carries, not by a side marker. A second run carries nothing instead of failing on `ORG_LEDGER_DUPLICATE_RECEIPT_RECOVERY_REQUIRED`.
* **Scope.** The repositories in scope are read off the service registry, which is the organization's own statement of what belongs to it. A list written into the propagation step would be a second answer to a question the registry already answers.
* **Absence is not failure.** A declared repository whose ledger is not present on this node has nothing here to carry, which is a report rather than an error — that is what an ephemeral node materializing a subset of capabilities looks like.

The organization state digests are the repository receipt's own predecessor and digest, so an organization transition reads as "the organization's record of this repository advanced from its predecessor to this receipt". A genesis receipt has no predecessor to name, so the absence is stated and reproducible rather than written as a zero digest that would read like a real state.

## Wired, not invoked by hand

`resident-runtime/federation_cycle.py` propagates on each cycle and reports what it carried in the cycle receipt. It runs *after* the frames are handled, so a cycle that failed to consume does not report having carried receipts it never reached.

```text
registration at the adapter's ingress boundary
  -> NODE_INGRESS_ADMITTED on StegVerse-org/LLM-adapter's ledger
     -> resident cycle
        -> REPO_STATE_PROPAGATION on StegVerse-org's ledger
           source_repository     StegVerse-org/LLM-adapter
           repo_receipt_sha256   the repository receipt's own digest
           repo_transition_id    NODE_INGRESS_ADMITTED:<node>
```

## Validation

`tests/test_organization_repository_propagation.py` — nine cases covering the chain reaching the organization, repository order preserved, a second run carrying nothing, a later transition carried while the earlier one is not, a tampered receipt never reaching the organization, an absent ledger reporting rather than failing, scope coming from the registry, the sweep naming no repository, and the boundary evidence recording that nothing was crossed.

Both ledger homes are redirected per test and per CI step. The ledgers are durable sovereign state, and a run that appended into either default location would be writing runtime reality from a test.

`federation_cycle.py` had no CI coverage before this; the new workflow is the first to exercise it. It now also asserts that two cycles are recorded in the node state root the node was told to use, that the resolution reports `DERIVED_FROM_ENVIRONMENT`, and that the run leaves `resident-runtime/federation/` absent from the checkout.

## The cycle receipt no longer lands in the repository tree

`federation_cycle.py` wrote its cycle receipt to `resident-runtime/federation/latest-cycle.json`, inside the repository tree — the same defect class registered in `StegVerse-org/LLM-adapter:.stegverse/pre-protocol-receipt-register.json`, a run writing an artifact into committed space. It also kept only the most recent pass; every earlier one was overwritten and gone.

Fixed rather than noted. Node state already had a seam, `org-kernel/node_store.py`, but every resident caller passed the repository checkout as the node root, so the seam existed and the resolution still landed in the tree. `kernel.resolve_node_state_root` now resolves it the way `resolve_federation_root` already resolved the mesh — `STEGVERSE_NODE_STATE_ROOT`, else `XDG_STATE_HOME/stegverse/node-state` — and returns the provenance with the path, so a node that was told where its state is reads as portable and one that derived it from its host says so instead of appearing equivalent.

A cycle is recorded through `kernel.record_federation_cycle`, addressed by what it reported under `federation/cycles.d/`, write-once like every other node document. Two writers of the same report agree byte for byte; a report that differs is a different cycle rather than an overwrite. Every pass is kept.

The documents that already live under a checkout — consumption markers, outbox, work intake — keep resolving exactly where they did. `node_store.py` states that as a property: keys keep the names the filesystem gave them and nothing migrates. Only newly recorded state resolves through the addressed root.

## One thing recorded, not fixed here

The organization to Master Records hop still reaches only `PUBLISHED_FOR_CUSTODY`. That one *is* inter-organization, does need Interlock/InTr, and carries the validator conflict recorded on `.github` #40.

Nothing here grants authority, performs a transition, or claims custody. It records, at the organization level, transitions that already occurred.
