# InTr ingress + organization ledger component (intr-ingress-ledger/v1)

Task `SVORG-INTR-INGRESS-LEDGER-COMPONENT-001` (orchestration/task-registry.json). Goal: StegVerse-org/.github#162.

## What it packages

The receiving half of the InTr mesh, as StegGhost/.github installed it in two commits:

- `cffd741`: advertise and serve InTr Destination at `stegghost.intr-destination`.
- `03d8b94`: designate the organization ledger ref and record diagnostic closures on it.

Files are taken at StegGhost `da5c947`, which also carries 643d36b (`hb_epoch` is a dispatch input). The InTr v1 validator comes from this repository's main.

| kind | files |
|---|---|
| vendored, byte-identical | `resident-runtime/aggregate_repo_transition.py`, `resident-runtime/ledger_store.py`, `.stegverse/transition-ledger/emit.py`, `org-boundary/runtime/capability_ingress.py`, `org-runtime/intr_protocol.py`, `data/intr-protocol/v1/protocol.json` |
| template, organization-bound | `resident-runtime/intr_destination_ingress.py`, `resident-runtime/organization_ledger_readback.py`, `.stegverse/transition-ledger/contract.json`, `.stegverse/transition-ledger/org-contract.json`, `.github/workflows/organization-ledger-transition.yml` (dispatch self-closure writer), `.github/workflows/intr-ingress-ledger-component-validation.yml`, `tests/test_intr_ingress_ledger_component.py` |
| bindings, add-only | the `<slug>.intr-destination` service entry; `ingress.capability_endpoint_bindings` and its two rules; `egress.peer_capability_resolution`; `org-kernel/kernel.py` `hb_reference` accepts a supplied epoch (no clock read) |

Every file is pinned by sha256 in `components/intr-ingress-ledger/v1/component.json`. The template variables are `ORGANIZATION` (from services.json), `REPOSITORY` and `SLUG` (from the target's own `org-kernel/kernel.py::organization_slug`).

## Install

```
python3 resident-runtime/intr_ingress_ledger_component.py plan    --target <org .github checkout>
python3 resident-runtime/intr_ingress_ledger_component.py install --target <org .github checkout>
python3 resident-runtime/intr_ingress_ledger_component.py verify  --target <org .github checkout>
```

- `plan` lists every ADD, BIND, PATCH and IDENTICAL step. The tool is deterministic, offline and holds no credential.
- `install` applies a plan only when it has no refusal, and writes `.stegverse/components/intr-ingress-ledger-v1.json`. A second install changes nothing.
- `verify` re-digests the installed files and runs `org-runtime/intr_protocol.py conform`.

Refusals are FAIL_CLOSED with the six fields, and nothing is written when one occurs:

- `COMPONENT_FILE_CONFLICT`
- `COMPONENT_BINDING_CONFLICT`
- `COMPONENT_INTERLOCK_DOCUMENT_ABSENT` (class B)
- `COMPONENT_SERVICE_REGISTRY_ABSENT`
- `COMPONENT_KERNEL_HB_REFERENCE_UNSUPPORTED`
- `COMPONENT_KERNEL_SLUG_UNAVAILABLE`
- `COMPONENT_TARGET_IDENTITY_MISMATCH`

## Not installed

- Organization egress.
- Organization batch release, or any handoff to the downstream recorder.
- A ledger ref. `refs/stegverse/organization-ledger` opens at genesis only when the adopting organization dispatches its own `organization-ledger-transition.yml`. Nothing here dispatches it.

## Adoption

Adoption drafts open per organization. Each draft's CI runs the installed test and `intr_protocol.py conform` at its head. The organization's row in the 16-org mesh (`tests/fixtures/intr-protocol/destinations/manifest.json`) turns ALLOW only from a byte snapshot of that organization's main after adoption lands.

The downstream recorder organization does not adopt. Its canonical role is `RELEASED_ORGANIZATION_BATCH_RECEIPT_RECORDER` (`data/master-records-role-audit.json`, docs/ORGANIZATION_ROLE_RUNTIME_REALITY_DEPLOYMENT.md "restated"), under which it "cannot create, admit, authorize, infer or repair a transition". An InTr destination admits diagnostic crossings, so adopting would contradict that role. Every interlock binding also declares it not in the path, and its federation directory row declares only an `org_control_service` with no addressed service.
