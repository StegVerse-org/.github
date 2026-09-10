# Organization Federation Generic Endpoint Adapter Mirror Handoff

Updated: 2026-09-10
Organization: `StegVerse-org`
Repository: `.github`
Goal Task ID: `SDK-GENERIC-MANIFEST-DOWNSTREAM-PROPAGATION-003`
Parent handoff: `StegVerse-org/StegVerse-SDK:docs/SHARED_DOCS_EPHEMERAL_MANIFEST_WORKSPACE_MIRROR_HANDOFF.md`
Implementation PR: `#9 MERGED`
Merge SHA: `d8baefb8674ebed00bbbf9784c54e092a5b1a04d`
Status: `ACTIVE / GENERIC INTERNAL ENDPOINT DISPATCH MERGED / WORKSPACE RECEIVER PENDING`

## Completed repair

`org-kernel/kernel.py::dispatch` already selected registered `INTERNAL_ENDPOINT` services generically, but the production `org-boundary/runtime/process_boundary.py` previously executed an `endpoint_adapter` only for `stegverse-org.stegverse-sdk`. That service-ID special case is removed.

The boundary processor now executes the registry-declared adapter for any `INTERNAL_ENDPOINT` after local destination/service resolution. Adapter paths must resolve inside the organization repository root and exist as files. Missing adapters, paths outside the organization root, failed adapter execution, and invalid output remain fail-closed.

The repair preserves:

```text
registry selects service
service boundary_role == INTERNAL_ENDPOINT
registry endpoint_adapter selects local adapter
adapter path constrained to organization repo root
boundary processor retains receipt generation
adapter does not gain transport/governance/credential/transition authority
```

No Shared Docs-specific route or service was introduced.

## Regression correction

The prior `tests/test_internal_endpoint_dispatch.py` used a stub `process_boundary.py`, so it verified generic kernel dispatch while bypassing the production processor containing the SDK-only hardcoding. The test now copies and exercises the real production boundary processor.

Coverage proves:

- a non-SDK registered internal endpoint executes through the production adapter path;
- the existing SDK service ID still executes through the same generic path;
- unknown service is rejected;
- internal endpoint without adapter is rejected;
- adapter outside organization root is rejected;
- failed adapter execution is rejected;
- boundary-local diagnostic behavior remains unchanged.

## Validation evidence

```text
PR: StegVerse-org/.github#9
exact validated head: f2ce79a277cd4038e4a8bb098f6fcacc62fb4ad4
Internal Endpoint Dispatch Validation: 34536206284 SUCCESS
PR mergeable before merge: true
merge: SUCCESS
merge SHA: d8baefb8674ebed00bbbf9784c54e092a5b1a04d
```

README maintenance was completed in the same PR and documents registry-driven internal endpoint dispatch and fail-closed adapter containment.

## Current proof boundary

```text
registry-driven kernel dispatch: IMPLEMENTED / MERGED
provider-neutral internal endpoint adapter dispatch: IMPLEMENTED / VALIDATED / MERGED
federation gateway transport: EXISTS
future WorkSpace service can use registry endpoint_adapter without boundary hardcoding: SOURCE PATH ENABLED
Shared Docs WorkSpace receiver: NOT YET IMPLEMENTED
Shared Docs live transport/projection proof: NOT PROVEN
```

This repair enables the next source step but does not itself prove an authentic WorkSpace runtime interaction.

## Next actions

1. Complete and merge the SDK canonical-ingress-to-external-Interlock binding.
2. Define the smallest organization-local generic external-resource/WorkSpace endpoint adapter using the now-generic registry path.
3. Preserve canonical `stegverse.ingress-manifest.v1` as the manifested-data object; transport envelopes remain control metadata only.
4. Bind active probe handling, projection lifecycle, expiry/revocation, MIR transition reporting, and independent Master Records evidence through authentic executable interfaces.
5. Run the eventual live-edit/synchronization/teardown experiment from a one-device-capable path.

## Human action

None.
