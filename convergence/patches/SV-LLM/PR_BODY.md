**HOLD. Do not open while this org's convergence is FAIL_CLOSED.** The patch shows exactly what `RESIDENT_RUNTIME_CONVERGENCE` would write. Applying it as it stands deletes org-specific behaviour and breaks imports.

Converges `SV-LLM/.github` (main 398326a2) to `StegVerse-org/.github@0f9481af` with `OWNER_REPOSITORY = "SV-LLM/.github"`. The transition component is StegVerse-org/.github#192 (P4 #166, InTr H52 #162).

**Files**
- `resident-runtime/organization_egress_boundary.py`: b5e019bf (603 lines) to 59344e0f (964 lines). Normalized dc70c6fe equals the baseline. The diff is 1049 lines.
- `tests/test_organization_egress_boundary.py`: ABSENT (0 lines) to c05d1d63 (732 lines). Normalized 12f4f4ec equals the baseline. The diff is 735 lines.
- `.github/workflows/organization-egress-boundary-validation.yml`: ABSENT (0 lines) to 7ff466ac (208 lines). Normalized 914bc594 equals the baseline. The diff is 211 lines.

**Hunks the target has and the baseline doesn't:** 5 org-specific, 37 divergent code, 12 comment-only.
- Top-level definitions that convergence would remove: `_boundary`, `_custody`, `_unattested`, `outbound_entries`, `select_outbound_binding`
- Closure files absent here: `docs/ORGANIZATION_EGRESS_BOUNDARY_MIRROR_HANDOFF.md`, `org-boundary/runtime/origin_attestation.py`, `resident-runtime/activation-manifest.json`, `tests/peer_organization.py`
- Baseline egress tests on the converged tree: 0 run, `passed=False` (FileNotFoundError at import)

**FAIL_CLOSED (dry run 2026-10-18)**
- `ORG_SPECIFIC_BEHAVIOUR_UNRECONCILED`: failed_predicate `EVERY_NON_PARAMETER_NON_COSMETIC_TARGET_HUNK_IS_RECONCILED`
- `BASELINE_DEPENDENCY_CLOSURE_ABSENT`: failed_predicate `EVERY_FILE_THE_BASELINE_LOADS_EXISTS_IN_THE_TARGET`
- `BASELINE_EGRESS_TESTS_FAIL_ON_CONVERGED_TREE`: failed_predicate `BASELINE_EGRESS_TESTS_PASS_ON_THE_CONVERGED_TREE`
- required_evidence_or_repair: reconcile each listed hunk (`evidence/SV-LLM/result.json`, by `hunk_sha256`) by porting it into the baseline or recording it as superseded. Then land the absent closure files. Then rerun.
- retry_entrypoint: `resident-runtime/resident_runtime_convergence.py::converge --organization SV-LLM`
- owning_existing_goal: StegVerse-org/.github#166 (P4), for H52 under StegVerse-org/.github#162
- next_attempt: when the manifest's `targets.SV-LLM.reconciled_hunk_sha256` covers every unreconciled hunk and the closure resolves

This is a draft. These are test results only, not authentic receipts. No dispatch.
