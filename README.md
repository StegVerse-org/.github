# Handoff: StegVerse-Labs/.github changes for #3099 (SDK-MR-A-VALIDATION-CUSTODY-001)

Transport branch, never merged. It carries `git format-patch` output for
StegVerse-Labs/.github, which the session that wrote it cannot attach. See
StegVerse-org/StegVerse-SDK#465.

Base: StegVerse-Labs/.github main `81b9f5ea`.

- `patches/pr1/`: publish the Labs organization ledger on
  `refs/stegverse/organization-ledger` (StegVerse-org's location structure).
- `patches/pr2/` (stacked on pr1): read StegCore only through TV/TVC
  (`tvc.private-source-read.v1`, request staged in StegVerse-Labs/TVC#506).

Apply: `sha256sum -c patches/SHA256SUMS`; then in StegVerse-Labs/.github on a
branch from main `git am patches/pr1/*.patch` (PR 1), and on a branch from that
one `git am patches/pr2/*.patch` (PR 2).
