# Node standing receipt shape

Status: proposed, for review. No code written against this yet.

## Why a receipt and not a response

An HTTP response holds the state of an exchange in the connection. Lose the
signal and the caller cannot tell whether it was recognized. Hold the
processing and the response can only say "not yet," which is an absence rather
than a state.

The ecosystem is state-transition dependent for exactly this reason. A pause in
signal or a hold in processing is itself a transition, and a transition emits a
receipt. Nothing is lost to a dropped connection, because the record was never
in the connection.

## The body

Identical to `org-kernel/kernel.py:receipt` so these reconcile with every other
receipt in the ecosystem, plus the fields a resumable chain needs.

| field | meaning |
| --- | --- |
| `schema` | `stegverse.node-standing-receipt.v1` |
| `kind` | the transition recorded |
| `registration_id` | stable across the whole chain, including resumption |
| `task_digest` | what makes two attempts the same task (see below) |
| `subject` | the declaring node's `node_ref` |
| `previous_receipt_id` | the chain; `null` only at genesis |
| `heartbeat_reference` | oscillator epoch, never a clock reading |
| `next_expected` | the transition this chain is waiting on; `null` when terminal |
| `detail` | transition-specific evidence |
| `receipt_id` | `<kind lowercased>-<sha256(body)[:24]>` |
| `evidence_hash` | `sha256(body)` |

`next_expected` is what distinguishes *held* from *finished*. The crossing
chain has a fixed five transitions so terminal is implicit; a registration can
legitimately stop at a hold and continue later, so a reader must be able to
tell the difference without guessing.

## Transitions

| kind | means | repeatable |
| --- | --- | --- |
| `REGISTRATION_RECEIVED` | a declaration arrived; nothing resolved | no |
| `STANDING_RESOLVED` | ALLOW / DENY / FAIL_CLOSED, in `detail` | no |
| `RECOGNITION_HELD` | attestation not yet obtained | yes |
| `RECOGNITION_ATTESTED` | TV/TVC signed it; `TV_EXPORT_HMAC_SIGN` evidence in `detail` | no |
| `INSTRUCTIONS_RELEASED` | the continuation was handed over; terminal | no |
| `REMEDIATION_CLASSIFIED` | a failure was classified; the judgement joins the evidence | yes |

A terminal chain ends at `INSTRUCTIONS_RELEASED`, or at `STANDING_RESOLVED`
carrying DENY or FAIL_CLOSED. A refusal is terminal and complete, not a hold.

## Resumption continues the chain

A resumed registration keeps the same `registration_id` and its
`previous_receipt_id` points at the held receipt. It never starts a new chain.

A new chain referencing a held one would create two candidate records for one
exchange, and every consumer would then have to decide which is authoritative.
That ambiguity cannot be closed afterwards; it is inherited by everything
downstream. One chain, one truth.

## Task identity

Two attempts are the same task when their `task_digest` matches.

* A **registration** chain has no manifest yet, so its `task_digest` is the
  canonical digest of the standing declaration: `mode`, `node_ref`,
  `generation`, `predecessor`.
* A **submission** chain's `task_digest` is the `manifest_sha256`.

This also draws the boundary resumption needs. The same digest after a failure
is a resumed chain. A different digest is a genuinely different exchange and
*should* be a new chain. So the rule is operable rather than a judgement call.

A registration chain's terminal receipt becomes the predecessor of the
submission chain that follows it, which is how a genesis receipt devolves into
the full tree from the inception of recording.

## Retry is a signal, not a counter

Retry is not a field. It is an observation about the chain: the same
`task_digest` attempted again after a failure.

A counter would record how many times and nothing about why. Reading it as a
signal lets a transient fault be told apart from a participant that is
genuinely broken, which is only visible in the pattern.

Remediation is therefore a separate concern that *reads* chains. It classifies
the failure and either remediates it, records that a temporary condition
resolved, or records that a recurring source is failing. Its classification
mints `REMEDIATION_CLASSIFIED` into the same chain, so the judgement sits
inside the evidence it was based on rather than beside it.

This keeps a separation the ecosystem holds everywhere: receipts record,
selection decides, standing gates, and nothing does two jobs. The registration
path stays truthful and dumb; interpretation lives elsewhere.

## Open: the remediation threshold

If retries are transitions, a persistently failing participant grows an
unbounded chain. That is correct as evidence, but "retry is a signal" needs a
point at which something notices, or nothing ever acts on it.

The threshold is not set here. It belongs to whoever owns remediation, and
naming a number in this document would make this a second authority on it.

## What this grants

Nothing. A receipt records that a transition occurred. It admits no transition,
advances no generation, and confers no authority. `RECOGNITION_ATTESTED` proves
TV/TVC signed a recognition statement; it does not make the recognized node
authorized for anything.
