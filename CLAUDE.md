# Operating notes for Claude sessions

Read this before concluding that a repository, org or file is out of reach.

## This ecosystem is inter-org by design

Work routinely spans `StegVerse-org`, `StegVerse-Labs`, `StegGhost` and
`StegVerse-002`. A session that needs a repository it was not started with is
**not blocked**:

- Call `add_repo` with `access: "push"` when commits, PRs or GitHub API writes
  are needed; `"read"` when only reading.
- Then clone it inline — one clone, not in parallel, with a generous timeout
  (~10 min) — and call `register_repo_root` so its own `CLAUDE.md`, skills and
  plugins load.
- **Do not report a repository as inaccessible before calling `add_repo`.** The
  system prompt's "Repository Scope" list is the session's *starting* set, not a
  ceiling. Account-level access already covers every org and repo here.
- **Do not open a new session per repository.** Attach it to the session you are
  already in and keep one thread of work. Opening a session per org is how work
  ends up spread across dozens of threads with nothing finished.

## Keep attachment bounded

The cross-references in this ecosystem *are* the ecosystem, so following them
without limit is expensive: one prior session followed them outward to 22
repositories and ran three days. The rule is narrow attachment, not no
attachment:

- Attach only what the current task needs, one repository at a time.
- Stop at the repository that answers the question. Do not follow its
  references outward on your own initiative.
- If the task appears to need more than about three additional repositories,
  stop and report what you need and why, rather than attaching them.

## Where authority lives

Do not invent a local `.gitignore`, workflow wiring, architecture manifest or
hygiene convention in a repository when one of these surfaces already defines
it. Read the owner first.

| Surface | Governs |
| --- | --- |
| `StegVerse-Labs/repo-standards` | ST-001…ST-020: repo layout, preflight, correction, protection, naming, validation |
| `StegVerse-Labs/StegDB` | Architecture canon; `tools/architecture_validator.py` and the `stegverse.architecture.json` contract that `architecture-guard` consumes |
| `StegVerse-Labs/StegVerse-Healer` | Repair surfaces |
| `StegVerse-org/.github` | Org profile, organization transition ledger, resident runtime, Interlock/InTr boundary |
| `StegVerse-Labs/.github` | Review records and retention requirements |
| `StegVerse-org/StegVerse-SDK` | The `stegverse` Python package; test workflows here install it from a pinned commit |

## Repository facts worth knowing before you run anything

- There is **no suite-wide test entry point**. Each test file is gated by its
  own workflow with its own dependency setup, and no workflow runs
  `unittest discover` across `tests/`. Running `discover` locally sweeps in
  files whose dependencies are not present and produces import errors that are
  **not** repository defects.
- `tests/test_workspace_internal_endpoint_binding.py` imports `stegverse.*`,
  which its workflow supplies by checking out `StegVerse-org/StegVerse-SDK` at a
  pinned commit and running `pip install -e ./sdk`. It cannot import outside
  that workflow.
- Workflows only run from `.github/workflows/`. A file under the root
  `workflows/` directory never executes.

## Never

- **Never merge or close a pull request.** Open it ready-for-review and stop.
- Open PRs **ready-for-review, never draft** — the environment tags sessions
  `config:auto-create-pr:draft`, so that flag must be flipped explicitly.
- The repository owner works from an iPhone, deliberately, as dogfooding of the
  invariant that anyone on any device can use every part of StegVerse. State
  what you ran and what passed **in the chat reply**, not only in the PR body:
  review should be a few lines to read, not a GitHub tree to navigate on a
  phone.
- Do not commit `__pycache__` or `.pyc` artifacts. Delete them instead; this
  repository has no `.gitignore` yet, and that is governed by
  `StegVerse-Labs/repo-standards`.
