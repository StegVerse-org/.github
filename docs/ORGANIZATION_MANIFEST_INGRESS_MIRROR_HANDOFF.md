# Organization Manifest Ingress Mirror Handoff

Updated: 2026-10-03
Organization: `StegVerse-org`
Repository: `.github`
Goal Task ID: `SVORG-STEGOS-PORTABILITY-001`
Related Task ID: `SDK-GENERIC-MANIFEST-ECOSYSTEM-INVARIANT-005`
Predecessor handoff: `docs/ORGANIZATION_INGRESS_CAPABILITY_BINDING_MIRROR_HANDOFF.md`
Settled specification: `docs/NODE_INGRESS_SETTLED_SPECIFICATION.md`
Status: `RECEIVING OPERATION LIVE / ORGANIZATION RECEIPT EMITTED / SDK ADMITS THE RESULT / CUSTODY PUBLISHED NOT AWAITED`

## What was missing

The capability binding resolved a destination and stopped there. `org-runtime/interlock-intr.json` said where this organization receives `sdk-manifest-ingress` / `SDK:ManifestIngress` / `SUBMIT_MANIFEST`, and nothing drove a submission into it. So a handoff resolved its destination and then reported, correctly, that nothing had happened:

```text
intr_admission_observed          false
far_side_transition_observed     false
organization_receipt_observed    false
consequence_committed            false
```

## The receiving operation

`resident-runtime/organization_manifest_ingress.py` is `ORGANIZATION_SDK_MANIFEST_INGRESS`. It runs the sequence the binding declares, in that order:

```text
derive_execution_request(manifest, this organization's own boundary document)
resident-runtime/sdk_manifest_crossing.py::cross              admission
org-boundary/runtime/process_boundary.py                      processing
.stegverse/transition-ledger/emit.py::append                  repository receipt
resident-runtime/aggregate_repo_transition.py::append         organization receipt
stegverse.manifest_state_transition_runtime.admit_runtime_result
```

The organization resolves its own destination from its own document. It is not handed one and does not fetch one: `repository_endpoint_rule` makes this repository the owner of organization communication, and a boundary document supplied by a caller would let the caller name its own organization. The operation then reads the resolution back off the request and refuses a capability bound to a different owner, a different operation, or a different profile — reading it rather than assuming it is what makes that refusal possible.

## Two resolutions at two boundaries

These are distinct and must not be conflated.

| Resolution | Question | Source |
| --- | --- | --- |
| Organization ingress | which organization receives this capability, on what operation | the capability overlay binding |
| Internal endpoint | which internal service of that organization serves the declared surface | the manifest's `completion.egress` |

The SDK's `completion_egress_controls_outbound_organization_routing: false` is about the first. It does not make a manifest's declared internal surface unreadable once the manifest has arrived at the organization that owns it.

## The chain is reconstructed, not taken on trust

The boundary reports `RECONSTRUCTED`. `cross` previously returned only the receipt *kinds*, so that status could not be checked from outside and a caller had to take the boundary's word. It now also returns the full receipt chain and the ingress payload digest, and the receiving operation recomputes every receipt from its own subject — the packet, the service, the payload digest, its kind and its declared predecessor. A receipt whose declared digest or id does not match what its subject produces fails the whole chain closed, before anything is appended.

Those recomputed digests become the `transition_closures` the SDK validates, chained predecessor to successor.

## Both ledger levels are written, in order

The transition occurs in this repository, so the repository ledger records it and the organization ledger consumes that receipt.

The first version of this operation authored its own source receipt and then recorded it as the organization's own, in one call. That is one writer standing in for two levels, and it showed:

```text
source_receipt_schema  stegverse.canonical-state-transition-receipt/v1
source_repository      null
repo_receipt_sha256    null
repo_transition_id     null
```

`preserves_repo_receipt: true` had nothing to preserve, and organization replay rested on a receipt the same call had just minted, where `ORGANIZATION_REPLAY_MUST_REQUIRE_ONLY_VERIFIED_REPO_RECEIPTS_AND_ORG_RECEIPTS` asks for a verified repository receipt underneath. It now reads:

```text
source_receipt_schema  stegverse.repo-transition-receipt/v1
source_repository      StegVerse-org/.github
repo_receipt_sha256    == the repository receipt's own digest
repo_transition_id     == the repository receipt's own transition id
org_transition_class   REPO_STATE_PROPAGATION
```

`.stegverse/transition-ledger/emit.py` grew an in-process `append` rather than a second implementation of the same write: it is one store with one lock, and a second writer is the chain fork that lock exists to prevent. The chain position comes from the ledger's own HEAD, so a second ingress links to the first instead of declaring its own sequence.

## The organization does not grade its own result

The operation reports what it observed and hands that to the SDK's own `admit_runtime_result`, which is the authority on whether a runtime result closes a transition. A refusal is returned verbatim, naming its own predicate, and is never retried into a success. `manifest_receipt_id` is the organization receipt's own digest, so the result is bound to the receipt that exists rather than to an identifier minted for the occasion.

## Organization records are published, never awaited

`propagation_gates_organization_runtime_reality` is false and Master Records `may_be_awaited_by_a_transition` is false, so this operation reports `master_records_organization_record_observed: false` and names `resident-runtime/submit_org_transition_to_master_records.py` as where its organization records are published to Master Records. The organization receipt is the organization's runtime reality; a refusal upstream does not unmake a transition that occurred here, which is why the receipt is appended before the SDK is asked and the result says so even on a refusal.

## Validation

```text
disposition                                            ALLOW
received                                               true
owner_repository                                       StegVerse-org/.github
receiving_operation                                    ORGANIZATION_SDK_MANIFEST_INGRESS
destination_resolution_source                          CANONICAL_CONNECTOR_CAPABILITY_OVERLAY
destination_resolution_environment_inputs              []
intr_admission_observed                                true
far_side_transition_observed                           true
organization_receipt_observed                          true
repository_receipt_observed                            true
organization_receipt_preserves_repository_receipt      true
boundary_receipt_chain_reconstructed_independently     true
sdk_admitted_result.state                              COMPLETE
sdk_admitted_result.manifest_receipt_id                == organization_receipt_sha256
master_records_organization_record_observed            false
authority_effect                                       NONE_RECEIVING_OPERATION_ONLY
```

`tests/test_organization_manifest_ingress.py` asserts against the SDK's own request derivation and result admission rather than a local copy of their rules. The workflow pins the SDK at the commit that owns them. The organization ledger root is redirected per test and per CI run: the ledger is durable sovereign state, and a run that appended into the default location would be writing runtime reality from a test.

## What this does not claim

A refused submission is refused, never retried into a success — and it is recorded. A state transition is the disposition of an intended action, not only a successful one: a submission that arrived and was refused is a transition whose disposition is DENY, and `organization_scope_rule` makes no exception for it. Every refusal path through `receive` — an unresolvable destination, a capability bound elsewhere, a manifest the crossing cannot drive, a far side that refused, a boundary chain that does not reconstruct — appends a repository receipt under `ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED` and the organization receipt that consumes it, in that order, because a refusal is not an exception to the layering the replay rule requires. A manifest with no declared standing used to leave the operation by exception with nothing written; it is now recorded as `CROSSING_IS_DRIVABLE_FROM_THE_MANIFEST_AS_DECLARED`.

What the refusal record does *not* claim is anything the organization did not produce: no resolved service, no boundary receipt chain, no runtime result. And `organization_receipt_observed` stays false on every refusal, because it means an admitted crossing was observed and a refusal receipt is not that — a caller reading one as the other would treat a refused submission as a completed transition. The refusal's own digests are returned under `refusal_repository_receipt_sha256` and `refusal_organization_receipt_sha256`.

The capability this organization's internal endpoint currently serves is `ecosystem_diagnostic`. `governance` is refused at the far side as a capability that service does not admit.

One latent conflict is recorded rather than worked around. The SDK's governance result validator requires `organization_master_records_closure_observed: true` before it will admit any governance result, while this organization's own `ORGANIZATION-ROLE-RUNTIME-REALITY-DEPLOYMENT-001` states that Master Records `may_be_awaited_by_a_transition: false` and `may_gate_organization_runtime_reality: false`. The organization publishes its organization records and observes no Master Records organization record for the result, so it cannot honestly satisfy that predicate. It is unreachable today because no internal endpoint admits `governance`; it is owned by `StegVerse-org/StegVerse-SDK` and is not resolved here.
