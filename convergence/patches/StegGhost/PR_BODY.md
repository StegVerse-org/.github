**HOLD. Do not open while this org's convergence is FAIL_CLOSED.** The patch shows exactly what `RESIDENT_RUNTIME_CONVERGENCE` would write. Applying it as it stands deletes org-specific behaviour and breaks imports.

Converges `StegGhost/.github` (main da5c9475) to `StegVerse-org/.github@0f9481af` with `OWNER_REPOSITORY = "StegGhost/.github"`. The transition component is StegVerse-org/.github#192 (P4 #166, InTr H52 #162).

**Files**
- `resident-runtime/organization_egress_boundary.py`: 35b54677 (898 lines) to 82320894 (964 lines). Normalized dc70c6fe equals the baseline. The diff is 1262 lines.
- `tests/test_organization_egress_boundary.py`: ABSENT (0 lines) to f3110bd2 (732 lines). Normalized 12f4f4ec equals the baseline. The diff is 735 lines.
- `.github/workflows/organization-egress-boundary-validation.yml`: 0caf696e (186 lines) to 73d7bdfc (208 lines). Normalized 914bc594 equals the baseline. The diff is 375 lines.

**Hunks the target has and the baseline doesn't:** 5 org-specific, 57 divergent code, 22 comment-only.
- Top-level definitions that convergence would remove: `INTENDED_ACTION_MATCH`, `MATCH_REFUSED_CLASS`, `MATCH_SATISFIED_CLASS`, `MATCH_SCHEMA`, `disclosure_module`, `observe_bilateral_match`, `request_bilateral_match`, `resolve_standing`
- Closure files absent here: `docs/ORGANIZATION_EGRESS_BOUNDARY_MIRROR_HANDOFF.md`, `org-kernel/node_store.py`, `tests/peer_organization.py`
- Baseline egress tests on the converged tree: 0 run, `passed=False` (FileNotFoundError at import)

**FAIL_CLOSED (dry run 2026-10-18)**
- `ORG_SPECIFIC_BEHAVIOUR_UNRECONCILED`: failed_predicate `EVERY_NON_PARAMETER_NON_COSMETIC_TARGET_HUNK_IS_RECONCILED`
- `BASELINE_DEPENDENCY_CLOSURE_ABSENT`: failed_predicate `EVERY_FILE_THE_BASELINE_LOADS_EXISTS_IN_THE_TARGET`
- `BASELINE_EGRESS_TESTS_FAIL_ON_CONVERGED_TREE`: failed_predicate `BASELINE_EGRESS_TESTS_PASS_ON_THE_CONVERGED_TREE`
- required_evidence_or_repair: reconcile each listed hunk (`evidence/StegGhost/result.json`, by `hunk_sha256`) by porting it into the baseline or recording it as superseded. Then land the absent closure files. Then rerun.
- retry_entrypoint: `resident-runtime/resident_runtime_convergence.py::converge --organization StegGhost`
- owning_existing_goal: StegVerse-org/.github#166 (P4), for H52 under StegVerse-org/.github#162
- next_attempt: when the manifest's `targets.StegGhost.reconciled_hunk_sha256` covers every unreconciled hunk and the closure resolves

This is a draft. These are test results only, not authentic receipts. No dispatch.
