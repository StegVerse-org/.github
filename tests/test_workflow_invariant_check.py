"""WORKFLOW_INVARIANTS_HOLD (#160 issuecomment-6353130407 rank 6): every rule refuses with six fields, a clean
change is ALLOW, words inside strings or comments never trip it, and this repository's own changes pass."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("workflow_invariant_check", ROOT / "resident-runtime/workflow_invariant_check.py")
wic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wic)

CLEAN = """name: clean
on:
  pull_request:
    paths: ["x/**"]
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  t:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
      - name: run
        run: |
          # a comment naming workflow_dispatch and schedule is not a trigger
          echo "workflow_dispatch: is only text here"
          python3 -m unittest
"""


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


class Repo:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "t@example.invalid")
        git(self.root, "config", "user.name", "t")
        self.write({".github/workflows/clean.yml": CLEAN, "resident-runtime/mod.py": "import json\n"})
        self.base = self.commit()

    def write(self, files: dict[str, str]) -> None:
        for path, text in files.items():
            p = self.root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)

    def commit(self) -> str:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "--allow-empty", "-m", "c")
        return git(self.root, "rev-parse", "HEAD")

    def evaluate(self, files: dict[str, str]) -> dict:
        self.write(files)
        head = self.commit()
        return wic.evaluate(self.root, self.base, head)


def codes(result: dict) -> list[str]:
    return [f["failure_code"] for f in result["findings"]]


class Rules(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Repo()
        self.addCleanup(self.repo.tmp.cleanup)

    def assertRefuses(self, files: dict[str, str], code: str) -> dict:
        result = self.repo.evaluate(files)
        self.assertEqual(result["disposition"], "FAIL_CLOSED")
        self.assertIn(code, codes(result))
        for f in result["findings"]:
            for field in wic.SIX_FIELDS:
                self.assertTrue(f[field], field)
        self.assertEqual(set(result["first_refusal"]), set(wic.SIX_FIELDS))
        return result

    def test_clean_change_is_allow_and_e0(self):
        result = self.repo.evaluate({".github/workflows/other.yml": CLEAN.replace("clean", "other")})
        self.assertEqual(result["disposition"], "ALLOW", result["findings"])
        self.assertEqual(result["lowest_supported_mode"], "E0")
        self.assertTrue(result["result_sha256"].startswith("sha256:"))

    def test_workflow_dispatch_in_block_form(self):
        r = self.assertRefuses({".github/workflows/d.yml": CLEAN.replace("on:\n", "on:\n  workflow_dispatch:\n")},
                               "WORKFLOW_DISPATCH_TRIGGER_PRESENT")
        self.assertEqual(r["findings"][0]["line"], 3)
        self.assertEqual(r["first_refusal"]["failed_predicate"], "ACTIONS_BY_MANIFEST_STATE_TRANSITION_TRIGGER_ONLY")

    def test_dispatch_in_flow_and_list_forms_and_repository_dispatch(self):
        self.assertRefuses({".github/workflows/f.yml": "on: [push, workflow_dispatch]\njobs: {}\n"}, "WORKFLOW_DISPATCH_TRIGGER_PRESENT")
        self.assertRefuses({".github/workflows/l.yml": "on:\n  - push\n  - repository_dispatch\njobs: {}\n"},
                           "WORKFLOW_DISPATCH_TRIGGER_PRESENT")
        self.assertRefuses({".github/workflows/s.yml": "on: workflow_dispatch\njobs: {}\n"}, "WORKFLOW_DISPATCH_TRIGGER_PRESENT")

    def test_schedule(self):
        self.assertRefuses({".github/workflows/c.yml": CLEAN.replace("on:\n", "on:\n  schedule:\n    - cron: '0 * * * *'\n")},
                           "SCHEDULE_TRIGGER_PRESENT")

    def test_polling_loop(self):
        self.assertRefuses({".github/workflows/p.yml": CLEAN.replace("python3 -m unittest",
                            "until curl -sf https://example.invalid; do\n            sleep 30\n          done")},
                           "EXTERNAL_POLLING_PRESENT")

    def test_external_machine(self):
        self.assertRefuses({".github/workflows/h.yml": CLEAN.replace("ubuntu-latest", "[self-hosted, linux]")},
                           "EXTERNAL_MACHINE_PREREQUISITE")
        self.assertRefuses({"deploy/receiver.service": "[Unit]\nDescription=x\n[Service]\nExecStart=/bin/true\n"},
                           "EXTERNAL_MACHINE_PREREQUISITE")
        self.assertRefuses({".github/workflows/e.yml": CLEAN.replace("python3 -m unittest", "sudo systemctl enable receiver")},
                           "EXTERNAL_MACHINE_PREREQUISITE")

    def test_new_actions(self):
        self.assertRefuses({".github/workflows/a.yml": CLEAN.replace("actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
                                                                     "someone/action@v1")}, "NEW_THIRD_PARTY_ACTION")
        self.assertRefuses({".github/workflows/b.yml": CLEAN.replace("@11d5960a326750d5838078e36cf38b85af677262", "@v4")},
                           "NEW_THIRD_PARTY_ACTION")

    def test_pinned_reusable_workflow_of_this_repository_is_allowed(self):
        text = ("on: pull_request\njobs:\n  i:\n    uses: StegVerse-org/.github/.github/workflows/workflow-invariant-check.yml@"
                + "a" * 40 + "\n")
        self.assertEqual(self.repo.evaluate({".github/workflows/r.yml": text})["disposition"], "ALLOW")

    def test_new_imports_installs_and_manifests(self):
        self.assertRefuses({"resident-runtime/mod.py": "import json\nimport requests\n"}, "NEW_THIRD_PARTY_IMPORT")
        self.assertRefuses({"requirements.txt": "requests\n"}, "NEW_THIRD_PARTY_IMPORT")
        self.assertRefuses({".github/workflows/i.yml": CLEAN.replace("python3 -m unittest", "pip install requests")},
                           "NEW_THIRD_PARTY_IMPORT")

    def test_existing_and_local_imports_are_not_new(self):
        self.repo.write({"resident-runtime/legacy.py": "import yaml\n"})
        self.repo.base = self.repo.commit()
        result = self.repo.evaluate({"resident-runtime/legacy.py": "import yaml\nimport mod\nimport stegverse\n"})
        self.assertEqual(result["disposition"], "ALLOW", result["findings"])

    def test_clock_read_in_receipt_path(self):
        self.assertRefuses({"resident-runtime/mod.py": "import time\nEPOCH = time.time()\n"}, "CLOCK_READ_IN_RECEIPT")
        self.assertRefuses({"resident-runtime/mod.py": "from datetime import datetime\nx = datetime.now()\n"}, "CLOCK_READ_IN_RECEIPT")
        self.assertRefuses({".github/workflows/t.yml": CLEAN.replace("python3 -m unittest", "epoch=$(date -u +%s)")},
                           "CLOCK_READ_IN_RECEIPT")

    def test_clock_words_in_strings_and_tests_are_not_reads(self):
        result = self.repo.evaluate({"resident-runtime/mod.py": "FORBIDDEN = ('time.time(', 'AI_SESSION_GATE')\n",
                                     "tests/test_mod.py": "import time\nt = time.time()\n"})
        self.assertEqual(result["disposition"], "ALLOW", result["findings"])

    def test_ai_session_gate(self):
        self.assertRefuses({".github/workflows/g.yml": CLEAN.replace("python3 -m unittest", "AI_SESSION_GATE=1 python3 x.py")},
                           "AI_SESSION_GATE_PRESENT")
        self.assertRefuses({"resident-runtime/mod.py": "AI_SESSION_GATE = True\n"}, "AI_SESSION_GATE_PRESENT")

    def test_findings_are_ordered_and_first_refusal_is_the_first(self):
        result = self.repo.evaluate({".github/workflows/z.yml": "on: workflow_dispatch\njobs: {}\n",
                                     ".github/workflows/a.yml": "on: schedule\njobs: {}\n"})
        self.assertEqual(result["findings"][0]["path"], ".github/workflows/a.yml")
        self.assertEqual(result["first_refusal"]["failure_code"], "SCHEDULE_TRIGGER_PRESENT")

    def test_census_mode_reports_and_exits_zero(self):
        self.repo.write({".github/workflows/z.yml": "on: workflow_dispatch\njobs: {}\n"})
        self.repo.commit()
        self.assertEqual(wic.main(["--root", str(self.repo.root), "--all"]), 0)
        self.assertEqual(wic.main(["--root", str(self.repo.root), "--base", self.repo.base]), 1)


class ThisRepository(unittest.TestCase):
    def test_convergence_workflow_has_no_request_trigger(self):
        text = (ROOT / ".github/workflows/resident-runtime-convergence-validation.yml").read_text()
        names = [n for _, n in wic.trigger_lines(text)]
        self.assertEqual(names, ["pull_request"])

    def test_the_check_workflow_obeys_its_own_rules(self):
        path = ".github/workflows/workflow-invariant-check.yml"
        findings = wic.check_workflow(path, (ROOT / path).read_text(), None)
        self.assertEqual(findings, [])
        self.assertEqual([n for _, n in wic.trigger_lines((ROOT / path).read_text())], ["pull_request", "workflow_call"])

    def test_the_checker_reads_no_clock_network_or_package(self):
        path = "resident-runtime/workflow_invariant_check.py"
        self.assertEqual(wic.check_python(path, (ROOT / path).read_text(), None, set()), [])
        import ast
        imported = {m for _, m in wic._imports(ast.parse((ROOT / path).read_text()))}
        self.assertEqual(imported, {"__future__", "argparse", "ast", "hashlib", "json", "re", "subprocess", "sys",
                                    "pathlib", "typing"})


if __name__ == "__main__":
    unittest.main()
