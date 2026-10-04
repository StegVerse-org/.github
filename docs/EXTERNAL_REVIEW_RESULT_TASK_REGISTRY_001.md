# External review result 001 — the Task Registry as work-intent authority

    document_id:     EXTERNAL-REVIEW-RESULT-TASK-REGISTRY-001
    status:          RECORDED_EXTERNAL_RESULT
    authority_effect: NONE_REVIEW_RECORD_ONLY
    reviewer:        Richard Whitney, external
    reviewed:        docs/EXTERNAL_REVIEWER_TASK_REGISTRY_PROMPT.md
    date:            2026-10-04
    instrument:      the reviewer's own LLM, against a clean public clone
    provenance:      every change in the pull request carrying this document
                     exists because of this review

## Why this is recorded at all

`EXTERNAL_REVIEWER_TASK_REGISTRY_PROMPT.md` asked a reviewer to attack three
claims rather than read them, and asked one question outright: whether
`in_review` is the right status for an invariant with two halves. This is the
first time anyone outside this organization has run it. The result is recorded
because an assessment nobody reproduced is the thing the prompt exists to stop
being.

The reviewer's text is quoted rather than summarized where it carries the
finding. It is evidence, not canon.

## What was run

A clean clone of the public repository, with `jsonschema` present so the
conformance suite ran as well as the standard-library suite. Twenty cases
green. Then three injections, two of which this organization did not write.

## Claim 1 — entity neutrality. Held, and in a layer the prompt did not name

> "CLAIM 1 holds in two layers, not one. Adding an assignee to a task fails
> conformance with `not in the schema: ['assignee']`, which is
> additionalProperties doing real work. It also fails [cases] in the
> standard-library suite, so entity-neutrality survives jsonschema not being
> installed -- you undersold that one."

Correct, and the prompt is corrected in the same pull request. Its claim-1
instruction said "re-run the schema conformance suite", which pointed only at
the layer that needs a dependency. Reproduced here:

```text
assignee added to a task

tests.test_task_registry                      FAIL test_no_task_records_which_entity_is_doing_the_work
                                              FAIL test_every_task_carries_the_required_fields_and_no_others
tests.test_task_registry_schema_conformance   ERROR test_the_registry_validates_against_the_schema
                                              FAIL  test_every_field_the_registry_uses_is_one_the_schema_defines
```

Two cases in the standard-library suite rather than the three the review
reports. The count differs; the finding does not, and the finding is the part
that matters: the refusal does not depend on `jsonschema` being installed.

## Claim 2 — resolution. Held against an injection we could not have anticipated

> "Pointing the contract's `goal_task_id` at a task that doesn't exist fails
> with the path, the key and the value named. Then I made up a location you
> could not have anticipated -- a new file at `orchestration/sub/injected.json`
> with the reference nested two levels down -- and the walk found it. That is
> discovery by rglob rather than a list somebody maintains, which is the
> difference between an authority and a document. And removing the contract's
> reference entirely trips your vacuity guard: *no task reference discovered;
> the walk is not working.* A check that cannot pass by finding nothing is
> rarer than it should be."

All three reproduced here, including the file he invented:

```text
goal_task_id -> a task that does not exist      FAIL test_every_declared_task_reference_resolves
orchestration/sub/injected.json, nested twice   FAIL test_every_declared_task_reference_resolves
the reference removed entirely                  FAIL test_every_declared_task_reference_resolves
                                                ERROR test_the_contracts_goal_task_id_is_a_task_in_this_registry
```

The second line is the one worth keeping. A reference in a file this
organization did not write, at a path it did not anticipate, nested two levels
below the root, was found — so resolution is discovery rather than a
maintained list, which is what the claim asserted and what a maintained list
could have faked.

> "The exemptions test is a nice touch you did not mention. A carve-out for a
> file that no longer exists fails -- so the exemption list cannot rot into a
> silent skip."

Also reproduced: a `FOREIGN_REGISTRY_PATHS` entry naming a path that is not
present fails `test_the_exemptions_are_real_paths_naming_foreign_registries`.
He is right that the prompt did not mention it. It was not withheld; it was not
thought of as a claim worth making, which is its own small lesson about what a
prompt chooses to advertise.

## Claim 3 — closure by evidence. Held, and the flagged item read correctly

> "'A recorded decision on what a lost compare-and-swap leaves behind' is doing
> more than a status field, not less. Blocked tells me nothing. That names the
> specific unmade decision doing the blocking, and a decision is checkable in
> the only way decisions ever are: it's in writing or it isn't. It also refuses
> to let an engineering fix stand in for a judgment nobody has made yet."

Recorded without further comment. The prompt invited the reviewer to judge
whether that evidence was checkable or merely restated the task, and this is
that judgement.

## The stated limit — confirmed rather than taken

> "worker_claim appears in six files, and the only JSON occurrence is
> `worker_claim_authority: WorkerCoordinator` -- which names an authority and
> carries no claim. A declaration, its test, and no surface."

The JSON occurrence is exactly as described and is the only one:
`data/organization-role-runtime-reality-deployment.json`. The file count
measured here is four tracked files rather than six, which may reflect a
different clone point; it does not bear on the finding.

This is the limit the prompt asked to have confirmed rather than believed, and
it was.

## The disagreement, which is the result

> "The invariant has two halves and `in_review` covers both, which flatters one
> and insults the other. Work-intent authority is enforced -- structurally, in
> two layers, against injections I invented on the spot. Claim authority has no
> surface at all, and a thing with no surface is not in review, it is absent. I
> would split them and say so: `enforced`, and `not_started`. Those are
> different claims about different objects, and collapsing them is the same
> move as rounding an unknown up to a pass."

This answers the question the prompt asked rather than contradicting a claim it
made, and this organization accepts it:

```text
the Task Registry is work-intent authority    enforced
claim authority has a reviewable surface      not_started
```

`not_started` is the harder half of that to say and the reason to say it. An
absent thing recorded as `in_review` reads as work underway, and nothing is
underway. The reviewer's phrase for why is better than ours: collapsing the two
is the same move as rounding an unknown up to a pass — which is the defect
class the assessment is about, appearing in the assessment's own status field.

The assessment is the reviewer's document and is not edited from here. What
this organization can do is stop repeating a single status for two objects in
its own surfaces, and that is what the pull request carrying this document
does.

## What this result does not establish

```text
One reviewer agreeing is not independent replication, and a second reviewer
  disagreeing with the first is a result worth having. The question stays open
  in the prompt.
Surviving three injections is not surviving every injection. Two of the three
  were invented by the reviewer, which is better than three of ours, and is
  still not a proof.
Nothing here gives claim authority a surface. It remains absent, and now says
  so in the word it deserves.
A recorded external result confers no admissibility, standing, execution or
  transition authority.
```
