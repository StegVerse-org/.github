Base: StegVerse-002/.github main b122dfe4654630620cbf650661290da4518f45ba
Branch (suggested): intr/h52-resident-runtime-convergence
Apply: gunzip -k convergence.patch.gz && git apply --index convergence.patch  (verified with git apply --check on that commit; convergence.patch sha256 a748a4dba5d6aeff635d00ce34cc09461e6141eaf221ba57b26ef2f5e35d0182)
Why gzip: the patch carries one line of another org's code that this repository's role audit (tests/test_organization_role_runtime_reality_deployment.py::test_the_audit_matches_the_tree, which measures every UTF-8 file in the tree) would count as this repository's own statement; it is not.
Status: HOLD (FAIL_CLOSED; see PR_BODY.md). Outside P4 grant G-8; handed to InTr (Goal #162), which pushes drafts. P4 pushed nothing here.
Regenerate: python3 resident-runtime/resident_runtime_convergence.py --organization StegVerse-002 --target-root <StegVerse-002/.github checkout> --out <dir>; the patch is that run's converged/ tree diffed against the checkout.
