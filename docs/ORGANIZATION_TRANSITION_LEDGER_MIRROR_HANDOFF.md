# Organization Transition Ledger Mirror Handoff

Organization: `StegVerse-org`

Repository-level transitions remain owned and replayable in their originating repositories. This `.github` layer verifies a source transition receipt, records only the organization-level state consequence, and links the exact source receipt hash.

Every state transition occurring within the organization emits an organization receipt (`organization_scope_rule`), so admission is governed by the contract's `consumes` list rather than by a single hard-coded schema:

- `stegverse.repo-transition-receipt/v1` — a repository transition, verified against its own self-hash and required to name a repository inside this organization. Recorded with `source_repository`, `repo_receipt_sha256` and `repo_transition_id`.
- `stegverse.canonical-state-transition-receipt/v1` — a canonical governed state transition manifested through Interlock/InTr. Bound by its own canonical digest as `canonical_state_transition_receipt_sha256`, keeping its own schema and transition id; it is not relabelled as a repository transition. It must carry exact inline canonical evidence bytes, each entry bound to its own `transition_id`, so organization replay terminates on this chain alone.

Both land on one chain. The source receipt's own schema, transition id and digest are preserved in the organization receipt rather than replaced (`preserves_source_transition_receipt`). Admission is decided before the append lock is taken, so an inadmissible source receipt never contends for the ledger.

Contract: `.stegverse/transition-ledger/org-contract.json`  
Rollup: `resident-runtime/aggregate_repo_transition.py`

Organization replay must terminate using verified source receipts plus this org chain; it must not depend on Master Records ecosystem replay.

Only the organization receipt and evidence required for ecosystem reconstruction propagate to `master-records/.github`. Recording creates no authority.

The organization ledger root is this organization's runtime-reality locus; see `docs/ORGANIZATION_ROLE_RUNTIME_REALITY_DEPLOYMENT.md` (`ORGANIZATION-ROLE-RUNTIME-REALITY-DEPLOYMENT-001`).
