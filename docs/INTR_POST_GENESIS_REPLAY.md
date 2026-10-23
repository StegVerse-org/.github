# InTr post-genesis kit (StegVerse-org/.github#162, Lane B)

Author session: Lane B (91117956).

The next InTr blocker is `INTR_PATH_DESTINATION_RECEIPT_NOT_LEDGERED`. It clears at admission genesis, when the inbound rows in StegVerse-org/.github#224 and StegVerse-Labs/.github#3312 land on main and each destination's `.github/workflows/intr-path-ingress.yml` appends an `ORGANIZATION_INTR_DESTINATION_INGRESS` receipt. That append is a `workflow_run` after the main-merge transfer, not a dispatch.

This kit does everything up to that event and nothing at it. It writes no ledger, dispatches nothing and uses no credential. The sealed records are not receipts and are not authentic.

## Files

| file | what it is |
|---|---|
| `.stegverse/intr-post-genesis/inputs.json` | Committed facts as observed on 2026-10-23: genesis PRs and heads, destination ingress on main, anonymous ledger readability and tips, and the TVC retry. |
| `.stegverse/intr-post-genesis/payloads/<S>__<D>.json` | One sealed record (`record_sha256`) per declared path, 56 in all. |
| `.stegverse/intr-post-genesis/manifest.json` | Sealed manifest: sha256 of every record and of `inputs.json`, class counts and the genesis-ALLOW set. |
| `.stegverse/intr-post-genesis/SHA256SUMS` | `sha256sum -c` form, including `manifest.json`. |
| `scripts/intr_post_genesis_replay.py` | `seal`, `check`, `replay` and `carry`. |
| `scripts/intr_post_genesis_replay.sh` | Anonymous ledger fetch, then `check` and `replay`. |
| `tests/test_intr_post_genesis_replay.py` | 9 kit tests plus 56 per-path tests. Each per-path test is its own callable set `intr-path:<S>-><D>` in `.stegverse/test-set-spec.json`. |

## The destination payload

For each path whose source receipt is on an anonymously readable source ledger, `seal` computes the evidence that `intr_path_ingress.py consume` will append. It does this field for field with `ingress_evidence`:
- `evidence_invariant`: every field that does not depend on when consume runs (schema, repository, path_id, source repository and both source receipt seals, message, message_sha256, addressed_service).
- `evidence_at_observed_source_tip`: the full evidence, including `source_inclusion` and `payload_sha256`, computed at the source ledger tip observed now. If the source ledger moves before consume runs, only `source_inclusion.source_ledger_tip` and `payload_sha256` change. The rule for that tip is recorded in the payload.
- The source receipt pair is embedded, so `check` recomputes every payload offline.

## Source writers and carry (AE, SV-LLM)

- **Destination ingress** for org/Labs→AE and org/Labs→SV-LLM: SV-LLM/.github#50 and Admissible-Existence/.github#99 (laneb/ G-8 drafts) each add `intr_path_ingress.py` plus `intr-path-ingress.yml`, byte-identical to org#224, and an `inbound.json` with those two rows.
- **Source receipts (`INTR_MESH_PATH_TRANSFER`)** for the 14 AE/SV-LLM-sourced paths: the same drafts add `intr_path_transfer.py` plus `intr-path-transfer.yml` and `transfers.json`. Each receipt links the push's `ORGANIZATION_MAIN_MERGE_TRANSFER`, from `organization-ledger-merge-transfer.yml`.
  - P4's B1 writer (StegVerse-org/.github#222) resolves to this established entity. Its census counts a repository with the merge-transfer writer as covered.
- `carry --public-ledgers DIR --destination ORG [--source ORG ...] [--merge-into inbound.json] --out FILE`: after a source writer has appended, this writes the inbound rows a destination must land, read back anonymously. It reproduces org#224's `inbound.json` byte for byte. A path that cannot be carried yet is refused with six fields.

## Classes (sealed 2026-10-23, run from the public ledger tips in inputs.json)

| class | paths | at genesis | primary six fields (all blockers are listed in each record) |
|---|---|---|---|
| `GENESIS_READY` | 4: org→Labs, Labs→org, org→SV-LLM, Labs→SV-LLM | **ALLOW** | now `INTR_PATH_DESTINATION_RECEIPT_NOT_LEDGERED`; retry: the destination's `intr-path-ingress.yml` after org#224 / Labs#3312 / SV-LLM#50 are admitted |
| `CARRY_AFTER_GENESIS` | 2: SV-LLM→org, SV-LLM→Labs | FAIL_CLOSED, then **ALLOW** after carry | `INTR_PATH_RECEIPT_NOT_LEDGERED` until SV-LLM#50's writer appends; then `carry` the rows into org/Labs; replay recomputes the evidence from the read-back source pair (`--require-carry-allow`) |
| `LEDGER_HEAD_EPOCH_UNOBSERVED` | 6: org→AE, Labs→AE, AE→org, AE→Labs, AE→SV-LLM, SV-LLM→AE | FAIL_CLOSED | `HB_EPOCH_SOURCE_UNOBSERVED` / `MERGE_TRANSFER_EPOCH_IS_THE_LEDGER_HEAD_SUPPLIED_EPOCH`: the AE ledger head has a clock-derived epoch; repair Admissible-Existence/.github#97 (B-P31), then an AE append with a supplied epoch |
| `TVC_PRIVATE_SOURCE_READ` | 28: every path from SV-011, GCAT, StegGhost or 002 | FAIL_CLOSED | `INTR_PATH_CROSS_ORG_READ_CREDENTIAL_NOT_ISSUED`; retry StegVerse-Labs/TVC#532 + #535; goal TVC-PRIVATE-SOURCE-READ-001 (TVC#33) |
| `TVC_PRIVATE_DESTINATION_READ` | 16: org, Labs, AE or SV-LLM → SV-011, GCAT, StegGhost, 002 | FAIL_CLOSED | `INTR_PATH_CROSS_ORG_READ_CREDENTIAL_NOT_ISSUED`; retry TVC#532 + #535; also an inbound row and an ingress or public-route port at the destination (the 4 AE-sourced paths also carry the AE epoch blocker) |

That gives 4 ALLOW at genesis and 6 after carry. All 12 public↔public paths are ready once the AE epoch blocker clears. The 44 private-end paths stay FAIL_CLOSED on TVC#532/#535.

Every path is terminal at E0: ALLOW, DENY, or FAIL_CLOSED with all six fields. No step waits on an LLM, the owner or a host.

## Post-genesis replay

```
scripts/intr_post_genesis_replay.sh "$RUNNER_TEMP/intr-post-genesis" --require-genesis-allow
```

For each path, the replay:
1. Verifies the sealed record (seal, manifest digest, payload recompute).
2. Reads both ledgers back from the local anonymous copies.
3. Runs `verify_end_to_end`.
4. Checks that the ledgered ingress evidence equals the sealed `evidence_invariant` and that `source_inclusion.state` is `VERIFIED_BY_ANONYMOUS_PUBLIC_LEDGER_READ`.
5. Where this organization is an end of the path, also runs `intr_path_ingress.py end-to-end-via-tvc --public-ledgers`, binding this organization's ledger read-only to its fetched copy. The two verifiers must agree.

A non-ALLOW carries the verifier's six fields and, beside them, the kit's known repairs (`kit_blockers`). With `--require-genesis-allow`, the run exits 1 unless every `GENESIS_READY` path is ALLOW. With `--require-carry-allow`, it does the same for `CARRY_AFTER_GENESIS`.

Before genesis (today's ledgers) the replay gives ALLOW 0, DENY 0, FAIL_CLOSED 56, and every path is E0-terminal.

Rehearsal on scratch copies (not ledgered, not authentic):
- `consume` was run on a scratch copy of each ledger, Labs (from this checkout, row org→Labs) and org (from org#224, row Labs→org).
- The replay then gave ALLOW 2 / FAIL_CLOSED 54, with `payload_matches_sealed: true` and `end-to-end-via-tvc` ALLOW for both paths.
- The appended evidence equalled `evidence_at_observed_source_tip` exactly.

Rehearsal of the AE/SV-LLM extension (NOT AUTHENTIC: scratch bare copies of all four public ledgers, simulated local merges of org#224, Labs#3312, SV-LLM#50 and AE#99 into scratch mains, every workflow step run locally, nothing published):
- SV-LLM: the main-merge transfers and the 7 SV-LLM source receipts went ALLOW, and so did the consumes for org→SV-LLM and Labs→SV-LLM.
- AE: every merge-transfer append and every consume was FAIL_CLOSED `HB_EPOCH_SOURCE_UNOBSERVED`, with nothing written.
- `carry` then landed SV-LLM→org and SV-LLM→Labs as a simulated PR, and their consumes went ALLOW.
- The replay over those copies gave ALLOW 6 / DENY 0 / FAIL_CLOSED 50, every non-ALLOW with six fields. The 6 ALLOW paths were org↔Labs, org/Labs→SV-LLM and SV-LLM→org/Labs.
