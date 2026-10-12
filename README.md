# Handoff: StegVerse-Labs/.github changes for #3099 (SDK-MR-A-VALIDATION-CUSTODY-001)

Transport branch, never merged. It carries `git format-patch` output for
StegVerse-Labs/.github, which the session that wrote it cannot attach. See
StegVerse-org/StegVerse-SDK#465.

Base: StegVerse-Labs/.github main `fee0c755` (after #3132).

- `patches/pr1/`: publish the Labs organization ledger on
  `refs/stegverse/organization-ledger` (StegVerse-org's location structure).
- `patches/pr2/` (stacked on pr1): read StegCore only through TV/TVC
  (`tvc.private-source-read.v1`, request staged in StegVerse-Labs/TVC#506).

Apply: `sha256sum -c patches/SHA256SUMS`; then in StegVerse-Labs/.github on a
branch from main `git am patches/pr1/*.patch` (PR 1), and on a branch from that
one `git am patches/pr2/*.patch` (PR 2).

- `patches/pr3/` (stacked on StegVerse-Labs/.github#3143 head `8e8a94f5`):
  optional `runs_on` runner label for the decision workflow, so a run that decides
  with StegCore can execute on a runner on the TV/TVC host (option C on
  StegVerse-org/StegVerse-SDK#465). Apply with `git am patches/pr3/*.patch` on a
  branch from #3143. **Withdrawn**: pr1 and pr2 merged as #3142 (`e3b93be4`) and
  #3146 (`cfab7759`), and the receiving review declined a TV/TVC-host runner as an
  external machine. Do not apply.
- `patches/pr4/` (on StegVerse-Labs/.github main `cfab7759`): install StegCore
  only from the verified checkout. The workflow resolves
  `decision_authority_source` with `realpath -e`, a dirty pinned checkout is
  refused, and `evaluator --installed --source` refuses an install whose
  `direct_url.json` is not that checkout. Without it, a bare `stegcore` passes
  the pinned-HEAD check (given a checkout at that relative path) but pip
  installs the unrelated `stegcore` 2.0.11 from PyPI. Apply with
  `git am patches/pr4/*.patch` on a branch from main.
