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
| `scripts/intr_post_genesis_replay.py` | `seal`, `check` and `replay`. |
| `scripts/intr_post_genesis_replay.sh` | Anonymous ledger fetch, then `check` and `replay`. |
| `tests/test_intr_post_genesis_replay.py` | 6 kit tests plus 56 per-path tests. Each per-path test is its own callable set `intr-path:<S>-><D>` in `.stegverse/test-set-spec.json`. |

## The destination payload

For each path whose source receipt is on an anonymously readable source ledger, `seal` computes the evidence that `intr_path_ingress.py consume` will append. It does this field for field with `ingress_evidence`:
- `evidence_invariant`: every field that does not depend on when consume runs (schema, repository, path_id, source repository and both source receipt seals, message, message_sha256, addressed_service).
- `evidence_at_observed_source_tip`: the full evidence, including `source_inclusion` and `payload_sha256`, computed at the source ledger tip observed now. If the source ledger moves before consume runs, only `source_inclusion.source_ledger_tip` and `payload_sha256` change. The rule for that tip is recorded in the payload.
- The source receipt pair is embedded, so `check` recomputes every payload offline.

## Classes (sealed 2026-10-23, run from the public ledger tips in inputs.json)

| class | paths | at genesis | primary six fields (all blockers are listed in each record) |
|---|---|---|---|
| `GENESIS_READY` | 2: org→Labs, Labs→org | **ALLOW** | now `INTR_PATH_DESTINATION_RECEIPT_NOT_LEDGERED` / `PATH_HAS_A_DESTINATION_LEDGER_RECEIPT`; retry: the destination's `intr-path-ingress.yml` after org#224 / Labs#3312 are admitted |
| `TVC_PRIVATE_SOURCE_READ` | 28: every path from SV-011, GCAT, StegGhost or 002 | FAIL_CLOSED | `INTR_PATH_CROSS_ORG_READ_CREDENTIAL_NOT_ISSUED` / `SOURCE_INCLUSION_IS_READ_FROM_THE_SOURCE_LEDGER`; retry StegVerse-Labs/TVC#532 + #535; goal TVC-PRIVATE-SOURCE-READ-001 (TVC#33) |
| `TVC_PRIVATE_DESTINATION_READ` | 8: org or Labs → SV-011, GCAT, StegGhost, 002 | FAIL_CLOSED | `INTR_PATH_CROSS_ORG_READ_CREDENTIAL_NOT_ISSUED` / `DESTINATION_READBACK_IS_READ_FROM_THE_DESTINATION_LEDGER`; retry TVC#532 + #535; also needs an inbound row and an ingress or public-route port at the destination |
| `SOURCE_RECEIPT_NOT_LEDGERED` | 14: every path from AE or SV-LLM | FAIL_CLOSED | `INTR_PATH_RECEIPT_NOT_LEDGERED` / `PATH_HAS_A_SOURCE_LEDGER_RECEIPT`; retry the source's `intr-path-transfer.yml`; 8 of them also need TVC#532 + #535 for a private destination |
| `DESTINATION_INGRESS_NOT_ON_MAIN` | 4: org or Labs → AE, SV-LLM | FAIL_CLOSED | `INTR_PATH_DESTINATION_INGRESS_NOT_ON_MAIN` / `DESTINATION_HAS_INTR_PATH_INGRESS`; retry a Lane B port draft to the destination |

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

A non-ALLOW carries the verifier's six fields and, beside them, the kit's known repairs (`kit_blockers`). With `--require-genesis-allow`, the run exits 1 unless both `GENESIS_READY` paths are ALLOW.

Before genesis (today's ledgers) the replay gives ALLOW 0, DENY 0, FAIL_CLOSED 56, and every path is E0-terminal.

Rehearsal on scratch copies (not ledgered, not authentic):
- `consume` was run on a scratch copy of each ledger, Labs (from this checkout, row org→Labs) and org (from org#224, row Labs→org).
- The replay then gave ALLOW 2 / FAIL_CLOSED 54, with `payload_matches_sealed: true` and `end-to-end-via-tvc` ALLOW for both paths.
- The appended evidence equalled `evidence_at_observed_source_tip` exactly.
