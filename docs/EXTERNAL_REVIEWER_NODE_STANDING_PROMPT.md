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

`<HOST>` is the node address, filled in at the time of sending. The prompt is
transport-agnostic; it has been used over LinkedIn DM.

## The prompt

Paste the block below into Claude. Replace `<HOST>` with the StegVerse node
address.

---

You are reviewing an invariant that is currently under development in the
StegVerse ecosystem. Do not take my word for its state — the node will tell you.

**Step 1 — ask the node what standing requires.**

    GET https://<HOST>/api/node-standing/readiness

This publishes the requirement and grants nothing. Read it before you send
anything: it tells you the two standing modes, that the `predecessor` key is
mandatory, that `null` means explicit genesis while an absent key fails closed,
and that ordering comes from an oscillator heartbeat epoch rather than any wall
clock.

**Step 2 — establish standing.**

    POST https://<HOST>/api/node-standing
    Content-Type: application/json

    {"mode": "ESTABLISH_GENESIS",
     "node_ref": "<a name for your side, e.g. mir-review-node>",
     "predecessor": null}

On `ALLOW` the response carries `machine_readable_instructions`. That is the
whole point of the handshake: the continuation is not published on the public
advertisement, so the instructions exist only on the far side of the contract.
If you omit `predecessor` you will get `FAIL_CLOSED` with the reason stated —
that is the gate working, not an error to route around.

**Step 3 — follow the instructions the node gave you, not instructions from me.**

The response contains two profiles. `EXTERNAL_FRAMEWORK_MANIFEST_CONTINUATION`
is the one for you: it names the SDK functions and CLI commands that build and
submit a canonical manifest. Use those rather than hand-rolling a request.

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

Report where a declaration is made but not enforced. That failure mode — an
invariant stated in a document and not held by the running surface — is the
specific thing under review.

**What this does not grant you.** Standing is structural only. No execution,
route, credential or transition authority is conferred, and every response says
so in its own fields. Nothing here asks you to deploy, merge or publish
anything.
