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
| destination | the destination ledger's sealed `ORGANIZATION_INTR_DESTINATION_INGRESS` receipt for the same communication_id, linked to its repository receipt | FAIL_CLOSED `INTR_PATH_DESTINATION_RECEIPT_UNOBSERVED` (class B) | DENY `INTR_PATH_DESTINATION_RECEIPT_CONTRADICTED` |

A path is ALLOW (VERIFIED) only when both halves verify. Every non-ALLOW carries the six fields.

**Class B.** The destination half needs (1) a carrier that delivers the message to the destination's ingress, so
the destination appends its own receipt, and (2) a TV/TVC-issued least-privilege read credential for the
destination's ledger ref (the repositories are internal). Neither exists, and none is worked around here. Paths
whose source is another organization also need this transition installed in that organization's `.github`.

**Real state** (`tests/fixtures/intr-path-transfer/expected-real-state.json`, ledger tip `0db6e0bd`): 56/56
FAIL_CLOSED `INTR_PATH_RECEIPT_NOT_LEDGERED`. No path receipt exists yet. Path receipts appear only once this
transition lands on main. After that, the 7 paths from StegVerse-org verify their source half, and every path
stays FAIL_CLOSED at the destination half (`INTR_PATH_DESTINATION_RECEIPT_UNOBSERVED`, class B). Receipts in
the tests and the PR dry-run are written to temporary directories or a scratch ref. They are not ledgered and
not authentic.
