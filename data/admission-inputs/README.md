# Lane B admission inputs (StegVerse-org/.github#162)

Author session: Lane B (91117956).

`lane-b-91117956.admission-inputs.json` lists every open Lane B draft as an input to the ecosystem
merge-admission transition SV_CHANGE_ADMIT (StegVerse-Labs/TVC#519, Lane C GitHub Product 6329a668). Each
record uses the P1 `stegverse.sv_change.v1` field names (StegVerse-Labs/.github#3264 e65ee21b): content is
`[{path, blob_digest = sha256 of the head blob, deleted}]` over the PR diff against its merge base.
`base_ref.tree_sha` is the merge base's tree and `base_ref.ledger_head` is the repository's
`refs/stegverse/organization-ledger` tip as observed. The GitHub PR is in `projection` only.

Fields that are not authentically observed are `UNKNOWN_NOT_AUTHENTICALLY_OBSERVED` and listed in
`unobserved_fields`: registry_generation, hb_epoch, resolves, signoffs and validation_receipts. `change_id`,
`head.change_digest` and `request_digest` are therefore left null. SV_CHANGE_ADMIT answers DENY
`SV_CHANGE_BASE_UNBOUND` until the base-state readback supplies the registry generation. This is a
registration, not an admission and not an authentic receipt.
