# StegVerse

**StegVerse** is a research and engineering effort focused on governed AI execution, admissibility testing, receipt-bound runtime paths, and reconstructable human-AI / agent-system collaboration.

> Submission is not execution. Execution is not authority. Authority is not admissibility.

---

## Core idea

Traditional software systems often assume that authenticated actors may execute operations freely.

StegVerse separates the path:

```text
submission
→ manifest binding
→ receipt binding
→ admissibility check
→ bounded execution / demonstration
→ result receipt
→ reconstruction packet
```

In this model:

- actions are evaluated before consequence attaches;
- receipts preserve transition history;
- reconstruction answers what happened;
- admissibility answers whether standing existed for consequence;
- public review does not create endorsement, compatibility, provenance, collaboration, or validation.

---

## Public ecosystem

| Component | Repo | Purpose |
|---|---|---|
| SDK intake | [StegVerse-SDK](https://github.com/StegVerse-org/StegVerse-SDK) | Public SDK boundary for manifest-bound and receipt-bound submissions. |
| LLM adapter | [LLM-adapter](https://github.com/StegVerse-org/LLM-adapter) | Converts LLM output into route-ready governance artifacts. |
| Demo suite | [stegverse-demo-suite](https://github.com/StegVerse-org/stegverse-demo-suite) | Reproducible public governance demonstrations. |
| Demo suite runner | [demo-suite-runner](https://github.com/StegVerse-org/demo-suite-runner) | Formal runner for GCAT/BCAT and related fixture probes. |
| Demo ingestion engine | [demo_ingest_engine](https://github.com/StegVerse-org/demo_ingest_engine) | Org-side orchestration and result-return boundary. |
| Demo sandbox | [demo-sandbox](https://github.com/StegVerse-org/demo-sandbox) | Public sandbox fixtures and controlled experiments. |
| Core-node runtime demo | [core-node-runtime-demo](https://github.com/StegVerse-org/core-node-runtime-demo) | Runtime comparison across ingestion, core-node, and micro-node paths. |
| GSL | [stegverse-gsl](https://github.com/StegVerse-org/stegverse-gsl) | Governance Specification Language for structure and manifest validation. |
| Discovery | [discovery](https://github.com/StegVerse-org/discovery) | Component discovery and repository indexing. |
| Manifests | [manifests](https://github.com/StegVerse-org/manifests) | Canonical pricing, package, tier, and configuration manifests. |

---

## Private authority-bearing / operational repos

The following repositories are expected to remain private unless separate public-safe scaffolds are created:

| Component | Purpose |
|---|---|
| trust-kernel | Authority-bearing governance kernel. |
| StegVerse-admission | Admission / threshold layer. |
| telemetry | Cross-org signal monitoring and operational records. |
| TV / TVC | TrustVault and TrustVaultController workflow material. |

---

## Current status

StegVerse is in an early prototype and demonstration phase. Public repositories are intended to expose interfaces, demos, schemas, receipts, path reports, and reconstruction-oriented artifacts. Private repositories retain authority-bearing or operationally sensitive logic.

---

## Boundary rule

Private review, artifact inspection, repository review, or technical comments do not become public attribution, endorsement, compatibility recognition, provenance recognition, collaboration, validation, semantic attribution, conceptual attribution, or publication authorization.

---

## License

Public repositories define their own licenses. Most public demonstration and SDK repositories currently use MIT.
