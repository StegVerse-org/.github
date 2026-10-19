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

## Ledger binding per organization (`resident-runtime/intr_path_ledger.py`)

The path transfer and the path ingress reach their organization's ledger through one adapter. The adapter is selected by `data/intr-protocol/v1/protocol.json` → `main_merge_transfer.verifiers_by_organization`.

**Organizations not listed** (StegVerse-org, SV-011, StegGhost, SV-LLM and the rest) use `MERGE_TRANSFER_PY`: `resident-runtime/merge_transfer.py` (032ed727) for readers, the transfer verdict and the head epoch, and `intr_destination_ingress.py::_append` for appends. This is unchanged; the same tests pass.

**StegVerse-Labs and GCAT-BCAT-Engine** use `MERGE_TRANSFER_GITSTORE`: Lane D's `resident-runtime/ledger_gitstore.py` (`pin.ledger_module`, sha256 `258e1cf5…`) over `resident-runtime/merge_transfer_gitstore.py` (`pin.path`, sha256 `bf9f1c15…`).
Each append, the path receipts' and the main-merge transfer's (`ledger_gitstore.append_merge_transfer`), is all or nothing. A two-level preflight resolves both halves' locations before either is written (FAIL_CLOSED `LEDGER_TWO_LEVEL_PREFLIGHT_REFUSED`), and a failed append is rolled back by compare-and-swap (FAIL_CLOSED `LEDGER_TWO_LEVEL_ROLLBACK_FAILED` when a ref cannot be restored). Both reach the path results with their six fields.
- Each file is loaded only at its pinned digest. Otherwise the result is FAIL_CLOSED `INTR_PATH_LEDGER_VERIFIER_DIGEST_UNPINNED`.
- The binding provides the readers (`org_store` / `repo_store`, re-built after every append), `verify_merge_transfer` in `pin.mode` (dual), `head_epoch`, `org_chain`, and `append(transition_class, packet_id, evidence, hb_epoch, *, operation, profile_id, boundary_extra, root)`. The append goes through the organization's own writer surface: `AGGREGATE_TRANSITION` for Labs, `DUAL_LEDGER` for GCAT.
- The path transfer verifies the transfer commit first. It then writes that transfer's `organization_receipt_sha256` into the path evidence (`merge_transfer_organization_receipt_sha256`).
- A checkout that carries the verifier but not the ledger module still reads and verifies. Every append there is FAIL_CLOSED `INTR_PATH_GITSTORE_WRITER_UNBOUND`, and nothing is written.

The operations are the same in every organization:
- source half: `INTR_MESH_PATH_TRANSFER` / `intr-mesh-path-transfer`
- destination half: `ORGANIZATION_INTR_DESTINATION_INGRESS` / `intr-destination`

`ledger_gitstore.append` accepts any operation, so no organization-specific names are needed.

**Tests:**
- `tests/test_intr_path_ledger.py` runs the real `ledger_gitstore.append` from pinned byte copies (`tests/fixtures/intr-path-ledger/gitstore-checkout/`). It runs on this organization's own writer surface, over temporary POSIX and bare-git ledgers at the pinned tip.
  - All 7 source-half appends are ALLOW, each linked to the verified transfer.
  - A replay writes nothing.
  - The retained `source-receipts/` copy equals the repository receipt.
  - The real state is unchanged when read through the git-store readers.
- `tests/intr_path_temp_ledger.py` builds the temporary ledger the way the bound backend reads it: a directory, or a bare git repository on the declared ref with a fixed git identity and date.
- `python3 resident-runtime/intr_path_ledger.py which` names the binding. `append-merge-transfer --commit <c>` appends through it; the dry-run job uses this for `temp_merge_transfers`.
