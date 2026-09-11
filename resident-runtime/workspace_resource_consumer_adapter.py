#!/usr/bin/env python3
"""Organization-local adapter for the canonical SDK WorkSpace resource consumer.

The adapter is intentionally thin: organization registry/dispatch selects this local
file, while the actual WorkSpace projection semantics remain owned by the installed
StegVerse SDK package. This module does not duplicate the consumer, mint InTr
receipts, grant governance authority, or claim MIR/Master Records custody.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SERVICE_ID = "stegverse-org.workspace-resource-consumer"
REQUEST_SCHEMA = "stegverse.workspace-resource-request.v1"
RESPONSE_SCHEMA = "stegverse.workspace-resource-response.v1"


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("workspace-envelope-must-be-object")
    return value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--envelope", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    packet = _load(args.envelope)
    destination = packet.get("destination") or {}
    if destination.get("org") != "StegVerse-org" or destination.get("service") != SERVICE_ID:
        raise SystemExit("wrong-workspace-consumer-destination")

    payload = packet.get("payload")
    if not isinstance(payload, dict) or payload.get("schema") != REQUEST_SCHEMA:
        raise SystemExit("workspace-request-schema-mismatch")

    operation = str(payload.get("operation") or "").strip().upper()
    projection_id = str(payload.get("projection_id") or "").strip()
    interlock_request = payload.get("interlock_request")
    if not operation:
        raise SystemExit("workspace-operation-required")
    if not projection_id:
        raise SystemExit("workspace-projection-id-required")
    if not isinstance(interlock_request, dict):
        raise SystemExit("workspace-interlock-request-required")

    prior_projection_ref = payload.get("prior_projection_ref")
    if prior_projection_ref is not None and not isinstance(prior_projection_ref, str):
        raise SystemExit("workspace-prior-projection-ref-invalid")

    try:
        from stegverse.workspace_resource_consumer import consume_workspace_resource
    except Exception as exc:  # fail closed if the canonical SDK runtime is absent
        raise SystemExit("workspace-sdk-consumer-not-installed") from exc

    try:
        state = consume_workspace_resource(
            request=interlock_request,
            operation=operation,
            projection_id=projection_id,
            prior_projection_ref=prior_projection_ref,
        )
    except Exception as exc:
        raise SystemExit(f"workspace-consumer-rejected:{exc}") from exc

    result = {
        "schema": RESPONSE_SCHEMA,
        "service_id": SERVICE_ID,
        "consumer_profile": state.get("profile"),
        "workspace_state": state,
        "authority_transfer": False,
        "governance_authority": False,
        "intr_receipt_minted_by_adapter": False,
        "mir_custody_claimed": False,
        "master_records_custody_claimed": False,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": "WORKSPACE_RESOURCE_CONSUMED", "projection_state_ref": state.get("projection_state_ref")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
