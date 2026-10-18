Base: GCAT-BCAT-Engine/.github main c3cf1b1ab171d0ea04a1d345e7567860f00519a3
Branch (suggested): intr/h52-resident-runtime-convergence
Apply: gunzip -k convergence.patch.gz && git apply --index convergence.patch  (verified with git apply --check on that commit; convergence.patch sha256 d65dc957e0c4eea2b66187daf1a199124c9c719953025a9c137fc43a816773c5)
Why gzip: the patch carries one line of another org's code that this repository's role audit (tests/test_organization_role_runtime_reality_deployment.py::test_the_audit_matches_the_tree, which measures every UTF-8 file in the tree) would count as this repository's own statement; it is not.
Status: HOLD (FAIL_CLOSED; see PR_BODY.md). Outside P4 grant G-8; handed to InTr (Goal #162), which pushes drafts. P4 pushed nothing here.
Regenerate: python3 resident-runtime/resident_runtime_convergence.py --organization GCAT-BCAT-Engine --target-root <GCAT-BCAT-Engine/.github checkout> --out <dir>; the patch is that run's converged/ tree diffed against the checkout.
