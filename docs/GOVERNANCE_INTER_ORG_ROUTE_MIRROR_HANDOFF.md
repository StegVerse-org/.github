# Governance inter-organization route — mirror handoff

Organization: `StegVerse-org`
Evidence class: `SOURCE_IMPLEMENTED`. A local three-leg round trip was run (below). No production runtime observation is claimed.

## The rule this implements

Each organization's `.github` is that organization's ingress and egress. StegCore is a StegVerse-Labs repository, so a governance decision belongs to StegVerse-Labs and is reached the way every organization reaches another: out through this organization's `.github`, across Interlock/InTr, in through `StegVerse-Labs/.github`.

Before this change `resident-runtime/governance_endpoint.py` imported StegCore in-process and decided here. The crossing it reported never left this organization.

## The route

```text
SDK manifest (processing.capability = governance)
  -> StegVerse-org/.github  organization_manifest_ingress.receive
       crossing to stegverse-org.governance  (binds the request; decides nothing)
       ORGANIZATION_SDK_MANIFEST_INGRESS        recorded, repo + org ledgers
       organization_egress_boundary.emit        ORGANIZATION_EGRESS_EMITTED, recorded
  -> InTr / federation mesh  (ecosystem.work.request to stegverse-labs.governance)
  -> StegVerse-Labs/.github  kernel dispatch -> governance_endpoint.py -> StegCore StegGate
       ORGANIZATION_GOVERNANCE_DECISION         recorded in StegVerse-Labs' own ledgers
  <- InTr / federation mesh  (ecosystem.work.ack carrying the decision)
  -> StegVerse-org/.github  governance_decision_return.return_decision
       organization_egress_boundary.close       ORGANIZATION_EGRESS_CLOSED, recorded
       runtime result rebuilt from this organization's records
       stegverse.manifest_state_transition_runtime.admit_runtime_result
```

The binding is declared in `org-runtime/interlock-intr.json` under `egress.capability_destination_bindings`: `governance` is sent to `StegVerse-Labs` at `stegverse-labs.governance`, and the egress boundary refuses to send it anywhere else (`CAPABILITY_IS_SENT_TO_THE_ORGANIZATION_THAT_OWNS_IT`).

## Conformance

- **Nothing waits.** `receive` returns once the request is emitted (`awaits_the_decision: false`). The SDK is handed the decision on its return, not before (`sdk_admission: AT_DECISION_RETURN`). `return_decision` with no answer yet is `PENDING` and records nothing — an absence is not an arrival. A receiver that is not running leaves the frame in the mesh, which is the durable queue.
- **The mesh is supplied, not discovered.** A node materialized without a mesh location records the refused emission (`ORGANIZATION_EGRESS_REFUSED`, `mesh_location_required_from_materializer`) and names the repair.
- **Organization records only.** Every transition on this side is appended to this organization's repository and organization ledgers; the decision is appended to StegVerse-Labs' own. The SDK admits the result as `ORGANIZATION_RECORDS_ONLY`. Master Records is not in this path.
- **The answer is verified, not trusted.** `close` recomputes the far side's receipt chain from this organization's own emission record. `return_decision` checks that the decision answers this request (`governance_request_sha256`), this submission (`sdk_request_sha256`), and came from the organization the overlay binds; anything else is decided `FAIL_CLOSED` and handed to the SDK as such.

## The other half

The StegVerse-Labs side — `stegverse-labs.governance`, the kernel's admitted-adapter dispatch, and the StegCore endpoint — lives in `StegVerse-Labs/.github`. It is carried here as `docs/migrations/stegverse-labs.governance-endpoint.patch` (apply with `git am`), with its own tests and workflow.

## Validation

- `tests/test_governance_inter_org_route.py` (`.github/workflows/governance-inter-org-route-validation.yml`, SDK pinned at `657576e`) drives emit, `PENDING`, return, SDK admission, and the refusal paths. The far side is played by the kernel's own `receipt` and `build_control_response`.
- Local round trip across both organizations: the committed fixture `governance-to-llm-adapter.json` entered this ingress, crossed the mesh, was decided by StegVerse-Labs with StegCore `ef38410` (`DENY`, `signal.inputs_incomplete`), and was admitted by the SDK at `657576e` as `ORGANIZATION_RECORDS_ONLY`.
