#!/usr/bin/env python3
"""Make a bound capability addressable, so a submission can actually reach it.

`org-runtime/interlock-intr.json` binds `sdk-manifest-ingress` to a receiving
operation this repository owns, and `capability_endpoint_binding_rule` says a
registered capability resolves to one organization receiving operation owned
here. It does. What it did not have was an **address**.

`org-kernel/kernel.py::dispatch` resolves `destination.service` against
`org-boundary/registry/services.json` and refuses `unknown_service` for anything
absent from it. No row resolved to `ORGANIZATION_SDK_MANIFEST_INGRESS`, so the
binding named a destination that transport could not reach. The receiving
operation could only be entered by running its CLI inside a checkout of this
repository -- which is to say, by already being inside the organization.

That is the same defect class as the ones corrected before it: a declaration
that nothing enforced. Here the declaration was a destination and what was
missing was the reachability it implied. The practical consequence is the whole
end-to-end question: a customer's manifest, or a peer organization's, had
nowhere to arrive.

This module is the resolution step, and deliberately nothing more:

* The **overlay** remains the single authority on which capability is received
  on which operation. Nothing is copied here. A registry row addressed under
  this role is refused unless the overlay itself names that row as the
  capability's addressed service, so an address cannot grant itself a
  capability by declaring one.
* The **registry row** remains the admissibility and transport surface -- it
  decides whether a service may be addressed and how it is reached, exactly as
  `manifest_selection` already says.
* **No processing is selected here.** This surface is not the processor of the
  declared capability; it hands the submission to the receiving operation,
  which resolves the manifest's own internal surface and selects processing
  there. `select_processing` returns `BOUNDARY_LOCAL_NO_PROCESSOR_SELECTED` for
  this role and that reading is correct at this surface. Where the capability
  was processed is reported rather than claimed here.
* **Route installation is not resolved here**, for the same reason
  `manifest_selection` does not resolve it: the route owner is the SDK.

A mis-wired address fails closed rather than running something adjacent. The
operation the overlay names is loaded and its own `OPERATION_ID` is compared to
the `operation_id` the binding declares; a module that does not identify itself
as the bound operation is refused. An address that silently ran a different
operation than the one the overlay published would be worse than no address.

Nothing here grants authority. Addressability is not admission: standing is
still required at ingress, the receiving operation still refuses what it cannot
drive, and every disposition is still receipted by the operation itself.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping

#: The boundary role a registry row carries to be addressable as a capability.
#:
#: Not `INTERNAL_ENDPOINT`: that role selects a processor, so `manifest_selection`
#: requires the addressed row to admit the declared capability bound to the
#: declared route. An organization's capability front door cannot enumerate
#: those pairs without growing a copy of the SDK's route table, which is the one
#: thing `manifest_selection` says this boundary must not do. It is a
#: `BOUNDARY_LOCAL_*` surface because the processor it reaches is owned here.
ROLE = "BOUNDARY_LOCAL_CAPABILITY_INGRESS"

BOUNDARY_PATH = "org-runtime/interlock-intr.json"
BINDINGS_FIELD = "capability_endpoint_bindings"
ADDRESSED_SERVICE_FIELD = "addressed_service"
OPERATION_FIELD = "operation"
MANIFEST_FIELD = "manifest"
MANIFEST_DIGEST_FIELD = "manifest_sha256"
SUBMISSION_READER_FIELD = "submission_reader"

#: How a binding says its submission is read. The manifest reader is the one
#: this resolver had when the only bound capability was a manifest. A second
#: capability that is not a manifest names its own reader on the binding, so
#: the address still cannot decide what arrives: the overlay does.
MANIFEST_READER = "MANIFEST"
COMMUNICATION_READER = "ECOSYSTEM_COMMUNICATION"
SUBMISSION_READERS = (MANIFEST_READER, COMMUNICATION_READER)
COMMUNICATION_CLASS = "ecosystem.communication"
COMMUNICATION_ID_FIELD = "communication_id"
BODY_FIELD = "body"

#: What this surface did and did not do, recorded with the result.
PROCESSOR_SELECTION = "NO_PROCESSOR_SELECTED_AT_THE_CAPABILITY_ADDRESS"
ROUTE_ADMISSIBILITY = "NOT_RESOLVED_AT_BOUNDARY_ROUTE_OWNER_IS_SDK"


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _refuse(predicate: str, detail: str) -> SystemExit:
    """Refusals name their failed predicate, as every other surface here does."""
    return SystemExit(predicate + ":" + detail)


def boundary(root: Path) -> dict[str, Any]:
    path = Path(root) / BOUNDARY_PATH
    if not path.is_file():
        raise _refuse("ORGANIZATION_DECLARES_ITS_CAPABILITY_BINDINGS", str(path))
    return json.loads(path.read_text())


def bindings(root: Path) -> list[dict[str, Any]]:
    declared = (boundary(root).get("ingress") or {}).get(BINDINGS_FIELD)
    if not isinstance(declared, list):
        raise _refuse("CAPABILITY_BINDINGS_ARE_DECLARED_AS_A_LIST", BINDINGS_FIELD)
    return [entry for entry in declared if isinstance(entry, dict)]


def binding_for_service(root: Path, service_id: Any) -> dict[str, Any]:
    """The one overlay binding that names this service as its address.

    Exactly one, for the reason `resolve_surface` requires exactly one: zero
    means this address serves no declared capability, and more than one means
    the overlay is ambiguous about which capability arrives here, where
    guessing would pick a receiving operation on the submitter's behalf.
    """
    matches = [entry for entry in bindings(root)
               if (entry.get("receiving_operation") or {}).get(ADDRESSED_SERVICE_FIELD) == service_id]
    if not matches:
        raise _refuse("ADDRESS_SERVES_A_CAPABILITY_THE_OVERLAY_BINDS_HERE", str(service_id))
    if len(matches) > 1:
        raise _refuse("ADDRESS_SERVES_EXACTLY_ONE_BOUND_CAPABILITY", str(service_id))
    return matches[0]


def resolve(root: Path, service: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the receiving operation the overlay binds to this address."""
    binding = binding_for_service(root, service.get("service_id"))
    receiving = binding.get("receiving_operation") or {}
    operation_id = receiving.get("operation_id")
    relative = receiving.get(OPERATION_FIELD)
    if not operation_id or not relative:
        raise _refuse("BOUND_RECEIVING_OPERATION_DECLARES_ITS_ID_AND_MODULE",
                      str(binding.get("profile_id")))
    path = (Path(root) / str(relative)).resolve()
    try:
        path.relative_to(Path(root).resolve())
    except ValueError:
        raise _refuse("RECEIVING_OPERATION_IS_OWNED_INSIDE_THIS_ORGANIZATION", str(relative)) from None
    if not path.is_file():
        raise _refuse("RECEIVING_OPERATION_MODULE_EXISTS", str(relative))
    return {
        "capability_profile_id": binding.get("profile_id"),
        "capability_profile_name": binding.get("profile_name"),
        "capability_operation": binding.get("operation"),
        "payload_schema": binding.get("payload_schema"),
        "receiving_operation_id": operation_id,
        "receiving_operation_module": str(relative),
        "receiving_operation_path": path,
        "addressed_service": service.get("service_id"),
        "resolution_source": "ORGANIZATION_CAPABILITY_OVERLAY",
        "resolved_from_the_addressed_row_alone": False,
        "authority_effect": "NONE_RESOLUTION_ONLY",
    }


def load_operation(resolved: Mapping[str, Any]):
    """Load the bound operation and refuse one that is not the operation bound.

    The overlay publishes an `operation_id`; the module declares its own. A
    path edited to point somewhere adjacent would otherwise run that other
    operation under this capability's name.
    """
    path = resolved["receiving_operation_path"]
    spec = importlib.util.spec_from_file_location("bound_receiving_operation", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # the operation's own import failure, named
        raise _refuse("RECEIVING_OPERATION_IS_LOADABLE_HERE",
                      type(exc).__name__ + ": " + str(exc)) from None
    declared = getattr(module, "OPERATION_ID", None)
    if declared != resolved["receiving_operation_id"]:
        raise _refuse("MODULE_IDENTIFIES_ITSELF_AS_THE_BOUND_OPERATION",
                      str(declared) + " is not " + str(resolved["receiving_operation_id"]))
    return module


def submission_reader(binding: Mapping[str, Any]) -> Any:
    """The reader the overlay names, with the manifest reader implied for SUBMIT_MANIFEST.

    A binding that predates readers does not carry the field. The only such
    operation is ``SUBMIT_MANIFEST``, and implying the reader it has always had
    keeps that binding unchanged. Any other operation must name its reader:
    inheriting the manifest reader would treat a communication as a manifest
    and refuse it for the wrong reason.
    """
    declared = binding.get(SUBMISSION_READER_FIELD)
    if declared is None and binding.get("operation") == "SUBMIT_MANIFEST":
        return MANIFEST_READER
    return declared


def declared_communication(binding: Mapping[str, Any], payload: Any) -> dict[str, Any]:
    """The ecosystem communication this payload submits, or a refusal.

    Closable crossings are ``ecosystem.communication`` payloads that carry a
    ``communication_id``. The diagnostic body is what the bound payload schema
    names. A payload missing either is not a submission under this reader, and
    nothing is reconstructed from the rest of it.
    """
    if not isinstance(payload, Mapping):
        raise _refuse("SUBMISSION_IS_AN_ECOSYSTEM_COMMUNICATION", "payload is not an object")
    if payload.get("message_class") != COMMUNICATION_CLASS:
        raise _refuse("SUBMISSION_DECLARES_A_RESPONDED_REQUEST_CLASS",
                      str(payload.get("message_class")))
    identifier = payload.get(COMMUNICATION_ID_FIELD)
    if not isinstance(identifier, str) or not identifier.strip():
        raise _refuse("SUBMISSION_CARRIES_THE_COMMUNICATION_ID_CLOSURE_CORRELATES_ON",
                      repr(identifier))
    body = payload.get(BODY_FIELD)
    schema = binding.get("payload_schema")
    if not isinstance(body, Mapping) or body.get("schema") != schema:
        raise _refuse("SUBMISSION_BODY_DECLARES_THE_BOUND_PAYLOAD_SCHEMA",
                      str(body.get("schema") if isinstance(body, Mapping) else body))
    return dict(payload)


def submission_for(binding: Mapping[str, Any], payload: Any) -> dict[str, Any]:
    """Read the submission the way the binding's reader says, or refuse."""
    reader = submission_reader(binding)
    if reader == MANIFEST_READER:
        return declared_manifest(payload)
    if reader == COMMUNICATION_READER:
        return declared_communication(binding, payload)
    raise _refuse("SUBMISSION_READER_IS_ONE_THIS_RESOLVER_IMPLEMENTS", str(reader))


def declared_manifest(payload: Any) -> dict[str, Any]:
    """The manifest this payload submits, or a refusal.

    A payload carrying no manifest is not a submission under this reader,
    and nothing is reconstructed from the rest of the payload on its behalf. A
    carried digest is checked when present, because a payload whose digest and
    manifest disagree has no single thing it submitted.
    """
    if not isinstance(payload, Mapping):
        raise _refuse("SUBMISSION_CARRIES_A_MANIFEST", "payload is not an object")
    manifest = payload.get(MANIFEST_FIELD)
    if not isinstance(manifest, Mapping):
        raise _refuse("SUBMISSION_CARRIES_A_MANIFEST",
                      "payload declares no " + MANIFEST_FIELD)
    carried = payload.get(MANIFEST_DIGEST_FIELD)
    if carried is not None:
        computed = "sha256:" + hashlib.sha256(canon(dict(manifest))).hexdigest()
        if str(carried) != computed:
            raise _refuse("CARRIED_MANIFEST_DIGEST_MATCHES_THE_MANIFEST", str(carried))
    return dict(manifest)


def receive(root: Path, service: Mapping[str, Any], packet: Mapping[str, Any], *, registry: Mapping[str, Any],
            mesh_root: Path | None = None) -> dict[str, Any]:
    """Hand an addressed submission to the receiving operation the overlay binds.

    The operation records its own dispositions at both ledger levels; this
    returns what it reported. A refusal is returned as the operation stated it,
    not retried into an admission.
    """
    resolved = resolve(root, service)
    # The overlay says how this capability's submission is read. A payload the
    # binding does not admit is refused before the operation is loaded, so a
    # communication is not forced through the manifest reader and a manifest is
    # not forced through the communication reader.
    binding = binding_for_service(root, service.get("service_id"))
    submission = submission_for(binding, packet.get("payload"))
    module = load_operation(resolved)
    result = module.receive(submission, registry=registry, standing=packet.get("standing"),
                            packet_id=str(packet.get("packet_id") or resolved["receiving_operation_id"]),
                            mesh_root=mesh_root)
    return {
        "capability_received": True,
        "capability_profile_id": resolved["capability_profile_id"],
        "capability_operation": resolved["capability_operation"],
        "receiving_operation_id": resolved["receiving_operation_id"],
        "receiving_operation_module": resolved["receiving_operation_module"],
        "capability_resolution_source": resolved["resolution_source"],
        # Said plainly so a completed crossing at this address is not read as
        # this surface having processed the declared capability.
        "processor_selection_at_this_address": PROCESSOR_SELECTION,
        "declared_capability_processed_at_this_address": False,
        "declared_capability_processed_by": resolved["receiving_operation_id"],
        "route_admissibility": ROUTE_ADMISSIBILITY,
        "addressability_grants_admission_authority": False,
        "receiving_operation_result": result,
    }
