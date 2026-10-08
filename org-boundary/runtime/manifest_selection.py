#!/usr/bin/env python3
"""Select processing from the admitted manifest, never from who is being addressed.

`SDK-GENERIC-MANIFEST-ECOSYSTEM-INVARIANT-005` states the rule this module
exists to hold:

    Every StegVerse processing action is manifest-driven. Processing semantics
    are selected only by an admitted manifest's declared `processing.capability`
    bound to `processing.route_id` and an installed admissible route.

    Source identity, provider identity, framework identity, adapter identity,
    transport identity, model identity, subsystem identity, response class,
    file type, or prior result may contribute provenance/policy evidence but
    MUST NOT independently select processing semantics.

This boundary selected processing entirely by identity. `process_boundary`
resolved the registry row for `destination.service` and dispatched on that
row's `boundary_role` and `endpoint_adapter`; neither it, `org-kernel/kernel.py`
nor `resident-runtime/sdk_manifest_crossing.py` referenced
`processing.capability` or `processing.route_id` even once. A manifest could
declare any capability at all and the boundary would process it according to
whichever adapter the addressed row happened to name.

What this module does not do is replace admissibility. The registry row remains
the admissibility and transport surface -- it decides whether a service may be
addressed and how it is reached. It simply no longer decides, by itself, what
processing the packet receives.

The two roles differ, and conflating them would be its own overclaim:

* An `INTERNAL_ENDPOINT` selects a processor, so a declaration must select it
  and the service must admit the declared capability bound to the declared
  route. A packet declaring nothing is refused before any receipt
  (`PROCESSING_SELECTED_ONLY_BY_ADMITTED_PROCESSING_CAPABILITY_AND_ROUTE_ID`);
  it was once recorded as identity-selected and dispatched anyway. The one
  exception is an endpoint response bound to the request it answers, which is
  the return leg of a transition whose manifest already selected processing.
* A `BOUNDARY_LOCAL_*` surface *is* the processor -- a diagnostic echoes -- so
  no selection occurs. A manifest declaring a capability there is transported,
  not processed under that capability, and the result says so rather than
  letting a completed crossing imply the declared capability ran.

Route *installation* is not decided here either. `StegVerse-org/StegVerse-SDK`
owns `PUBLISHED_ROUTES` and the capability-to-processor binding; this boundary
has no copy of that table and must not grow one. What it checks is the binding
the addressed service has itself declared it admits, and it records that route
admissibility was not resolved here, so a crossing that passes cannot be read
as the boundary having proven an installed route.

Nothing here grants authority. Selection is not admission.
"""
from __future__ import annotations

MANIFEST_DECLARED = "MANIFEST_DECLARED"
IDENTITY_SELECTED = "IDENTITY_SELECTED_NO_MANIFEST_DECLARATION"
RETURN_BOUND = "RETURN_BOUND_TO_REQUEST"
# The refusal an undeclared internal-endpoint packet now earns. It was recorded
# as IDENTITY_SELECTED and dispatched anyway, which left the adapter's own
# payload checks as the only thing standing between an undeclared packet and an
# action. The label survives only as the refusal's diagnostic.
UNDECLARED_REFUSAL = "PROCESSING_SELECTED_ONLY_BY_ADMITTED_PROCESSING_CAPABILITY_AND_ROUTE_ID"
# An answer to a request is not a new action: it is the return leg of the
# transition the request began, and the request's manifest selected its
# processing. It is admitted only in this shape, only where the addressed
# service declares it accepts it, and only bound to the request it answers.
ENDPOINT_RESPONSE_SCHEMA = "stegverse.org-endpoint-response/v1"
BOUNDARY_LOCAL = "BOUNDARY_LOCAL_NO_PROCESSOR_SELECTED"

# A passing selection says nothing about whether the declared route is
# installed. The route owner is the SDK; naming that here keeps a PASS from
# being read as more than it is.
ROUTE_ADMISSIBILITY = "NOT_RESOLVED_AT_BOUNDARY_ROUTE_OWNER_IS_SDK"

ADMITS_FIELD = "admits_processing"
INTERNAL = "INTERNAL_ENDPOINT"


def _text(value):
    """Return a non-empty declared string, or None. Nothing is coerced."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def declared_processing(payload):
    """Return the `processing` object a manifest in this payload declares, or None.

    A payload may be a manifest, or may carry one under `manifest`. Nothing is
    inferred: a payload declaring no `processing` returns None rather than a
    default, because defaulting is how identity ends up selecting again. A
    payload that declares `processing` returns it even when malformed -- the
    caller fails closed on it rather than letting a broken declaration read as
    an absent one and fall through to the identity path.
    """
    for candidate in (payload, (payload or {}).get("manifest") if isinstance(payload, dict) else None):
        if not isinstance(candidate, dict):
            continue
        processing = candidate.get("processing")
        if isinstance(processing, dict):
            return processing
    return None


def admitted_bindings(service):
    """Return the capability-to-route bindings this service declares it admits.

    Each entry is an object carrying `capability` and `route_id`. A bare
    capability string is refused rather than accepted as a wildcard route: the
    invariant binds the two, so a half-declaration cannot admit anything.
    """
    declared = service.get(ADMITS_FIELD)
    if not isinstance(declared, list):
        raise SystemExit("service-declares-no-admitted-processing:" + str(service.get("service_id")))
    bindings = []
    for entry in declared:
        if not isinstance(entry, dict):
            raise SystemExit("service-admitted-processing-entry-not-a-binding:" + str(service.get("service_id")))
        capability = _text(entry.get("capability"))
        route_id = _text(entry.get("route_id"))
        if capability is None or route_id is None:
            raise SystemExit("service-admitted-processing-binding-incomplete:" + str(service.get("service_id")))
        bindings.append({"capability": capability, "route_id": route_id})
    return bindings


def bound_return(service, payload):
    """The request an endpoint response answers, or None if this is not one.

    Admitted only as the response schema, only where the service declares it
    accepts that schema, and only naming both the request packet and the
    manifest digest it answers. Whether this organization recorded emitting
    that request is not decided here; the binding is declared, not verified.
    """
    if not isinstance(payload, dict) or payload.get("schema") != ENDPOINT_RESPONSE_SCHEMA:
        return None
    if ENDPOINT_RESPONSE_SCHEMA not in (service.get("accepts") or []):
        return None
    request_packet_id = _text(payload.get("response_to_packet_id"))
    manifest_sha256 = _text(payload.get("request_manifest_sha256"))
    if request_packet_id is None or manifest_sha256 is None:
        return None
    return {"response_to_packet_id": request_packet_id,
            "request_manifest_sha256": manifest_sha256,
            "binding": "DECLARED_NOT_VERIFIED_AGAINST_EMISSION_RECORD"}


def select_processing(service, payload):
    """Decide how this packet's processing was selected, and refuse what it must.

    Raises SystemExit on a declaration the addressed service does not admit;
    the caller surfaces that as the boundary's refusal.
    """
    role = service.get("boundary_role")
    processing = declared_processing(payload)
    capability = _text(processing.get("capability")) if processing is not None else None
    route_id = _text(processing.get("route_id")) if processing is not None else None

    if role != INTERNAL:
        # The boundary is the processor here. Nothing selects a processor, so
        # the invariant has nothing to bind -- but a declaration that will not
        # be processed must not read as one that was.
        return {"processing_selection": BOUNDARY_LOCAL,
                "declared_capability": capability,
                "declared_route_id": route_id,
                "declared_capability_processed": False,
                "route_admissibility": ROUTE_ADMISSIBILITY}

    if processing is None:
        bound = bound_return(service, payload)
        if bound is not None:
            return {"processing_selection": RETURN_BOUND,
                    "declared_capability": None,
                    "declared_route_id": None,
                    "declared_capability_processed": False,
                    "route_admissibility": ROUTE_ADMISSIBILITY,
                    "return_bound_to": bound}
        # With nothing declared, the addressed row's adapter would be what
        # selected the processing. That is refused here, before any receipt,
        # rather than recorded and dispatched.
        raise SystemExit(UNDECLARED_REFUSAL + ":" + IDENTITY_SELECTED + ":"
                         + str(service.get("service_id")))

    if capability is None:
        raise SystemExit("manifest-declares-processing-without-capability")
    if route_id is None:
        # The owner contract requires a non-empty route_id. A capability with
        # no route is not a selection, and must not be completed as one by the
        # addressed adapter.
        raise SystemExit("manifest-declares-capability-without-route:" + capability)

    bindings = admitted_bindings(service)
    if capability not in {b["capability"] for b in bindings}:
        raise SystemExit("declared-capability-not-admitted-by-service:" + capability)
    if {"capability": capability, "route_id": route_id} not in bindings:
        # Capability/route mismatch: both are admitted names, but not as this
        # pair. Processing the capability under an unadmitted route is exactly
        # the substitution the invariant forbids.
        raise SystemExit("declared-capability-route-binding-not-admitted:" + capability + "@" + route_id)

    return {"processing_selection": MANIFEST_DECLARED,
            "declared_capability": capability,
            "declared_route_id": route_id,
            "declared_capability_processed": True,
            "route_admissibility": ROUTE_ADMISSIBILITY}
