#!/usr/bin/env python3
"""Carry an SDK manifest across the organization boundary.

An SDK manifest declares where it is bound -- `completion.egress`, naming a
`final_stegverse_transition_surface` reached over `INTERLOCK_INTR` with
`far_side_transition_required` true. The SDK deliberately holds no transport
client, and this organization's contract says the same thing from the other
side: ALL_ORGANIZATION_INGRESS_EGRESS_GENERATED_AT_ORG_DOT_GITHUB_BOUNDARY.

Both halves were right and nothing joined them. The SDK prepared a handoff and
stopped; the boundary could complete a crossing but was never handed anything.
This is the join: it reads the destination a manifest declares, resolves it
against the service registry, and drives the crossing the boundary already
performs.

It consumes an SDK *artifact*, never the SDK itself, so the two repositories
stay decoupled -- the SDK produces a document, the boundary transports it.

Nothing here grants authority. The crossing's authority effect is whatever the
manifest's transition declares, and this module does not supply one.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSOR = ROOT / "org-boundary/runtime/process_boundary.py"
BOUNDARY_WRITE_FAULT_EXIT = 75

_spec = importlib.util.spec_from_file_location(
    "intr_transport", ROOT / "org-boundary/runtime/intr_transport.py")
intr_transport = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(intr_transport)

INTR_TRANSPORT = "INTERLOCK_INTR"

# What the boundary recorded about how processing was selected. The SDK reads
# this result, so a completed crossing that omitted the record would read as a
# manifest's declared capability having been processed when it may not have
# been -- the overclaim `SDK-GENERIC-MANIFEST-ECOSYSTEM-INVARIANT-005` exists
# to remove. The boundary's values are carried through, never recomputed here.
SELECTION_FIELDS = ("processing_selection", "declared_capability", "declared_route_id",
                    "declared_capability_processed", "route_admissibility",
                    "identity_selected_by")

# Every non-ALLOW this module produces carries these six fields, so a caller can
# repair and retry without reading prose (D6; the conformance standard's rule 5
# in docs/ORGANIZATION_ROLE_RUNTIME_REALITY_DEPLOYMENT.md). They are data on the
# refusal, never an authority: a refusal grants nothing.
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
OWNING_EXISTING_GOAL = "INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001"
RETRY_ENTRYPOINT = "resident-runtime/sdk_manifest_crossing.py::cross"
#: The protocol's own answer to a receiver that is not there. Nothing waits on
#: it, polls for it or reports its absence as a blocker.
RECEIVER_UNAVAILABLE_DISPOSITION = "DURABLE_QUEUE_OR_EVENT_EPHEMERAL_MATERIALIZATION"

#: Each code-only refusal: the predicate it failed and the repair that clears it.
REFUSALS = {
    "CROSSING_REQUIRES_MATERIALIZED_CAPABILITY_MAP": (
        "CROSSING_IS_GIVEN_A_MATERIALIZED_CAPABILITY_MAP",
        "supply the organization's materialized capability map "
        "(org-boundary/registry/services.json) as a JSON object"),
    "MANIFEST_DECLARES_NO_EGRESS": (
        "MANIFEST_DECLARES_COMPLETION_EGRESS",
        "declare completion.egress as an object in the manifest"),
    "MANIFEST_DECLARES_NO_TRANSITION_SURFACE": (
        "MANIFEST_DECLARES_A_FINAL_TRANSITION_SURFACE",
        "declare completion.egress.final_stegverse_transition_surface as a non-empty string"),
    "MANIFEST_DECLARES_NON_INTR_TRANSPORT": (
        "MANIFEST_DECLARES_INTERLOCK_INTR_TRANSPORT",
        "declare completion.egress.transport as INTERLOCK_INTR"),
    "MANIFEST_DECLARES_NO_FAR_SIDE_REQUIREMENT": (
        "MANIFEST_DECLARES_FAR_SIDE_TRANSITION_REQUIREMENT",
        "declare completion.egress.far_side_transition_required as a boolean"),
    "ORG_EXPOSES_NO_SUCH_TRANSITION_SURFACE": (
        "DECLARED_SURFACE_RESOLVES_TO_EXACTLY_ONE_SERVICE",
        "declare a transition surface this organization registers, or register the "
        "service in org-boundary/registry/services.json"),
    "TRANSITION_SURFACE_AMBIGUOUS_IN_REGISTRY": (
        "DECLARED_SURFACE_RESOLVES_TO_EXACTLY_ONE_SERVICE",
        "leave exactly one service in org-boundary/registry/services.json whose id "
        "matches the declared surface"),
    "PROCESSING_AMBIGUOUS_IN_REGISTRY": (
        "DECLARED_PROCESSING_PAIR_IS_ADMITTED_BY_AT_MOST_ONE_SERVICE",
        "leave exactly one admits_processing row for the declared {capability, route_id} "
        "in org-boundary/registry/services.json"),
    "CROSSING_REQUIRES_DECLARED_STANDING": (
        "CROSSING_STANDING_IS_DERIVED_FROM_THE_MANIFEST_OR_DECLARED",
        "declare the crossing standing (mode, node_ref and the predecessor key), or submit a "
        "manifest that carries its own generation and predecessor"),
    "CROSSING_STANDING_MUST_DECLARE_THE_PREDECESSOR_KEY": (
        "CROSSING_STANDING_DECLARES_THE_PREDECESSOR_KEY",
        "declare the standing as an object carrying the predecessor key (null is explicit genesis)"),
}


def refusal_fields(code, detail=""):
    """The six fields of a code-only refusal, built from the code it was raised with."""
    failed_predicate, repair = REFUSALS[code]
    return {
        "failure_code": code,
        "failed_predicate": failed_predicate,
        "required_evidence_or_repair": repair + (" (" + detail + ")" if detail else ""),
        "retry_entrypoint": RETRY_ENTRYPOINT,
        "owning_existing_goal": OWNING_EXISTING_GOAL,
        "next_attempt": "resubmit the same manifest once the repair is in place; "
                        "nothing crossed and nothing was dispatched",
    }


class CrossingRefused(SystemExit):
    """A refusal that is still a `SystemExit`, now carrying the six fields.

    It stays a `SystemExit` so the CLI exits as it did and every caller that
    catches `SystemExit` keeps working; `str()` is the message it always had.
    The six fields ride on `.refusal` for a caller that passes them through.
    """

    def __init__(self, code, detail=""):
        super().__init__(code + (":" + detail if detail else ""))
        self.code = code
        self.refusal = refusal_fields(code, detail)


def far_side_fields(service, disposition):
    """The six fields of a crossing the far side did not complete.

    A service with no installed endpoint adapter is an unavailable receiver:
    the protocol answers it with RECEIVER_UNAVAILABLE_DISPOSITION and nothing
    waits or polls. An installed adapter that refused is the far side's own
    refusal, stated as it was given.
    """
    if not service.get("endpoint_adapter"):
        return {
            "failure_code": "FAR_SIDE_RECEIVER_UNAVAILABLE",
            "failed_predicate": "RESOLVED_SERVICE_HAS_AN_INSTALLED_ENDPOINT_ADAPTER",
            "required_evidence_or_repair": "install the endpoint adapter for "
                                           + str(service.get("service_id"))
                                           + " (" + disposition + ")",
            "retry_entrypoint": RETRY_ENTRYPOINT,
            "owning_existing_goal": OWNING_EXISTING_GOAL,
            "next_attempt": RECEIVER_UNAVAILABLE_DISPOSITION
                            + ": the crossing is re-driven when the receiver is materialized "
                              "by the next event; nothing waits or polls",
        }
    return {
        "failure_code": "FAR_SIDE_REFUSED_THE_CROSSING",
        "failed_predicate": "ADMITTED_CROSSING_REACHES_ITS_INTERNAL_ENDPOINT",
        "required_evidence_or_repair": "satisfy the far side's refusal at "
                                       + str(service.get("service_id")) + " (" + disposition + ")",
        "retry_entrypoint": RETRY_ENTRYPOINT,
        "owning_existing_goal": OWNING_EXISTING_GOAL,
        "next_attempt": "resubmit the same manifest once the far side admits it; "
                        "the far side's refusal is returned verbatim",
    }


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def declared_destination(manifest):
    """Read the far side the manifest declares, and nothing else.

    This never supplies, discovers or defaults a destination. A manifest that
    declares none is not bound anywhere, and carrying it would be inventing a
    route its author did not ask for.
    """
    egress = (manifest.get("completion") or {}).get("egress")
    if not isinstance(egress, dict):
        raise CrossingRefused("MANIFEST_DECLARES_NO_EGRESS")
    surface = egress.get("final_stegverse_transition_surface")
    if not isinstance(surface, str) or not surface.strip():
        raise CrossingRefused("MANIFEST_DECLARES_NO_TRANSITION_SURFACE")
    # Read the transport, never assume it. Defaulting an absent transport to
    # InTr would carry a manifest over a crossing its author never declared --
    # the same defaulting this module's own docstring refuses.
    transport = egress.get("transport")
    if transport != INTR_TRANSPORT:
        raise CrossingRefused("MANIFEST_DECLARES_NON_INTR_TRANSPORT", str(transport))
    required = egress.get("far_side_transition_required")
    if not isinstance(required, bool):
        raise CrossingRefused("MANIFEST_DECLARES_NO_FAR_SIDE_REQUIREMENT")
    return {"surface": surface.strip(), "transport": transport,
            "far_side_transition_required": required}


def resolve_surface(surface, registry):
    """Resolve a declared surface to exactly one registered service.

    Resolution is by exact match on the normalized surface against the tail of
    a service id, and it requires exactly one. Zero means the organization does
    not expose that surface; more than one means the registry is ambiguous and
    guessing which was meant is worse than refusing.
    """
    normalized = surface.strip().lower().replace("_", "-")
    matches = [service for service in registry.get("services", [])
               if str(service.get("service_id", "")).split(".", 1)[-1] == normalized]
    if not matches:
        raise CrossingRefused("ORG_EXPOSES_NO_SUCH_TRANSITION_SURFACE", surface)
    if len(matches) > 1:
        raise CrossingRefused("TRANSITION_SURFACE_AMBIGUOUS_IN_REGISTRY", surface)
    return matches[0]


def manifest_standing(manifest, declared=None):
    """Derive this crossing's standing from the manifest, or take what was declared.

    A generation manifest already carries `generation` and `predecessor`, which
    is where the chain position belongs; deriving it means the envelope and the
    manifest cannot disagree. An ingress manifest declares no chain position, so
    the caller declares one, and there is no default: a silent default is the
    defaulting `CANONICAL-NODE-INGRESS-CONTRACT-001` exists to prevent.
    """
    if isinstance(manifest, dict) and "generation" in manifest and "predecessor" in manifest:
        generation, predecessor = manifest["generation"], manifest["predecessor"]
        source = (manifest.get("source_organization") or {}).get("organization_id")
        return {"mode": "ESTABLISH_GENESIS" if generation == 1 and predecessor is None
                        else "VERIFY_EXISTING",
                "node_ref": source or str(manifest.get("source_framework") or "unknown"),
                "generation": generation, "predecessor": predecessor}
    if declared is None:
        raise CrossingRefused("CROSSING_REQUIRES_DECLARED_STANDING",
                              "this manifest declares no chain position, so one must be supplied")
    if not isinstance(declared, dict) or "predecessor" not in declared:
        raise CrossingRefused("CROSSING_STANDING_MUST_DECLARE_THE_PREDECESSOR_KEY",
                              "null is explicit genesis; an absent key fails closed")
    return declared


def crossing_packet(manifest, destination, service, registry, origin, packet_id, standing):
    """Build the InTr ingress packet that carries this manifest and its standing."""
    envelope = intr_transport.build_ingress(
        origin,
        {"org": registry["organization"], "service": service["service_id"]},
        {"schema": "stegverse.sdk-manifest-crossing-payload/v1",
         "declared_transition_surface": destination["surface"],
         "manifest_sha256": "sha256:" + sha(manifest),
         "manifest": manifest},
        "canonical",
        "intr:transition:" + packet_id,
        authority_effect=str((manifest.get("transition") or {}).get("authority_effect", "NONE")),
        packet_id=packet_id,
    )
    # Carried on the envelope so the receiving boundary can validate it without
    # parsing an arbitrary payload, which is what
    # `organization_boundary_must_carry_predecessor` asks for.
    return {**envelope, "standing": standing}


def processing_service(manifest, registry):
    """The one service admitting the manifest's declared capability and route, or None.

    Processing is selected by what the manifest declares, never by the surface
    its result returns to: `completion.egress` names the return path, and
    addressing that service for processing hands a governance manifest to the
    transport that will carry its answer back.
    """
    processing = manifest.get("processing") or {}
    declared = {"capability": processing.get("capability"), "route_id": processing.get("route_id")}
    matches = [service for service in registry.get("services", [])
               if declared in (service.get("admits_processing") or [])]
    if len(matches) > 1:
        raise CrossingRefused("PROCESSING_AMBIGUOUS_IN_REGISTRY", str(declared["capability"]))
    return matches[0] if matches else None


def cross(manifest, *, registry, origin=None, packet_id="sdk-manifest-crossing", standing=None):
    """Drive the manifest's declared crossing and return what it produced."""
    if not isinstance(registry, dict):
        raise CrossingRefused("CROSSING_REQUIRES_MATERIALIZED_CAPABILITY_MAP")
    destination = declared_destination(manifest)
    service = processing_service(manifest, registry) or resolve_surface(destination["surface"], registry)
    origin = origin or {"org": "StegVerse-org", "service": "stegverse-org.stegverse-sdk"}
    resolved_standing = manifest_standing(manifest, standing)
    ingress = crossing_packet(manifest, destination, service, registry, origin, packet_id,
                              resolved_standing)
    # The boundary binds each receipt to the packet, the service and this
    # digest. Returning only the receipt kinds left the chain unreconstructible
    # from outside, so a caller had to take `RECONSTRUCTED` on the boundary's
    # word. It is returned so the chain can be recomputed independently.
    payload_hash = sha(ingress["payload"])
    intr_transport.validate_org_crossing(ingress, "INGRESS")

    with tempfile.TemporaryDirectory() as work:
        envelope = Path(work) / "ingress.json"
        execution = Path(work) / "execution.json"
        envelope.write_text(json.dumps(ingress, indent=2, sort_keys=True) + "\n")
        registry_path = Path(work) / "registry.json"
        registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")
        completed = subprocess.run(
            [sys.executable, str(PROCESSOR), "--envelope", str(envelope), "--registry", str(registry_path), "--out", str(execution)],
            cwd=str(ROOT), capture_output=True, text=True, check=False)
        if completed.returncode == BOUNDARY_WRITE_FAULT_EXIT:
            # PB-EXIT-SPLIT: the boundary's own write faulted (75). Not a refusal
            # of the manifest: nothing is recorded as refused, and the caller's
            # writer wrapper reports a non-terminal WRITE_FAILED to rerun.
            raise RuntimeError("PROCESS_BOUNDARY_WRITE_FAULT: " + (completed.stderr or "").strip()[-400:])
        if completed.returncode != 0 or not execution.is_file():
            # The far side refused or could not be reached (65 is the boundary's
            # terminal input refusal). Say which, and say
            # it as a disposition rather than as a crossing that happened.
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            far_side_disposition = detail[-1] if detail else "FAR_SIDE_UNREACHABLE"
            return {
                "schema": "stegverse.sdk-manifest-crossing-result/v1",
                "declared_transition_surface": destination["surface"],
                "resolved_service_id": service["service_id"],
                "crossing_completed": False,
                "manifest_sha256": ingress["payload"]["manifest_sha256"],
                "far_side_disposition": far_side_disposition,
                "profile_status": service.get("profile_status"),
                "endpoint_adapter_installed": bool(service.get("endpoint_adapter")),
                "ingress_packet_id": ingress["packet_id"],
                "disposition": "FAIL_CLOSED",
                **far_side_fields(service, far_side_disposition),
                "receiver_unavailable_disposition": RECEIVER_UNAVAILABLE_DISPOSITION,
                "awaits_the_receiver": False,
                "authority_effect": "NONE_CROSSING_ATTEMPT_ONLY",
            }
        result = json.loads(execution.read_text())

    egress = intr_transport.build_egress(ingress, result)
    intr_transport.validate_org_crossing(egress, "EGRESS")
    return {
        "schema": "stegverse.sdk-manifest-crossing-result/v1",
        "declared_transition_surface": destination["surface"],
        "resolved_service_id": service["service_id"],
        "crossing_completed": True,
        "manifest_sha256": ingress["payload"]["manifest_sha256"],
        "consumed": bool(result.get("consumed")),
        "reconstruction": (result.get("reconstruction") or {}).get("status"),
        "receipts": [receipt["kind"] for receipt in result.get("receipts", [])],
        "boundary_receipts": [dict(receipt) for receipt in result.get("receipts", [])],
        "payload_hash": payload_hash,
        "terminal_receipt_id": (result.get("reconstruction") or {}).get("terminal_receipt_id"),
        "ingress_packet_id": ingress["packet_id"],
        "egress_packet_id": egress["packet_id"],
        "egress": egress,
        "authority_effect": result.get("authority_effect", "NONE"),
        "application_result": result.get("application_result"),
        **{field: result[field] for field in SELECTION_FIELDS if field in result},
    }


def main():
    parser = argparse.ArgumentParser(
        description="Carry an SDK manifest across the organization boundary to the surface it declares.")
    parser.add_argument("--manifest", type=Path, required=True,
                        help="an SDK manifest declaring completion.egress")
    parser.add_argument("--packet-id", default="sdk-manifest-crossing")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--origin-org", default="StegVerse-org")
    parser.add_argument("--origin-service", default="stegverse-org.stegverse-sdk")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--standing", type=Path, default=None,
                        help="JSON file declaring mode, node_ref and the predecessor key; "
                             "required unless the manifest declares its own generation and predecessor")
    args = parser.parse_args()
    result = cross(load(args.manifest), registry=load(args.registry),
                   origin={"org": args.origin_org, "service": args.origin_service},
                   packet_id=args.packet_id,
                   standing=load(args.standing) if args.standing else None)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered)
    print(json.dumps({k: v for k, v in result.items() if k != "egress"}, sort_keys=True))
    return 0 if result.get("crossing_completed") else 1


if __name__ == "__main__":
    sys.exit(main())
