# StegVerse

**StegVerse** is a research and engineering effort focused on building a **governed distributed operating system for autonomous agents, AI systems, and human‑AI collaboration**.

The project explores how complex autonomous systems can operate safely and reliably when their actions are mediated by **policy enforcement, verifiable receipts, and governed state transitions**.

> Execution is not assumed. Execution is admitted.

---

## Core Idea

Traditional software systems assume that actors can execute operations freely once authenticated.

StegVerse introduces a different model:

```
intent → policy gate → decision → execution → receipt → next admissible state
```

In this model:

- actions are evaluated **before execution**
- the system produces **verifiable receipts**
- receipts authorize **subsequent actions or information access**
- workflows become **state‑aware and governed**

---

## Organization federation boundary

Organization-crossing messages use the registered Interlock/InTr federation boundary rather than service-ID-specific transport logic. A service registered as an `INTERNAL_ENDPOINT` may declare an `endpoint_adapter`; the boundary processor dispatches that registered adapter generically after destination/service validation.

The adapter must resolve inside the organization repository root and must exist as a file. Missing, external-path, or failing adapters fail closed. Registry-driven dispatch does not itself grant transport, credential, governance, or transition authority; those authorities remain governed by their applicable layers.

The provider-neutral WorkSpace resource consumer is exposed through the registered `stegverse-org.workspace-resource-consumer` internal endpoint. Its organization-local adapter remains thin and delegates projection semantics to the installed canonical StegVerse SDK consumer instead of copying that logic into the organization boundary. The adapter and SDK consumer remain non-authorizing; boundary receipts, governance authority, MIR custody, and Master Records custody are not conferred by the adapter.

This keeps the organization boundary extensible without hardcoding each future service into the boundary processor.

---

## Canonical external node ingress — review contract

The proposed machine-readable contract at [`docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json`](docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json) defines one canonical ecosystem-ingress **contract** for node standing, not one mandatory host. It covers both explicit genesis and later access by already-established nodes: the predecessor key is mandatory, `null` means explicit genesis only, and continuity requires the canonical SDK predecessor binding. Participant/framework, browser/console/API surface, device/machine substrate, StegNode materialization, StegOS runtime and processing continuation are orthogonal dimensions rather than caller-selected peer identities. Missing or invalid standing fails closed and may not silently re-enroll. HTTP/TLS metadata remains descriptive only. The document is `DRAFT_FOR_REVIEW`; KV-as-established-node, StegBrowser semantics, deployed continuations, attestation and bypass rejection remain `NOT_PROVEN` until their owners/evidence establish them.


---

## Ecosystem

| Component | Repo | Status | Purpose |
|-----------|------|--------|---------|
| **StegVerse SDK** | [StegVerse-SDK](https://github.com/StegVerse-org/StegVerse-SDK) | v1.0.1 | Developer toolkit for governed execution |
| **Trust Kernel** | [Trust-Kernel](https://github.com/StegVerse-org/Trust-Kernel) | v1.0.0 | Foundational governance layer |
| **StegVerse Admission** | [StegVerse-Admission](https://github.com/StegVerse-org/StegVerse-Admission) | v1.0.0 | GCAT/BCAT admissibility evaluation |
| **LLM Adapter** | [LLM-adapter](https://github.com/StegVerse-org/LLM-adapter) | v2.1 | AI output governance bridge |
| **Demo Suite** | [stegverse-demo-suite](https://github.com/StegVerse-org/stegverse-demo-suite) | v1.0.0 | Reproducible validation scenarios |
| **Ingestion Engine** | [demo_ingest_engine](https://github.com/StegVerse-org/demo_ingest_engine) | v1.2.1 | Orchestrated bundle ingestion |
| **StegTalk** | StegTalk | — | Secure messaging layer |
| **StegCore** | StegCore | — | Policy evaluation engine |
| **Token Vault** | TV / TVC | — | Ephemeral secret distribution |

---

## Demonstrations

The **StegVerse Demo Suite** provides runnable examples illustrating the core primitives:

- AI agents operate under governed execution
- actions are evaluated by policy gates
- receipts are generated and chained
- workflows unlock subsequent steps through verified state transitions

Repository: [stegverse-demo-suite](https://github.com/StegVerse-org/stegverse-demo-suite)

---

## Current Status

StegVerse is currently in an **early prototype phase**, providing experimental implementations and architecture demonstrations.

Core SDK v1.0.1 is published to PyPI and integrated with the ingestion engine for automated downstream distribution.

---

## Contributing

Engineers and researchers interested in:

- AI infrastructure
- distributed systems
- autonomous agents
- governance and safety architectures

are welcome to explore the demos and participate in discussion.

---

## License

Open research / prototype environment. Individual repositories define their own licenses (MIT for SDK, Trust Kernel, Admission, LLM Adapter, Demo Suite, Ingestion Engine).


## Open-source licensing census — organization-owned baseline (2026-09-25)

The source-owned [organization inventory](docs/OPEN_SOURCE_ORGANIZATION_INVENTORY_20260925.json) records all 18 StegVerse-org repositories visible through the connected GitHub search (10 public, 8 private), with 13 GitHub-detected MIT and five without a detected license. Private repository names are not published in the inventory. The existing [central goal](https://github.com/StegVerse-Labs/.github/blob/main/docs/ECOSYSTEM_OPEN_SOURCE_STRATEGY_MIRROR_HANDOFF.md) retains task ownership and COSV `20010010100000`; this repository owns its scope-specific licensing and contributor evidence. Metadata does not prove ownership, distribution rights or release authorization. The SDK's optional pinned dependencies and complete contributor history remain under review. No license was changed or release made.


PR #31 also requires discovery to publish two machine-readable continuation recipes using existing owners only: `LLM_MACHINE_CONTINUATION` for a machine/LLM that can supply a canonical manifest to the governed LLM-adapter path, and `EXTERNAL_FRAMEWORK_MANIFEST_CONTINUATION` for a framework that must use the SDK Manifest Builder / external-framework handoff first. Both require canonical node standing and preserve manifest capability + route binding; neither instruction grants authority or creates an endpoint.



## Test 5/6 external submission boundary — 2026-10-02

External instructions terminate at `SUBMIT_CANONICAL_MANIFEST` and `RETAIN_SUBMISSION_RESULT_AND_EVIDENCE`. Interlock/InTr is `INTERNAL_POST_SUBMISSION`; `EXTERNAL_INTERLOCK_INTR` is deferred to a separate successor expansion after Tests 5/6. This changes the caller instruction boundary, not the retained experiment, Test 5-before-Test 6 ordering, or downstream receipt/custody acceptance. Source tests are not Test 5/6 runtime results.

`SDK_MACHINE_CONTRACT` derives from existing SDK builder signatures, processor/route declarations, return projections and console commands. The adapter consumes that SDK projection instead of maintaining a second instruction recipe. The console wrapper already dispatched manifest/external-run; its top-level help omitted them. Shared dispatch/help declarations repair that discovery mismatch.

The external-framework helper currently reports `SDK_LOCAL_MANIFEST_HANDOFF`; it does not prove receiver observation. Adapter predecessor checks establish structural validity only, not authenticated standing. Production endpoint binding, authentic standing, runtime execution, deployment and custody remain NOT_PROVEN. No endpoint, runtime, credential path or authority was created.
