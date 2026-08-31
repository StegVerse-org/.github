# HB Machine Continuation Organization Profile Mirror Handoff

Updated: 2026-08-31
Organization: `StegVerse-org`
Repository: `StegVerse-org/.github`

## Authority

Repository-local authority reviewed before this mutation:

`this file is the first repository-local mirror handoff for this knowledge`

Canonical ecosystem sources:

- `StegVerse-Labs/.github/docs/HEARTBEAT_CARRIER_SIGNAL_MIRROR_HANDOFF.md`
- `StegVerse-Labs/.github/docs/ALL_ORGS_HEARTBEAT_FEDERATION_MIRROR_HANDOFF.md`
- `StegVerse-Labs/.github/HB_MACHINE_CONTINUATION_MIRROR_HANDOFF.md` on implementation PR #688 until merged
- `StegVerse-Labs/.github/heartbeat_runtime/independent_oscillator.py`
- `StegVerse-Labs/.github/heartbeat_runtime/worker_runtime.py`

This profile installs shared technical knowledge only. It does not create a second heartbeat, scheduler, worker coordinator, credential plane, repository-mutation authority, or runtime claim.

## Canonical technical knowledge

```text
HB primary reference:
  frequency: 100 Hz
  period: 10 ms
  progression: OSCILLATOR_ONLY
  canonical protocol anchor: HB32
  continuous process required for reference existence: false

Machine continuation:
  timing basis: deterministic HB-derived window
  default continuation interval: 360000 HB quanta
  equivalent nominal interval at 100 Hz: 3600 seconds
  wall-clock scheduler authority: NONE
  external ChatGPT/hosted monitor dependency: NONE

Derived continuation trigger:
  authority_effect: NONE_TRIGGER_ONLY
  grants admission: false
  grants execution: false
  grants claim/fence: false
  grants credentials: false
  grants repository mutation: false
  grants merge/release/publication: false

Execution:
  canonical task-control authority remains the applicable WorkerCoordinator / handoff / policy path
  already-admitted machine-owned work may be revisited when a continuation window becomes current
  missed windows collapse to the current derived window rather than replaying every missed interval
  task-specific admission and dependency predicates remain independently fail-closed

Credentials:
  credential authority: TV/TVC
  GitHub token runtime authority: NONE
```

## Derived-window rule

For a continuation period of one nominal hour:

```text
100 HB references/second * 3600 seconds = 360000 HB quanta
```

A conforming observer derives the current continuation window from the canonical HB protocol reference. Observation does not cause HB progression. The continuation trigger is a deterministic signal that tells an already-running machine-control plane that a bounded re-evaluation opportunity exists; it does not authorize the work being evaluated.

## Organization adoption rule

This organization's `.github` repository should treat this profile as shared ecosystem knowledge:

```text
canonical HB reference
-> derive continuation window
-> emit/observe non-authorizing continuation trigger
-> inspect existing machine-owned/admitted tasks
-> use existing task-specific execution authority only
-> persist receipts/checkpoints/evidence
```

Do not implement an organization-local cron, GitHub Actions schedule, ChatGPT automation, or third-party scheduler as the authority for this behavior. If this organization later hosts a resident worker implementation, it should consume the same HB-derived continuation semantics and preserve the organization's existing admission, worker, repository, and credential boundaries.

## Relationship to HB-derived carriers / InTr

HB may be used as the synchronization/carrier substrate, including deterministic derived phase/channel signals. InTr governs any packet carried by those signals. Carrier presence/correctness remains non-authorizing.

```text
HB / HB-derived signal authority:
  admission: NONE
  execution: NONE
  credential: NONE
  routing: NONE
  transition: NONE
  receiving: NONE
  publication: NONE
  custody: NONE
```

Machine continuation is therefore a derived synchronization/trigger use of HB, not a new authority plane.

## Local implementation status

```text
shared technical knowledge: INSTALLED_BY_THIS_HANDOFF
organization-local runtime implementation: NOT IMPLIED
organization-local worker activation: NOT IMPLIED
cross-organization runtime proof: NOT IMPLIED
canonical implementation owner: StegVerse-Labs/.github
canonical implementation PR at propagation time: #688
```

## Collision / continuation rule

Before any future local implementation derived from this profile:

1. Read the most specific current repository `*_MIRROR_HANDOFF.md`.
2. Reuse the organization's existing worker/task/admission machinery.
3. Do not introduce a duplicate heartbeat or scheduler.
4. Keep HB timing/reference separate from execution authority.
5. Preserve TV/TVC credential authority and any stricter organization-local authority boundary.
6. Treat source/merge/CI evidence separately from authentic resident execution evidence.
