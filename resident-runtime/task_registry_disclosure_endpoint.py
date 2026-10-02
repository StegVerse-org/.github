#!/usr/bin/env python3
"""Serve this organization's current task registry to an admitted manifest.

This is the endpoint adapter for `stegverse-org.llm-adapter`. Until now that
registry row carried no `endpoint_adapter` and no `admits_processing`, so a
manifest addressed to it was refused -- correctly, but it meant nothing could
ask this organization what it is working on and get an answer across the
boundary.

What crosses back is the committed registry, read at request time, with its
digest. The registry is the work-intent truth for this organization, so a
reader gets the current generation rather than a copy someone pasted into a
document. That is the whole point: provenance a machine verifies instead of
provenance a person mails.

The capability is `ecosystem_diagnostic`, which `StegVerse-org/StegVerse-SDK`
publishes and binds to `stegverse.route.ecosystem-diagnostic.v1`. Reading a
registry is read-only diagnostic observation, which is what that route
declares. An adapter does not get to invent a capability name: the SDK
derives `processing.capability` from `process` and publishes the vocabulary,
so a name this repository made up could not be built by the owner at all.

Processing is selected by the manifest, not by this adapter. The boundary
resolves `processing.capability` bound to `processing.route_id` against what
the service admits before this file is ever executed, so reaching here means
the declared capability was admitted. This adapter re-reads the declaration it
was invoked under and refuses anything else, because an adapter that would
serve any capability is an adapter that selects its own.

Nothing here grants authority. Disclosure is not admission: returning the
registry neither claims a task, advances a generation, nor admits a
transition.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "orchestration/task-registry.json"

CAPABILITY = "ecosystem_diagnostic"
ROUTE_ID = "stegverse.route.ecosystem-diagnostic.v1"
SCHEMA = "stegverse.task-registry-disclosure/v1"


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canon(value)).hexdigest()


def declared_processing(payload):
    """Read the processing declaration this crossing was admitted under."""
    for candidate in (payload, (payload or {}).get("manifest") if isinstance(payload, dict) else None):
        if not isinstance(candidate, dict):
            continue
        processing = candidate.get("processing")
        if isinstance(processing, dict):
            return processing
    return None


def disclosure(payload):
    """Build the registry disclosure for a payload that declared this capability."""
    processing = declared_processing(payload)
    if processing is None:
        # The boundary admits an undeclared manifest to an internal endpoint and
        # records that identity selected the processing. This adapter will not
        # serve that case: disclosure must be something a manifest asked for.
        raise SystemExit("task-registry-disclosure-requires-a-declared-capability")
    capability = str(processing.get("capability") or "").strip()
    route_id = str(processing.get("route_id") or "").strip()
    if capability != CAPABILITY:
        raise SystemExit("task-registry-disclosure-not-the-declared-capability:" + (capability or "<none>"))
    if route_id != ROUTE_ID:
        raise SystemExit("task-registry-disclosure-not-the-declared-route:" + (route_id or "<none>"))

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    tasks = registry.get("tasks") or []
    return {
        "schema": SCHEMA,
        "served_capability": capability,
        "served_route_id": route_id,
        "registry_path": str(REGISTRY.relative_to(ROOT)),
        "registry_sha256": digest(registry),
        "organization": registry.get("org"),
        "active_goal": registry.get("active_goal"),
        "archive_status": registry.get("archive_status"),
        "task_count": len(tasks),
        "tasks": tasks,
        # Said plainly so a reader cannot take a served registry for more than
        # it is. The registry records intent and evidence; it admits nothing.
        "disclosure_is_not_admission": True,
        "registry_is_work_intent_truth_not_runtime_proof": True,
        "authority_effect": "NONE_DISCLOSURE_ONLY",
    }


def main():
    parser = argparse.ArgumentParser(
        description="Serve the organization task registry to a manifest that declared the disclosure capability.")
    parser.add_argument("--envelope", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    packet = json.loads(args.envelope.read_text(encoding="utf-8"))
    destination = (packet.get("destination") or {}).get("service")
    if destination != "stegverse-org.llm-adapter":
        raise SystemExit("task-registry-disclosure-wrong-destination:" + str(destination))

    result = disclosure(packet.get("payload"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "served_capability": result["served_capability"],
                      "registry_sha256": result["registry_sha256"],
                      "task_count": result["task_count"]}, sort_keys=True))


if __name__ == "__main__":
    main()
