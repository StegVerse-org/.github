# Organization Federation Generic Endpoint Adapter Mirror Handoff

Updated: 2026-09-10
Organization: `StegVerse-org`
Repository: `.github`
Goal Task ID: `SDK-GENERIC-MANIFEST-DOWNSTREAM-PROPAGATION-003`
Parent handoff: `StegVerse-org/StegVerse-SDK:docs/SHARED_DOCS_EPHEMERAL_MANIFEST_WORKSPACE_MIRROR_HANDOFF.md`
Generic dispatch PR: `#9 MERGED`
Generic dispatch merge SHA: `d8baefb8674ebed00bbbf9784c54e092a5b1a04d`
Status: `ACTIVE / GENERIC INTERNAL ENDPOINT DISPATCH MERGED / WORKSPACE ENDPOINT BINDING VALIDATION PENDING`

## Completed generic dispatch repair

`org-kernel/kernel.py::dispatch` and `org-boundary/runtime/process_boundary.py` now execute a registry-declared `endpoint_adapter` generically for any `INTERNAL_ENDPOINT`. Adapter paths must resolve inside the organization repository root and exist as files. Missing adapters, paths outside the organization root, failed adapter execution, and invalid output remain fail-closed.

The generic boundary preserves:

```text
registry selects service
service boundary_role == INTERNAL_ENDPOINT
registry endpoint_adapter selects organization-local adapter
adapter path constrained to organization repository root
boundary processor retains receipt generation
adapter does not gain transport/governance/credential/transition authority
```

## WorkSpace endpoint binding candidate

The next organization-local binding is implemented on branch `workspace-internal-endpoint-binding`.

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

The adapter is intentionally thin. It validates destination and request shape, then imports and calls `stegverse.workspace_resource_consumer.consume_workspace_resource` from the installed canonical SDK. It does not copy projection semantics into the organization repository and does not mint InTr receipts, confer governance authority, or claim MIR/Master Records custody.

Dedicated regression coverage uses the real organization boundary processor plus the exact merged SDK consumer source at `07ceb1f131dd8fd27b3b8c89ab747e58aa55e55c`. Tests cover READY materialization, fail-closed `PROBE_REQUIRED` materialization, teardown availability while probe-required, and unknown-service rejection.

Candidate files:

```text
resident-runtime/workspace_resource_consumer_adapter.py
org-boundary/registry/services.json
tests/test_workspace_internal_endpoint_binding.py
.github/workflows/workspace-internal-endpoint-binding-validation.yml
README.md
docs/ORG_FEDERATION_GENERIC_ENDPOINT_ADAPTER_MIRROR_HANDOFF.md
```

README maintenance is included and documents the organization-local WorkSpace endpoint without claiming live provider execution.

## Current proof boundary

```text
registry-driven kernel dispatch: IMPLEMENTED / MERGED
provider-neutral internal endpoint adapter dispatch: IMPLEMENTED / VALIDATED / MERGED
provider-neutral WorkSpace resource consumer in SDK: IMPLEMENTED / VALIDATED / MERGED
organization-local WorkSpace endpoint binding source: IMPLEMENTED / VALIDATION PENDING
active provider probe execution: PENDING
Shared Docs live transport/projection proof: NOT PROVEN
MIR transition reporting: NOT PROVEN
Master Records authentic custody/reconstruction: NOT PROVEN
one-device authentic end-to-end execution: NOT PROVEN
```

This binding is source/CI work only. It must not be represented as authentic provider access, live synchronization, runtime activation, or custody proof.

## Next actions

1. Validate and merge the organization-local WorkSpace endpoint binding.
2. Reconcile the SDK WorkSpace handoff and canonical task registry with the merge evidence.
3. Add provider-neutral active-probe execution so `PROBE_REQUIRED` can only become resolvable through authentic current evidence, never caller assertion.
4. Bind an authentic external-provider adapter only after its authority/consent boundary is available.
5. Execute the controlled `OBSERVE -> MATERIALIZE -> live edit -> REFRESH -> authorization/probe change -> REVOKE/EXPIRE -> DESTROY` experiment.
6. Retain MIR transition reporting and independent Master Records custody/reconstruction evidence.
7. Verify the entire path on one current mobile device.

## Human action

None for the organization-local endpoint binding or provider-neutral active-probe source work.
