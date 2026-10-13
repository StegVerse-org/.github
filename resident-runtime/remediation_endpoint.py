#!/usr/bin/env python3
"""`stegverse-org.remediation` -- bind a remediation fork for the next hop of its calculated route.

A non-ALLOW carries its remediation fork (NODE_INGRESS_SETTLED_SPECIFICATION §8;
StegVerse-SDK `stegverse/remediation_fork.py`). The fork's route is calculated
from where the need for remediation was recognized, the packet's manifested
path, and the direct route to StegHealer, and every organization crossing on it
is an Interlock/InTr egress followed by an Interlock/InTr ingress. The SDK
re-derived that route when this organization's ingress derived the request, so
this adapter does not recalculate it. It confirms the lane entered here, at the
route's entry organization, and binds the next hop the route names. The
receiving operation then emits the lane through this organization's `.github`
egress, across InTr, to that organization.

Nothing here classifies, decides or retries. StegHealer classifies; the
classification is non-authorizing and returns through the governance
interfaces.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE_ID = "stegverse-org.remediation"
ORGANIZATION = "StegVerse-org"
REQUEST_EXTENSION = "stegverse_remediation_fork_request"
RESULT_SCHEMA = "stegverse.org-remediation-classification-request/v1"
BOUNDARY = ROOT / "org-runtime/interlock-intr.json"


def canon(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def remediation_binding() -> dict:
    """The overlay's declaration of the remediation capability and the organization that owns it."""
    egress = json.loads(BOUNDARY.read_text()).get("egress") or {}
    for entry in egress.get("capability_destination_bindings") or []:
        if isinstance(entry, dict) and entry.get("profile_id") == "remediation":
            return entry
    raise SystemExit("remediation-destination-binding-not-declared")


def next_hop(route: dict, here: str) -> dict:
    """The InTr egress the calculated route takes from this organization, with its matching ingress."""
    if route.get("entry_organization") != here:
        raise SystemExit("remediation-lane-did-not-enter-at-this-organization:" + str(route.get("entry_organization")))
    hops = route.get("direct_route_to_steghealer")
    if not isinstance(hops, list):
        raise SystemExit("remediation-route-has-no-hops")
    egress = [h for h in hops if isinstance(h, dict) and h.get("from") == here
              and h.get("crossing") == "INTERLOCK_INTR_EGRESS"]
    if len(egress) != 1:
        raise SystemExit("remediation-route-names-no-single-intr-egress-from-this-organization")
    ingress = [h for h in hops if isinstance(h, dict) and h.get("crossing") == "INTERLOCK_INTR_INGRESS"
               and h.get("from") == here and h.get("to") == egress[0].get("to")]
    if len(ingress) != 1:
        raise SystemExit("remediation-route-egress-has-no-intr-ingress")
    return egress[0]


def bind(manifest: dict) -> dict:
    processing = manifest.get("processing") or {}
    if processing.get("capability") != "remediation":
        raise SystemExit("remediation-endpoint-received-other-capability:" + str(processing.get("capability")))
    binding = remediation_binding()
    if processing.get("route_id") != binding.get("route_id"):
        raise SystemExit("remediation-endpoint-received-other-route:" + str(processing.get("route_id")))
    request = (manifest.get("extensions") or {}).get(REQUEST_EXTENSION)
    if not isinstance(request, dict) or not isinstance(request.get("remediation_route"), dict):
        raise SystemExit("remediation-fork-request-missing")
    route = request["remediation_route"]
    hop = next_hop(route, ORGANIZATION)
    steghealer = route.get("steghealer") or {}
    # The calculated route and the overlay must agree on who serves remediation;
    # neither alone may send the lane somewhere the other does not name.
    if (hop.get("to"), steghealer.get("organization"), steghealer.get("service_id")) != (
            binding.get("destination_organization"), binding.get("destination_organization"),
            binding.get("destination_service")):
        raise SystemExit("remediation-route-and-overlay-disagree")
    return {
        "schema": RESULT_SCHEMA,
        "service_id": SERVICE_ID,
        "remediation_request": request,
        "remediation_request_sha256": hashlib.sha256(canon(request)).hexdigest(),
        "remediation_route_sha256": route.get("route_sha256"),
        "next_organization": hop["to"],
        "steghealer_service": steghealer.get("service_id"),
        "steghealer_repository": steghealer.get("repository"),
        "classification_state": "REQUESTED_OF_STEGHEALER",
        "classifier_imported_in_this_organization": False,
        "external_side_effect": False,
        "authority_effect": "NONE_CLASSIFICATION_REQUEST_ONLY",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--envelope", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    packet = json.loads(a.envelope.read_text())
    if (packet.get("destination") or {}).get("service") != SERVICE_ID:
        raise SystemExit("wrong-remediation-destination")
    manifest = (packet.get("payload") or {}).get("manifest")
    if not isinstance(manifest, dict):
        raise SystemExit("remediation-manifest-missing")
    result = bind(manifest)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
