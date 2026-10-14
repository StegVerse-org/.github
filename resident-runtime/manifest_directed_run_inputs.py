#!/usr/bin/env python3
"""Resolve a runtime workflow's inputs from the committed request that directs it.

Every ACTION is by manifest: a committed request under `.stegverse/` is the
state transition that starts a run, and the run takes its inputs from that
request. No dispatching actor, external machine or resident host has to supply
them. A `workflow_dispatch` input, where a workflow still accepts one, is
used unchanged; it is no longer required.

- `organization-ledger-transition.yml`: a pushed transition request may declare
  `mesh_root`. Every request of one run that declares one must declare the same
  locator, because a run binds one mesh.
- `organization-ledger-transition.yml`: a pushed transition request carries its
  manifest either as `build_manifest` arguments, built by the pinned SDK in the
  run, or as the exact already-built `manifest` together with its
  `expected_canonical_manifest_sha256`. A manifest prepared and frozen
  elsewhere is then submitted unchanged: the run refuses it unless it
  reproduces that canonical digest exactly (`committed_manifest`).
- `organization-governance-return.yml`: a pushed return request under
  `.stegverse/governance-return-requests/` declares `mesh_root` and `peer_mesh`,
  and optionally `sdk_ref` and `deciding_ledger`. One run returns for exactly
  one committed return request.

Nothing here designates, binds or contacts a mesh. Each locator still goes
through `mesh_locator_binding.py` or `peer_mesh_intake.py` exactly as a
dispatched one would. Any refusal carries all six fields.
"""
import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA = "stegverse.manifest-directed-run-inputs/v1"
RETURN_REQUEST_SCHEMA = "stegverse.organization-governance-return-request/v1"
RETURN_REQUEST_DIR = ".stegverse/governance-return-requests/"
OWNING_EXISTING_GOAL = "SVORG-MESH-LOCATION-BINDING-001"
_SDK_REF = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _refused(failure_code, failed_predicate, repair, retry_entrypoint, next_attempt, **detail):
    return {
        "schema": SCHEMA,
        "disposition": "FAIL_CLOSED",
        "failure_code": failure_code,
        "failed_predicate": failed_predicate,
        "required_evidence_or_repair": repair,
        "retry_entrypoint": retry_entrypoint,
        "owning_existing_goal": OWNING_EXISTING_GOAL,
        "next_attempt": next_attempt,
        "authority_effect": "NONE_INPUT_RESOLUTION_ONLY",
        **detail,
    }


def _printable(value):
    # A value is written to GITHUB_ENV, so a newline would inject a variable.
    return isinstance(value, str) and all(32 <= ord(c) <= 126 for c in value)


def _load(path):
    try:
        document = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(str(exc))
    if not isinstance(document, dict):
        raise ValueError("request is not a JSON object")
    return document


def transition_mesh_root(dispatch_mesh_root, request_paths):
    """The mesh locator for one ledger-transition run.

    A dispatched locator is used as given. Otherwise the locator is the one the
    committed requests of this run declare; none declared leaves it empty, and
    the workflow defers an egress-bound request as before.
    """
    entrypoint = ".github/workflows/organization-ledger-transition.yml (push: .stegverse/transition-requests/*.json)"
    if dispatch_mesh_root:
        return {"schema": SCHEMA, "disposition": "ALLOW", "mesh_root": dispatch_mesh_root,
                "source": "WORKFLOW_DISPATCH", "authority_effect": "NONE_INPUT_RESOLUTION_ONLY"}
    declared = {}
    for path in request_paths:
        try:
            request = _load(path)
        except ValueError as exc:
            return _refused("TRANSITION_REQUEST_UNREADABLE", "COMMITTED_TRANSITION_REQUEST_IS_A_JSON_OBJECT",
                            "commit the request as a JSON object", entrypoint,
                            "commit a corrected successor request", request=str(path), detail=str(exc))
        if "mesh_root" not in request:
            continue
        locator = request["mesh_root"]
        if not _printable(locator) or not locator:
            return _refused("DECLARED_MESH_ROOT_INVALID", "DECLARED_MESH_ROOT_IS_A_PRINTABLE_LOCATOR",
                            "declare mesh_root as git+<repository>#refs/<name>", entrypoint,
                            "commit a corrected successor request", request=str(path))
        declared[str(path)] = locator
    locators = sorted(set(declared.values()))
    if len(locators) > 1:
        return _refused("DECLARED_MESH_ROOTS_CONFLICT", "ONE_RUN_BINDS_ONE_DECLARED_MESH",
                        "commit requests that declare different meshes in separate pushes", entrypoint,
                        "commit each request on its own", declared=declared)
    return {"schema": SCHEMA, "disposition": "ALLOW", "mesh_root": locators[0] if locators else "",
            "source": "COMMITTED_TRANSITION_REQUEST" if locators else "NONE_DECLARED",
            "declared_by": sorted(declared), "authority_effect": "NONE_INPUT_RESOLUTION_ONLY"}


def request_process(request):
    """The processing capability a committed transition request declares, or None."""
    if isinstance(request.get("build_manifest"), dict):
        return request["build_manifest"].get("process")
    manifest = request.get("manifest")
    processing = manifest.get("processing") if isinstance(manifest, dict) else None
    return processing.get("capability") if isinstance(processing, dict) else None


def committed_manifest(request, *, build, canonical_of):
    """The manifest one committed transition request submits.

    `build` is the SDK Manifest Builder and `canonical_of` the canonical
    manifest digest the ingress derives; both come from the pinned SDK. A
    request carries exactly one form. An exact manifest is submitted unchanged,
    and only when it reproduces the digest the request names.
    """
    entrypoint = ".github/workflows/organization-ledger-transition.yml (push: .stegverse/transition-requests/*.json)"
    has_build, has_manifest = "build_manifest" in request, "manifest" in request
    if has_build == has_manifest:
        return _refused("TRANSITION_REQUEST_MANIFEST_FORM_INVALID", "REQUEST_CARRIES_EXACTLY_ONE_MANIFEST_FORM",
                        "declare either build_manifest arguments or an exact manifest, not both or neither",
                        entrypoint, "commit a corrected successor request", request_id=request.get("request_id"))
    if has_build:
        try:
            manifest = build(**request["build_manifest"])
        except (TypeError, ValueError) as exc:
            return _refused("TRANSITION_REQUEST_NOT_BUILDABLE", "BUILD_MANIFEST_ARGUMENTS_BUILD_A_MANIFEST",
                            "build_manifest arguments the pinned SDK Manifest Builder accepts", entrypoint,
                            "commit a corrected successor request", request_id=request.get("request_id"),
                            detail=str(exc)[:300])
        return {"schema": SCHEMA, "disposition": "ALLOW", "manifest": manifest, "canonical_manifest_sha256": canonical_of(manifest),
                "source": "BUILT_BY_PINNED_SDK", "authority_effect": "NONE_INPUT_RESOLUTION_ONLY"}
    manifest, expected = request["manifest"], request.get("expected_canonical_manifest_sha256")
    if not isinstance(manifest, dict) or not (isinstance(expected, str) and _SHA256.match(expected)):
        return _refused("EXACT_MANIFEST_UNBOUND", "EXACT_MANIFEST_NAMES_ITS_CANONICAL_DIGEST",
                        "an exact manifest object with expected_canonical_manifest_sha256 (64 lowercase hex)",
                        entrypoint, "commit a corrected successor request", request_id=request.get("request_id"))
    try:
        canonical = canonical_of(manifest)
    except (TypeError, ValueError) as exc:
        return _refused("EXACT_MANIFEST_NOT_ADMISSIBLE", "EXACT_MANIFEST_IS_A_VALID_INGRESS_MANIFEST",
                        "a manifest the pinned SDK admits at ingress", entrypoint,
                        "commit a corrected successor request", request_id=request.get("request_id"),
                        detail=str(exc)[:300])
    if canonical != expected:
        return _refused("EXACT_MANIFEST_DIGEST_MISMATCH", "EXACT_MANIFEST_REPRODUCES_ITS_CANONICAL_DIGEST",
                        "the unchanged manifest whose canonical digest is " + expected, entrypoint,
                        "commit the exact frozen manifest unchanged", request_id=request.get("request_id"),
                        observed=canonical)
    return {"schema": SCHEMA, "disposition": "ALLOW", "manifest": manifest, "canonical_manifest_sha256": canonical,
            "source": "EXACT_COMMITTED_MANIFEST", "authority_effect": "NONE_INPUT_RESOLUTION_ONLY"}


def governance_return_inputs(dispatch, changed_paths):
    """The inputs of one governance-return run: dispatched, or from one committed return request."""
    entrypoint = ".github/workflows/organization-governance-return.yml (push: " + RETURN_REQUEST_DIR + "*.json)"
    fields = ("mesh_root", "peer_mesh", "sdk_ref", "deciding_ledger")
    if dispatch.get("mesh_root") or dispatch.get("peer_mesh"):
        values = {name: dispatch.get(name) or "" for name in fields}
        source = "WORKFLOW_DISPATCH"
    else:
        requests = [p for p in changed_paths if p.startswith(RETURN_REQUEST_DIR) and p.endswith(".json")]
        if len(requests) != 1:
            return _refused("RETURN_REQUEST_NOT_SINGULAR", "ONE_COMMITTED_RETURN_REQUEST_PER_RUN",
                            "commit exactly one governance return request per push", entrypoint,
                            "commit each return request on its own", requests=requests)
        try:
            request = _load(requests[0])
        except ValueError as exc:
            return _refused("RETURN_REQUEST_UNREADABLE", "COMMITTED_RETURN_REQUEST_IS_A_JSON_OBJECT",
                            "commit the return request as a JSON object", entrypoint,
                            "commit a corrected successor request", request=requests[0], detail=str(exc))
        if request.get("schema") != RETURN_REQUEST_SCHEMA or not request.get("owning_existing_goal"):
            return _refused("RETURN_REQUEST_SCHEMA_INVALID", "COMMITTED_RETURN_REQUEST_SCHEMA",
                            "declare schema " + RETURN_REQUEST_SCHEMA + " and owning_existing_goal", entrypoint,
                            "commit a corrected successor request", request=requests[0])
        values = {name: request.get(name) or "" for name in fields}
        source = "COMMITTED_RETURN_REQUEST:" + requests[0]
    for name in ("mesh_root", "peer_mesh"):
        if not values[name]:
            return _refused("RETURN_LOCATOR_MISSING", "RETURN_DECLARES_" + name.upper(),
                            "declare " + name + " as git+<repository>#refs/<name>", entrypoint,
                            "commit a corrected successor request", source=source)
    for name, value in values.items():
        if not _printable(value):
            return _refused("RETURN_INPUT_INVALID", "RETURN_INPUT_IS_PRINTABLE",
                            name + " must be printable ASCII on one line", entrypoint,
                            "commit a corrected successor request", source=source, field=name)
    if values["sdk_ref"] and not _SDK_REF.match(values["sdk_ref"]):
        return _refused("SDK_REF_INVALID", "SDK_REF_IS_AN_EXACT_COMMIT",
                        "declare sdk_ref as a full 40-hex StegVerse-SDK commit, or omit it for the current pin",
                        entrypoint, "commit a corrected successor request", source=source)
    return {"schema": SCHEMA, "disposition": "ALLOW", **values, "source": source,
            "authority_effect": "NONE_INPUT_RESOLUTION_ONLY"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    transition = sub.add_parser("transition-mesh")
    transition.add_argument("--dispatch-mesh-root", default="")
    transition.add_argument("--requests", dest="request_list", required=True, type=Path,
                            help="file listing this run's request paths")
    ret = sub.add_parser("governance-return")
    for name in ("mesh-root", "peer-mesh", "sdk-ref", "deciding-ledger"):
        ret.add_argument("--dispatch-" + name, default="")
    ret.add_argument("--changed", required=True, type=Path, help="file listing the paths this push changed")
    args = parser.parse_args(argv)
    if args.command == "transition-mesh":
        paths = [line for line in args.request_list.read_text().splitlines() if line]
        result = transition_mesh_root(args.dispatch_mesh_root, paths)
    else:
        changed = [line for line in args.changed.read_text().splitlines() if line]
        result = governance_return_inputs({"mesh_root": args.dispatch_mesh_root, "peer_mesh": args.dispatch_peer_mesh,
                                           "sdk_ref": args.dispatch_sdk_ref,
                                           "deciding_ledger": args.dispatch_deciding_ledger}, changed)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["disposition"] == "ALLOW" else 1


if __name__ == "__main__":
    sys.exit(main())
