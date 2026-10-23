# InTr mesh path transfer v1

`resident-runtime/intr_path_transfer.py` checks every declared InTr mesh path by running a real transfer
transition on main and reading back the path's own sealed receipt.

**Declared paths.** Every ordered pair of distinct organizations whose destination documents conform to
`data/intr-protocol/v1/protocol.json` in the pinned mesh snapshot, for the one declared capability,
`intr-destination`. With 8 conformant organizations that is 56 paths (`<SOURCE>-><DESTINATION>:intr-destination`).

**Transition.** A row of `.stegverse/intr-path-transfer/transfers.json` (one per path from this organization)
lands on main. The push's main-merge transfer is ledgered by `organization-ledger-merge-transfer.yml`, and then
`.github/workflows/intr-path-transfer.yml` runs (`workflow_run` on that workflow's completion for a push; no
dispatch, schedule or cross-organization call). For each row not yet ledgered it appends one repository receipt
and one organization receipt (operation `INTR_MESH_PATH_TRANSFER`) through the existing two-level append, at the
ledger head's supplied epoch. The repository receipt's evidence (`stegverse.intr-path-transfer-evidence/v1`)
carries the protocol-conformant InTr message, the derived destination address, the transfer commit, and the seal
of that commit's main-merge transfer organization receipt. A ledgered row is answered from the ledger.

**Verification** (`python resident-runtime/intr_path_transfer.py verify`), two halves:

| half | ALLOW when | absent / unsealed | contradicted |
|---|---|---|---|
| source | sealed path organization receipt, linked to its sealed repository receipt, linked to the transfer commit's sealed main-merge transfer receipt | FAIL_CLOSED `INTR_PATH_RECEIPT_NOT_LEDGERED` | DENY `INTR_PATH_RECEIPT_LINK_UNVERIFIED` |
| destination | the destination ledger's sealed `ORGANIZATION_INTR_DESTINATION_INGRESS` receipt for the same path_id and communication_id, linked to its repository receipt, both carrying the source organization and repository receipt seals, read back from the destination ledger | FAIL_CLOSED `INTR_PATH_CROSS_ORG_READ_CREDENTIAL_NOT_ISSUED` (no verified TVC read receipt; class A) or `INTR_PATH_DESTINATION_RECEIPT_NOT_LEDGERED` | DENY `INTR_PATH_DESTINATION_RECEIPT_LINK_UNVERIFIED` |

A path is ALLOW (VERIFIED) only when both halves verify. Every non-ALLOW carries the six fields.

**Destination carrier** (`resident-runtime/intr_path_ingress.py`). The destination organization's `.github`
carries `.stegverse/intr-path-transfer/inbound.json` (`stegverse.intr-path-inbound/v1`): per row, the path_id,
the communication_id and copies of the source's sealed organization and repository path receipts. When a row
lands on the destination's main, `.github/workflows/intr-path-ingress.yml` runs after that push's main-merge
transfer is ledgered (workflow_run, no dispatch). It checks the carried pair (sealed, linked, naming this path,
this destination and its kernel-derived address, a message the destination ingress accepts), then appends
through `resident-runtime/intr_destination_ingress.py` `_append` its own `ORGANIZATION_INTR_DESTINATION_INGRESS`
receipt (`stegverse.intr-path-ingress-evidence/v1`, transition class `INTR_MESH_PATH_INGRESS`) whose
boundary_evidence and repository evidence carry both source seals. A ledgered row is answered from the ledger.

| check | refusal |
|---|---|
| carried pair absent or unsealed | FAIL_CLOSED `INTR_PATH_SOURCE_RECEIPT_NOT_CARRIED` (nothing appended) |
| carried pair names another path, destination, address or message, or the receipts do not link | DENY `INTR_PATH_CARRIED_RECEIPT_CONTRADICTED` (nothing appended) |
| carried pair's inclusion in the source ledger | FAIL_CLOSED `INTR_PATH_CROSS_ORG_READ_CREDENTIAL_NOT_ISSUED`, recorded in the evidence as `source_inclusion` |

**End to end** (`python resident-runtime/intr_path_ingress.py end-to-end --source-readback S --destination-readback D`)
takes a readback of each ledger (`stegverse.intr-path-ledger-readback/v1`: tip, head seal, chain, the pair). It is
ALLOW only when the source pair is sealed and included in the source chain, the destination pair is sealed and
included in the destination chain, and the destination pair carries the source seals. Without either readback it
is FAIL_CLOSED `INTR_PATH_CROSS_ORG_READ_CREDENTIAL_NOT_ISSUED` (six fields; retry at the TV/TVC issuance
transition StegVerse-Labs/TVC `TVC-PRIVATE-SOURCE-READ-001`, consumer `INTR-PATH-LEDGER-READBACK-001`, TVC#528;
owning goal `TVC-PRIVATE-SOURCE-READ-001`).

**Through TV/TVC** (`python resident-runtime/intr_path_ingress.py end-to-end-via-tvc --path-id P --communication-id C`)
reads this organization's half from its own ledger and the other organization's half from its TVC read receipt
(`stegverse.tvc-intr-path-ledger-read-receipt/v1`, landed byte for byte at
`.stegverse/intr-path-transfer/tvc-read-receipts/<SOURCE>--<DESTINATION>.<purpose>.json`;
`resident-runtime/intr_path_tvc_read.py`). The receipt verifies only when its digests recompute, it names this
scope (path, purpose, reader organization, the other organization's `.github`, `refs/stegverse/organization-ledger`,
`contents:read`), authorized = observed = requested tip = the readback's tip, the head epoch is supplied (int >= 32),
the read-only flags are false and its evidence class is `TVC_RESIDENT_EXECUTION`. A contradicted receipt is DENY
`INTR_PATH_TVC_READ_RECEIPT_CONTRADICTED`; a fixture outside the tests is FAIL_CLOSED
`INTR_PATH_TVC_READ_RECEIPT_NOT_RESIDENT`. On ingress, a verified `source_inclusion` receipt is recorded in the
ingress evidence (`source_inclusion.state: VERIFIED_BY_TVC_READ_RECEIPT`, with the source ledger tip). No bot holds a
credential; no classic PAT or FEDERATION_* token is used.

**Class B.** In CI the other organization's ledger is not readable: `GITHUB_TOKEN` is scoped to the repository and
the repositories are internal. No token is minted and no `FEDERATION_*` token is used. Paths whose source is
another organization also need this transition installed in that organization's `.github`.

**Real state** (`tests/fixtures/intr-path-transfer/expected-real-state.json`, ledger tip `0db6e0bd`): 56/56
FAIL_CLOSED `INTR_PATH_RECEIPT_NOT_LEDGERED`. No path receipt exists yet. Path receipts appear only once this
transition lands on main. After that, the 7 paths from StegVerse-org verify their source half, and every path
stays FAIL_CLOSED at the destination half (`INTR_PATH_CROSS_ORG_READ_CREDENTIAL_NOT_ISSUED`, class A, retry at TVC) until its TVC read receipt is landed. Receipts in
the tests and the PR dry-run are written to temporary directories or a scratch ref. They are not ledgered and
not authentic.

## Typed bodies (INTR-PATH-TRANSFER-TYPED-BODY-001, #162)

A declaration row that carries `typed_body` is a **typed transfer**. Instead of the fixed
`{schema, path_id, transfer_commit}` body, its message body is the typed body. The row is checked in this order,
and every refusal carries six fields. Nothing is written for a refused row.

1. `endpoint_kind` must be one of `EPHEMERAL, PERMANENT, GATEWAY, KV, SKAP_VAULT, ORG` (StegVerse-org/LLM-adapter#432
   `schemas/endpoint-kind.v1.json`). Otherwise the row fails closed with `INTR_PATH_ENDPOINT_KIND_UNDECLARED`.
2. An `endpoint_kind: GATEWAY` row must not carry an external ledger ref. That means no `ledger_root`,
   `external_ledger_ref`, `external_ledger`, `external_chain`, `imported_chain` or `source_ledger_root` key anywhere
   in the row, and a `destination_location` inside `refs/stegverse/organization-ledger` (no `#`, no URL, no `..`).
   Otherwise the row is denied with `INTR_PATH_GATEWAY_CARRIES_EXTERNAL_LEDGER_REF`.
3. The row must have exactly `path_id, communication_id, destination_location, endpoint_kind, typed_body,
   typed_body_sha256`.
4. `typed_body.schema` must be on the allowlist `TYPED_BODY_SCHEMAS`. The allowlist currently holds only
   `stegverse.repository-ledger-genesis-pointer/v1` (`REPOSITORY_LEDGER_GENESIS_OBSERVED`). Any other schema fails
   closed with `INTR_PATH_TYPED_BODY_SCHEMA_NOT_ALLOWLISTED`.
5. The body is sealed: `typed_body_sha256` must equal the body's digest. Otherwise the row is denied with
   `INTR_PATH_TYPED_BODY_UNSEALED`.
6. The body must be exactly the pointer StegVerse-org/LLM-adapter#431's pre-pin receiver
   (`scripts/llm_adapter_genesis_pin_ingress.py`) accepts: `{schema, ledger_location, genesis_receipt_sha256}`. It
   points at the genesis on the recorded receipt chain and copies no record (StegVerse-org/.github#167 comment
   6372442705). In addition:
   - `ledger_location` points at another repository of this organization;
   - `ledger_location` and `destination_location` are that repository's `repository-ledger/` location;
   - `endpoint_kind` is `ORG`;
   - `path_id` is `StegVerse-org/.github->StegVerse-org:intr-destination`.

   A row that breaks any of these fails closed with `INTR_PATH_TYPED_BODY_NONCONFORMANT`.
7. The path must be a declared intra-org repository-destination path. It is a data row of the existing path
   schema in `data/intr-protocol/v1/protocol.json` `mesh_path_transfer.intra_org_paths`, with `path_id`, `source`,
   `destination` and `capability` as in the `declared_paths` rows, plus the `endpoint_kinds`, `typed_body_schemas`
   and `destination_location_prefix` the path admits. The one row is
   `StegVerse-org/.github->StegVerse-org:intr-destination` (`ORG`, the genesis-pointer schema,
   `refs/stegverse/organization-ledger:repository-ledger/StegVerse-org/`). Otherwise the row fails closed with
   `INTR_PATH_INTRA_ORG_PATH_UNDECLARED`. The mesh `declared_paths` are unchanged. Adding `intra_org_paths` and
   `endpoint_paths` changes the code-defined declared-paths definition, so it is recorded as a class C entry on
   StegVerse-org/.github#167.
8. The envelope keeps every protocol predicate. Only the body-schema predicate is replaced by the allowlist.

The typed evidence is `stegverse.intr-path-transfer-evidence/v1` in the source shape of `intr_transport_carrier`
(LLM-adapter#431/#432/#433):
- `destination_location`, `endpoint_kind`, `typed_body_schema` and `typed_body_sha256` are added to the core;
- `payload_sha256` is computed over the core and excludes `boundary_evidence`;
- `boundary_evidence.operation` is `INTR_MESH_PATH_TRANSFER`.

`typed-row --repository <repo> --genesis-receipt <sha256>` prints the row, which lands on main as its own transition
once the genesis is receipted. No typed row is declared by this change.

**Trigger (reuse first).** A repository's genesis is appended in this repository, by
`.github/workflows/organization-ledger-transition.yml` (a committed `.stegverse/transition-requests/` request, under
`ORGANIZATION_LEDGER_LOCK`). That run reads the published ref back with `organization_ledger_readback.py
--repository-namespace ... --out readback.json`. `typed-row --from-readback readback.json`
(`genesis_observed_row_from_readback`) derives the typed row from that read-back only. The read-back's first chain
receipt must be the `REPOSITORY_LEDGER_INITIALIZATION` genesis, and every receipt must verify and be retained.
Otherwise the result is a six-field `FAIL_CLOSED` `INTR_PATH_GENESIS_NOT_READ_BACK` and nothing is emitted. When the
row lands in `transfers.json` on main, the existing `intr-path-transfer.yml` fires on it (`workflow_run` after the
main-merge transfer). No workflow is added or changed.

**Backward compatible.** Rows without the typed keys take the untyped code, which is unchanged. Its output for the
existing fixtures is byte-identical to main @907f4305 (`tests/fixtures/intr-path-transfer/untyped-golden.json`), and
`real_state` gains `typed_transfers` only when a typed row is declared.

**Cross-repo fixture.** `tests/fixtures/intr-path-transfer/typed-genesis-observed.json` is the
writer's output on a temporary copy of the pinned tip, for one typed row naming a synthetic genesis. The synthetic
genesis is byte-deterministic (emit.py's receipt body at supplied epoch 446655631, `observed_at`
`SUPPLIED_HB_EPOCH:446655631`, no clock), so the fixture regenerates byte-identically. It is not
ledgered and not authentic. It is copied byte-identically to LLM-adapter#431, where `receive()` accepts it as
`ACCEPTED_FOR_GENESIS_PIN`.

### Independent endpoints and the endpoint head digest (KV independence; StegVerse-org/.github#160 comment 6372216673)

KV and SKAP Vault are independent of the Orgs. Each runs its own ledger behind its own InTr ingress/egress endpoint, and that ledger is never stored on `refs/stegverse/organization-ledger`. Two things change here:

- **Endpoint paths.** `mesh_path_transfer.endpoint_paths` is a list of data rows in the `intra_org_paths` path schema, with `destination_endpoint` in place of `destination`. It is empty for now, and each row lands through its own admitted change. The typed gate looks up `intra_org_paths` first, then `endpoint_paths`.
- **Endpoint head digest.** A typed row can carry an optional `endpoint_head_sha256`. For KV and SKAP_VAULT it is the `KV_RECORDED_RECEIPT_CHAIN_HEAD` digest only (StegVerse-Labs/TVC#542 @4c2504da; the chains are STEGVERSE_KV `_StegVerse/Receipts` and `_Vault/SKAP/Receipts`, on no org ref, StegVerse-Labs/continuity-vault-kit#263 @706877b6; path_id `StegVerse-org->STEGVERSE_KV:<location>:intr-destination`). It rides in `boundary_evidence` (reused; no new envelope field), in both the typed evidence and the Org receipt's boundary, so the Org-side linked receipt records the endpoint's ledger head. It is required when `endpoint_kind` is KV or SKAP_VAULT; a missing digest fails closed with `INTR_PATH_ENDPOINT_HEAD_DIGEST_MISSING`, with six fields. The value is a `sha256:` digest and never a ledger ref; anything else is denied with `INTR_PATH_ENDPOINT_HEAD_NOT_A_DIGEST`. Rows without the field produce byte-identical evidence.
- **Rollback watermark.** KV uses the newest recorded digest as its rollback watermark. A presented head older than that watermark is refused with `KV_LEDGER_HEAD_ROLLBACK_DETECTED` (StegVerse-org/LLM-adapter#431, `llm_adapter/endpoint_ledger_designation.py`).

### Both sides record each crossing (StegVerse-org/.github#162 comment 6372641743)

A crossing is two events, one recorded at each endpoint. The source records its egress (`INTR_MESH_PATH_TRANSFER`, the
typed source half above) and the destination records its ingress (`INTR_MESH_PATH_INGRESS` on its own recorded receipt
chain, `stegverse.intr-path-ingress-evidence/v1`). Each record points at the other by digest or location: the ingress
names the egress's `receipt_sha256` (`source_repository_receipt_sha256`), its `destination_location`
(`addressed_location`), `path_id` and `communication_id`. Neither copies the other's body. Both carry a supplied
heartbeat epoch (`hb_reference.derived_from_clock` false; `observed_at`, when present, `SUPPLIED_HB_EPOCH:<epoch>`).
`verify_typed_crossing(row, destination_receipt)` refuses a one-sided crossing with six fields
(`INTR_CROSSING_NOT_RECORDED_BY_BOTH_SIDES`, `one_sided` SOURCE_ONLY / DESTINATION_ONLY / NEITHER), records that do not
point at each other with DENY, and a record without a supplied epoch with `HB_EPOCH_NOT_SUPPLIED` / `HB_EPOCH_INVALID`.
The Org's own append and read-back of the genesis crossing (ENVELOPE v2 line 55) stands as the Org's record.

## No endpoint is a source of org-ledger records

No endpoint, whether externally or ecosystem maintained (KV, SKAP Vault, node or gateway), is a GitHub Organization member or a source of org-ledger records (Rigel, relayed on StegVerse-org/.github#160 comment 6372871021). A typed row lands its record inside `refs/stegverse/organization-ledger`, so only `endpoint_kind` ORG may name one. Any other kind is six-field FAIL_CLOSED `INTR_PATH_ENDPOINT_NOT_AN_ORG_LEDGER_SOURCE` (failed_predicate `NO_ENDPOINT_IS_AN_ORG_MEMBER_OR_A_SOURCE_OF_ORG_LEDGER_RECORDS`) and nothing is written. Endpoint data crosses only through InTr to the endpoint's own recorded receipt chain and is recorded at both ends. The Org side is this organization's own digest-only crossing receipt (pointer/digest plus `SUPPLIED_HB_EPOCH`). An endpoint destination (`endpoint_paths`, the endpoint's own `ledger_location`, and the gateway's owning-endpoint designation from LC-KV-20) is a change to the code-defined path definition, so it is class C on StegVerse-org/.github#167 and is not built here.
