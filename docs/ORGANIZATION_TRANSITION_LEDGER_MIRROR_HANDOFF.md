# Organization Transition Ledger Mirror Handoff

Organization: `StegVerse-org`

Repository-level transitions remain owned and replayable in their originating repositories. This `.github` layer verifies a repo receipt, records only the organization-level state consequence, and links the exact repo receipt hash.

Contract: `.stegverse/transition-ledger/org-contract.json`  
Rollup: `resident-runtime/aggregate_repo_transition.py`

Organization replay must terminate using verified repo receipts plus this org chain; it must not depend on Master Records ecosystem replay.

Only the organization receipt and evidence required for ecosystem reconstruction propagate to `master-records/.github`. Recording creates no authority.
