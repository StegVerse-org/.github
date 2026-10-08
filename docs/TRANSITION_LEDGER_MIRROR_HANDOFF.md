# Transition Ledger Mirror Handoff

Repository: `StegVerse-org/.github`

Every durable transition owned here is recorded first in this repository ledger. Repo replay/reconstruction must terminate without org/ecosystem replay.

Contract: `.stegverse/transition-ledger/contract.json`  
Emitter: `.stegverse/transition-ledger/emit.py`  
Durable root: supplied by the materializer as `STEGVERSE_REPO_LEDGER_ROOT` (or `repo_ledger_root` in process). There is no host-derived default: without it the emitter refuses with `ledger_location_required_from_materializer`.

Receipts are append-only/hash-linked. Only evidence needed for organization reconstruction propagates to `StegVerse-org/.github`. Recording grants no authority.
