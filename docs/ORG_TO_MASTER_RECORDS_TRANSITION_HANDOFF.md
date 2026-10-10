# Organization to Master Records Transition Handoff

Organization: `StegVerse-org`

After a repository transition is verified and rolled into the organization ledger, the exact `stegverse.organization-transition-receipt/v1` may be written to Master Records as an organization record through the existing organization federation.

Publisher: `resident-runtime/submit_org_transition_to_master_records.py`

Route:

`StegVerse-org/.github -> InTr -> master-records/.github -> organization.ecosystem-transition-ledger -> master-records/orchestration`

The packet's `destination.service` is `organization.ecosystem-transition-ledger` (legacy wire name: `master-records.ecosystem-transition-ledger`, which receivers still accept). The ledger role belongs to the organization transition ledger; Master Records keeps the organization record.

The packet carries the already-hash-bound organization receipts of the released segment. Transport and the organization record do not create source authority and do not replace repo/org replay.

## Role and ordering

Master Records is the **recorder of released organization batch receipts** — downstream evidence preservation only (`docs/ORGANIZATION_ROLE_RUNTIME_REALITY_DEPLOYMENT.md`, "master-records restated"). It cannot create, admit, authorize, infer or repair a transition; it is not runtime-reality authority, not a gate and not custody. The contract says so: `propagation_gates_organization_runtime_reality: false`, `always_on_receiver_required: false`.

- Publication runs **after** the organization ledger append. The release predecessor is a verified organization receipt-chain segment: `--org-receipt` is repeatable and supplied in chain order (a single receipt is a batch of one), and each receipt must be this organization's, match its own `receipt_sha256` exactly as appended, and link to the one before it by `previous_receipt_sha256`. The payload is `RECORD_RELEASED_ORGANIZATION_BATCH` with `recorder_role: RELEASED_ORGANIZATION_BATCH_RECEIPT_RECORDER`, `gates_organization_runtime_reality: false` and `awaited_by_organization: false`. The transitions it carries are already real on the organization chain.
- Nothing awaits it. A batch not yet released or recorded is a value in the transition's evidence state, not a blocker and not proof of non-occurrence.
- Any release failure is a downstream `DENY` carrying `failure_code`, `failed_predicate`, `required_evidence_or_repair`, `retry_entrypoint`, `owning_existing_goal` and `next_attempt`, with `organization_transition_blocked: false` and `master_records_awaited: false`. It never refuses, holds or unmakes the organization transition. Retrying with the same segment publishes the same write-once frame, stamped with the segment head's epoch.
