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

The snapshot covers all 16 organizations of the federation directory
(`org-boundary/registry/federation.json`, generation 3, denominator 16; the StegVerse-Labs copy and
the StegVerse account's organization memberships list the same 16). One disagreement: the directory
lists SV-011 as `SV-011/entity` (`sv-011.boundary-diagnostic`), while this snapshot checks
`SV-011/.github`, which serves `sv-011.intr-destination`.

Snapshot result: 8 ALLOW, 8 FAIL_CLOSED. AaCT-E, Data-Continuation, ECAT-ICAT-Formal,
Infrastructure-Continuity-Ventures, Triad-Test, formalism-tests and the records organization fail closed at
`PEER_ADDRESS_FORM_IS_SLUG_DOT_PROFILE`, and AdmittedCode at `INTERLOCK_DOCUMENT_IS_AN_OBJECT` (no
`org-runtime/interlock-intr.json`). Each row records `observed_gaps`: none of the eight declares an
`intr-destination` binding or serves the address, and none installs the receiving operation
(`resident-runtime/intr_destination_ingress.py`) or the ledger. This is class B (missing capability).
A destination entry alone would declare a receiver that does not exist, so no per-organization
entry drafts are opened. The repair is installing the capability, as StegGhost/.github `cffd741`
and `03d8b94` did.

Original eight: The SV-011 row pins the head of SV-011/.github#14 (merged as
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

### Git-store verifier for StegVerse-Labs and GCAT-BCAT-Engine

`merge_transfer.py` (032ed727) fails in two organizations before it reads a receipt
(`MERGE_TRANSFER_VERIFIER_STORE_INCOMPATIBLE`):

- StegVerse-Labs declares its organization ledger as `{store: git}`.
- GCAT-BCAT-Engine appends through `resident-runtime/dual_ledger.py` and has no `repository_ledger`.

`main_merge_transfer.verifiers_by_organization` pins both to Lane D's
`resident-runtime/merge_transfer_gitstore.py verify`, mode `dual`.

- **Digest:** sha256 `bf9f1c15420b1c9c8e21655fe176d6b009e190357e09e433bac170bf09247176`.
- **Where:** byte-identical at the three open draft heads: StegVerse-org/.github#211 `5f5f3669`, StegVerse-Labs/.github#3292 `e3a0f506` and GCAT-BCAT-Engine/.github#16 `f0d55e81`. The pins say `landed: false`; re-pin them to the merge commits when those land.
- **Other organizations:** every other organization stays on `merge_transfer.py`, single read (`verifier_rule`).

Dual mode reads both copies of the linked repository receipt: the one in the repository chain, and the one the organization ledger retained under `source-receipts/`.

- When both copies are the same receipt, the predicate is checked as before.
- When they are not, the result is FAIL_CLOSED `MERGE_TRANSFER_DUAL_LEDGER_DIVERGENCE` (evidence predicate `REPOSITORY_AND_ORGANIZATION_LEDGERS_HOLD_ONE_RECEIPT`). That code is now in the predicate's `fail_closed_failure_codes`.

For these organizations the offline readback carries `retained_repository_receipt`. Single-read organizations are not held to it. SV-011's published ledger retains no `source-receipts/` copy at all, so dual mode would refuse it, and it stays on `merge_transfer.py`.

**Side by side** (`tests/test_intr_protocol_conformance_merge_transfer_gitstore.py`):

- The test runs the verifier from a sha-pinned byte copy (`tests/fixtures/intr-protocol/merge-transfer-gitstore/merge_transfer_gitstore.py`). Once #211 lands, the landed file must be the same bytes.
- It lays every case out in the ledger layout in a temporary directory.
- It requires the same disposition, failure_code and failed_predicate from both checks, in dual and in single mode.
- The ALLOW receipts (`expected-receipts.json`, NOT_LEDGERED_NOT_AUTHENTIC) were appended by that verifier to temporary bare copies of the published tips. StegVerse-Labs used writer surface `AGGREGATE_TRANSITION`, GCAT-BCAT-Engine `DUAL_LEDGER`.

**Real state** (`manifest.json`): the published ledgers hold no main-merge transfer receipt at these tips, the same tips and verdicts Lane D pinned.

- StegVerse-Labs `978b8880` at tip `a5bb54d8`: FAIL_CLOSED `MERGE_TRANSFER_RECEIPT_NOT_LEDGERED`.
- GCAT-BCAT-Engine `c3cf1b1a` at tip `ba0098da`: FAIL_CLOSED `MERGE_TRANSFER_RECEIPT_NOT_LEDGERED`.

**Not repaired here:** StegVerse-Labs' organization writer stamps a clock `observed_at` on organization receipts (`resident-runtime/aggregate_repo_transition.py:1083`). The verifier does not read it, and a test shows that changing it and resealing still verifies. This is tracked in StegVerse-Labs/.github#3263 and #3290.
