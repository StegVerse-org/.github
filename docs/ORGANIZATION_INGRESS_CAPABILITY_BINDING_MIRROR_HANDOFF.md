# Organization Ingress Capability Binding Mirror Handoff

Updated: 2026-10-03
Organization: `StegVerse-org`
Repository: `.github`
Goal Task ID: `SVORG-STEGOS-PORTABILITY-001`
Related Task ID: `SDK-GENERIC-MANIFEST-ECOSYSTEM-INVARIANT-005`
Settled specification: `StegVerse-org/.github:docs/NODE_INGRESS_SETTLED_SPECIFICATION.md`
Status: `BINDING PUBLISHED / RESOLVES AGAINST THE SDK RESOLVER / CROSSING NOT YET DRIVEN BY IT`

## What was missing

The canonical connector registry at `StegVerse-Labs/StegOS:specs/universal-intr-connector-profiles.v1.json` declares the capability `sdk-manifest-ingress` / `SDK:ManifestIngress` and names `StegVerse-org/StegVerse-SDK` as the subsystem that binds it. Nothing declared where this organization *receives* a submission on that capability.

So every SDK manifest handoff failed closed on one predicate:

```text
failed_predicate  REGISTERED_CAPABILITY_RESOLVES_TO_CANONICAL_ORGANIZATION_GITHUB_INGRESS_ENDPOINT
failure_code      CANONICAL_ORGANIZATION_INGRESS_ENDPOINT_NOT_RESOLVED
next_attempt      RETRY_AFTER_CANONICAL_ORGANIZATION_ENDPOINT_MAPPING_IS_AVAILABLE
```

Both halves of the system were correct and nothing joined them. The SDK cannot supply the missing half: `sdk_may_declare_its_own_capability` is false, and `repository_endpoint_rule` is `APPLICATION_REPOSITORIES_EXPOSE_PROFILES_ONLY_ORG_DOT_GITHUB_OWNS_ORG_COMMUNICATION`. The declaration belongs here.

## The binding

`org-runtime/interlock-intr.json` carries `ingress.capability_endpoint_bindings`. One binding per capability, keyed on the three fields the SDK resolves against:

```text
profile_id    sdk-manifest-ingress
profile_name  SDK:ManifestIngress
operation     SUBMIT_MANIFEST
```

Its `receiving_operation` is an operation this repository owns, not an address:

```text
owner_repository   StegVerse-org/.github
operation_id       ORGANIZATION_SDK_MANIFEST_INGRESS
admission          resident-runtime/sdk_manifest_crossing.py::cross
processing         org-boundary/runtime/process_boundary.py
receipt_append     resident-runtime/aggregate_repo_transition.py::append
emits              stegverse.organization-transition-receipt/v1
transport          INTERLOCK_INTR
address_form       REPOSITORY_OWNED_OPERATION_NOT_HOST_OR_URL
```

There is no host and no environment URL. A located receiving operation would reintroduce exactly the dependency `ORGANIZATION-ROLE-RUNTIME-REALITY-DEPLOYMENT-001` removes, so `host_required` and `environment_url_required` are both false and the validator refuses a binding that sets either.

## Why it grants nothing

The binding says where a registered capability is received. It is not an admission, a route selection or an execution grant — the receiving operation decides each of those on its own evidence. `binding_role` is `ORGANIZATION_RECEIVING_OPERATION_RESOLUTION`, `authority_effect` is `NONE_BINDING_ONLY`, and `grants_routing_authority`, `grants_admission_authority`, `grants_execution_authority` and `environment_selected_ingress` are all false. The SDK refuses the binding if any of them is otherwise, and so does `org-runtime/runtime_boundary.py validate`.

`completion.egress` remains not an outbound routing authority, and neither the LLM-adapter nor the Publisher is an outbound organization destination.

## Validation

`tests/test_organization_ingress_capability_binding.py` asserts against the SDK's own `resolve_organization_ingress` and `execute_manifest` rather than a local copy of their rules. The SDK is the enforcing authority: a local restatement could pass here while real resolution still failed, so the thing under test is the thing that enforces. The workflow pins the SDK at the commit that owns the resolver.

```text
without the boundary document  FAIL_CLOSED  CANONICAL_ORGANIZATION_INGRESS_ENDPOINT_NOT_RESOLVED
with the boundary document     ALLOW        MANIFESTED_FOR_INTERLOCK_INTR_HANDOFF
```

## What this does not claim

A named destination is not a reached one. On a resolved handoff the SDK still reports `intr_admission_observed`, `far_side_transition_observed`, `organization_receipt_observed`, `master_records_reconstruction_observed`, `receiver_contacted` and `consequence_committed` as false, and this binding changes none of them.

What remains unbuilt is the join on the other side: no surface in this repository yet calls `execute_manifest` with this document, so the resolved handoff is not yet driven into `ORGANIZATION_SDK_MANIFEST_INGRESS`. That is the next transition, not a claim of this one.
