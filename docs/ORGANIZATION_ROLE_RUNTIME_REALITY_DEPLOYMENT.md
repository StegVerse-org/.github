# Organization Role runtime-reality deployment

Organization: `StegVerse-org`
Declaration: `ORGANIZATION-ROLE-RUNTIME-REALITY-DEPLOYMENT-001`
Date: 2026-10-01
Evidence class: `SOURCE_IMPLEMENTED` (completion contract v1). No runtime observation, no InTr admission, no emitted organization receipt and no Master Records reconstruction is claimed.
Deployment scope: this organization. The Organization Role is deployed per organization, in each organization's own `.github`. This declaration deploys it here and does not deploy it elsewhere.

## The change

```text
runtime_reality_authority:  Master Records  ->  Organization
```

Reality locus: the **organization ledger root**, held under the **organization ledger lock**, written by **manifest-directed append**.

This organization emits a receipt for every state transition that occurs within it (`.stegverse/transition-ledger/org-contract.json`, `stegverse.organization-transition-receipt/v1`, scope rule `EVERY_STATE_TRANSITION_OCCURRING_WITHIN_THE_ORGANIZATION_EMITS_AN_ORGANIZATION_RECEIPT`). That append-only hash-linked chain, at its own ledger root, under its own lock, is where runtime reality for this organization now lives. The authority follows the receipts rather than being assigned to a destination the receipts are later shipped to.

Unchanged by this declaration: Interlock/InTr remains transition authority, WorkerCoordinator remains claim/fence authority, TV/TVC remains credential authority, KV/SKAP Vault remains sole user-verification authority, Task Registry remains work-intent/coordination truth, HeartBeat and GitHub remain non-authorizing.

## Organization scope rule: the consumed-schema generalization

This part is due independently of the role change, and is landed with it.

The contract previously consumed one schema, `stegverse.repo-transition-receipt/v1`, and `resident-runtime/aggregate_repo_transition.py` hard-rejected every other. An organization whose ledger consumes repository receipts only has **no path from a canonical governed state transition to an organization receipt**: such a transition is dropped, not recorded, which contradicts the organization scope rule above.

This is live. The SDK lives in this organization and, as of `StegVerse-org/StegVerse-SDK` #416, manifests canonical state transitions through Interlock/InTr. None of them could emit an organization receipt.

What changed:

- `consumes` is now a list and holds `stegverse.canonical-state-transition-receipt/v1` alongside the repository receipt. The contract's `consumes` list is the admission gate; the emitter no longer carries a hard-coded schema of its own.
- A canonical state transition is admitted **on its own terms**. It is bound by its own canonical digest (`canonical_state_transition_receipt_sha256`) and keeps its own schema and transition id, rather than being relabelled as a repository transition it is not. `source_repository`, `repo_receipt_sha256` and `repo_transition_id` are null for it; a repository receipt is unaffected and still carries all three.
- A canonical state transition must carry exact inline canonical evidence bytes (`required_evidence_manifest`, digest-checked, each entry bound to the receipt's own `transition_id`). Organization replay terminates on this chain alone, so evidence travels as bytes rather than as a reachability promise.
- `preserves_source_transition_receipt` is declared: the source receipt's own schema, transition id and digest are carried into the organization receipt rather than replaced.

Admission is decided before the append lock is taken, so an inadmissible source receipt never contends for the ledger.

## master-records restated

`master-records` is the **recorder of released organization batch receipts**.

- It records organization batches that the organization has independently verified and released, as organization records for complex reconstruction across organizations (`propagation_target: master-records/.github`).
- Its release predecessor is a verified organization receipt-chain segment. It cannot create, admit, authorize, infer or repair a transition, and it never held transition authority.
- It is **not** the runtime-reality authority of this organization and is **not** a gate on this organization's runtime reality. An organization transition is real when it is appended under the organization ledger lock, not when a batch carrying it is recorded downstream.
- Nothing in this organization awaits it. A batch that has not been released or recorded is a value in the attempted transition's evidence state, not a blocker and not proof of non-occurrence.

Master Records keeps organization records and reconstructs from them; custody and durable history stay with each Organization. Every existing statement in this repository that Master Records is *organization records/reconstruction only and holds no transition authority* remains correct and is strengthened, not superseded, by this declaration.

## Conformance standard

Standing standard, restated as the condition every surface in this organization must meet:

> There are no and will be no external machines awaiting anything. This ecosystem is state-transition dependent for all ACTIONS BY MANIFEST. Any place that is not built this way must be updated to this standard or request an exemption.

Operationally:

1. Every action is a manifest-bound attempted state transition with an explicit predecessor, proposed successor, manifested capability and route, governing constraints, evidence and disposition.
2. The manifest determines the destination. So long as the destination exists, the state transition succeeds at ingress into the Interlock and at egress. Destination existence is sufficient; destination liveness is not a predicate.
3. An unavailable receiver is answered by the protocol's own disposition — `DURABLE_QUEUE_OR_EVENT_EPHEMERAL_MATERIALIZATION`, with `always_on_receiver_required: false`. No surface waits on a receiver, polls for one, or reports its absence as a blocker.
4. No surface requires an external machine, a second user-operated device, or a remote computer, and none may be introduced as a completion predicate, machine dependency or substrate-unsuitability finding.
5. No separate post-transition "authentic observer" gate exists after verified canonical closure. A non-ALLOW result carries `failure_code`, `failed_predicate`, `required_evidence_or_repair`, `retry_entrypoint`, `owning_existing_goal` and `next_attempt`; a bare `BLOCKED`, `UNKNOWN` or `NOT_OBSERVED` is not a finding.

A surface that does not meet this standard is non-conforming with `failure_code: ORGANIZATION_ROLE_CONFORMANCE_NOT_DECLARED`, and must either be updated or hold a registered exemption.

## Exemption path

Register: `data/organization-role-exemption-register.json` (`stegverse.organization-role-exemption-register/v1`).

An exemption is an actionable non-ALLOW disposition for a named surface, not permission to be non-conforming: it carries `surface`, `owning_existing_goal`, `failure_code`, `failed_predicate`, `why_manifest_bound_state_transition_is_not_yet_possible`, `required_evidence_or_repair`, `retry_entrypoint`, `next_attempt` and `expires_or_review_on`. It grants no authority and may not satisfy a terminal predicate.

The register refuses the justifications the standard already forbids — an external machine must be running, a second device is required, a remote computer is unavailable, evidence reachability is pending, a receiver is not always on, an authentic observer has not yet looked. The register opens empty: no surface in this organization has claimed an exemption.

## Superseded prose

Measured on the commit of this declaration, every prose statement in this repository places *observed reality* and *runtime reality* with the Organization, so the supersession inventory is empty — `count: 0`, enumerated in `data/organization-role-runtime-reality-deployment.json` under `superseded_prose_statements`. The emptiness is measured, not assumed: `tests/test_organization_role_runtime_reality_deployment.py` re-measures the tree with the same pattern that would enumerate a non-empty set, so a statement added later fails the test rather than passing silently.

The Master Records statements this repository does carry are organization-records/reconstruction-only and explicitly non-authorizing. They are retained, not superseded.

## Record-side work this declaration does not perform

This organization holds no canonical task record or Task Registry surface, so there is no record-side reconciliation to defer here; `deferred_record_side_reconciliation.items` is empty for that measured reason.

The completion evidence class `MASTER_RECORDS_RECONSTRUCTED` is **unchanged**. Renaming a completion evidence class is a registry-wide vocabulary migration requiring its own registration; it is not folded into this declaration.

## Validation

`tests/test_organization_role_runtime_reality_deployment.py` asserts the declaration, the register, the generalized ledger contract, the emitter's admission behaviour and the measured supersession inventory agree. `tests/test_org_ledger_atomic_append.py` continues to assert serialized append and fail-closed recovery. Source validation and merge grant no runtime authority.
