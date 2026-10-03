#!/usr/bin/env python3
"""Rebuild the committed SDK manifest fixtures from their build spec.

The fixtures let `tests/test_sdk_manifest_crossing.py` exercise the crossing
without the SDK installed, which is what keeps the two repositories decoupled.
The cost is that a fixture can drift into a shape the SDK no longer produces,
leaving the crossing tested against a fiction.

`sdk-manifest-build-spec.json` holds the exact `build_manifest` arguments the
fixtures came from, so a workflow with the SDK installed can rebuild them and compare. Same
arguments, same SDK, same bytes -- any difference is real drift, on one side or
the other.

Requires the installed StegVerse SDK. Writes nothing unless asked.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = HERE / "sdk-manifest-build-spec.json"
MANIFESTS = HERE / "sdk-manifests"


def rebuild():
    """Return {name: manifest} built from the spec by the installed SDK."""
    from stegverse.manifest_builder import build_manifest
    from stegverse.manifest_contract import validate_ingress_manifest

    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    built = {}
    for name, overrides in sorted(spec["manifests"].items()):
        # Merged, not double-unpacked: `f(**common, **overrides)` raises
        # TypeError on any shared key, which meant a per-manifest entry could
        # add arguments but never actually override one.
        # Each published capability has its own processor_request schema, so a
        # manifest entry may supply one; the governance request is the default.
        arguments = {"data": spec["data"], "processor_request": spec["processor_request"],
                     **spec["common"], **overrides}
        manifest = build_manifest(**arguments)
        validate_ingress_manifest(manifest)
        built[name] = manifest
    return built


def rendered(manifest):
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="overwrite the committed fixtures with what the SDK builds now")
    args = parser.parse_args()
    drift = []
    for name, manifest in rebuild().items():
        path = MANIFESTS / (name + ".json")
        fresh = rendered(manifest)
        if args.write:
            path.write_text(fresh, encoding="utf-8")
            print("wrote", path.name)
            continue
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if current != fresh:
            drift.append(name)
        print(("DRIFT " if current != fresh else "MATCH ") + name)
    if drift:
        raise SystemExit("SDK_MANIFEST_FIXTURE_DRIFT:" + ",".join(drift))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
