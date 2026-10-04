# WorkerCoordinator Claim Surface Reconciliation Mirror Handoff

Updated: 2026-10-04
Goal Task ID: `SVORG-WORKERCOORDINATOR-CLAIM-SURFACE-001`
Parent Goal Task ID: `SVORG-STEGOS-PORTABILITY-001`
Repository: `StegVerse-org/.github`
Status: `PROPOSED / DRAFT PLAN ONLY`
COSV ID: `ABSENT_FROM_CURRENT_TASK_REGISTRY_SCHEMA`

## Why this successor exists

The first external Task Registry review independently established that the organization Task Registry is an enforced, entity-neutral work-intent authority while the separately declared WorkerCoordinator claim authority has no reviewable claim surface in this organization. The two states must not be collapsed.

This successor is genuinely separable from the parent portability goal. It owns reconciliation of the claim/fence authority seam only. It does not change the parent portability obligations.

## Existing lineage that must be reused

Do not invent claim semantics.

`StegVerse-org/StegVerse-SDK` already contains the externally replayable semantic contract in `stegverse/atomic_task_worker_binding.py` and `SDK_TT_ATOMIC_TASK_WORKER_BINDING_MIRROR_HANDOFF.md`. That contract already models:

- `task_id`;
- deterministic `claim_id`;
- `claim_generation`;
- `fencing_token`;
- reciprocal task/worker binding;
- constitutive activation;
- invocation-after-claim closure;
- completion and worker retirement;
- no continued task-bound authority.

Its evidence boundary is explicit: local semantic proof only, with no claim of authentic WorkerCoordinator execution.

The installed SDK state graph in `stegverse/atomic_task_worker_processor.py` already requires `WORKERCOORDINATOR_CLAIM_FENCE_BOUND` as the first ordered transition and assigns `claim_fence` authority to `WORKERCOORDINATOR`.

The organization declaration `data/organization-role-runtime-reality-deployment.json` separately declares `worker_claim_authority: WorkerCoordinator`.

These are precursor contracts, not an authentic WorkerCoordinator claim surface.

## Current disposition

```text
TASK_REGISTRY_WORK_INTENT_AUTHORITY = ENFORCED
WORKERCOORDINATOR_AUTHORITY_DECLARATION = PRESENT
WORKERCOORDINATOR_REVIEWABLE_CLAIM_SURFACE = NOT_STARTED
AUTHENTIC_WORKERCOORDINATOR_CLAIM_FENCE_OBSERVED = NOT_PROVEN
```

## Remediation plan

1. Inventory all canonical claim/fence/checkout/lease surfaces and prove whether any existing owner already emits authentic WorkerCoordinator claim evidence.
2. Reuse the SDK Test 2 claim/fence vocabulary where compatible; do not create a second claim lifecycle merely because the authentic owner is absent from the organization repository.
3. Identify or establish the canonical WorkerCoordinator-owned surface. If its owner is outside this repository, this repository records only the reference/status contract and the owner implements the authoritative claim.
4. Require a claim to bind an existing entity-neutral Task Registry `task_id` without adding assignee, agent, session, worker_claim, owner, or claimant fields to the Task Registry.
5. Require claim identity/generation/fence plus lifecycle evidence sufficient to distinguish current, superseded, released/returned, and stale claims.
6. Require stale or mismatched fences to fail closed and prevent an old claim from being promoted as current.
7. Bind the existing SDK `WORKERCOORDINATOR_CLAIM_FENCE_BOUND` transition to authentic claim evidence rather than SDK-local semantic construction.
8. Preserve authority separation: Task Registry owns work intent; WorkerCoordinator owns claims/fences; Interlock/InTr owns transitions; TV/TVC owns credential/warrant authority; Master Records owns custody/reconstruction.
9. Add adversarial tests for nonexistent task references, duplicate/current competing claims, stale generation/fence, mismatched task/claim identity, lifecycle closure, and vacuous discovery.
10. Update README and this handoff when implementation exists. Do not mark claim authority ENFORCED until the authoritative surface and its negative tests exist.

## Explicit non-goals

This plan does not create a broker, dispatcher, scheduler, runtime, ingress, credential route, device prerequisite, AI_SESSION_GATE, authority plane, or Task Registry assignee model. It does not promote SDK-local semantic evidence into authentic WorkerCoordinator execution.

## Completion evidence required

- canonical owner of the WorkerCoordinator claim surface identified;
- machine-readable claim contract exists at that owner;
- every claim resolves an existing Task Registry `task_id`;
- generation/fence freshness and lifecycle are fail-closed;
- SDK `WORKERCOORDINATOR_CLAIM_FENCE_BOUND` consumes/references authentic owner evidence rather than manufacturing authority;
- adversarial tests pass;
- README and canonical handoff are reconciled;
- exact-head repository validation succeeds.

Until those predicates are met, `WORKERCOORDINATOR_REVIEWABLE_CLAIM_SURFACE` remains `NOT_STARTED` or, after actual implementation begins, an explicitly evidenced nonterminal state.