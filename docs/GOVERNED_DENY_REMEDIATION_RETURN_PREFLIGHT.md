# NON-ALLOW dispositions

StegVerse-org records each NON-ALLOW (`DENY` or `FAIL_CLOSED`) as a six-field receipt on its repository ledger and its organization ledger. Those receipts are exposed through the existing ledger refs.

A route-related NON-ALLOW is one whose manifest derives an execution request. The manifest requires that disposition to be delivered to StegHealer over InTr. The route is calculated from where the NON-ALLOW was recognized, the manifested path, and the direct InTr leg (`stegverse.remediation_fork.remediation_route`). The delivery carries the six-field receipt and the manifest's packet reference. It is a disposition delivery. This organization makes no remediation decision and consumes no classification and no return.

A NON-ALLOW whose manifest derives no request has no manifested route. It stays the six-field receipt on both ledgers and is not emitted. No mesh frame is published.

Every ACTION is a manifest-driven state transition. StegHealer decides whether remediation is triggered.

Related: [StegVerse-org/.github #98](https://github.com/StegVerse-org/.github/issues/98), [StegVerse-Labs/.github #3183](https://github.com/StegVerse-Labs/.github/issues/3183).
