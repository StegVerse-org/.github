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

The provider-neutral WorkSpace resource consumer is exposed through the registered `stegverse-org.workspace-resource-consumer` internal endpoint. Its organization-local adapter remains thin and delegates projection semantics to the installed canonical StegVerse SDK consumer instead of copying that logic into the organization boundary. The adapter and SDK consumer remain non-authorizing; boundary receipts, governance authority and MIR custody are not conferred by the adapter, and neither is any Master Records organization record.

This keeps the organization boundary extensible without hardcoding each future service into the boundary processor.

### Where a registered capability is received

`org-runtime/interlock-intr.json` carries `ingress.capability_endpoint_bindings`: one binding per capability, keyed on the `profile_id`, `profile_name` and `operation` the SDK resolves against, declaring the operation **this repository** receives it on. `sdk-manifest-ingress` / `SDK:ManifestIngress` / `SUBMIT_MANIFEST` resolves to `ORGANIZATION_SDK_MANIFEST_INGRESS`, which is an operation this repository owns and not an address — `host_required` and `environment_url_required` are both false, and the validator refuses a binding that sets either. The binding resolves a destination; it confers no routing, admission or execution authority, and the validator refuses a binding that claims any of them or that gives one capability two receiving operations.

`resident-runtime/organization_manifest_ingress.py` is that operation. It resolves its own destination from the organization's own boundary document — not handed one and not fetched, because a document supplied by a caller would let the caller name its own organization — then drives admission through the registered crossing, processing through the boundary processor, and appends the organization transition receipt. It recomputes every boundary receipt from its own subject before appending anything, so the boundary's `RECONSTRUCTED` is checked here rather than taken on trust, and a chain that does not recompute fails closed.

Both ledger levels are written, in order. The transition occurs in this repository, so `.stegverse/transition-ledger/emit.py` records a `stegverse.repo-transition-receipt/v1` first and the organization ledger consumes *that* — the organization authoring its own source receipt and then recording it as its own was one writer standing in for two levels, which left `preserves_repo_receipt` with nothing to preserve and left organization replay resting on a receipt the same call had minted. The organization receipt now carries `source_repository`, `repo_receipt_sha256` and `repo_transition_id`, so `ORGANIZATION_REPLAY_MUST_REQUIRE_ONLY_VERIFIED_REPO_RECEIPTS_AND_ORG_RECEIPTS` has a verified repository receipt underneath it.

The organization does not grade its own result: it reports what it observed to the SDK's own `admit_runtime_result` and returns that verdict, with `manifest_receipt_id` bound to the organization receipt that exists. Organization records are published to Master Records through `resident-runtime/submit_org_transition_to_master_records.py` and never awaited — `propagation_gates_organization_runtime_reality` is false and Master Records `may_be_awaited_by_a_transition` is false — so `master_records_organization_record_observed` stays false and says so.

### Repository transitions reach the organization chain

`organization_scope_rule` is that every state transition occurring within the organization emits an organization receipt. Repositories here append their own transitions to their own ledgers — the LLM-adapter records a node's arrival at its ingress boundary — and nothing carried them up, so the organization's record began at its own boundary.

`resident-runtime/propagate_repository_receipts.py` walks a repository's chain and hands the receipts to the organization ledger as `REPO_STATE_PROPAGATION`, in repository chain order, each verified against its own body first, and skipping what the organization chain already carries so a second run carries nothing rather than failing on a duplicate. The repositories in scope are read off `org-boundary/registry/services.json`, and a declared repository whose ledger is not present on this node reports its absence rather than failing — that is what an ephemeral node materializing a subset of capabilities looks like. `resident-runtime/federation_cycle.py` runs it on each cycle and reports what it carried, so this happens without anyone naming a repository.

None of this is a crossing. `StegVerse-org/LLM-adapter` and `StegVerse-org/.github` are both inside `StegVerse-org`, so no organization boundary is between them and no Interlock/InTr is involved; the receipts record that explicitly. The hop that does need Interlock/InTr is organization to `propagation_target: master-records/.github`.

Two resolutions happen at two boundaries and are not interchangeable. The capability overlay resolves which organization receives a capability and on what operation; a manifest's `completion.egress` resolves which internal endpoint of that organization serves the declared surface. `completion_egress_controls_outbound_organization_routing: false` is about the first.

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


### ICV v1 Site propagation verification

`ICV-V1-SITE-PROPAGATION-VERIFICATION-001` (issue #64) completed with `NO_PROPAGATION_REQUIRED`: it verified the published ICV `v1.0.0` release at `9b691cfaac076b565153c5a1c0f6c4072b8b044e` against the existing `StegVerse-Labs/Site` public commercial mirror. Site is the only demonstrated destination; no propagation work is inferred for Publisher, admissibility-wiki, or stegguardian-wiki without an explicit contract. See `docs/ICV_V1_SITE_PROPAGATION_VERIFICATION_MIRROR_HANDOFF.md`.


### Test 5/6 machine submission reconciliation

Existing goal: `SVORG-STEGOS-PORTABILITY-001` (parent counter 28/20).
COSV source projection candidate: `20011100100000`, retained with exact metrics
in StegVerse-org/.github `control/task-vector-index.json`; canonical admission
requires review/merge. SDK `machine-contract` projects current declarations and
peer execution profiles. The framework helper uses existing run-manifest routing;
adapter discovery preserves its own receiving operation. External instructions
end at canonical manifest submission and evidence retention. Local handoff is not
receiver observation; external reciprocal Interlock/InTr remains deferred.
See the repository's portability/canonical-standing/machine-contract mirror handoff
for source validation and remaining evidence.


## LLM Org foundation — canonical ecosystem work context

Task `SVORG-LLM-ORG-FOUNDATION-001` / issue #74 defines an organization-level coordination foundation for ecosystem construction and repair. It does not create a second provider broker or governance engine. Canonical work context is resolved through Interlock/InTr from relevant ecosystem evidence; participating LLM/AI entities produce attributable candidate work in a provider-neutral Sandbox and acquire no governance authority.

Existing `StegVerse-org/LLM-adapter` provider-neutral routing, distributed workload, contributor provenance and governed-reconciliation packaging remain the provider execution layer. Ecosystem AI is defined here as governance by matching manifested claims/proposed transitions against admissible evidence and reconstructable receipted history, not as an LLM or interpretive/consensus judge. The forward-looking Inference Window evaluates, for every disposition available in the applicable Admissibility Matrix, what states or consequences might or might not become reachable; projections do not become historical evidence without subsequent admissible observation and receipts.

The later Ecosystem Chat consumer loop through SDK Manifest Builder -> LLM Org -> governance -> Publisher -> SDK return is explicitly deferred from this foundation task.


## LLM Org foundation — bounded source contracts

The existing `SVORG-LLM-ORG-FOUNDATION-001` goal is owned by this organization's Task Registry and COSV vector `71000000100100` (see `docs/LLM_ORG_FOUNDATION_MIRROR_HANDOFF.md`). `llm_org_foundation_validation.py` validates relevance-bounded canonical work-context references, Sandbox work objects, non-authorizing LLM/AI-entity candidates, and disposition-complete forward-looking Inference Window projections. Its structural `ALLOW` means only that the supplied source object passes these checks; it is **not** an Interlock/InTr authorization or evidence of observed execution. Every source refusal carries actionable six-field `DENY` or `FAIL_CLOSED` metadata.

External LLM ingress stays on the declared `healthy node → LLM-adapter → SDK → StegVerse-org/.github → Interlock/InTr → Organization Ledger` path. HCB is optional and never a required hop; already-admitted internal Sandbox work does not re-enter the external adapter. The existing SDK builds/submits manifests, Interlock/InTr alone determines governance transitions, and Master Records is downstream and non-gating. The foundation introduces no provider broker, credential authority, always-on receiver, independent ledger, or required second machine. Runtime activation and terminal owner/COSV disposition require separate authentic evidence.

The foundation source obligations were reconciled against merged PR #115 and its
seven successful exact-head workflows on 2026-10-10. See the canonical
[handoff](docs/LLM_ORG_FOUNDATION_MIRROR_HANDOFF.md) for evidence and the separate
LLMA-368 ledger readback. Registry/COSV terminal review and Sandbox activation
remain distinct from source validation.

Terminal review (2026-10-10): LLMA-368 source conformance and the LLM Org foundation
are **CI_VALIDATED source complete**, with COSV `71000000100100`. The LLMA
read-only declared-path transition is separately ledger-verified. See
[data/llma-hcb-terminal-review.json](data/llma-hcb-terminal-review.json).
Provider/Sandbox activation, release, and propagation are not inferred.
