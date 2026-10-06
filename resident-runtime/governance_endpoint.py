#!/usr/bin/env python3
"""`stegverse-org.governance` -- decide a governance manifest that crossed InTr.

The organization registry admitted no service for `governance`, so a governance
manifest had nowhere to be processed: it was either handed to the transport its
return surface names (`LLM_ADAPTER`, refused) or echoed by a boundary-local
diagnostic (crossed, never decided). This is the processor.

It evaluates the governance request the manifest carries with StegCore's
StegGate and returns the disposition. It records nothing itself: the receiving
operation writes the decision to this organization's own ledgers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SERVICE_ID = "stegverse-org.governance"
REQUEST_EXTENSION = "stegverse_governance_request"


def canon(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


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

    result = {
        "schema": "stegverse.org-governance-decision/v1",
        "service_id": SERVICE_ID,
        "decision_authority": "stegcore.steggate.evaluate_admissibility",
        "governance_request_sha256": hashlib.sha256(canon(request)).hexdigest(),
        "external_side_effect": False,
        "authority_effect": "NONE_DECISION_ONLY",
    }
    try:
        from stegcore.steggate import AdmissibilityRequest, evaluate_admissibility
    except ImportError:
        # No decision can be made without the canonical evaluator, and none is
        # substituted. The run is decided FAIL_CLOSED and says why.
        result.update({"disposition": "FAIL_CLOSED", "reason": "GOVERNANCE_RUNTIME_STEGCORE_UNAVAILABLE",
                       "evaluation": None})
    else:
        body = evaluate_admissibility(AdmissibilityRequest(**request)).model_dump(mode="json")
        result.update({"disposition": body.get("disposition"),
                       "reason": body.get("canonical_three_layer_reason"),
                       "evaluation": body})
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
