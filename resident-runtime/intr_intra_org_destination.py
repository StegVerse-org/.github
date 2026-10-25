#!/usr/bin/env python3
"""InTr destination rule, declared form: only an organization's .github is an InTr destination.

SKAP Vault inside KV is the only PII and credential store for every user, the ecosystem's own included; the ecosystem holds none (HST citation pending P1 #163).

StegVerse-org/.github#237 (Lane B, lane-b-91117956; definition #167). The governing text declares InTr paths only
between distinct organizations, each addressed at its own .github:
  data/intr-protocol/v1/protocol.json        declared_paths: "every ordered pair of distinct organizations ..."
  docs/INTR_PATH_TRANSFER_V1.md              "Every ordered pair of distinct organizations ..."
  resident-runtime/federation_cycle.py       "intra-organization: no boundary is crossed and no InTr is involved"
  README.md                                  "StegVerse-org/LLM-adapter and StegVerse-org/.github are both inside
                                              StegVerse-org, so ... no Interlock/InTr is involved"
  org-runtime/interlock-intr.json            llm_adapter_is_outbound_organization_destination: false
No invariant, Task Registry entry or operational doc declares an intra-organization or repository-to-repository InTr
destination, so the default is fail-closed: such an edge is refused with six fields and nothing is appended. A
crossing between two organizations' .github repositories is answered by the declared mesh paths
(resident-runtime/intr_path_transfer.py declared_paths). Within an organization, repository transitions are carried
up by the resident cycle (federation_cycle.py / propagate_repository_receipts.py), not by InTr.

No clock, no network, no ledger write, no credential; authority effect NONE_REFUSAL_ONLY.

  check --source OWNER/REPO --destination OWNER/REPO   -> the judgment (exit 1 unless ALLOW)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ALLOW = "ALLOW"
FAIL_CLOSED = "FAIL_CLOSED"
DESTINATION_REPOSITORY = ".github"
GOAL = "StegVerse-org/.github#162 (Lane B); definition StegVerse-org/.github#167"
RETRY = "python resident-runtime/intr_intra_org_destination.py check --source <ORG>/.github --destination <ORG>/.github"
# (path, a phrase that line must contain): the declaring text this rule rests on; tests resolve each to its line.
CITATIONS = (
    ("data/intr-protocol/v1/protocol.json", "every ordered pair of distinct organizations"),
    ("docs/INTR_PATH_TRANSFER_V1.md", "Every ordered pair of distinct organizations"),
    ("resident-runtime/federation_cycle.py", "intra-organization: no boundary is crossed and no InTr is involved"),
    ("README.md", "so no organization boundary is between them and no Interlock/InTr is involved"),
    ("org-runtime/interlock-intr.json", '"llm_adapter_is_outbound_organization_destination": false'),
)


def citations() -> list[str]:
    """Each citation as path:line, resolved from the committed text (a missing phrase is an error, never skipped)."""
    out = []
    for rel, phrase in CITATIONS:
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        hits = [i + 1 for i, line in enumerate(lines) if phrase in line]
        if not hits:
            raise SystemExit("FAIL_CLOSED: INTR_DESTINATION_RULE_CITATION_MISSING " + rel)
        out.append(rel + ":" + str(hits[0]))
    return out


def _transfer() -> Any:
    name = "intr_path_transfer"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "resident-runtime" / "intr_path_transfer.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def _split(repository: str) -> tuple[str, str]:
    owner, _, name = str(repository).partition("/")
    if not owner or not name or "/" in name:
        raise SystemExit("FAIL_CLOSED: INTR_DESTINATION_REPOSITORY_INVALID " + str(repository))
    return owner, name


def _refuse(source: str, destination: str, code: str, predicate: str, repair: str) -> dict[str, Any]:
    return {"source_repository": source, "destination_repository": destination, "disposition": FAIL_CLOSED,
            "failure_code": code, "failed_predicate": predicate, "required_evidence_or_repair": repair,
            "retry_entrypoint": RETRY, "owning_existing_goal": GOAL,
            "next_attempt": "only after a #167 definition ruling amends the cited text; until then this edge stays "
                            "refused and nothing is appended",
            "citations": citations(), "authority_effect": "NONE_REFUSAL_ONLY"}


def judge(source: str, destination: str, declared: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    s_org, s_repo = _split(source)
    d_org, d_repo = _split(destination)
    if s_org == d_org:
        return _refuse(source, destination, "INTR_INTRA_ORG_DESTINATION_UNDECLARED",
                       "INTR_PATH_IS_BETWEEN_DISTINCT_ORGANIZATIONS",
                       "within one organization no boundary is crossed: carry the repository's transition up with the "
                       "resident cycle (resident-runtime/federation_cycle.py, propagate_repository_receipts.py), not InTr")
    if s_repo != DESTINATION_REPOSITORY or d_repo != DESTINATION_REPOSITORY:
        return _refuse(source, destination, "INTR_REPOSITORY_DESTINATION_UNDECLARED",
                       "ONLY_AN_ORGANIZATION_DOT_GITHUB_IS_AN_INTR_ENDPOINT",
                       "address the crossing from " + s_org + "/.github to " + d_org + "/.github; the receiving "
                       "organization routes inside itself")
    paths = _transfer().declared_paths() if declared is None else declared
    pid = s_org + "->" + d_org + ":intr-destination"
    if pid not in {p["path_id"] for p in paths}:
        return _refuse(source, destination, "INTR_PATH_UNDECLARED", "PATH_IS_A_DECLARED_MESH_PATH",
                       "both organizations' destination documents conform in the pinned mesh snapshot "
                       "(tests/fixtures/intr-protocol/destinations/manifest.json)")
    return {"source_repository": source, "destination_repository": destination, "disposition": ALLOW,
            "path_id": pid, "authority_effect": "NONE_DECLARATION_CHECK_ONLY"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check")
    c.add_argument("--source", required=True)
    c.add_argument("--destination", required=True)
    args = parser.parse_args(argv)
    result = judge(args.source, args.destination)
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0 if result["disposition"] == ALLOW else 1


if __name__ == "__main__":
    raise SystemExit(main())
