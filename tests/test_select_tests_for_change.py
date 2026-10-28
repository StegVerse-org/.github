"""select_tests_for_change.py: the tests a change needs, from the declared map.

Temporary trees only. Nothing here is skipped.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "select_tests_for_change", ROOT / "scripts" / "select_tests_for_change.py")
sel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sel)

MAP = {"schema": sel.SCHEMA, "unmapped_path_policy": "SELECT_FULL_SUITE",
       "rules": [{"id": "r", "paths": ["tools/*.sh"], "tests": ["tests/test_tool*.py"]},
                 {"id": "none", "paths": ["self/run.py"], "tests": []}],
       "no_test_paths": ["*.md"]}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        files = {
            "lib/core.py": "import helper\n",
            "lib/helper.py": "DATA = 'data/table.json'\n",
            "data/table.json": "{}",
            "data/other.json": "{}",
            "README.md": "x",
            "docs/read.md": "x",
            "tools/a.sh": "",
            "self/run.py": "",
            "tests/test_core.py": "import core\n",
            "tests/test_reads_doc.py": "p = ROOT / 'docs' / 'read.md'\n",
            "tests/test_tool.py": "",
            "tests/test_other.py": "x = 'data/other.json'\n",
        }
        for rel, text in files.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text, encoding="utf-8")
        self.tests = sel.test_files(sel.repo_files(self.root))
        self.refs = sel.generate(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def pick(self, *changed):
        return sel.select(MAP | {"references": self.refs}, list(changed), self.tests)

    def test_a_changed_test_selects_itself_only(self):
        r = self.pick("tests/test_tool.py")
        self.assertEqual(r["selected_tests"], ["tests/test_tool.py"])
        self.assertEqual(len(r["not_selected_for_this_change"]), 3)

    def test_a_path_a_test_reaches_through_its_imports_selects_it(self):
        self.assertEqual(self.pick("data/table.json")["selected_tests"], ["tests/test_core.py"])
        self.assertEqual(self.pick("lib/helper.py")["selected_tests"], ["tests/test_core.py"])

    def test_a_joined_path_reference_selects_the_test_even_under_no_test_paths(self):
        self.assertEqual(self.pick("docs/read.md")["selected_tests"], ["tests/test_reads_doc.py"])

    def test_a_declared_rule_selects_its_tests(self):
        self.assertEqual(self.pick("tools/a.sh")["selected_tests"], ["tests/test_tool.py"])

    def test_a_rule_with_no_tests_and_a_no_test_path_select_nothing(self):
        r = self.pick("self/run.py", "README.md")
        self.assertEqual(r["selected_tests"], [])
        self.assertEqual(r["unmapped_changed_paths"], [])
        self.assertEqual(r["changed_paths_no_test_reads"], ["README.md"])

    def test_an_unmapped_path_over_selects_the_whole_suite(self):
        r = self.pick("brand/new.cfg")
        self.assertEqual(r["unmapped_changed_paths"], ["brand/new.cfg"])
        self.assertEqual(r["selected_tests"], self.tests)
        self.assertEqual(r["not_selected_for_this_change"], [])

    def test_unselected_tests_are_never_reported_as_passing(self):
        r = self.pick("tests/test_tool.py")
        self.assertTrue(r["not_selected_are_not_run_for_this_verdict_and_not_reported_as_passing"])
        self.assertNotIn("passed", json.dumps(r).replace("not_reported_as_passing", ""))

    def test_selection_is_deterministic(self):
        self.assertEqual(self.pick("lib/core.py", "tools/a.sh"), self.pick("tools/a.sh", "lib/core.py"))

    def test_main_writes_the_selection_and_an_unreadable_map_selects_everything(self):
        changed = self.root / "changed.txt"
        changed.write_text("tests/test_tool.py\n", encoding="utf-8")
        out = self.root / "sel.json"
        (self.root / "map.json").write_text(json.dumps(MAP), encoding="utf-8")
        self.assertEqual(sel.main(["--root", str(self.root), "--map", str(self.root / "map.json"),
                                   "--changed", str(changed), "--out", str(out)]), 0)
        self.assertEqual(json.loads(out.read_text())["selected_tests"], ["tests/test_tool.py"])
        sel.main(["--root", str(self.root), "--map", str(self.root / "absent.json"),
                  "--changed", str(changed), "--out", str(out)])
        self.assertEqual(json.loads(out.read_text())["selected_tests"], self.tests)

    def test_this_repositorys_map_is_readable_and_declares_the_full_suite_fallback(self):
        doc = json.loads((ROOT / "data" / "test-selection-map.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["schema"], sel.SCHEMA)
        self.assertEqual(doc["unmapped_path_policy"], "SELECT_FULL_SUITE")


class PayloadCopyTests(unittest.TestCase):
    """An import resolves to the live module, not to a component's packaged copy of it."""

    def test_a_vendored_payload_copy_does_not_select_the_live_modules_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                "resident-runtime/store.py": "",
                "components/pkg/v1/files/resident-runtime/store.py": "",
                "components/pkg/v1/templates/resident-runtime/store.py": "",
                "tests/test_store.py": "import store\n",
                "tests/test_pkg.py": "p = 'components/pkg/v1/files/resident-runtime/store.py'\n",
            }
            for rel, text in files.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(text, encoding="utf-8")
            refs = sel.generate(root)
            tests = sel.test_files(sel.repo_files(root))
            pick = lambda *c: sel.select(MAP | {"references": refs}, list(c), tests)["selected_tests"]
            self.assertEqual(pick("resident-runtime/store.py"), ["tests/test_store.py"])
            self.assertEqual(pick("components/pkg/v1/files/resident-runtime/store.py"), ["tests/test_pkg.py"])


if __name__ == "__main__":
    unittest.main()
