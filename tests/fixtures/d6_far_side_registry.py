#!/usr/bin/env python3
"""Write the registry a D6 far-side case runs against (stdlib only).

The case adds the fixture's admitted pair to one service of a copy of the
committed registry, so the crossing selects that service by the manifest's
declared processing and reaches the far side. The committed registry is read,
never written.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/d6-far-side-non-allow.json"


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def registry_for(case):
    spec = fixture()
    chosen = spec["cases"][case]
    registry = copy.deepcopy(json.loads((ROOT / spec["registry"]).read_text(encoding="utf-8")))
    matches = [service for service in registry["services"]
               if service.get("service_id") == chosen["admit_on_service"]]
    if len(matches) != 1:
        raise SystemExit("D6_FIXTURE_SERVICE_NOT_IN_REGISTRY:" + chosen["admit_on_service"])
    rows = list(matches[0].get("admits_processing") or [])
    if spec["admitted_pair"] not in rows:
        rows.append(dict(spec["admitted_pair"]))
    matches[0]["admits_processing"] = rows
    return registry


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case", required=True, choices=sorted(fixture()["cases"]))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(registry_for(args.case), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
