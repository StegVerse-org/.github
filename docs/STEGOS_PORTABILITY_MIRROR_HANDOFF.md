# StegOS Portability Mirror Handoff

Updated: 2026-10-02
Organization: `StegVerse-org`
Repository: `.github`
Goal Task ID: `SVORG-STEGOS-PORTABILITY-001`
Task Registry status: `in_progress`
Task Registry source: `orchestration/task-registry.json`
Task Registry baseline: `2901c6a9eb87266545e66e70e1dafba5016c9a56`
COSV ID: `ABSENT_FROM_CURRENT_TASK_REGISTRY_SCHEMA`
Status: `ACTIVE / CANONICAL NODE STANDING CONTRACT UNDER REVIEW`

## Current truth

The active organization goal is to remove host dependency from StegOS node and mesh state. The canonical Task Registry remains the work-intent authority for this goal. This handoff does not promote source evidence into runtime proof and does not grant execution, repository mutation, publication, route, credential, or Master Records authority.

## Canonical ingress review contract

The review artifact `docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json` now defines:

`ALL_EXTERNAL_ECOSYSTEM_INGRESS_REQUIRES_CANONICAL_NODE_STANDING`

The contract covers both first establishment and later access by an already-established node. The predecessor key is mandatory: `null` means explicit genesis only; an established node must carry a validated SDK canonical predecessor binding. Missing or invalid predecessor evidence fails closed and may not silently re-enroll as genesis.

Ingress is modeled across orthogonal dimensions rather than mutually exclusive identities: participant/framework, browser or console/API interaction surface, device/machine substrate, StegNode materialization, StegOS runtime, and processing continuation. An external LLM is not assumed to be the node itself. KV-as-node and StegBrowser-as-KV-surface remain NOT_PROVEN pending their canonical owners.

There is one canonical ingress CONTRACT, not one mandatory host. The currently observed gateway is a replaceable discovery host and grants no authority. Existing advertised surfaces must be mapped as continuations before creating new endpoints.

## Source-classification boundary

HTTP transport metadata such as User-Agent, client hints, network metadata, and TLS characteristics is descriptive only. It may not establish authoritative ingress class or device/runtime identity. Load-bearing classification must be bound from non-caller-editable observation/attestation or previously established canonical node evidence.

A caller-editable `ingress_source` or equivalent field is insufficient for authority-bearing classification.

## Fail-closed dependency

Every covered destination must validate canonical node standing before downstream processing. Explicit genesis requires a present null predecessor; continuity requires the SDK canonical predecessor binding. An absent predecessor key, invalid continuity, or unprovable claimed standing fails closed. Failed continuity may not silently create a new identity. Standing is necessary for downstream processing but is not itself sufficient for execution authority.

Manifest processing remains selected only by the manifest-declared capability and route binding owned by the SDK.

## Current proof boundary

- deployed canonical-standing contract, explicit genesis, existing-node verification and continuation mapping: `NOT_PROVEN`
- automatic authoritative ingress-source classification and an attestation owner: `NOT_PROVEN`
- ingress-to-LLM-adapter end-to-end handoff: `NOT_PROVEN`
- bypass rejection at every destination: `NOT_PROVEN`
- SDK manifest-only route-selection contract: source contract exists
- this handoff creates no runtime, authority, credential route, device prerequisite, or second ingress

## COSV reconciliation

The current Task Registry schema forbids unspecified task properties and defines no COSV field. COSV is therefore recorded as `ABSENT_FROM_CURRENT_TASK_REGISTRY_SCHEMA`, not merely unresolved. No COSV is invented.

## Review resolution incorporated

The uploaded review identified and this branch now resolves at the design-contract level: optional-lineage contradiction; wall-clock ordering ambiguity; single-host portability conflict; framework/surface conflation; omission of already-established-node continuity; and omission of browser as an explicit interaction surface. Runtime implementation findings remain NOT_PROVEN and are not upgraded by this handoff.

## Next actions

1. Map each standing continuation to an existing advertised surface before adding endpoints.
2. Identify the existing canonical owner, if any, for non-caller-editable classification/attestation; otherwise retain FAIL_CLOSED.
3. Add the organization-boundary carrier/validator for SDK canonical predecessor standing without redefining predecessor semantics as receipt chaining.
4. Repair the live LLM-adapter path so caller-fabricated identity and message-keyword routing cannot bypass canonical standing and manifest-only route selection.
5. Trace canonical KV and StegBrowser owners before asserting KV-as-node or StegBrowser-as-KV-surface.
6. Preserve every authority boundary and NOT_PROVEN runtime claim.
