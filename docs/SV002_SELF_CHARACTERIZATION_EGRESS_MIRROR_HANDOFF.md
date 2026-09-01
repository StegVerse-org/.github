# SDK -> StegVerse-002 Self-Characterization Egress Mirror Handoff

Status: ACTIVE
Updated: 2026-09-01
Repository: StegVerse-org/.github

The exact frozen request created by StegVerse-org/StegVerse-SDK is bound here to the canonical organization egress:

```text
StegVerse-org/StegVerse-SDK
-> resident-runtime/sdk_self_characterization_egress.py
-> StegVerse-org/.github InTr packet/carrier
-> StegVerse-002/.github
-> stegverse-002.self-characterization
```

The adapter validates the exact experiment ID, source evaluator, target entity, objective, non-prescriptive knowledge policy, manifest hash, and request bindings before creating the organization packet. It does not mint authority or claim delivery.


## Executable federation round trip — 2026-09-01

The source organization boundary now supports the complete request/response path:

```text
SDK exact request
-> sdk_self_characterization_egress.py --submit
-> shared organization federation Gateway
-> StegVerse-002/.github internal endpoint
-> response packet addressed to stegverse-org.stegverse-sdk
-> StegVerse-org/.github internal endpoint
-> sdk_self_characterization_response.py
-> write-once response record
```

`stegverse-org.stegverse-sdk` is ACTIVE as an internal response endpoint. The org kernel now dispatches registered internal endpoint adapters and suppresses response recursion when `response_to_packet_id` is present. The response remains manifest-bound and authority-neutral.
