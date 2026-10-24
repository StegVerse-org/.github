"""Conformance of the proposed stegverse.org-emp-kv-projection/v1 schema.

The schema declares the projection a WorkSpace Org gate reads; it produces no projection and grants nothing.
The test validates with a stdlib subset of JSON Schema (const, enum, type, pattern, required,
additionalProperties, properties, $ref to $defs) so no dependency is added, and checks that the gate rule opens
only on five receipt-backed OBSERVED_TRUE predicates under Interlock/InTr admission, failing closed otherwise.
"""
from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "orchestration/schemas/org-emp-kv-projection.v1.schema.json").read_text(encoding="utf-8"))
GATE_KEYS = ["employee_identity_matches", "machine_identity_matches", "active_membership",
             "role_capability_admitted", "transition_admitted"]
SIX = ["failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
       "owning_existing_goal", "next_attempt"]
TYPES = {"object": dict, "string": str, "null": type(None), "array": list, "boolean": bool}


def errors(value, schema, path="$"):
    if "$ref" in schema:
        schema = SCHEMA["$defs"][schema["$ref"].rsplit("/", 1)[-1]]
    out = []
    if "const" in schema and value != schema["const"]:
        return [f"{path}: const"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: enum"]
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(isinstance(value, TYPES[t]) and not (t == "object" and isinstance(value, bool)) for t in allowed):
            return [f"{path}: type"]
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        out.append(f"{path}: pattern")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                out.append(f"{path}.{key}: required")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            out += [f"{path}.{k}: additional" for k in value if k not in props]
        for key, sub in props.items():
            if key in value:
                out += errors(value[key], sub, f"{path}.{key}")
    return out


def projection(state="OBSERVED_TRUE"):
    return {
        "schema": "stegverse.org-emp-kv-projection/v1",
        "projection_id": "org-emp-kv:example:0001",
        "organization": "StegVerse-org",
        "principal_ref": "principal:example",
        "ledger": {"root": "ORGANIZATION_LEDGER_ROOT", "head_sha256": "a" * 64},
        "predicates": {k: {"state": state, "receipt_ref": None if state == "NOT_OBSERVED" else f"receipt:{k}"}
                       for k in GATE_KEYS},
        "admission": {"transition_authority": "Interlock/InTr", "credential_authority": "TV/TVC",
                      "receipt_ref": "receipt:intr-admission"},
        "issued_at": "2026-10-18T23:00:00Z",
        "authority_effect": "NONE",
    }


def gate_opens(value) -> bool:
    """The schema's x-stegverse-gate-rule, applied: conformance plus five receipt-backed OBSERVED_TRUE states."""
    if errors(value, SCHEMA):
        return False
    return all(value["predicates"][k]["state"] == "OBSERVED_TRUE" and value["predicates"][k]["receipt_ref"]
               for k in GATE_KEYS)


class OrgEmpKVProjectionSchemaTests(unittest.TestCase):
    def test_schema_identity_and_proposed_status(self):
        self.assertEqual(SCHEMA["properties"]["schema"]["const"], "stegverse.org-emp-kv-projection/v1")
        self.assertEqual(SCHEMA["properties"]["authority_effect"]["const"], "NONE")
        rule = SCHEMA["x-stegverse-gate-rule"]
        self.assertEqual(rule["gate_predicate"], "ADMITTED_ORG_LEDGER_PROJECTION_SCHEMA_DECLARED")
        self.assertEqual(rule["status"], "PROPOSED_OWNER_CHOOSES_BY_MERGE")
        self.assertIs(rule["storage_is_evidence"], False)
        self.assertEqual(rule["otherwise"]["disposition"], "FAIL_CLOSED")
        self.assertEqual(rule["otherwise"]["required_actionable_fields"], SIX)

    def test_predicates_are_exactly_the_five_org_gate_keys(self):
        self.assertEqual(SCHEMA["properties"]["predicates"]["required"], GATE_KEYS)
        self.assertEqual(sorted(SCHEMA["properties"]["predicates"]["properties"]), sorted(GATE_KEYS))

    def test_full_receipt_backed_projection_conforms_and_opens(self):
        self.assertEqual(errors(projection(), SCHEMA), [])
        self.assertTrue(gate_opens(projection()))

    def test_not_observed_or_false_conforms_but_never_opens(self):
        for state in ("NOT_OBSERVED", "OBSERVED_FALSE"):
            value = projection(state)
            self.assertEqual(errors(value, SCHEMA), [], state)
            self.assertFalse(gate_opens(value), state)
        one_false = projection()
        one_false["predicates"]["active_membership"]["state"] = "OBSERVED_FALSE"
        self.assertFalse(gate_opens(one_false))

    def test_true_without_receipt_never_opens(self):
        value = projection()
        value["predicates"]["transition_admitted"]["receipt_ref"] = None
        self.assertFalse(gate_opens(value))

    def test_nonconforming_projections_fail_closed(self):
        cases = {
            "missing predicate": lambda v: v["predicates"].pop("machine_identity_matches"),
            "extra predicate": lambda v: v["predicates"].update(storage_flag={"state": "OBSERVED_TRUE", "receipt_ref": "x"}),
            "authority claimed": lambda v: v.update(authority_effect="ALLOW"),
            "wrong transition authority": lambda v: v["admission"].update(transition_authority="sessionStorage"),
            "wrong credential authority": lambda v: v["admission"].update(credential_authority="GITHUB_TOKEN"),
            "wrong ledger root": lambda v: v["ledger"].update(root="BROWSER_STORAGE"),
            "malformed head": lambda v: v["ledger"].update(head_sha256="not-a-digest"),
            "unknown state": lambda v: v["predicates"]["active_membership"].update(state="ASSUMED"),
            "extra top-level field": lambda v: v.update(cached_from="sessionStorage"),
            "wrong schema": lambda v: v.update(schema="stegverse.org-emp-kv-projection/v0"),
            "missing admission": lambda v: v.pop("admission"),
        }
        for name, mutate in cases.items():
            value = copy.deepcopy(projection())
            mutate(value)
            self.assertNotEqual(errors(value, SCHEMA), [], name)
            self.assertFalse(gate_opens(value), name)

    def test_non_object_inputs_fail_closed(self):
        for value in (None, "projection", [], 1, True):
            self.assertFalse(gate_opens(value))


if __name__ == "__main__":
    unittest.main()
