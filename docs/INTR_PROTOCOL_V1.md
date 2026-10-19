# InTr protocol v1 — canonical contract

`data/intr-protocol/v1/protocol.json` is the single versioned contract for InTr
across the eight organization `.github` destinations. It fixes:

- **message** (`stegverse.intr-message/v1`): `message_class` = `ecosystem.communication`,
  a printable `communication_id`, and `body.schema` equal to the destination payload schema.
- **route** (`stegverse.intr-route/v1`): the destination address is
  `organization_slug(org) + ".intr-destination"` (kernel derivation), over `INTERLOCK_INTR`,
  with no host, URL or GitHub-token authority; credentials are TV/TVC.
- **destination capability** (`stegverse.intr-destination-capability/v1`): the predicates an
  organization's `org-runtime/interlock-intr.json` and `org-boundary/registry/services.json`
  must satisfy.

`org-runtime/intr_protocol.py` checks those offline (no clock, network, environment or ledger):

    python org-runtime/intr_protocol.py conform --org <ORG> --interlock <file> --services <file>
    python org-runtime/intr_protocol.py mesh --manifest tests/fixtures/intr-protocol/destinations/manifest.json

Results are `ALLOW`, `DENY` (observed value differs) or `FAIL_CLOSED` (document, field or version
unobserved). Every non-ALLOW result carries `failure_code`, `failed_predicate`,
`required_evidence_or_repair`, `retry_entrypoint`, `owning_existing_goal`, `next_attempt`.

The mesh snapshot under `tests/fixtures/intr-protocol/destinations/` is byte copies of each
organization's default-branch documents at the `source_commit` recorded in `manifest.json`,
with sha256 per file; altered bytes fail closed. It is conformance evidence only, not an
authentic receipt and not proof that a live peer serves the capability.

Snapshot result: 8 ALLOW. The SV-011 row pins the head of SV-011/.github#14 (merged as
`d7beaf59`), which declares `authority_effect: NONE_BINDING_ONLY` on its `intr-destination` binding.

## Main-merge transfer (`MAIN_MERGE_TRANSFER_RECEIPT_LEDGERED`)

`main_merge_transfer` in the contract adds one destination predicate, reported as a separate
`merge_transfer` dimension that never changes destination conformance:

- **predicate** `MAIN_MERGE_TRANSFER_RECEIPT_LEDGERED`, operation `ORGANIZATION_MAIN_MERGE_TRANSFER`,
  evidence `stegverse.main-merge-transfer-evidence/v1`, checked by
  `resident-runtime/merge_transfer.py verify`.
- **VERIFIED / ALLOW** only when a sealed organization receipt (`receipt_sha256` is the digest of
  its other fields) has `boundary_evidence` naming the operation, the repository and the merge
  commit, and its `repo_receipt_sha256` is the seal of a sealed repository receipt whose evidence
  carries the same `merge_commit` and `repository` on `refs/heads/main` with the `payload_sha256` it claims.
- **FAIL_CLOSED `MERGE_TRANSFER_RECEIPT_NOT_LEDGERED`** (failed predicate
  `MAIN_MERGE_HAS_AN_ORGANIZATION_LEDGER_RECEIPT`) when the evidence is absent or unsealed: no
  organization receipt, an unsealed organization or repository receipt, or an organization receipt
  whose `boundary_evidence` is not this merge's transfer (another operation, merge or repository;
  `merge_transfer.py` skips such receipts on the chain).
- **DENY `MERGE_TRANSFER_RECEIPT_LINK_UNVERIFIED`** (failed predicate
  `ORGANIZATION_RECEIPT_LINKS_TO_THE_MERGE_COMMIT`) when present, sealed evidence contradicts the
  merge: the organization receipt names another repository or links a different repository receipt,
  or the repository receipt evidence names another schema, merge commit, repository or ref, or does
  not carry the digest it claims. `detail` lists every contradiction.
- **FAIL_CLOSED `MERGE_TRANSFER_SUBJECT_UNOBSERVED`** (`READBACK_NAMES_THE_MERGE`) when the readback
  does not name a repository and a 40-hex merge commit; this is the readback's own precondition
  (the verifier's CLI reads the commit object instead).
- Every refusal also carries `destination_predicate: MAIN_MERGE_TRANSFER_RECEIPT_LEDGERED`.
- `retry_entrypoint` is `.github/workflows/organization-ledger-merge-transfer.yml (push to main)`.

`org-runtime/intr_protocol.py` checks a supplied readback
(`stegverse.intr-main-merge-transfer-readback/v1`) offline; it reads no ledger, git, clock or network:

    python org-runtime/intr_protocol.py merge-transfer --readback <readback.json>
    python org-runtime/intr_protocol.py mesh --manifest tests/fixtures/intr-protocol/destinations/manifest.json \
        --merge-transfer tests/fixtures/intr-protocol/merge-transfer/manifest.json

`merge_transfer.py` landed in both organizations byte-identical, sha256 `032ed727...e20e`:
StegVerse-org/.github#202 (head `b590fb0a`, merge `41035e9e`) and SV-011/.github#15 (head `8c02f276`,
merge `a636fafc`; not the earlier pinned head `2e74ecb3`, but the file is unchanged between them).
`main_merge_transfer.verifier.landed_at` pins each organization's digest separately. The conformance
test checks that the file on this main agrees with the contract's names and equals this
organization's pin.

State before the first append (`readbacks-before-append.json`): StegVerse-org `f160ac7d` (tip
`2acec0e1`) and SV-011 `d7beaf59` (tip `2cc58cec`) were both `MERGE_TRANSFER_RECEIPT_NOT_LEDGERED`.

Current state (`tests/fixtures/intr-protocol/merge-transfer/manifest.json`): `merge_transfer`
4 ALLOW / 0 DENY / 1 FAIL_CLOSED, read back from the ledger refs at StegVerse-org tip `824e0b76` and
SV-011 tip `6594bafc`. The first merge-transfer push runs (StegVerse-org run 39184244707 on push
`41035e9e`, SV-011 run 39184321363 on push `a636fafc`) backfilled `f160ac7d` and `d7beaf59` from
`.stegverse/merge-transfer/pending.json` and appended `41035e9e` and `a636fafc`; all four are VERIFIED.
`f40ad7dd` (merge of #203) landed before the workflow existed and is not listed as pending, so it is
`MERGE_TRANSFER_RECEIPT_NOT_LEDGERED`; a push alone does not append it, it must be listed in
`.stegverse/merge-transfer/pending.json`. The snapshot is conformance evidence copied from the ledger
ref, not a claim of authentic receipts.

The ALLOW refusal tests use the receipts #202 and SV-011#15 computed over a temporary copy of each
ledger tip (`expected-receipts.json`); the receipts later appended for `f160ac7d` and `d7beaf59` are
equal to them by value.
