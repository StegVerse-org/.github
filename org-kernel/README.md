# Universal Organization Resident Kernel

Reference implementation extracted from the organization-neutral behavior already present in StegVerse-Labs/.github.

This kernel is intended to be vendored identically into every organization .github repository. Organization identity, service registry, endpoint profiles, and application workers remain local configuration.

The kernel provides canonical HB reference derivation, deterministic HB-derived InTr carrier frames, organization addressing, fail-closed service dispatch, receipt chaining, same-execution reconstruction, and a write-once federation outbox. Carrier presence grants no authority.
