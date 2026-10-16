# NON-ALLOW receipts

StegVerse-org records each NON-ALLOW (`DENY` or `FAIL_CLOSED`) as a six-field receipt on its repository ledger and its organization ledger. Those receipts are exposed through the existing ledger refs.

StegHealer observes the receipts, maps them against known failures, and decides whether remediation is triggered. This organization does not request remediation and has no mechanism for deciding what needs it.

Every ACTION is a manifest-driven state transition.

Related: [StegVerse-org/.github #98](https://github.com/StegVerse-org/.github/issues/98), [StegVerse-Labs/.github #3183](https://github.com/StegVerse-Labs/.github/issues/3183).
