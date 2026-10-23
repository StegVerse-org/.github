`tvc-record-synthetic-pr200.json` is a **synthetic test input**, not an admission of PR #200. PR #200 is the merge in the merge-transfer fixture `tests/fixtures/merge-transfer/f160ac7d.json`, which is already on main.

The record is the byte output of StegVerse-Labs/TVC `sv_merge_admission.evaluate` at TVC#534 head 5d11cb0. It was run on a test-local observation:
- the fixture positive control, re-pointed to this repository, PR 200, head 8129a936 and base 40a5d235;
- a test-local sealed push receipt and genesis receipt;
- ledger head 2acec0e1 at hb_epoch 446655631, which is the merge-transfer fixtures' pinned ledger tip.

It is used only to prove that the op appends what TVC emits and that the B2 checkpoint finds it.
