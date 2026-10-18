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

Snapshot result: 7 ALLOW, 1 FAIL_CLOSED — SV-011's `intr-destination` binding does not declare
`authority_effect` (`BINDING_AUTHORITY_EFFECT_IS_NONE`).
