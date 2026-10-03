# Node ingress: settled specification

Every decision below is made. Where a name or value was chosen rather than
read off an existing owner, it says so, so it can be overridden in one pass.

## 1. What this settles

Four things were unsettled and each caused real breakage:

* **"API" meant two things.** The SDK contract's `builder_api`,
  `validator.api` and `submission_api` are *Python function paths*. The
  adapter's `/api/...` routes are *HTTP*. Reading the first as the second
  produced instructions telling a caller to reach `process_manifest`, which no
  caller could reach over any transport.
* **Request/response loses work.** A response holds the exchange's state in the
  connection. A dropped signal cannot be told from a refusal, and a hold can
  only be reported as "not yet," which is an absence rather than a state.
* **Standing was inside the manifest.** `governed_manifest_ingress` required
  `node_endpoint` and `predecessor` as manifest fields. The SDK's own runtime
  rejects those as unknown top-level fields, so a manifest the adapter accepted
  could not be handed off at all.
* **Recognition was self-asserted.** `node_endpoint.recognized: true` is a
  field the caller writes. The contract forbids treating a caller-editable
  field as authoritative evidence.

## 2. Naming

Transport surfaces are `/intr/...`. This is not a new convention: the adapter
already serves `/intr/evaluator`, `/intr/materialization`, `/intr/profile`,
`/intr/source-package`, `/intr/device-kv` and `/intr/sv`.

`/api/...` stays for the non-InTr gateway surfaces that already use it. It is
not extended to anything that carries a state transition, because a name that
says "API" invites request/response usage, and request/response is what loses
the work.

| surface | purpose |
| --- | --- |
| `/intr/node/standing/readiness` | publish what standing requires; grants nothing |
| `/intr/node/standing` | register a node; emits a receipt chain |
| `/intr/node/standing/{registration_id}` | re-read the chain after a gap |
| `/intr/sdk/contract` | the SDK's own machine contract |
| `/intr/sdk/manifest/build` | build; refusal returned verbatim |
| `/intr/sdk/manifest/validate` | check; side-effect free |
| `/intr/sdk/manifest/handoff` | hand off to the installed runtime |

`handoff`, not `submit`. The SDK states that it does not perform the transition
and does not wait for one; `submit` implies a completed act and would be read
as a result.

**Chosen, not read:** the path segments themselves. The `/intr/` prefix is the
repository's; the words after it are mine.

## 3. Standing lives on the crossing, never in the manifest

The manifest stays as the SDK builds it. Standing travels beside it, where the
transfer envelope already carries it as `canonical_node_standing`.

This is not a preference. The SDK runtime refuses a manifest carrying
`node_endpoint`, `node_standing_mode`, `generation` or `predecessor` at top
level, so the end-to-end path is blocked until they come out. The adapter
already reads them *out* of the manifest and into the envelope, so the envelope
is the established home and the manifest copy is the redundant one.

Removing them also removes the self-assertion hole, because recognition stops
being a field anyone writes.

## 4. Recognition is attested by TV/TVC

`recognized` is not consulted from the manifest. The boundary determines
recognition from the standing it resolved on that same crossing, and TV/TVC
attests it.

TV/TVC already has the primitive: `TV_EXPORT_HMAC_SIGN` and
`TV_EXPORT_HMAC_VERIFY`, merged at `3faf0e5` (PR 106, 7/7 pass,
`hard_coded_development_key_fallback_present: false`). The caller cannot forge
an attestation because it holds no key; the adapter cannot either, for the same
reason. It asks.

This is what fills `attestation_owner_state: NOT_PROVEN`, and it required no
new TVC capability.

## 5. The destination comes from the capability overlay

Not from an injected callable. The SDK already declares it:

```
DESTINATION_RESOLUTION_SOURCE = CANONICAL_CONNECTOR_CAPABILITY_OVERLAY
UNIVERSAL_RUNTIME_BINDING     = stegverse.manifest_state_transition_runtime.execute_manifest
RECEIVER_UNAVAILABLE_DISPOSITION = DURABLE_QUEUE_OR_EVENT_EPHEMERAL_MATERIALIZATION
```

Every published route carries `runtime_installed: true`. The receiver was never
missing; it was never bound.

An unavailable receiver is a durable queue or an ephemeral re-materialization,
not a dropped call. That is the owner's disposition, not this document's.

## 6. Every transition emits a receipt

The body is `org-kernel/kernel.py:receipt` unchanged, so these reconcile with
every other receipt in the ecosystem, plus `registration_id`, `task_digest` and
`next_expected`.

`next_expected` distinguishes held from finished. The crossing chain has a
fixed five transitions so terminal is implicit; a registration can legitimately
stop at a hold and continue later.

| kind | means |
| --- | --- |
| `REGISTRATION_RECEIVED` | a declaration arrived; nothing resolved |
| `STANDING_RESOLVED` | ALLOW / DENY / FAIL_CLOSED |
| `RECOGNITION_HELD` | attestation not yet obtained |
| `RECOGNITION_ATTESTED` | TV/TVC signed it |
| `INSTRUCTIONS_RELEASED` | the continuation was handed over; terminal |
| `HANDOFF_EMITTED` | a manifest was handed to the installed runtime |
| `RESULT_ADMITTED` | a result came back through `admit_runtime_result` |

A refusal is terminal and complete, not a hold.

`HANDOFF_EMITTED` and `RESULT_ADMITTED` are two transitions because the SDK
makes them two: handoff returns a disposition, and the result arrives
separately. The gap between them is the thing a response body cannot represent.

**A hold carries its own reason, read from the disposition rather than
invented.** The SDK's handoff disposition already names
`failed_predicate`, `failure_code`, `required_evidence_or_repair`,
`next_attempt` and `retry_entrypoint`. `RECOGNITION_HELD` and any other hold
carry those through verbatim.

## 7. Resumption continues the chain

Same `registration_id`; `previous_receipt_id` points at the held receipt. Never
a new chain.

A new chain referencing a held one leaves two candidate records for one
exchange, and every consumer downstream must then decide which is
authoritative. That ambiguity cannot be closed afterwards; it is inherited.

Task identity decides what counts as the same exchange. A registration chain's
`task_digest` is the canonical digest of the declaration (`mode`, `node_ref`,
`generation`, `predecessor`); a handoff chain's is `manifest_sha256`.
Registration happens before any manifest exists, so the two cannot share one
rule. Same digest after a failure is a resumed chain; a different digest is a
different exchange and should be a new one.

A registration chain's terminal receipt is the predecessor of the handoff chain
that follows it, which is how a genesis receipt devolves into the full tree.

## 8. Retry is a signal; remediation is a forked lane

Retry is not a field and not a counter. It is an observation about a chain: the
same `task_digest` attempted again after a failure. A counter records how many
times and nothing about why.

The SDK already behaves this way: a correctable DENY is repaired and
re-manifested once, producing a new handoff with its own distinct hash, never a
replay of the identical request.

Remediation is a **remediation manifest carried on the packet**. Its job is to
recognize patterns that indicate errors or failures. On recognizing one it
releases from the main packet and goes to `StegVerse-Labs/StegHealer`, while
the main packet proceeds to its own destination simultaneously. Two lanes, one
fork, each with its own receipts.

Its classification mints `REMEDIATION_CLASSIFIED` into the chain it judged, so
the judgement sits inside the evidence it rests on.

**Open, and deliberately not set here:** the threshold at which a pattern
becomes a signal. That belongs to whoever owns remediation; a number in this
document would make it a second authority.

## 9. Order of work

Each step is verifiable before the next begins.

1. **Standing out of the manifest.** `governed_manifest_ingress` drops
   `node_endpoint` and `predecessor` from required fields and takes standing on
   the call. All 18 existing tests port rather than being deleted — they are
   right about intent and wrong about location.
2. **Handoff bound.** The handoff surface calls `execute_manifest` and returns
   the disposition as a disposition. Already proven to reach the runtime; it
   fails closed on `CANONICAL_ORGANIZATION_INGRESS_ENDPOINT_NOT_RESOLVED`,
   which is step 3.
3. **Capability overlay entry.** Resolve `sdk-manifest-ingress` /
   `SDK:ManifestIngress` to the organization ingress endpoint, which is what the
   SDK's `required_evidence_or_repair` asks for.
4. **Receipts.** Every transition above emits one; the chain is re-readable.
5. **TV/TVC attestation.** Recognition signed and verified.
6. **Rename to `/intr/`.** Last, because a rename of a settled surface is
   mechanical and a rename of an unsettled one is churn.
7. **Remediation lane.** After end-to-end works, never before.

## 10. What this does not claim

No deployment. No host. No authority. A receipt records that a transition
occurred; it admits no transition, advances no generation and confers nothing.
An attested recognition proves TV/TVC signed a statement, not that the
recognized node is authorized for anything.

No `current_proof_boundary` status in `CANONICAL-NODE-INGRESS-CONTRACT-001` is
upgraded by this document.
