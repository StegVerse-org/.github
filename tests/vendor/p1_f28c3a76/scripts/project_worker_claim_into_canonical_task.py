#!/usr/bin/env python3
"""Project existing WorkerCoordinator ownership into canonical task state.

The WorkerCoordinator registry is the sole source for claim/fence ownership.
This utility never creates or alters a WorkerCoordinator claim. It only copies a
uniquely matched existing claim/fence into canonical task projection after the
task has reached an admitted state.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"FAIL_CLOSED: object required: {path}")
    return value


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise SystemExit("FAIL_CLOSED: " + reason)


def worker_projection(worker_registry: dict[str, Any], task_id: str) -> dict[str, Any]:
    matches = [row for row in worker_registry.get("tasks", []) if row.get("task_id") == task_id or row.get("goal_id") == task_id]
    require(len(matches) <= 1, "WorkerCoordinator task identity ambiguous")
    if not matches:
        return {
            "matched": False,
            "claim_ref": None,
            "fence_ref": None,
            "worker_id": None,
            "worker_instance_id": None,
            "state": None,
            "projection_only": True,
        }
    row = matches[0]
    timing = row.get("heartbeat_timing") if isinstance(row.get("heartbeat_timing"), dict) else {}
    timer = row.get("assignment_timer") if isinstance(row.get("assignment_timer"), dict) else {}
    fence = timer.get("fencing_token", timing.get("fencing_token"))
    claim = row.get("claim_id")
    return {
        "matched": True,
        "claim_ref": claim,
        "fence_ref": fence,
        "worker_id": row.get("worker_id"),
        "worker_instance_id": row.get("worker_instance_id"),
        "state": row.get("state"),
        "executor_binding": row.get("executor_binding"),
        "last_checkpoint_ref": row.get("last_checkpoint_ref"),
        "projection_only": True,
    }


def project(registry: dict[str, Any], worker_registry: dict[str, Any], task_id: str) -> dict[str, Any]:
    proposed = copy.deepcopy(registry)
    matches = [task for task in proposed.get("tasks", []) if task.get("task_id") == task_id]
    require(len(matches) == 1, "canonical task identity must resolve exactly once")
    task = matches[0]
    require(task.get("coordination_state") not in {None, "PROPOSED"}, "task must be admitted before ownership projection")

    projection = worker_projection(worker_registry, task_id)
    task["worker_claim"] = {
        "authority": "WORKERCOORDINATOR",
        "claim_ref": projection.get("claim_ref"),
        "fence_ref": projection.get("fence_ref"),
        "worker_id": projection.get("worker_id"),
        "worker_instance_id": projection.get("worker_instance_id"),
        "worker_state": projection.get("state"),
        "executor_binding": projection.get("executor_binding"),
        "last_checkpoint_ref": projection.get("last_checkpoint_ref"),
        "projection_only": True,
    }

    if projection["matched"] and projection.get("claim_ref") is not None and projection.get("fence_ref") is not None:
        if task.get("coordination_state") in {"INGRESS_ADMITTED", "CLAIMABLE", "CLAIMED", "IN_PROGRESS"}:
            task["coordination_state"] = "CLAIMED" if projection.get("state") not in {"IN_PROGRESS", "RUNNING"} else "IN_PROGRESS"
        task["allowed_next_transitions"] = ["IN_PROGRESS", "COMPLETION_CLAIMED", "TRANSFERRED"]
    elif task.get("coordination_state") == "INGRESS_ADMITTED":
        task["allowed_next_transitions"] = ["CLAIMABLE", "RECONCILIATION_REQUIRED"]

    proposed["generation"] = int(registry.get("generation", 0)) + 1
    proposed["status"] = "WORKERCOORDINATOR_OWNERSHIP_PROJECTED" if projection["matched"] else "WORKERCOORDINATOR_NO_MATCH_PROJECTED"
    proposed.setdefault("nonclaims", [])
    for claim in (
        "TASK_REGISTRY_PROJECTION_DOES_NOT_MINT_WORKERCOORDINATOR_CLAIM_OR_FENCE",
        "WORKERCOORDINATOR_PROJECTION_DOES_NOT_PROVE_TASK_EXECUTION",
        "HB32_OSCILLATOR_REFERENCE_DOES_NOT_GRANT_TASK_AUTHORITY",
    ):
        if claim not in proposed["nonclaims"]:
            proposed["nonclaims"].append(claim)
    return proposed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--registry", default="data/canonical-task-registry.json")
    parser.add_argument("--worker-registry", default="control/worker-registry.json")
    parser.add_argument("--output")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    registry_path = Path(args.registry)
    proposed = project(load(registry_path), load(Path(args.worker_registry)), args.task_id)
    text = json.dumps(proposed, indent=2, sort_keys=True) + "\n"
    if args.apply:
        registry_path.write_text(text, encoding="utf-8")
    elif args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
