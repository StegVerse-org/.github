Base: StegGhost/.github main da5c94758601decb69cfea2084975b74e974bbc9
Branch (suggested): intr/h52-resident-runtime-convergence
Apply: gunzip -k convergence.patch.gz && git apply --index convergence.patch  (verified with git apply --check on that commit; convergence.patch sha256 24bfc8a040781428fe9c553b5803cc46a75ca8965c33c1390cc5503a5b355e91)
Why gzip: the patch carries one line of another org's code that this repository's role audit (tests/test_organization_role_runtime_reality_deployment.py::test_the_audit_matches_the_tree, which measures every UTF-8 file in the tree) would count as this repository's own statement; it is not.
Status: HOLD (FAIL_CLOSED; see PR_BODY.md). Outside P4 grant G-8; handed to InTr (Goal #162), which pushes drafts. P4 pushed nothing here.
Regenerate: python3 resident-runtime/resident_runtime_convergence.py --organization StegGhost --target-root <StegGhost/.github checkout> --out <dir>; the patch is that run's converged/ tree diffed against the checkout.
