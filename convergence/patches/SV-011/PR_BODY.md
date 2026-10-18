**HOLD. Do not open while this org's convergence is FAIL_CLOSED.** The patch shows exactly what `RESIDENT_RUNTIME_CONVERGENCE` would write. Applying it as it stands deletes org-specific behaviour and breaks imports.

Converges `SV-011/.github` (main 52cd447e) to `StegVerse-org/.github@0f9481af` with `OWNER_REPOSITORY = "SV-011/.github"`. The transition component is StegVerse-org/.github#192 (P4 #166, InTr H52 #162).

**Files**
- `resident-runtime/organization_egress_boundary.py`: 47891138 (509 lines) to c680c100 (964 lines). Normalized dc70c6fe equals the baseline. The diff is 1003 lines.
- `tests/test_organization_egress_boundary.py`: ABSENT (0 lines) to 235099ff (732 lines). Normalized 12f4f4ec equals the baseline. The diff is 735 lines.
- `.github/workflows/organization-egress-boundary-validation.yml`: ABSENT (0 lines) to e5739233 (208 lines). Normalized 914bc594 equals the baseline. The diff is 211 lines.

**Hunks the target has and the baseline doesn't:** 1 org-specific, 35 divergent code, 11 comment-only.
- Top-level definitions that convergence would remove: `_constraint_fields`
- Closure files absent here: `docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json`, `docs/ORGANIZATION_EGRESS_BOUNDARY_MIRROR_HANDOFF.md`, `org-boundary/runtime/manifest_selection.py`, `org-boundary/runtime/node_standing.py`, `org-boundary/runtime/origin_attestation.py`, `org-kernel/node_store.py`, `org-runtime/activation.json`, `resident-runtime/activation-manifest.json`, `tests/peer_organization.py`
- Baseline egress tests on the converged tree: 0 run, `passed=False` (FileNotFoundError at import)

**FAIL_CLOSED (dry run 2026-10-18)**
- `ORG_SPECIFIC_BEHAVIOUR_UNRECONCILED`: failed_predicate `EVERY_NON_PARAMETER_NON_COSMETIC_TARGET_HUNK_IS_RECONCILED`
- `BASELINE_DEPENDENCY_CLOSURE_ABSENT`: failed_predicate `EVERY_FILE_THE_BASELINE_LOADS_EXISTS_IN_THE_TARGET`
- `BASELINE_EGRESS_TESTS_FAIL_ON_CONVERGED_TREE`: failed_predicate `BASELINE_EGRESS_TESTS_PASS_ON_THE_CONVERGED_TREE`
- required_evidence_or_repair: reconcile each listed hunk (`evidence/SV-011/result.json`, by `hunk_sha256`) by porting it into the baseline or recording it as superseded. Then land the absent closure files. Then rerun.
- retry_entrypoint: `resident-runtime/resident_runtime_convergence.py::converge --organization SV-011`
- owning_existing_goal: StegVerse-org/.github#166 (P4), for H52 under StegVerse-org/.github#162
- next_attempt: when the manifest's `targets.SV-011.reconciled_hunk_sha256` covers every unreconciled hunk and the closure resolves

This is a draft. These are test results only, not authentic receipts. No dispatch.
