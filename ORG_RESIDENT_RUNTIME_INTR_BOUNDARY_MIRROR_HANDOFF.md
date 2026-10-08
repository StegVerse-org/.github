# Organization Resident Runtime + Interlock/InTr Boundary Mirror Handoff

Status: ACTIVE
Updated: 2026-08-31
Organization: `StegVerse-org`
Repository: `StegVerse-org/.github`

This `.github` is the organization-level owner of resident-runtime activation source and all ingress/egress generation.

Application repositories expose endpoint/runtime profiles only. Cross-organization traffic is generated here as Interlock/InTr envelopes.

Authentic runtime execution remains a sovereign resident process. GitHub and GitHub Actions are source/evidence/validation surfaces only.

HB/HB-derived carriers may synchronize and carry packets but grant no admission, execution, credential, routing, transition, receiving, publication, or release authority.

Action admission, authority transfer, capability realization, and authority effect are distinct; standing/effects are `DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS`.

Machine surfaces:
- `org-runtime/activation.json`
- `org-runtime/interlock-intr.json`
- `org-runtime/runtime_boundary.py`

The tool validates the contract and emits resident activation requests plus ingress/egress envelopes. It cannot self-grant authority.


## Consumed crossings are recorded at both ledger levels

`consume_and_respond` and `consume_addressed_frames` consumed control,
diagnostic and internal-endpoint frames and minted the kernel's five boundary
receipts, but appended nothing to the repository or organization ledger, so a
crossing consumed and answered left no organization receipt
(`organization_scope_rule`). Both now take `repo_ledger_root` and
`org_ledger_root`, supplied like the mesh and node state, and refuse before
consuming anything when either is missing
(`ledger_location_required_from_materializer`). Each consumed crossing appends
a repository receipt (`ORGANIZATION_FEDERATION_CROSSING_CONSUMED`) and the
organization receipt consuming it before its answer is published or its frame
marked; a failed append leaves the frame unanswered and unmarked, and the next
pass completes it. The transition is identified by the content-addressed frame,
so consuming it again returns the recorded receipts. Crossings to a capability
address are not recorded here: the receiving operation records both levels.

The emitters are loaded from the kernel's own repository, and a dispatch root
that is not that repository, or whose registry names another organization, is
refused (`dispatch_root_is_not_this_kernels_organization`). A peer organization
in a test is therefore its own copy of the kernel, emitters and contracts
(`tests/peer_organization.py`), consuming into its own ledger roots.

`resident-runtime/federation_cycle.py` passes the supplied
`STEGVERSE_REPO_LEDGER_ROOT` and `STEGVERSE_ORG_LEDGER_ROOT` to the kernel; when
either is missing the cycle reports `consumption` as `FAIL_CLOSED` with retry
entrypoint `resident-runtime/federation_cycle.py::main` and consumes nothing.
The frames stay in the mesh.

A crossing the boundary refuses is recorded too, under its own class
(`ORGANIZATION_FEDERATION_CROSSING_REFUSED`), instead of leaving the pass by
exception and stopping every frame behind it. A deterministic refusal
(standing, unknown service, undeclared or unadmitted processing, no installed
adapter) is `DENY`: recorded and marked. Anything else, such as an adapter that
failed to execute, is `FAIL_CLOSED`: recorded once with retry entrypoint
`org-kernel/kernel.py::consume_and_respond`, left unmarked and offered again. A
crossing refused and later admitted is two transitions. Custody refusals
(missing node state or ledger location, a foreign root) still refuse the whole
pass before any mutation, and a capability-address refusal still raises: its
receiving operation records it.
