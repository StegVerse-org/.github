# Organization to Master Records Transition Handoff

Organization: `StegVerse-org`

After a repository transition is verified and rolled into the organization ledger, the exact `stegverse.organization-transition-receipt/v1` may be written to Master Records as an organization record through the existing organization federation.

Publisher: `resident-runtime/submit_org_transition_to_master_records.py`

Route:

`StegVerse-org/.github -> InTr -> master-records/.github -> organization.ecosystem-transition-ledger -> master-records/orchestration`

The packet's `destination.service` is `organization.ecosystem-transition-ledger` (legacy wire name: `master-records.ecosystem-transition-ledger`, which receivers still accept). The ledger role belongs to the organization transition ledger; Master Records keeps the organization record.

The packet carries the already-hash-bound organization receipt. Transport and the organization record do not create source authority and do not replace repo/org replay.
