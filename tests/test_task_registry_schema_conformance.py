"""The registry must conform to the schema its owner publishes, not a copy.

`StegVerse-Labs/repo-standards` owns the orchestration task registry: ST-021
defines the progression automaton, `schemas/task-registry.schema.json` defines
the record, and `tools/validate_orchestration_surface.py` checks the surface.
Vendoring a copy of that schema here would drift silently the moment the owner
changes it, and a registry validated against a stale copy is a registry
nothing is really checking.

So this validates against the owner's schema, checked out at a pin by the
workflow that runs these cases -- the same arrangement the SDK manifest
crossing uses for the SDK's manifest contract.

Requires the checked-out repo-standards schema; it cannot run without it.

Source validation only. No authority effect is claimed.
"""
import json
import os
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "orchestration/task-registry.json").read_text(encoding="utf-8"))
STANDARDS = Path(os.environ.get("REPO_STANDARDS_ROOT", str(ROOT.parent / "repo-standards")))
SCHEMA_PATH = STANDARDS / "schemas/task-registry.schema.json"


class SchemaConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SCHEMA_PATH.is_file():
            raise unittest.SkipTest("repo-standards schema not checked out: " + str(SCHEMA_PATH))
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_the_registry_validates_against_the_owners_schema(self):
        jsonschema.validate(REGISTRY, self.schema)

    def test_the_schema_is_the_orchestration_task_registry(self):
        """Guard against validating happily against some other schema."""
        self.assertEqual(self.schema["title"], "StegVerse Orchestration Task Registry")
        self.assertEqual(
            self.schema["properties"]["registry_type"]["const"],
            "orchestration_task_registry")

    def test_the_owners_schema_still_carries_no_entity_field(self):
        """Entity neutrality is a property of the canon, not a local choice.

        If the owner ever adds an assignee or agent field, this organization's
        entity-neutrality cases need revisiting rather than quietly passing.
        """
        task_properties = set(
            self.schema["properties"]["tasks"]["items"]["properties"])
        for name in ("assignee", "assignees", "agent", "entity", "model", "llm", "claimed_by"):
            self.assertNotIn(name, task_properties)

    def test_every_field_this_registry_uses_is_one_the_schema_defines(self):
        """`additionalProperties: false` already rejects extras; this names which."""
        defined = set(self.schema["properties"]["tasks"]["items"]["properties"])
        for task in REGISTRY["tasks"]:
            with self.subTest(task=task["task_id"]):
                self.assertTrue(set(task) <= defined,
                                "not in the owner's schema: " + str(sorted(set(task) - defined)))


if __name__ == "__main__":
    unittest.main()
