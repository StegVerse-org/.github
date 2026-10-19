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

`merge_transfer.py` is not on main yet. The contract pins it by sha256
(`032ed727...e20e`, byte-identical at StegVerse-org/.github#202 head `b590fb0a` and SV-011/.github#15
head `2e74ecb3`), so admission of this predicate depends on #202 (and SV-011#15 for SV-011). Once the
file is on main, the conformance test checks that its names agree with the contract and its digest
equals the pin.

Current state (`tests/fixtures/intr-protocol/merge-transfer/manifest.json`): `merge_transfer`
0 ALLOW / 0 DENY / 2 FAIL_CLOSED. StegVerse-org merge `f160ac7d` (ledger tip `2acec0e1`) and SV-011
merge `d7beaf59` (ledger tip `2cc58cec`) have no ledgered transfer receipt, so both are
`MERGE_TRANSFER_RECEIPT_NOT_LEDGERED` until the merge-transfer append runs. The ALLOW tests use the
receipts #202 and SV-011#15 compute over a temporary copy of each ledger tip
(`expected-receipts.json`); those are not ledgered and are not authentic receipts.
