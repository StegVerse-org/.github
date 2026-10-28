"""G17 workflow-surface registry: an unregistered or drifted workflow fails closed.

Replaces exact-count pins: the repository's workflow files must equal the
registry's surfaces[], each with its registered classification, triggers and
permissions; the count stays within the preferred maximum unless every surface
beyond it is a documented exception pending owner approval; every folded
workflow's checks are catalog groups the stable dispatcher runs. Stdlib only.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "control/workflow-surface-registry.json"
CATALOG = ROOT / "tools/tasks/task_catalog.json"
WORKFLOWS = ROOT / ".github/workflows"
NON_ALLOW_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
                    "retry_entrypoint", "owning_existing_goal", "next_attempt")
GATED_TRIGGERS = {"workflow_dispatch", "schedule", "repository_dispatch", "issues",
                  "issue_comment", "workflow_run", "workflow_call", "release"}


def _strip(value):
    value = value.split(" #", 1)[0].strip()
    return value.strip("'\"")


def triggers(text):
    if "\non:\n" not in text:
        line = re.search(r"^on: *(.+)$", text, re.M)
        if not line:
            return []
        raw = line.group(1).strip()
        return [_strip(t) for t in raw.strip("[]").split(",")] if raw.startswith("[") else [_strip(raw)]
    block = text.split("\non:\n", 1)[1]
    keys = []
    for line in block.splitlines():
        if line and not line.startswith(" ") and not line.startswith("#"):
            break
        m = re.match(r"^  ([A-Za-z_]+):", line)
        if m:
            keys.append(m.group(1))
    return keys


def _block(lines, start, indent):
    out = {}
    for line in lines[start:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        lead = len(line) - len(line.lstrip(" "))
        if lead < indent:
            break
        if lead == indent:
            k, _, v = line.strip().partition(":")
            out[k] = _strip(v)
    return out


def _perm(lines, index, indent):
    rest = lines[index].split(":", 1)[1].strip()
    if rest:
        rest = _strip(rest)
        return {} if rest == "{}" else rest
    return _block(lines, index + 1, indent + 2)


def permissions(text):
    lines = text.splitlines()
    out = {"workflow": None, "jobs": {}}
    job = None
    in_jobs = False
    for i, line in enumerate(lines):
        if line.startswith("permissions:"):
            out["workflow"] = _perm(lines, i, 0)
        if line.startswith("jobs:"):
            in_jobs = True
            continue
        if in_jobs:
            m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
            if m:
                job = m.group(1)
            elif job and line.startswith("    permissions:"):
                out["jobs"][job] = _perm(lines, i, 4)
    return out


def registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def fail_closed(test, condition, code, predicate, repair):
    test.assertTrue(condition, json.dumps({
        "disposition": "FAIL_CLOSED", "failure_code": code, "failed_predicate": predicate,
        "required_evidence_or_repair": repair,
        "retry_entrypoint": "tests/test_workflow_surface_registry.py",
        "owning_existing_goal": registry()["goal_id"],
        "next_attempt": "the next push or pull request touching .github/workflows/"}))


class WorkflowSurfaceRegistryTests(unittest.TestCase):
    def setUp(self):
        self.reg = registry()
        self.files = sorted(".github/workflows/" + p.name for p in WORKFLOWS.iterdir()
                            if p.suffix in (".yml", ".yaml"))
        self.surfaces = {s["path"]: s for s in self.reg["surfaces"]}

    def test_every_workflow_file_is_registered(self):
        for path in self.files:
            fail_closed(self, path in self.surfaces, "UNREGISTERED_WORKFLOW_SURFACE",
                        "EVERY_WORKFLOW_FILE_IS_REGISTERED",
                        f"register {path} in control/workflow-surface-registry.json surfaces[] or fold it into tools/tasks/task_catalog.json")
        for path in self.surfaces:
            fail_closed(self, path in self.files, "REGISTERED_WORKFLOW_ABSENT",
                        "EVERY_REGISTERED_SURFACE_EXISTS", f"remove {path} from surfaces[] or restore it")

    def test_the_unregistered_outcome_carries_the_six_fields(self):
        outcome = self.reg["unregistered_workflow_outcome"]
        self.assertEqual(outcome["disposition"], "FAIL_CLOSED")
        for field in NON_ALLOW_FIELDS:
            self.assertTrue(outcome[field], field)

    def test_registered_triggers_and_permissions_match_the_files(self):
        for path, surface in self.surfaces.items():
            text = (ROOT / path).read_text(encoding="utf-8")
            fail_closed(self, sorted(triggers(text)) == sorted(surface["triggers"]),
                        "WORKFLOW_TRIGGERS_DRIFTED", "REGISTERED_TRIGGERS_EQUAL_THE_FILE",
                        f"{path}: file {triggers(text)} registry {surface['triggers']}")
            fail_closed(self, permissions(text) == surface["permissions"],
                        "WORKFLOW_PERMISSIONS_DRIFTED", "REGISTERED_PERMISSIONS_EQUAL_THE_FILE",
                        f"{path}: file {permissions(text)} registry {surface['permissions']}")

    def test_count_is_within_the_rule_and_exceptions_are_documented(self):
        preferred = self.reg["preferred_repository_workflow_count_max"]
        ceiling = self.reg["exception_repository_workflow_count_max"]
        fail_closed(self, len(self.files) <= ceiling, "WORKFLOW_COUNT_ABOVE_CEILING",
                    "WORKFLOW_COUNT_WITHIN_EXCEPTION_CEILING", f"{len(self.files)} > {ceiling}: fold into the catalog")
        exceptions = [s for s in self.surfaces.values() if s["classification"] == "KEEP_STANDALONE_EXCEPTION"]
        self.assertLessEqual(len(self.files) - len(exceptions), preferred)
        for surface in exceptions:
            exception = surface.get("exception") or {}
            fail_closed(self, exception.get("status") == "EXCEPTION_PENDING_OWNER_APPROVAL"
                        or exception.get("status") == "EXCEPTION_APPROVED",
                        "UNDOCUMENTED_WORKFLOW_EXCEPTION", "ABOVE_TWO_REQUIRES_DOCUMENTED_NECESSITY",
                        f"{surface['path']}: document technical_necessity and evidence")
            self.assertTrue(exception.get("technical_necessity"))
            self.assertTrue(exception.get("evidence"))
        handoff = ROOT / "docs/WORKFLOW_SURFACE_MIRROR_HANDOFF.md"
        for surface in exceptions:
            self.assertIn(surface["path"], handoff.read_text(encoding="utf-8"))
        self.assertIn("exception pending owner approval", handoff.read_text(encoding="utf-8")) if exceptions else None

    def test_gated_triggers_only_on_registered_exceptions(self):
        for path, surface in self.surfaces.items():
            gated = set(surface["triggers"]) & GATED_TRIGGERS
            allowed = set((surface.get("exception") or {}).get("retained_triggers_needing_decision", []))
            fail_closed(self, gated <= allowed, "NON_MANIFEST_TRIGGER", "TRIGGERS_ARE_STATE_TRANSITIONS",
                        f"{path}: remove {sorted(gated - allowed)} or record it as an exception")

    def test_the_dispatcher_runs_every_event_without_path_filters(self):
        dispatchers = [s for s in self.surfaces.values()
                       if s["classification"] == "KEEP_STABLE_DISPATCHER" and s.get("catalog")]
        self.assertEqual(len(dispatchers), 1)
        text = (ROOT / dispatchers[0]["path"]).read_text(encoding="utf-8")
        head = text.split("\npermissions:", 1)[0]
        self.assertEqual(sorted(triggers(text)), ["pull_request", "push"])
        self.assertNotIn("paths", head)
        self.assertIn("run_catalog.py verify", text)
        self.assertIn("run_catalog.py run --group", text)
        self.assertEqual(permissions(text)["workflow"], {})

    def test_every_folded_check_is_a_catalog_group(self):
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        ids = {g["id"] for g in catalog["groups"]}
        claimed = set()
        for row in self.reg["folded"]:
            self.assertNotIn(row["workflow"], self.files, row["workflow"])
            for gid in row.get("catalog_groups", []):
                fail_closed(self, gid in ids, "FOLDED_CHECK_NOT_IN_CATALOG", "EVERY_FOLDED_CHECK_STILL_RUNS",
                            f"{row['workflow']}: restore catalog group {gid}")
                claimed.add(gid)
        for gid in ids:
            self.assertTrue(gid in claimed or any(gid in (e.get("catalog_groups") or [])
                                                  for e in self.reg.get("catalog_additions", [])), gid)

    def test_the_catalog_verifies(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools/tasks/run_catalog.py"), "verify"],
                                capture_output=True, text=True)
        fail_closed(self, result.returncode == 0, "CATALOG_DRIFT", "CATALOG_MATCHES_PINNED_BODIES", result.stdout[-2000:])

    def test_pending_non_allow_records_carry_the_six_fields(self):
        for row in self.reg.get("fail_closed_pending", []) + self.reg.get("transfer_pending", []):
            for field in NON_ALLOW_FIELDS:
                self.assertTrue(row.get(field), (row.get("surface"), field))


if __name__ == "__main__":
    unittest.main()
