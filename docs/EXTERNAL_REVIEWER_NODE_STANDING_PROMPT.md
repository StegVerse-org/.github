# External reviewer prompt — canonical node standing

A purpose-specific prompt for an external reviewer who will use an LLM to
review the in-review manifest invariant. It is not a general-purpose
introduction to the ecosystem and should not be published as one: a reviewer
with a different purpose or a different access type needs a different prompt.

Why it reads this way. The point of `CANONICAL-NODE-INGRESS-CONTRACT-001` is
that provenance becomes machine-verifiable rather than resolved by documents we
send someone. So this prompt does not describe the ecosystem's claims — it
tells the reviewer to establish standing and read the claims off the node. Two
steps, in that order: establish a healthy node connection, and the instructions
become available. Everything the reviewer needs after step 2 comes from the
node, not from us.

## There is no host, and the contract says so

An earlier revision of this prompt sent the reviewer at
`GET/POST https://<HOST>/api/node-standing`. That was wrong in three separate
ways, and each one would have failed in the reviewer's hands:

1. No such route exists anywhere in this repository, and nothing here serves
   HTTP at all.
2. The body it specified was flat — `{"mode": ..., "node_ref": ...}` — while
   the contract surface reads the declaration from a `standing` key. Fed the
   documented body, `require()` refuses with
   `claimed-standing-not-provable:no-standing-declared`.
3. It contradicted the contract it was meant to exercise. The contract's own
   `machine_readable_instructions` block declares
   `no_new_host_required: true` and `no_new_endpoint_required: true`.

A reviewer handed that prompt would have concluded the claims do not hold, and
would have been right about the prompt while wrong about the invariant. It is
recorded here rather than quietly replaced, because a prompt asserting a
surface that does not exist is the same defect class the reviewer is being
asked to look for — stated in a document, not held by the running surface.

The carrier is a repository checkout. A node registers by running the contract
where the contract lives. That is the same rule the ledger follows: addressed,
not located.

## What the reviewer needs

Nothing from us. `StegVerse-org/.github` is public, and the standing surface is
one stdlib Python module with no third-party dependency and no network access.

## The prompt

Paste the block below into Claude.

---

You are reviewing an invariant that is currently under development in the
StegVerse ecosystem. Do not take my word for its state — the node will tell
you. Everything below runs locally. There is no host, no account, no key, and
nothing to request from me.

**Step 1 — get the node.**

    git clone https://github.com/StegVerse-org/.github stegverse-org-profile
    cd stegverse-org-profile

**Step 2 — ask the node what standing requires.**

    python3 org-boundary/runtime/node_standing.py readiness

This publishes the requirement and grants nothing. Read it before you declare
anything: it tells you the two standing modes, that the `predecessor` key is
mandatory, that `null` means explicit genesis while an absent key fails closed,
and that ordering comes from an oscillator heartbeat epoch rather than any wall
clock. It also publishes both machine-readable continuation profiles, so you
can see what you are being admitted *to* before you declare.

**Step 3 — establish standing, and say what kind of node you are.**

    python3 org-boundary/runtime/node_standing.py establish \
      --node-ref mir-review-node \
      --node-class LLM_OR_MACHINE_ALREADY_CAPABLE_OF_EMITTING_A_CANONICAL_MANIFEST

That class is one of the consumers the contract declares; `readiness` lists
them under `declared_node_classes`. On `ALLOW` the disposition carries
`machine_readable_instructions` and names which profile is yours in
`selected_continuation_profile`. That is the whole point of the handshake: the
continuation is carried on the disposition, so your next step comes from the
node rather than from me.

Omit `--node-ref` and the parser stops you. Declare a `VERIFY_EXISTING`
predecessor that is missing lineage fields and you get `FAIL_CLOSED` with the
reason stated — that is the gate working, not an error to route around.

**Step 4 — follow the instructions the node gave you, not instructions from
me.** Your profile names the SDK functions and CLI commands that build and
submit a canonical manifest, and the owner surface that receives it. Use those
rather than hand-rolling a request.

**What I am asking you to check**

Three claims the ecosystem makes about itself, each of which the node either
substantiates or does not:

1. **Processing is selected only by an admitted manifest's declared
   `processing.capability` bound to `processing.route_id`.** Source identity,
   adapter identity, transport identity and model identity may carry provenance
   but must never independently select processing. Try to get processing to
   happen without declaring a capability, or with a capability bound to a route
   the service does not admit.

2. **Standing is a gate, not a statement.** The node's own disposition says
   `structural_standing_is_authenticated_standing: false` and
   `attestation_owner_state: "NOT_PROVEN"`. I want you to confirm the node is
   honest about the weaker claim rather than reading an `ALLOW` as more than it
   is.

3. **The lineage owner is singular.** A declared predecessor is checked against
   the SDK's own field set, and the disposition carries
   `declared_predecessor_lineage_recomputed: false` — the node says plainly that
   it checked a shape rather than recomputing a chain.

The cases behind all three run offline:

    python3 -m unittest tests.test_node_standing_ingress \
                        tests.test_boundary_processing_selection

Report where a declaration is made but not enforced. That failure mode — an
invariant stated in a document and not held by the running surface — is the
specific thing under review. The section above this prompt records one I found
in the prompt itself; finding more is the assignment, not an embarrassment.

**What this does not grant you.** Standing is structural only. No execution,
route, credential or transition authority is conferred, and every response says
so in its own fields. The continuation is contract data: publishing the steps
is not performing them, and naming an owner surface is not reaching it — the
disposition states both as `continuation_executed_here: false` and
`named_owner_surfaces_reached_here: false`. Nothing here asks you to deploy,
merge or publish anything.

## What this prompt still does not cover

Interlock/InTr. Both continuation profiles declare
`interlock_intr: INTERNAL_POST_SUBMISSION` and
`external_interlock_intr: DEFERRED_TO_SUCCESSOR_AFTER_TESTS_5_AND_6`, so a
reviewer reaching `SUBMIT_CANONICAL_MANIFEST` has not exercised external
organization-to-organization transport and should not be told they have.
