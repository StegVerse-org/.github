# Origin Attestation Mirror Handoff

**Repository:** `StegVerse-org/.github`
**Binding:** `org-boundary/runtime/origin_attestation.py`
**Credential authority:** TV/TVC — `TV_EXPORT_HMAC_SIGN`, `TV_EXPORT_HMAC_VERIFY`
**Authority source:** `StegVerse-Labs/tvc:scripts/tv_credential_verify_export_resident.py`
**Boundary document:** `org-runtime/interlock-intr.json` → `egress.origin_attestation`
**Status:** ORIGIN_ATTESTED_BY_TV_TVC_ASKER_BINDING_STILL_THE_AUTHORITYS

## The one dimension that was the whole score

Every inter-organization record carried:

```json
"origin_attestation_state": "NOT_PROVEN",
"origin_is_asserted_by_the_sender": true,
"origin_is_verified_by_this_boundary": false
```

Measured against RE's ten disorder classes, that single dimension *was* the
score: `unresolved_actor_identity` at 1.0, every other class at zero. A frame in
a shared mesh says it came from this organization and nothing verified it.

## It needed no new capability

`docs/NODE_INGRESS_SETTLED_SPECIFICATION.md` section 4 settled this and said so.
TV/TVC already holds the primitive:

| | |
| --- | --- |
| `TV_EXPORT_HMAC_SIGN` | `scripts/tv_credential_sign_export_resident.py` |
| `TV_EXPORT_HMAC_VERIFY` | `scripts/tv_credential_verify_export_resident.py` |
| key | `TV_HMAC_SIGNING_KEY`, from a systemd credential directory |
| | never persisted, never in a receipt, no development fallback |

The caller cannot forge an attestation because it holds no key. Neither can this
boundary. **It asks.**

## What is attested

A statement naming the crossing and its origin. All six fields are
reconstructible by the receiver from the packet it recovered, so **nothing
travels but the signature**:

```
origin_organization        destination_organization
destination_service        packet_id
payload_sha256             transport_profile
```

A statement that travelled beside its signature would be one the sender could
edit to match. The receiver rebuilds it from the packet instead, and the whole
statement is bound into one digest, so a signature cannot be moved.

The signature travels *inside* the packet, where `packet_sha256` binds it, so
the mesh cannot alter it in transit.

## This boundary does not verify

No signing or verification algorithm appears in it, and both a test and a
boundary check assert that. A repository that could verify a signature itself
would be a second credential authority, which the `credential_authority: TV/TVC`
split exists to prevent. The algorithm is TVC's; the statement shape is this
boundary's.

The authority is **asked to sign and then asked to verify**. Recording `PROVEN`
on the strength of having asked for a signature would be this boundary asserting
its own origin again, one level up — trusting its own request rather than the
authority's answer.

Neither call takes a key. A surface that accepted one from here would let this
boundary hold key material it must never hold.

**An unreachable authority is a hold, never a pass.** An attestation that
silently read as proven when nothing checked it would be the same defect class
as the assertion it replaces, with the record now claiming the opposite of the
truth.

## Three dispositions, kept distinct

| state | means |
| --- | --- |
| `PROVEN` | the authority signed this statement and confirmed its signature |
| `REFUSED` | an attestation was offered and did not establish |
| `NOT_PROVEN` | none was offered — what every crossing carried before |

`REFUSED` is not `NOT_PROVEN`. Collapsing them would hide an attempted forgery
behind the value an ordinary unattested crossing carries. An offered attestation
that fails **refuses the emission** rather than emitting it as unattested.

## What attestation proves, and what it does not

It proves TV/TVC signed this statement, and that whoever assembled the frame
could not have produced the signature. It does **not** prove TV/TVC
authenticated the asker as the organization the statement names: TV/TVC signs
what it is handed, and binding the asker to the claimed origin is TV/TVC's to
do. Its own receipts record `consumer_secret_received: false`, so that binding
is observed nowhere yet.

`tv_consumer_integration_observed` **is** now true, in
`StegVerse-Labs/tvc:receipts/security/tv-consumer-integration-origin-attestation-2026-10-03.json`
(merged at `1e6c909`), which observes this consumer against those functions
from TV/TVC's own side. That is a different flag and it closes a different
gap: the exchange is integrated, and the asker is still not authenticated.
Citing the integration flag as evidence for the asker gap would read the one as
the other.

What closes the gap is already here. Three layers, each necessary, none
sufficient alone:

```
frame digest       integrity -- the packet was not altered in the mesh
TV/TVC signature   a credential authority attested this origin statement
bilateral match    the claimed origin's own chain records emitting it
```

A forged origin would need TV/TVC to sign a statement about a packet the claimed
organization's own ledger holds no emission receipt for. Every record carries
`initiator_identification_also_requires_the_bilateral_match: true` so no reader
takes layer two for the whole proof.

An attested origin is an **identified sender, not an authorized one**.

## The unattested disposition is declared, not implicit

All fourteen peers are unattested today. `unattested_crossing_disposition` is
`ADMITTED_AND_RECORDED_AS_UNATTESTED`, and
`requiring_attestation_is_an_owner_policy_decision_not_made_here: true`.
Refusing unattested crossings would stop inter-organization transport for every
peer at once; that is the owner's call and this change does not make it.

## Verified

Against TV/TVC's **real functions**, not a reimplementation:

```
TV/TVC sign : TV_EXPORT_HMAC_SIGN | hmac-sha256 | key exposed false | fallback used false
statement reconstructs from the frame alone: true
TV/TVC verify: TV_EXPORT_HMAC_VERIFY | signature_valid true

a signature is not transferable:
  forged origin organization      -> REFUSED: digest mismatch
  moved to another packet         -> REFUSED: digest mismatch
  tampered payload digest         -> REFUSED: digest mismatch
  redirected destination org      -> REFUSED: digest mismatch
  redirected destination service  -> REFUSED: digest mismatch
  altered transport profile       -> REFUSED: digest mismatch
  verified under a forger's key   -> signature_valid false
```

TVC's verifier checks the carried digest against the payload *before* the
signature compare, so a changed statement fails closed with a refusal rather
than returning a false. Both are refusals; the type is reported as the authority
stated it.

A real attested crossing, emitted and closed:

```
emission disposition        ALLOW
origin_attestation_state    PROVEN
closure attestation state   PROVEN  (read from this organization's own emission record)

unresolved_actor_identity   0.0   0/2
observed                    10 of 10
any class above zero        none
```

**The measured disorder is zero.** All ten classes observed, every one at 0.0.

```
tests.test_origin_attestation                      24 OK
tests.test_origin_attestation_tvc_conformance       8 OK  (against real TVC)
org-runtime/runtime_boundary.py validate           valid, 16/16
actionlint                                         clean
```

Both CI steps extracted verbatim and run locally.

## What this repository's CI cannot prove

`StegVerse-Labs/tvc` is another organization, and a cross-organization checkout
needs a credential while `github_token_runtime_authority` is NONE — the same
constraint RE's validators are under. So the conformance module **skips** in
this CI and the skip is reported as
`TVC_CONFORMANCE=UNPROVEN_HERE_TVC_NOT_CHECKED_OUT`, never as a pass. It runs
wherever TVC is present via `STEGVERSE_TVC_ROOT`, and it now **also runs in
TVC's own CI**: `tv-consumer-integration-validation.yml` there exercises these
same functions against this consumer's pinned statement shape, and
`tv_consumer_integration_observed` is true as of `1e6c909`. So the exchange is
proven on the side that holds the key, and this repository's skip remains
honest about what it did not prove here.

What this repository's CI does prove is the binding it owns — the statement
shape, the two-call exchange, every refusal predicate, that no credential
algorithm lives here, and that an attested crossing measures zero disorder.

## What this does not close

`credential_bearing_execution_observed: false` and
`post_migration_operational_proof_observed: false` are still TVC's own findings:
the signing source is validated as source and has never signed in a production
run, because the key lives on a TV/TVC resident host and there is no live host.
A test key is used here exactly as TVC's own signing test uses one, so no key
used anywhere in this change can be the production key.

Attestation at *ingress* — a receiving organization refusing an inbound forged
origin — is the natural second half and is a policy decision, not a mechanism
gap: the verification path is built and available.

Nothing here grants authority.
