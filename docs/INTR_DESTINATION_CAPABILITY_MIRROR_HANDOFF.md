# InTr Destination Capability Mirror Handoff

**Repository:** `StegVerse-org/.github`
**Capability:** `intr-destination` / `InTr:Destination` / `DIAGNOSTIC_CROSSING`
**Address:** `stegverse-org.intr-destination` → `ORGANIZATION_INTR_DESTINATION_INGRESS`
**Operation:** `resident-runtime/intr_destination_ingress.py`
**Boundary document:** `org-runtime/interlock-intr.json` → `ingress.capability_endpoint_bindings`, `egress.peer_capability_resolution`
**Status:** ADVERTISED_AND_SERVED_HERE_PEER_INSTALLATION_UNPROVEN

## Why this capability exists

A peer could be addressed at a purpose route — governance, remediation — or at
`org-control`. Neither is a universal destination. Governance is decided by the
organization that owns StegCore. Remediation is classified by the organization
that owns the healer. `org-control` answers a control message. A diagnostic
that only asks whether an organization is reachable as an InTr destination had
to borrow one of those, and a borrowed purpose route reads as that purpose.

`intr-destination` is the mesh primitive those routes sit on. Every
organization can advertise it. A crossing that uses it is a purpose-neutral
diagnostic: an `ecosystem.communication` whose body schema is
`stegverse.org-intr-destination-diagnostic/v1`. It acknowledges. It does not
govern, classify, admit, route, or execute.

## What is declared here

The overlay remains the single authority. One binding, owned here, granting
nothing:

```text
profile_id     intr-destination
profile_name   InTr:Destination
operation      DIAGNOSTIC_CROSSING
reader         ECOSYSTEM_COMMUNICATION
address        stegverse-org.intr-destination
role           BOUNDARY_LOCAL_CAPABILITY_INGRESS
operation_id   ORGANIZATION_INTR_DESTINATION_INGRESS
authority      NONE_BINDING_ONLY
```

`address_grants_admission_authority` and `selects_processing_at_this_address`
are false on the registry row and on the binding. An address cannot grant
itself the capability: `capability_ingress.receive` refuses a row the overlay
does not name, and it refuses a module whose `OPERATION_ID` is not the one the
binding publishes.

The profile name is local. The pinned SDK subsystem baseline does not declare
it, and `StegVerse-Labs/StegOS` `specs/universal-intr-connector-profiles.v1.json`
was not readable when this binding was added. This repository therefore does
not claim the canonical connector registry already named `InTr:Destination`.
The declaration owner is `StegVerse-org/.github`.

`SUBMIT_MANIFEST` still uses the manifest reader. The diagnostic names
`ECOSYSTEM_COMMUNICATION`, so a communication is not refused for lacking a
manifest and a manifest is not accepted as a diagnostic. The validator refuses
a non-manifest operation that tries to inherit the manifest reader.

## What a peer address is

`resolve_destination(peer, capability="intr-destination")` derives
`organization_slug(peer) + "." + "intr-destination"`. That is the same rule as
`sdk-manifest-ingress`. Peer capability services are not written into
`federation.json`. `peer_serves_this_capability_is_proven_here` stays false at
resolution. An unserved address does not close.

`proven_on_this_organization` names every capability address **this**
organization serves:

```text
stegverse-org.sdk-manifest-ingress
stegverse-org.intr-destination
```

A string still names the one address a single-capability organization serves.
Two addresses are a list, because a string can name only one and naming one of
two would understate what is served here. A peer address in that list is
refused. The field is not a peer map.

## What the crossing proves

| | |
| --- | --- |
| This organization advertises and serves the address | yes — a frame at `stegverse-org.intr-destination` is consumed and receipted at both ledger levels |
| The acknowledgement grants authority | no |
| A peer address is derived, not enumerated | yes |
| The peer installed the receiving operation | **not proven at resolution** |
| Something at the addressed service ran this packet | yes, **at closure**, when the far-side terminal receipt recomputes |
| Which organization that boundary belongs to | **no** |
| The far side persisted the chain on its own ledger | **no** |
| No answer is a close | no — `close` returns `PENDING` and writes nothing |

The unit test's far side is this repository's `kernel.receipt` and
`build_control_response`, the same stand-in the governance route uses. That is
a fabricated answer in a temporary mesh. It is not a live peer, and it is not
an authentic production receipt.

Governance and remediation `capability_destination_bindings` are unchanged.
Those remain purpose routes.

## Verified

`tests.test_intr_destination_capability` covers the declaration, the overlay
fail-closed miswires, derived resolution, the refused undeclared capability,
receipt of a diagnostic at this address, emit `ALLOW`, close `PENDING` with no
answer, and close `ALLOW` when the fabricated far side answers.

`org-runtime/runtime_boundary.py validate` includes `capability_addresses_resolve`
and `peer_capability_addresses_derive`.

Both ledger roots in the unittest and in CI are redirected. The mesh is a
temporary directory.

## What other organizations do next

This repository is the template. AaCT-E, StegGhost, and the other federation
organizations mirror the same binding in their own `.github` repositories.
This change does not install the capability for them, and it does not claim
they already serve it.

Nothing here grants authority.
