# Lane B anonymous InTr reads (lane-b-91117956, StegVerse-org/.github#162)

SKAP invariant: the SKAP Vault inside KV is the only PII and credential store for every user, the ecosystem's own
included. These reads need and hold none: anonymous https only (no credential helper, no token, no TVC receipt).

- `read_org.sh <org>`: re-runnable, about 2 s per org. Checks the anonymous visibility of all 16 org `.github` repos, fetches
  `refs/stegverse/organization-ledger` without credentials into the local mirror, reads the org's InTr destination
  (federation row, protocol.json manifest entry, the org's own .github documents), verifies every InTr receipt
  (seal over canonical bytes, stored bytes, HEAD chain, repository receipt), and runs
  `resident-runtime/intr_path_ingress.py verify_end_to_end` (StegVerse-org main) for every declared path with the org
  as an endpoint. Never writes a ledger ref; never dispatches.
- `read_org.py`: the clock-free, network-free evaluator.
- `out/<org>.json`: one result per org. A non-ALLOW result carries the six fields.
