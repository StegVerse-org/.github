# StegVerse

**StegVerse-org is the public evaluator- and developer-facing organization for governed StegVerse execution and comparison work.**

It exposes the SDK, manifests, adapters, discovery surfaces, and reproducible evaluation tooling that let an external tester describe a proposition, submit it through published governed paths, and receive portable evidence without requiring a special route to be created for that evaluator.

## Core operating model

```text
evaluator proposition
-> manifest
-> published governed intake
-> canonical execution path
-> receipts / evidence
-> replay / reconstruction / comparison
```

A new comparison case should normally be expressed as a manifest against existing published capabilities. A tester should not need a StegVerse developer to construct a one-off evaluator route.

## Public repositories

Representative public components include:

- **StegVerse-SDK** — evaluator/developer intake, manifests, receipts, and evidence navigation;
- **LLM-adapter** — bounded conversion of model output into governed artifacts;
- **manifests** — reusable configuration and experiment declarations;
- **discovery** — component and capability discovery;
- **stegverse-gsl** — governance/specification structure;
- public runners, fixtures, and sandbox surfaces used to exercise published paths.

Some repositories retain historical names containing “demo.” Those names do **not** define a weaker demo-only authority lane. Tests and demonstrations are expected to exercise the same published governance semantics and production-capable routes, with manifests and receipts distinguishing the experiment.

## Boundary rule

Submission is not execution. Model output is not authority. A manifest cannot silently create a new runtime capability or hot-patch a route. Unsupported requested capability should fail closed or be rejected before execution.

Private authority-bearing repositories remain separate where required, including TV/TVC and trust/admission internals.
