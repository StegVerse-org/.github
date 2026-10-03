# Capability Ingress Address Mirror Handoff

**Repository:** `StegVerse-org/.github`
**Resolver:** `org-boundary/runtime/capability_ingress.py`
**Address:** `stegverse-org.sdk-manifest-ingress` → `ORGANIZATION_SDK_MANIFEST_INGRESS`
**Boundary document:** `org-runtime/interlock-intr.json` → `ingress.capability_address_rule`, `egress.peer_capability_resolution`
**Status:** BOUND_CAPABILITY_IS_ADDRESSABLE_PEER_SERVICE_INSTALLATION_UNPROVEN

## The bound capability had no address

`ingress.capability_endpoint_bindings` binds `sdk-manifest-ingress` /
`SDK:ManifestIngress` / `SUBMIT_MANIFEST` to a receiving operation this
repository owns, and `capability_endpoint_binding_rule` —
`REGISTERED_CAPABILITY_RESOLVES_TO_ONE_ORGANIZATION_RECEIVING_OPERATION_OWNED_HERE`
— held. The binding named an operation. What it did not have was an **address**.

`org-kernel/kernel.py::dispatch` resolves `destination.service` against
`org-boundary/registry/services.json` and refuses `unknown_service` for anything
absent from it. No row in that registry resolved to
`ORGANIZATION_SDK_MANIFEST_INGRESS`:

```text
stegverse-org.org-control             BOUNDARY_LOCAL_CONTROL
stegverse-org.boundary-diagnostic     BOUNDARY_LOCAL_DIAGNOSTIC
stegverse-org.llm-adapter             INTERNAL_ENDPOINT
...18 rows, none of them the manifest ingress
```

So the binding resolved a destination that **transport could not reach**. The
receiving operation could only be entered by running its CLI inside a checkout
of this repository — which is to say, by already being inside the organization.

This is the same defect class as the ones corrected before it: a declaration
nothing enforced. Here the declaration was a destination, and what was missing
was the reachability it implied. The practical consequence was the whole
end-to-end question. A paying customer's manifest, or a peer organization's, had
nowhere to arrive.

## What the address is, and what it is not

A registry row carrying `boundary_role: BOUNDARY_LOCAL_CAPABILITY_INGRESS`.
`dispatch` resolves that role through `capability_ingress.receive`, which reads
the overlay, finds the binding that names this row as its address, loads the
operation the binding names, and hands it the submitted manifest.

**The overlay stays the single authority.** Nothing is copied into the resolver.
A row addressed under this role is refused unless the overlay itself names that
row as the capability's addressed service, so an address cannot grant itself a
capability by declaring one. Exactly one binding may name a row: zero means the
address serves no declared capability, and more than one means the overlay is
ambiguous about what arrives there, where guessing would pick a receiving
operation on the submitter's behalf.

**Not an `INTERNAL_ENDPOINT`.** That role selects a processor, so
`manifest_selection` requires the addressed row to admit the declared capability
bound to the declared route. An organization's capability front door cannot
enumerate those pairs without growing a copy of the SDK's route table, which is
the one thing `manifest_selection` says this boundary must not do. It is a
`BOUNDARY_LOCAL_*` role because the processor it reaches is owned here.

**No processing is selected at the address.** `select_processing` returns
`BOUNDARY_LOCAL_NO_PROCESSOR_SELECTED`, and that reading is correct at this
surface: the capability is processed one layer in, by the receiving operation,
which resolves the manifest's own internal surface. The result says so rather
than letting a completed crossing at the address imply the capability ran there.

**A mis-wired address fails closed.** The overlay publishes an `operation_id`
and the module declares its own; the two are compared, and a module that does
not identify itself as the bound operation is refused rather than run. An
address that silently ran something adjacent under this capability's name would
be worse than no address.

**Addressability is not admission.** Standing is still required at ingress, the
receiving operation still refuses what it cannot drive, and every disposition is
still receipted by that operation at both ledger levels.

## The resolver is required only for its own role

`manifest_selection` and `node_standing` gate every dispatch, so a root without
them cannot dispatch at all. This one gates a single role. A root that never
serves a capability address is not defective for having no capability resolver,
and failing its control dispatch over one would be a limit that is not real — so
it loads inside the branch, and a root addressed under the role without it fails
closed with `org_boundary_capability_ingress_missing`.

## Outbound: a peer's capability address is derived

`resolve_destination` took no capability, so every outbound crossing addressed
the peer's `org_control_service`. That is correct for a control message and
wrong for a manifest: a submission delivered to a control service arrives at a
surface that does not receive submissions, and the crossing completes as a
control acknowledgement rather than as the capability it declared.

With a capability, the address is `organization_slug(org) + "." + profile_id`.
Derived, not enumerated, and derived by the rule already in use: that is how
`organization_slug(org) + ".org-control"` has always been spelled for every
peer, and it is how this organization's own capability address is spelled.
Enumerating a service per peer in this organization's directory would be this
organization writing down what its peers serve, which is a declaration none of
them made.

Two refusals bound it. A capability absent from this organization's own overlay
is refused — emitting under a name nothing declares is the outbound form of
letting a caller name its own peer. A peer whose `transport_profile` is not this
boundary's is refused as before.

### What the derivation proves and does not prove

| | |
| --- | --- |
| Address form is this organization's own | yes, shared by every peer declaring the profile |
| Form is the one this organization answers at | yes — `stegverse-org.sdk-manifest-ingress` is served here |
| The peer declared this service in the peer directory | **no** |
| The peer installed this receiving operation | **not proven here** |

The peer's own registry is the authority on what it serves and this boundary
cannot read it. The gap is observable rather than silent: a peer that does not
serve the capability mints no boundary receipt chain, so the crossing never
closes and `close` records the refusal under its own disposition.

The emission record binds `far_side_service_id` to the service actually
addressed. A closure reconstructs the far side's chain against that, so
recording the control service while having addressed a capability would make
every capability crossing unclosable.

## Enforced, not just declared

`org-runtime/runtime_boundary.py validate` is 15 checks, two of them new:

* `capability_addresses_resolve` — `capability_address_rule` holds: every bound
  capability's addressed service exists in the registry, carries the role whose
  dispatch resolves a capability, agrees with the binding on which capability
  arrives there, selects no processing and grants no admission authority, and
  names an operation module and a resolution entrypoint present in this
  repository.
* `peer_capability_addresses_derive` — the egress derivation declares its form,
  declares that the capability must be in this organization's overlay, names the
  address it is proven on (and that address is actually served here), and
  declares that the peer's installation is **not** proven and that an unserved
  address is observable as an unclosed crossing.

## Verified

A peer organization published a frame into the shared mesh addressed to this
organization's capability address — no checkout on the submitting side, no CLI:

```text
origin       StegVerse-Labs / stegverse-labs.sdk-manifest-ingress
destination  StegVerse-org  / stegverse-org.sdk-manifest-ingress
dispatch     CONSUMED   processing_selection BOUNDARY_LOCAL_NO_PROCESSOR_SELECTED
address      capability_received true   profile sdk-manifest-ingress
operation    ORGANIZATION_SDK_MANIFEST_INGRESS
             resolved_service_id             stegverse-org.llm-adapter
             intr_admission_observed         true
             far_side_transition_observed    true
             repository_receipt_observed     true
             organization_receipt_observed   true
             organization_receipt_preserves_repository_receipt  true
```

`tests.test_capability_ingress_address` 24 cases.
`org-runtime/runtime_boundary.py validate` 15/15.
Every CI step extracted verbatim and run locally. `actionlint` clean.

## What this does not close

Origin remains asserted rather than attested. A frame in a shared mesh carries
whatever origin its writer put in it, and `credential_authority` is TV/TVC with
`origin_attestation_state: NOT_PROVEN`. Giving the capability an address does
not change that, and it is the one dimension the receipt-disorder measurement
scores non-zero. What the address changes is reachability, not identity.

Nothing here grants authority.
