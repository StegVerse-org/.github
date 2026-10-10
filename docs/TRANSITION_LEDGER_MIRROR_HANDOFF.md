# Transition Ledger Mirror Handoff

Repository: `StegVerse-org/.github`

Every durable transition owned here is recorded first in this repository ledger. Repo replay/reconstruction must terminate without org/ecosystem replay.

Contract: `.stegverse/transition-ledger/contract.json`  
Emitter: `.stegverse/transition-ledger/emit.py`  
Durable root: supplied by the materializer as `STEGVERSE_REPO_LEDGER_ROOT` (or `repo_ledger_root` in process). There is no host-derived default: without it the emitter refuses with `ledger_location_required_from_materializer`.

Where the durable root is (`contract.json` `repository_ledger_location`): a subtree, `repository-ledger/StegVerse-org/.github/`, of the designated organization ledger ref `refs/stegverse/organization-ledger` in this repository, addressed as `git+<checkout>#refs/stegverse/organization-ledger:repository-ledger/StegVerse-org/.github`. The organization ledger ref was the only designated durable location (`org-contract.json`, `preserves_repo_receipt: true`), and a repository chain materialized under a runner's temporary directory restarted at genesis on every run, so the only way to reconstruct repository history was organization replay, which `replay_rule` forbids (StegVerse-org/.github#118). Keeping the repository chain in its own subtree of that same ref makes it exactly as durable as the organization chain -- one commit history, one compare-and-swap, one fast-forward push under `ORGANIZATION_LEDGER_LOCK` -- names no second ref, and lets repository replay walk `repository-ledger/<repository>/HEAD.json` back through repository receipts alone. `organization-ledger-transition.yml` binds the root from the contract and reads both chains back from a fresh fetch (`resident-runtime/organization_ledger_readback.py --repository-namespace`). The two repository receipts minted before this binding (`previous_receipt_sha256: null`, retained under `source-receipts/`) remain retained history; the durable chain opens at its own genesis and is never re-minted over them.

Receipts are append-only/hash-linked. Only evidence needed for organization reconstruction propagates to `StegVerse-org/.github`. Recording grants no authority.
