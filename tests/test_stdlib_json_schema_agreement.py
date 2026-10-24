"""The pinned stdlib JSON Schema validator agrees with jsonschema (StegVerse-org/.github#166).

jsonschema is the oracle here and only here: every other use in this repository validates with the pinned
StegVerse-Labs stdlib validator (`resident-runtime/pinned_labs.py`). This module re-derives, with
jsonschema.Draft202012Validator, the verdict for every case in the pinned agreement corpus (the instances the
Labs consumer tests assert, plus good/bad cases for each implemented keyword) and for this repository's own task
registry (as committed and with the violations the reviewer prompt describes), and requires the stdlib validator
to give the same verdict; and that every unsupported-keyword case is refused with six fields, never accepted.

Inputs: jsonschema (installed in required-verification.yml full-suite) and STEGVERSE_LABS_ROOT (the pinned Labs
checkout). Either missing is an error, never a skip. Source validation only. No authority effect is claimed.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import json
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "resident-runtime"))
import pinned_labs  # noqa: E402

SIX = pinned_labs.SIX
CORPUS = "tests/fixtures/stdlib-json-schema/agreement-corpus.json"


ORACLE_VERSION = "4.26.0"   # the version required-verification.yml installs; 4.10.3 equates nested true with 1


def oracle(schema, instance) -> bool:
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema).is_valid(instance)


class Agreement(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sjs = pinned_labs.json_schema()
        cls.labs = pinned_labs.labs_root()
        cls.corpus = json.loads(pinned_labs.path(CORPUS).read_text(encoding="utf-8"))

    def agree(self, schema, instance, label: str) -> bool:
        want = oracle(schema, instance)
        got = self.sjs.Validator(schema).is_valid(instance)
        self.assertEqual(got, want, label)
        return want

    def test_the_oracle_is_the_qualified_jsonschema(self) -> None:
        # an oracle that is itself wrong cannot adjudicate agreement: require the pinned version and that it keeps
        # booleans distinct from numbers at depth (JSON Schema instance equality), as the stdlib validator does
        self.assertEqual(importlib.metadata.version("jsonschema"), ORACLE_VERSION,
                         "install the qualified oracle: python -m pip install \"jsonschema==%s\"" % ORACLE_VERSION)
        for schema, instance in (({"enum": [{"k": [1]}]}, {"k": [True]}), ({"const": [0]}, [False]),
                                 ({"enum": [1]}, True)):
            self.assertFalse(oracle(schema, instance), (schema, instance))
            self.assertFalse(self.sjs.Validator(schema).is_valid(instance), (schema, instance))
        from tests.workflow_surface import catalog_group, step_bodies   # G17 (#238): a catalog group
        wf = step_bodies(catalog_group("required-verification.full-suite"))
        self.assertIn('python -m pip install "jsonschema==%s"' % ORACLE_VERSION, wf)

    def test_the_corpus_is_the_pinned_one_and_names_its_validator(self) -> None:
        self.assertEqual(self.corpus["schema"], "stegverse.stdlib-json-schema-agreement-corpus/v1")
        self.assertEqual(self.corpus["validator"], "scripts/stdlib_json_schema.py")
        self.assertGreaterEqual(len(self.corpus["schema_cases"]), 40)

    def test_every_consumer_case_agrees_with_jsonschema_and_its_recorded_verdict(self) -> None:
        verdicts = set()
        for case in self.corpus["schema_cases"]:
            raw = (self.labs / case["schema_path"]).read_bytes()
            # the schema bytes are pinned transitively: the corpus (pinned by sha256) records their sha256
            self.assertEqual(hashlib.sha256(raw).hexdigest(), case["schema_sha256"].removeprefix("sha256:"),
                             case["schema_path"])
            with self.subTest(case=case["label"]):
                want = self.agree(json.loads(raw), case["instance"], case["label"])
                self.assertEqual(want, case["expected_valid"], case["source_test"])
                verdicts.add(want)
        self.assertEqual(verdicts, {True, False})       # both verdicts are exercised

    def test_every_keyword_case_agrees_with_jsonschema(self) -> None:
        for case in self.corpus["keyword_cases"]:
            for expected, key in ((True, "good"), (False, "bad")):
                for instance in case.get(key, []):
                    with self.subTest(keyword=case["keyword"], instance=instance):
                        self.assertEqual(self.agree(case["schema"], instance, case["keyword"]), expected)

    def test_every_unsupported_case_is_refused_with_six_fields_never_accepted(self) -> None:
        for case in self.corpus["unsupported"]:
            with self.subTest(case=case["label"]):
                with self.assertRaises(self.sjs.SchemaUnsupported) as caught:
                    self.sjs.Validator(case["schema"])
                self.assertTrue(all(caught.exception.item.get(k) for k in SIX), caught.exception.item)

    def test_this_repositorys_task_registry_agrees_as_committed_and_violated(self) -> None:
        schema = json.loads((ROOT / "orchestration/schemas/task-registry.schema.json").read_text(encoding="utf-8"))
        registry = json.loads((ROOT / "orchestration/task-registry.json").read_text(encoding="utf-8"))
        self.assertTrue(self.agree(schema, registry, "committed registry"))
        violations = {}
        v = copy.deepcopy(registry); v["tasks"][0]["assignee"] = "someone"; violations["assignee"] = v
        v = copy.deepcopy(registry); v["registry_type"] = "other"; violations["registry_type const"] = v
        v = copy.deepcopy(registry); del v["tasks"][0]["task_id"]; violations["task_id required"] = v
        v = copy.deepcopy(registry); v["tasks"][0]["issue"] = "1"; violations["issue type"] = v
        v = copy.deepcopy(registry); v["tasks"] = "none"; violations["tasks type"] = v
        for label, instance in violations.items():
            with self.subTest(violation=label):
                self.assertFalse(self.agree(schema, instance, label))


if __name__ == "__main__":
    unittest.main()
