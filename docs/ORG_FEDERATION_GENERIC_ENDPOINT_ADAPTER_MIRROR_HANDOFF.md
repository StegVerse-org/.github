# Organization Federation Generic Endpoint Adapter Mirror Handoff

Updated: 2026-09-10
Organization: `StegVerse-org`
Repository: `.github`
Goal Task ID: `SDK-GENERIC-MANIFEST-DOWNSTREAM-PROPAGATION-003`
Parent handoff: `StegVerse-org/StegVerse-SDK:docs/SHARED_DOCS_EPHEMERAL_MANIFEST_WORKSPACE_MIRROR_HANDOFF.md`
Generic dispatch PR: `#9 MERGED`
Generic dispatch merge SHA: `d8baefb8674ebed00bbbf9784c54e092a5b1a04d`
WorkSpace binding PR: `#10 MERGED`
WorkSpace binding merge SHA: `b851996afc5c5323d0d0db970dd46e511bd36338`
Status: `ACTIVE / WORKSPACE ENDPOINT BINDING MERGED-VALIDATED / PROVIDER AUTHORITY REUSE NEXT`

## Completed generic dispatch repair

`org-kernel/kernel.py::dispatch` and `org-boundary/runtime/process_boundary.py` execute a registry-declared `endpoint_adapter` generically for any `INTERNAL_ENDPOINT`. Adapter paths must resolve inside the organization repository root and exist as files. Missing adapters, paths outside the organization root, failed adapter execution, and invalid output remain fail-closed.

The generic boundary preserves:

```text
registry selects service
service boundary_role == INTERNAL_ENDPOINT
registry endpoint_adapter selects organization-local adapter
adapter path constrained to organization repository root
boundary processor retains receipt generation
adapter does not gain transport/governance/credential/transition authority
```

## WorkSpace endpoint binding — merged

The organization-local WorkSpace binding is now merged and validated.

Registry service:

```text
service_id: stegverse-org.workspace-resource-consumer
repository: StegVerse-org/StegVerse-SDK
boundary_role: INTERNAL_ENDPOINT
profile_status: ACTIVE
endpoint_adapter: resident-runtime/workspace_resource_consumer_adapter.py
accepts: stegverse.workspace-resource-request.v1
runtime_required_for_consumption: true
```

The adapter is intentionally thin. It validates destination/request shape and delegates projection semantics to `stegverse.workspace_resource_consumer.consume_workspace_resource` from the installed canonical SDK. It does not duplicate consumer logic, mint InTr receipts, confer governance authority, or claim MIR/Master Records custody.

Validation evidence:

```text
PR #10 exact head: 7fb6783ec7bbfbdc249dfdba45b7c454ae0beed4
WorkSpace Internal Endpoint Binding Validation 34545811959: PASS
Internal Endpoint Dispatch Validation 34545811830: PASS
merge: b851996afc5c5323d0d0db970dd46e511bd36338
```

README maintenance was included in PR #10 and documents the organization-local WorkSpace endpoint without claiming live provider execution.

## Active probe relationship

Provider-neutral active probe execution is now implemented and merged in `StegVerse-org/StegVerse-SDK` PR #181 at `5c8a3c0246a0ae48e498c10f85d9eee0a2d1ba2c`. Runtime-supplied probe evidence may resolve represented `PROBE_REQUIRED` state, but readiness remains canonically re-derived and probe evidence remains `authority_effect: NONE`.

No provider-specific OAuth, callback, secret store, or provider authority is created here. Existing provider authority must be reused.

## Current provider reuse finding

Google Drive owner-consent/callback authority already exists in `StegVerse-Labs/TVC` under its Personal-KV Google Drive lane. The sovereign Service Gateway query-secret-safe source prerequisite is owned by `StegVerse-org/LLM-adapter#271`; its source hardening PR #328 is merged, while authentic deployed-ingress proof remains a distinct prerequisite. The WorkSpace lane must therefore reuse those boundaries rather than create a second Google OAuth or credential path.

## Current proof boundary

```text
registry-driven kernel dispatch: IMPLEMENTED / MERGED
provider-neutral internal endpoint adapter dispatch: IMPLEMENTED / VALIDATED / MERGED
provider-neutral WorkSpace resource consumer in SDK: IMPLEMENTED / VALIDATED / MERGED
organization-local WorkSpace endpoint binding: IMPLEMENTED / VALIDATED / MERGED
provider-neutral active probe execution: IMPLEMENTED / VALIDATED / MERGED
authentic provider probe: NOT PROVEN
Shared Docs live transport/projection proof: NOT PROVEN
MIR transition reporting: NOT PROVEN
Master Records authentic custody/reconstruction: NOT PROVEN
one-device authentic end-to-end execution: NOT PROVEN
```

## Next actions

1. Reuse the existing TVC Google Drive owner-consent/credential authority rather than creating a parallel provider stack.
2. Determine the narrow provider operation/probe interface that WorkSpace can consume without exposing credentials or moving TVC authority.
3. Keep authentic deployed-ingress proof separate from source/CI evidence.
4. Once provider access is explicitly available, execute the controlled `OBSERVE -> MATERIALIZE -> live edit -> REFRESH -> authorization/probe change -> REVOKE/EXPIRE -> DESTROY` experiment.
5. Retain MIR transition reporting and independent Master Records custody/reconstruction evidence.
6. Verify the entire path on one current mobile device.

## Human action

None for provider-interface source design and validation. Owner-present Google authorization is only required when authentic provider-backed execution begins.
