#!/usr/bin/env python3
"""`stegverse-org.governance` -- bind a governance manifest's request for the organization that decides it.

A governance manifest submitted to this organization is processed here, and the
governance request it carries is decided by StegCore's StegGate. StegCore is a
StegVerse-Labs repository, so the decision belongs to StegVerse-Labs, reached
the way every organization reaches another: out through this organization's
`.github` egress, across Interlock/InTr, in through StegVerse-Labs/.github.
This organization does not import StegCore and decide for itself.

So this processor makes no decision. It binds the request to the manifest that
carried it -- the request, its digest, and the organization the overlay binds
`governance` to -- and the receiving operation emits it outbound. The decision
returns on the crossing's closure, through
`resident-runtime/governance_decision_return.py`, and is recorded in this
organization's records before the SDK is handed it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE_ID = "stegverse-org.governance"
REQUEST_EXTENSION = "stegverse_governance_request"
REQUEST_SCHEMA = "stegverse.org-governance-decision-request/v1"
BOUNDARY = ROOT / "org-runtime/interlock-intr.json"


def canon(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def governance_binding() -> dict:
    """The organization the overlay binds `governance` to, read from the overlay."""
    egress = json.loads(BOUNDARY.read_text()).get("egress") or {}
    for entry in egress.get("capability_destination_bindings") or []:
        if isinstance(entry, dict) and entry.get("profile_id") == "governance":
            return entry
    raise SystemExit("governance-destination-binding-not-declared")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--envelope", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    packet = json.loads(a.envelope.read_text())
    if (packet.get("destination") or {}).get("service") != SERVICE_ID:
        raise SystemExit("wrong-governance-destination")
    manifest = (packet.get("payload") or {}).get("manifest")
    if not isinstance(manifest, dict):
        raise SystemExit("governance-manifest-missing")
    processing = manifest.get("processing") or {}
    if processing.get("capability") != "governance":
        raise SystemExit("governance-endpoint-received-other-capability:" + str(processing.get("capability")))
    request = (manifest.get("extensions") or {}).get(REQUEST_EXTENSION)
    if not isinstance(request, dict):
        raise SystemExit("governance-request-missing")

    binding = governance_binding()
    result = {
        "schema": REQUEST_SCHEMA,
        "service_id": SERVICE_ID,
        "governance_request": request,
        "governance_request_sha256": hashlib.sha256(canon(request)).hexdigest(),
        "decision_state": "REQUESTED_OF_DECIDING_ORGANIZATION",
        "deciding_organization": binding["destination_organization"],
        "deciding_repository": binding["destination_repository"],
        "deciding_service": binding["destination_service"],
        "decision_authority": binding["decision_authority"],
        "decision_authority_repository": binding["decision_authority_repository"],
        "evaluator_imported_in_this_organization": False,
        "external_side_effect": False,
        "authority_effect": "NONE_DECISION_REQUEST_ONLY",
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
