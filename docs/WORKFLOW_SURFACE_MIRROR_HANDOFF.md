# Workflow surface (G17) — mirror handoff

Goal: G17-WORKFLOW-SURFACE-MINIMIZATION (StegVerse-Labs/.github#167/#168), enforced retroactively
under Rigel's 2026-10-24 direction (StegVerse-org/.github#166).

| | Before | After |
|---|---|---|
| Workflow files | 37 | 3 (2 stable + 1 exception pending owner approval) |

## Surfaces

- `.github/workflows/validation-dispatcher.yml` — KEEP_STABLE_DISPATCHER. `pull_request` + `push` to main,
  no path filter, `permissions: {}` / job `contents: read`. Runs `tools/tasks/task_catalog.json`
  (one matrix job per group; each group is one folded job, its steps byte-for-byte, sha256-pinned).
- `.github/workflows/organization-ledger-writer.yml` — KEEP_STABLE_DISPATCHER (writer lifecycle). Push to main
  only; the five ledger/InTr writers as jobs chained by state transition (`needs`), not `workflow_run`
  by name; changed-path selection from `control/workflow-surface-registry.json` `writer_jobs[]`.
- `.github/workflows/organization-egress-boundary-validation.yml` — KEEP_STANDALONE_EXCEPTION,
  **exception pending owner approval**. Distinct lifecycle: its bytes are the workflow member of the
  organization-egress-boundary convergence unit pinned in
  `resident-runtime/resident-runtime-convergence-manifest.json` (L23-28) and carried to peer `.github`
  repositories; folding or editing it moves the baseline every peer patch is measured against.
  It keeps its `workflow_dispatch` trigger for the same reason (decision pending).

## Rules while this change is open

- Single owner for this repository's workflow surface: changes to `.github/workflows/` go through the
  consolidation PR; lane PRs carry checks as catalog groups instead of workflow files.
- New checks: add a catalog group (`tools/tasks/task_catalog.json` + `tools/tasks/steps/<group>/`),
  never a workflow file. `tests/test_workflow_surface_registry.py` fails closed on an unregistered
  workflow, drifted triggers/permissions, or a catalog body whose sha256 moved.

## FAIL_CLOSED pending (six fields in the registry `fail_closed_pending[]`)

- ledger-transition self-closure mode (was a `workflow_dispatch` mode).
- governance-return dispatched locators (was `workflow_dispatch` inputs).
- InTr destination hop `hop` job (`workflow_dispatch` + `secrets.FEDERATION_HOP_TOKEN`); retained verbatim at
  `tools/tasks/retired/intr-destination-hop.yml`, not executed. No secret added or moved.

## Open decisions (Rigel)

1. Approve or refuse the 3rd-workflow exception above.
2. Token handling for the InTr hop (TV/TVC credential path).
3. Manifest form of the dispatch-only writer modes.
