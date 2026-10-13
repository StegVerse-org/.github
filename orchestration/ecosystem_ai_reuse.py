"""Source-only reusable capability matching for Ecosystem AI issue #160.

Consumes existing Task Registry tasks and SDK capability inventory projections.
No new registry, authority, runtime discovery, or component admission is created.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence


def discover_reuse(
    task: Mapping[str, Any],
    capabilities: Sequence[Mapping[str, Any]],
    *,
    required_capabilities: Sequence[str],
) -> dict[str, Any]:
    """Return deterministic candidate reuse decisions, never execution authority.

    An empty required_capabilities sequence is explicit: no inferred requirements.
    Candidate routes must be declared and installed, but source-only installed
    status never constitutes runtime observation or authorization.
    """
    task_id = task.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("task_id required from canonical Task Registry")
    if isinstance(required_capabilities, (str, bytes)):
        raise TypeError("required_capabilities must be a sequence of identifiers")
    rows = []
    for requested in sorted(set(required_capabilities)):
        if not isinstance(requested, str) or not requested:
            raise ValueError("capability identifiers must be nonempty strings")
        matches = sorted(
            (c for c in capabilities if c.get("capability_id") == requested),
            key=lambda c: str(c.get("route_id") or ""),
        )
        candidates = [
            {
                "capability_id": requested,
                "route_id": c.get("route_id"),
                "runtime_installed": c.get("runtime_installed") is True,
                "evidence_ceiling": "SOURCE_DECLARATION_ONLY",
                "execution_authorized": False,
            }
            for c in matches if c.get("route_id")
        ]
        rows.append({
            "required_capability": requested,
            "disposition": (
                "CANDIDATE_REUSE" if any(c["runtime_installed"] for c in candidates)
                else "CAPABILITY_DEVELOPMENT_REVIEW_REQUIRED"
            ),
            "candidates": candidates,
        })
    return {
        "schema": "stegverse.ecosystem-ai.reuse-discovery.v1",
        "task_id": task_id,
        "source": "EXISTING_TASK_REGISTRY_AND_SDK_CAPABILITY_INVENTORY",
        "requirements_explicit": True,
        "results": rows,
        "execution_authorized": False,
        "runtime_observed": False,
        "library_admission_granted": False,
    }
