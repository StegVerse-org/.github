"""The pinned StegVerse-Labs tool loader fails closed (StegVerse-org/.github#166). Stdlib only, no network."""
from __future__ import annotations

import json
import re
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "resident-runtime"))
if str(ROOT) not in sys.path:  # tests.workflow_surface (G17 #238) when run with --start tests
    sys.path.append(str(ROOT))
import pinned_labs  # noqa: E402


class PinnedLabsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = os.environ.get(pinned_labs.ENV)
        self.addCleanup(self.restore)

    def restore(self) -> None:
        if self.old is None:
            os.environ.pop(pinned_labs.ENV, None)
        else:
            os.environ[pinned_labs.ENV] = self.old

    def refusal(self, fn, *args) -> dict:
        with self.assertRaises(pinned_labs.PinnedLabsUnavailable) as caught:
            fn(*args)
        item = caught.exception.item
        self.assertEqual(set(item), set(pinned_labs.SIX))
        self.assertTrue(all(item.values()), item)
        self.assertEqual(item["failure_code"], "PINNED_LABS_TOOL_UNAVAILABLE")
        return item

    def test_the_pin_names_the_validator_and_its_agreement_corpus_by_sha256(self) -> None:
        pin = pinned_labs.pin()
        self.assertRegex(pin["commit"], r"^[0-9a-f]{40}$")
        for rel in ("scripts/stdlib_json_schema.py", "tests/fixtures/stdlib-json-schema/agreement-corpus.json",
                    "scripts/test_set_selection.py", "scripts/test_suite_baseline_drift.py"):
            self.assertRegex(pin["files"][rel], r"^[0-9a-f]{64}$", rel)

    def test_no_named_checkout_is_refused_never_skipped(self) -> None:
        os.environ.pop(pinned_labs.ENV, None)
        item = self.refusal(pinned_labs.json_schema)
        self.assertEqual(item["failed_predicate"], "THE_PINNED_LABS_CHECKOUT_IS_NAMED")
        os.environ[pinned_labs.ENV] = str(Path(self.tmp.name) / "absent")
        self.refusal(pinned_labs.path, "scripts/stdlib_json_schema.py")

    def test_a_missing_or_altered_file_and_an_unpinned_file_are_refused(self) -> None:
        root = Path(self.tmp.name)
        os.environ[pinned_labs.ENV] = str(root)
        self.assertEqual(self.refusal(pinned_labs.path, "scripts/stdlib_json_schema.py")["failed_predicate"],
                         "EVERY_PINNED_FILE_IS_PRESENT")
        for rel in pinned_labs.pin()["files"]:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("not the pinned bytes\n")
        self.assertEqual(self.refusal(pinned_labs.verify, root)["failed_predicate"],
                         "EVERY_PINNED_FILE_MATCHES_ITS_SHA256")
        self.assertEqual(self.refusal(pinned_labs.path, "scripts/other.py")["failed_predicate"], "THE_FILE_IS_PINNED")
        self.assertEqual(pinned_labs.main(["verify", "--root", str(root)]), 2)

    def test_the_workflows_load_the_validator_from_the_pin_and_jsonschema_only_as_the_agreement_oracle(self) -> None:
        from tests.workflow_surface import DISPATCHER, catalog_group, catalog_groups, step_bodies
        from required_verification import workflow_pr_filter
        # G17 (#238): both workflows are folded catalog groups; #222's edit is carried onto their steps
        for gid in ("task-registry-validation.validate-task-registry",
                    "reviewer-prompt-conformance.validate-reviewer-prompts"):
            text = step_bodies(catalog_group(gid))
            self.assertIn("resident-runtime/pinned_labs.py fetch", text, gid)
            self.assertIn("STEGVERSE_LABS_ROOT", text, gid)
            self.assertNotIn("-m pip install", text, gid)
        self.assertIsNone(workflow_pr_filter(DISPATCHER.read_text())[1])   # a change to the loader runs every group
        rv = "\n".join(step_bodies(g) for g in catalog_groups("required-verification.yml"))
        self.assertIn('python -m pip install "jsonschema==4.26.0"', rv)                # the agreement oracle input
        self.assertIn("STEGVERSE_LABS_ROOT", rv)
        importer = re.compile(r"(?m)^\s*(import jsonschema|from jsonschema\b)")
        uses = sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*.py")
                      if ".git" not in p.parts and importer.search(p.read_text(encoding="utf-8", errors="replace")))
        self.assertEqual(uses, ["tests/test_stdlib_json_schema_agreement.py"])   # the only jsonschema import in org
        spec = json.loads((ROOT / ".stegverse/test-set-spec.json").read_text())
        self.assertEqual([m for m, ins in spec["module_inputs"].items() if "jsonschema" in ins],
                         ["tests/test_stdlib_json_schema_agreement.py"])


if __name__ == "__main__":
    unittest.main()
