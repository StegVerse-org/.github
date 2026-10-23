`tvc-record-synthetic-pr200.json` is a **synthetic test input**, not an admission of PR #200. PR #200 is the merge in the merge-transfer fixture `tests/fixtures/merge-transfer/f160ac7d.json`, which is already on main.

The record is the byte output of StegVerse-Labs/TVC `sv_merge_admission.evaluate` at TVC#534 head 3019f1c2, under the committed manifest v2.2 (sha256:9f0e58ec…). It was regenerated for v2.2; change_digest is unchanged (76de67c6…). It was run on a test-local observation:
- the fixture positive control, re-pointed to this repository, PR 200, head 8129a936 and base 40a5d235;
- a test-local sealed push receipt, genesis receipt, Lane B selected-tests receipt (0 skipped) and the Lane B producer files at the base (the org #231 pins);
- ledger head 2acec0e1 at hb_epoch 446655631, which is the merge-transfer fixtures' pinned ledger tip.

It is used only to prove that the op appends what TVC emits and that the B2 checkpoint finds it.

The signed delivery envelope is built in the test with an ephemeral ed25519 key generated in a temp dir for each run. It is never committed and is not a credential. The contract pins no key (FAIL_CLOSED ADMISSION_RECORD_SIGNER_KEY_NOT_PINNED) until a TVC resident issuance receipt publishes the real public key.
