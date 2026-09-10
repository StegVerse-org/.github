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

This keeps the organization boundary extensible without hardcoding each future service into the boundary processor.

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
