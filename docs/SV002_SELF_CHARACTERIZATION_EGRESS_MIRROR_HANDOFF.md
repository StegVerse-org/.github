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


## Sovereign same-host runtime availability — 2026-09-01

The SDK query now has a direct sovereign runtime path that does not require a hosted scheduler or GitHub Actions:

```text
StegVerse-org/StegVerse-SDK exact frozen request
-> StegVerse-org/.github resident-runtime/sdk_self_characterization_egress.py
-> SHARED_SERVICE_GATEWAY when configured
   OR canonical LOCAL_SPOOL_FALLBACK for same-host sovereign federation
-> StegVerse-002/.github resident-runtime/federation_cycle.py
-> stegverse-002.self-characterization
-> StegVerse-002/micro-node-runtime principal
-> StegVerse-002 response packet
-> StegVerse-org/.github resident federation cycle
```

New executable bridge:
- `resident-runtime/run_sv002_self_characterization_roundtrip.py`

The bridge requires the SDK, StegVerse-002/.github, and micro-node-runtime repositories to already be locally materialized on the same sovereign resident. It rejects hosted CI/runtime environments and credential-bearing GitHub execution environments. It never invokes the StegVerse-002 principal directly from the source organization; target execution remains owned by `StegVerse-002/.github`.

`sdk_self_characterization_egress.py --submit` now uses the shared HTTPS Service Gateway when configured and otherwise publishes to the canonical same-host federation spool. The fallback remains an InTr/org-boundary carrier path and is limited to same-host sovereign federation.

Source availability is now established. Authentic principal execution, response transport, Master Records organization records and reconstruction, and public observation remain runtime-evidence transitions and must not be inferred from these commits.

## Declared carrier only; submission without orchestration — 2026-10-08

Supersedes the transport and bridge description in the 2026-09-01 section above, which is kept as history.

```text
StegVerse-org/StegVerse-SDK exact frozen request (supplied --sdk-root)
-> StegVerse-org/.github resident-runtime/run_sv002_self_characterization_roundtrip.py
-> resident-runtime/sdk_self_characterization_egress.py build_packet
-> org-kernel publish_frame on the supplied mesh (INTERLOCK_INTR_SUPPLIED_MESH)
   ... StegVerse-002 consumes on its own materialization ...
-> StegVerse-org federation cycle consumes the response on a later materialization
```

- No hosted gateway: `federation_gateway_transport.py`, `activate_org_federation_gateway.py` and its activation request are removed; no caller selects a carrier from the host environment.
- The submission does not search the host for checkouts and does not run StegVerse-002's or this organization's federation cycle. The SDK source, mesh and state location are supplied or it refuses (`STEGVERSE_SDK_SOURCE_SUPPLIED`).
- `resident_executor.py` runs one federation cycle per invocation and records it under the supplied node-state root. The polling loop and the systemd unit with `Restart=always` are removed; frames arriving later are consumed by a later materialization.
- `sdk_self_characterization_egress.py --submit` takes `--mesh-root`.

Evidence class: source implementation and local tests. No principal execution, response, organization readback or Master Records reconstruction is claimed.
