# External reviewer prompt — the Task Registry as work-intent authority

A purpose-specific prompt for an external reviewer who will use an LLM to
review the invariant their engineering assessment still lists as `in_review`.
Like the node-standing prompt beside it, this is not a general-purpose
introduction and should not be published as one.

## Which invariant this is, and which it is not

`StegVerse-Engineering-Assessment` lists nine instances of the defect class
under `engineering_problem.instances` — eight `enforced`, one `in_review`. The
open one is:

    declared: the Task Registry is work-intent authority
    observed: no task registry surface existed in the organization

**That is the invariant this prompt reviews.**

`EXTERNAL_REVIEWER_NODE_STANDING_PROMPT.md` reviews a different thing —
`CANONICAL-NODE-INGRESS-CONTRACT-001`, the canonical node standing contract —
and describes its subject as "the in-review manifest invariant". Two documents
therefore call two different things in-review, which is how a reviewer asking
for "the one still in_review" can be sent to the wrong surface. The collision
is recorded here rather than silently resolved, because a reader who was sent
to the wrong place deserves to know a name was ambiguous rather than conclude
they were misled.

## What has changed since the assessment was written

The assessment's `observed` line is accurate for when it was written and is now
stale: a registry surface exists. What a reviewer should test is not whether a
file is present but whether the second half of the word *authority* holds — that
work intent named anywhere in the organization resolves in the registry, rather
than the registry being an internally tidy document nothing refers to.

## What the reviewer needs

Nothing from us. `StegVerse-org/.github` is public. The nineteen-case registry
suite is standard-library only. One further suite needs `jsonschema`, and the
prompt says so where it matters rather than letting an import error read as a
finding.

## The prompt

Paste the block below into Claude.

---

You are reviewing an invariant that an engineering assessment of the StegVerse
ecosystem lists as still `in_review`:

    declared: the Task Registry is work-intent authority
    observed: no task registry surface existed in the organization

Do not take my word for its current state. Everything below runs locally. There
is no host, no account, no key, and nothing to request from me.

**Step 1 — get the organization.**

    git clone https://github.com/StegVerse-org/.github stegverse-org-profile
    cd stegverse-org-profile

**Step 2 — read the surface the invariant is about.**

    python3 -c "import json;d=json.load(open('orchestration/task-registry.json'));\
    print(d['registry_type'], '| active_goal:', d['active_goal']);\
    [print(' ', t['task_id'], t['status']) for t in d['tasks']]"

**Step 3 — run the cases that hold it.**

    python3 -m unittest tests.test_task_registry -v

That suite is standard library only. A second suite validates the registry
against the schema its owning repository publishes and needs `jsonschema`
installed; run it if you have it, and treat its absence as an absence rather
than a finding:

    python3 -m unittest tests.test_task_registry_schema_conformance -v

**What I am asking you to check**

Three claims, each of which the repository either substantiates or does not.
For each one, the interesting move is the injection — change the repository to
violate the claim and see whether anything notices.

1. **The registry is entity-neutral by construction.** It records what the work
   is and what evidence closes it, never who is doing it. Which entity holds a
   task is a *claim*, and claims belong to WorkerCoordinator, not here. Read
   `orchestration/schemas/task-registry.schema.json`: the task item declares
   `additionalProperties: false` and no `assignee`, `agent`, `model`, `owner`,
   `session` or `worker_claim`. Then try to add one — give a task an
   `assignee` and re-run the schema conformance suite. Decide for yourself
   whether the refusal is structural or incidental.

2. **Work intent named anywhere in the organization resolves in this registry.**
   This is the half that makes it an authority rather than a list: a registry
   coherent with itself and referenced by nothing is a document.
   `docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json` declares a `goal_task_id`,
   and the registry declares an `active_goal`. Change the contract's
   `goal_task_id` to a task that does not exist and re-run
   `tests.test_task_registry`. Check also how the reference is found: whether
   the case walks for references or works from a list someone has to maintain,
   and whether it would pass vacuously if it found none.

3. **Closure is by evidence, not by assertion.** Every task carries
   `required_evidence` naming what would close it. Read the entries for the
   `blocked` tasks in particular, and judge whether what they name is
   genuinely checkable or merely restates the task. One of them names a
   decision the repository owner has to record; consider whether a registry
   that can name an unmade decision as the thing blocking work is doing more
   or less than a status field.

**What this does not establish, and I would rather you confirm it than take
it from me**

The registry cannot carry a claim at all. That is deliberate — but it means
this surface establishes work *intent* and says nothing whatever about who
holds a task. Search the repository for `worker_claim` or `WorkerCoordinator`:
you should find a declaration and its test, and **no claim surface**. So the
declared invariant has two halves and this organization holds one of them.
Whether `in_review` is the right status for that is a judgement, and it is
yours rather than mine.

Report where a declaration is made but not enforced, and equally where an
enforcement exists that nothing declares. That failure mode — an invariant
stated in a document and not held by the running surface — is the specific
thing under review, and the section above this prompt records one I found in
our own documents while preparing it.

**What this does not grant you.** Nothing here confers admissibility, standing,
execution or transition authority. Validation and merge grant no runtime
authority, and the registry's own records say so. Nothing asks you to deploy,
merge or publish anything.

## What this prompt still does not cover

Whether the tasks in the registry are the *right* work, which is a judgement
about the roadmap rather than about the invariant; and the WorkerCoordinator
half named above, which has no surface in this organization to review.
