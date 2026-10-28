**HOLD. Do not open while this org's convergence is FAIL_CLOSED.** The patch is exactly what `RESIDENT_RUNTIME_CONVERGENCE` writes for `SV-011/.github` at main `52cd447e`. Component and manifest: StegVerse-org/.github#192 (P4 #166, InTr H52 #162).

**What it writes**
- `resident-runtime/organization_egress_boundary.py` is the StegVerse-org baseline `0f9481af` with `OWNER_REPOSITORY = "SV-011/.github"`, then a declared **org extension** of 319 lines (sha256 `b78538bd88ea740104561d04ebda3d53dd2b7fa0f9f11a2be2f8257dcf5abefa`). The extension carries 13 of this org's own definitions byte for byte: `EgressRefused`, `declared_capabilities`, `destination_bindings`, `peer_capability_service`, `resolve_destination`, `closability_refusal`, `_constraint_fields`, `emission_record`, `emit_refusal_record`, `closure_record`, `_record`, `_refusal_result`, `emit`. With the extension removed and the parameter normalized, the module equals `dc70c6fe…`. That proposed predicate is a joint-discovery item and is not settled.
- `tests/test_organization_egress_boundary.py` and `.github/workflows/organization-egress-boundary-validation.yml` are the baseline with the `{repository}` parameter applied.
- Closure files added as exact baseline bytes: `docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json` (398c794b3d1c), `docs/ORGANIZATION_EGRESS_BOUNDARY_MIRROR_HANDOFF.md` (1003399b44ed), `org-boundary/runtime/manifest_selection.py` (188601c5c2ad), `org-boundary/runtime/node_standing.py` (a24b7d2cc546), `org-boundary/runtime/origin_attestation.py` (d736f10892c6), `org-kernel/node_store.py` (fb125119a6b8), `tests/peer_organization.py` (fb47e1aef438)
- `org-runtime/interlock-intr.json` egress keys added from baseline values, only where absent: `/egress/peer_destination_resolution`, `/egress/origin_attestation`

**Hunk reconciliation:** 19 ported, 28 superseded, 0 unreconciled. Every entry has a decision, reason and evidence in the manifest under `targets.SV-011.reconciled_hunk_sha256`. Hunks inside `close()` are marked `superseded_by: InTr close() port (H52)`.

**Tests on the converged tree (dry run)**
- Baseline `tests.test_organization_egress_boundary`: 16/52 pass. Before this round: 0 ran (import error). Failures by cause:
  - DIVERGENT_CLOSURE_FILE:org-kernel/kernel.py: 12
  - DIVERGENT_CLOSURE_FILE:org-runtime/runtime_boundary.py: 19
  - UNATTRIBUTED: 5
- `tests.test_intr_destination_capability`: passed True before, False after (all 1 failures go through `close()`, which waits on the InTr port)

**FAIL_CLOSED (remaining; each record has all six fields in `result.json`)**
- `ORG_CONFIG_KEY_UNDECIDABLE`: `ORG_CONFIG_KEY_THE_BASELINE_READS_IS_DECLARED_BY_THE_ORGANIZATION`. Repair: org-runtime/interlock-intr.json/egress/capability_destination_bindings: the baseline value is StegVerse-org's routing policy (which capability goes to which destination organization and decision authority). ORRD conformance item 2: the manifest determines the 
- `BASELINE_DEPENDENCY_CLOSURE_ABSENT`: `EVERY_FILE_THE_BASELINE_LOADS_EXISTS_IN_THE_TARGET`. Repair: declare each absent closure file (detail) as a closure addition of baseline bytes, or, where it is that organization's own configuration, have the organization author it
- `BASELINE_EGRESS_TESTS_FAIL_ON_CONVERGED_TREE`: `BASELINE_EGRESS_TESTS_PASS_ON_THE_CONVERGED_TREE`. Repair: repair the unattributed failures named in detail (evidence/tests.out); each is a divergence between a carried org extension or org-owned closure file and the baseline contract
- `BASELINE_CLOSURE_FILE_DIVERGENT`: `THE_TARGETS_CLOSURE_FILES_EXPOSE_THE_API_THE_BASELINE_CALLS`. Repair: each closure file in detail is the organization's own revision and lacks baseline symbols or signatures the converged files call; converge it as a further manifest unit with its own hunk reconciliation, or have the organization add the named symbols
- `INTR_CLOSE_PORT_PENDING`: `CONVERGED_CLOSE_IS_THE_INTR_PORT_FOR_THIS_ORGANIZATION`. Repair: InTr's per-organization close() port (H52), with the names it needs, lands in this target; these tests fail only with a traceback through close()
- retry_entrypoint: `resident-runtime/resident_runtime_convergence.py::converge --organization SV-011`
- owning_existing_goal: StegVerse-org/.github#166 (P4) for H52 under #162; the close() port is #162 (InTr)

This is a draft. These are test results only, not authentic receipts. No dispatch.
