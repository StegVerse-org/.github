Base: SV-LLM/.github main 398326a27bc5816a5d06bffac8894a19d997ccdf
Branch (suggested): intr/h52-resident-runtime-convergence
Apply: gunzip -k convergence.patch.gz && git apply --index convergence.patch  (verified with git apply --check on that commit; convergence.patch sha256 3f054549e921e0375bde6a49f0fca42859c3e0ab9d2570e661acd74210e80b50)
Why gzip: the patch carries one line of another org's code that this repository's role audit (tests/test_organization_role_runtime_reality_deployment.py::test_the_audit_matches_the_tree, which measures every UTF-8 file in the tree) would count as this repository's own statement; it is not.
Status: HOLD (FAIL_CLOSED; see PR_BODY.md). Outside P4 grant G-8; handed to InTr (Goal #162), which pushes drafts. P4 pushed nothing here.
Regenerate: python3 resident-runtime/resident_runtime_convergence.py --organization SV-LLM --target-root <SV-LLM/.github checkout> --out <dir>; the patch is that run's converged/ tree diffed against the checkout.
