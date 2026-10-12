# Governed DENY remediation return — organization preflight (2026-10-12)

**Implementation state: source-only preflight, not authenticated governance admission.**

The existing canonical specification [Node ingress: settled specification](NODE_INGRESS_SETTLED_SPECIFICATION.md) §8 defines a parallel remediation-manifest fork: the original packet continues to its declared destination while a remediation packet proceeds to StegHealer. Each lane has its own receipts; `REMEDIATION_CLASSIFIED` is minted into the judged chain. §9 requires verified end-to-end ingress before activation of the remediation lane.

The intended return path is SDK DENY → source-bound StegHealer classification → organization-governed authorization → SDK RESUBMIT or RE-MANIFEST → independently governed disposition. This return must not rewrite the original packet's disposition, substitute a destination, or treat a source-level SDK handoff as InTr admission.

`resident-runtime/governed_remediation_return_preflight.py` implements a **non-authorizing** inspection of the existing Healer classification envelope. It rejects source/request substitution, preapproved classifications, unrecognized actions and an unclassified RE-MANIFEST. Its successful preflight result is still `FAIL_CLOSED` with `AUTHENTIC_GOVERNED_RETURN_AND_SOVEREIGN_LEDGER_READBACK` outstanding. It does not mint receipts, verify cryptographic authority, contact an ingress, or create a return to SDK. Unit tests are in `tests/test_governed_remediation_return_preflight.py`.

**Required before closure:** reconcile canonical Task Registry/COSV and historical PR evidence; implement the parallel remediation packet and immutable receipt fork; verify the Healer source classification against actual SDK DENY; authenticate the organization decision/return through the authorized ingress and ledger readback; bind SDK return to original request, wire manifest and source disposition; test RESUBMIT, RE-MANIFEST, rejection and terminal FAIL_CLOSED end to end; validate exact-head checks and merge with expected-head protection.

Related: [StegVerse-org/.github #98](https://github.com/StegVerse-org/.github/issues/98), [SDK #489](https://github.com/StegVerse-org/StegVerse-SDK/pull/489), [Healer #110](https://github.com/StegVerse-Labs/StegVerse-Healer/pull/110), [Labs #2682](https://github.com/StegVerse-Labs/.github/issues/2682).

## Existing merged implementations — reuse, do not replace

- SDK merged PR #478 introduced `stegverse/remediation_return.py::validate_remediation_return`, checking the manifest-selected proposal, route/capability, evaluator identity, receipt continuity and readback binding.
- SDK merged PR #479 repaired its self-asserted readback flaw by requiring `organization_ledger_readback` and invoking `organization_ledger_evidence.verify_organization_ledger_readback`. The SDK still does not independently fetch the ledger or authenticate a runtime crossing.
- Healer merged PR #109 introduced `app/manifest_remediation_intake.py::ingest_manifest_remediation`, a non-authorizing manifest-selected intake. New Healer PR #110 extends it with SDK profile-DENY classification; it must not become a second scheduler or admission authority.
- Labs canonical merged PR #2717 reconciled Experiment 3 DENY provenance, but did not prove live InTr or ledger custody.

The new organization preflight in this PR is **not** a replacement for the merged SDK validator or Healer intake. The missing work is authenticated orchestration and return wiring across these existing contracts, including the canonical parallel packet fork and actual receipt/readback evidence. Avoid introducing a duplicate authorization mechanism.
