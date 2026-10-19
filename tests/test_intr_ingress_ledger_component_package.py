"""The intr-ingress-ledger/v1 component: pinned bytes, a deterministic install, and its refusals.

The target is a temporary copy of tests/fixtures/intr-ingress-ledger-component/target
(byte snapshots of an organization that has not adopted the component). Receipts
the installed tests write go to temporary ledgers: NOT LEDGERED, NOT AUTHENTIC.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/intr-ingress-ledger-component"
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
       "owning_existing_goal", "next_attempt")


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


comp = load("intr_ingress_ledger_component_under_test", "resident-runtime/intr_ingress_ledger_component.py")


def sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


class Pinned(unittest.TestCase):
    def test_every_packaged_file_is_its_pinned_bytes(self):
        manifest = json.loads((comp.COMPONENT / "component.json").read_text())
        self.assertEqual(manifest["component_id"], "intr-ingress-ledger/v1")
        self.assertEqual({p["commit"][:7] for p in manifest["packages"]} >= {"cffd741", "03d8b94"}, True)
        for row in manifest["files"]:
            with self.subTest(path=row["path"]):
                self.assertEqual(sha((comp.COMPONENT / row["component_file"]).read_bytes()), row["sha256"])
                if row["kind"] == "VENDORED":
                    self.assertEqual(row["sha256"], row["source"]["sha256"])

    def test_vendored_protocol_files_are_this_repositorys(self):
        manifest = json.loads((comp.COMPONENT / "component.json").read_text())
        for row in manifest["files"]:
            if row["source"].get("repository") == "StegVerse-org/.github":
                self.assertEqual(sha((ROOT / row["path"]).read_bytes()), row["sha256"], row["path"])

    def test_the_target_fixture_is_its_pinned_bytes(self):
        manifest = json.loads((FIXTURE / "manifest.json").read_text())
        self.assertFalse(manifest["authentic_receipt"])
        for row in manifest["files"]:
            self.assertEqual(sha((FIXTURE / "target" / row["path"]).read_bytes()), row["sha256"])


class Install(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.target = Path(self.dir.name) / "org"
        shutil.copytree(FIXTURE / "target", self.target)

    def tearDown(self):
        self.dir.cleanup()

    def tree(self):
        return {str(p.relative_to(self.target)): p.read_bytes() for p in self.target.rglob("*")
                if p.is_file() and "__pycache__" not in p.parts}

    def six(self, result):
        for field in SIX:
            self.assertTrue(result.get(field), field)

    def test_install_conforms_and_the_installed_tests_pass(self):
        plan = comp.plan(self.target)
        self.assertEqual(plan["disposition"], "ALLOW", plan.get("refusals"))
        self.assertEqual(plan["context"], {"ORGANIZATION": "AaCT-E", "REPOSITORY": "AaCT-E/.github",
                                           "SLUG": "aact-e"})
        before = self.tree()
        self.assertEqual(comp.install(self.target)["disposition"], "ALLOW")
        self.assertEqual(comp.verify(self.target)["disposition"], "ALLOW")
        run = subprocess.run([sys.executable, "-B", "-m", "unittest", "tests.test_intr_ingress_ledger_component"],
                             cwd=self.target, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr[-3000:])
        installed = self.tree()
        for path in before:
            if path not in ("org-boundary/registry/services.json", "org-runtime/interlock-intr.json",
                            "org-kernel/kernel.py"):
                self.assertEqual(installed[path], before[path], path)
        again = comp.plan(self.target)
        self.assertEqual(again["disposition"], "ALLOW")
        self.assertEqual({s[0] for s in again["steps"]}, {"IDENTICAL"})
        comp.install(self.target)
        self.assertEqual(self.tree(), installed)

    def test_the_bindings_only_add(self):
        services = json.loads((self.target / "org-boundary/registry/services.json").read_text())
        interlock = json.loads((self.target / "org-runtime/interlock-intr.json").read_text())
        comp.install(self.target)
        after_s = json.loads((self.target / "org-boundary/registry/services.json").read_text())
        after_i = json.loads((self.target / "org-runtime/interlock-intr.json").read_text())
        self.assertEqual(after_s["services"][:-1], services["services"])
        self.assertEqual(after_s["services"][-1]["service_id"], "aact-e.intr-destination")
        for side in ("ingress", "egress"):
            for key, value in interlock[side].items():
                self.assertEqual(after_i[side][key], value)
        self.assertEqual({k: v for k, v in after_i.items() if k not in ("ingress", "egress")},
                         {k: v for k, v in interlock.items() if k not in ("ingress", "egress")})

    def test_a_conflicting_file_refuses_and_writes_nothing(self):
        (self.target / "resident-runtime").mkdir()
        (self.target / "resident-runtime/ledger_store.py").write_text("# another ledger store\n")
        before = self.tree()
        result = comp.install(self.target)
        self.assertEqual((result["disposition"], result["failure_code"]), ("FAIL_CLOSED", "COMPONENT_FILE_CONFLICT"))
        self.six(result)
        self.assertEqual(self.tree(), before)

    def test_a_missing_interlock_document_refuses(self):
        (self.target / "org-runtime/interlock-intr.json").unlink()
        result = comp.plan(self.target)
        self.assertEqual((result["disposition"], result["failure_code"], result["classification"]),
                         ("FAIL_CLOSED", "COMPONENT_INTERLOCK_DOCUMENT_ABSENT", "B"))
        self.six(result)

    def test_an_unknown_kernel_form_refuses(self):
        kernel = self.target / "org-kernel/kernel.py"
        kernel.write_text(kernel.read_text().replace("def hb_reference(now_ns:int|None=None)->dict[str,Any]:",
                                                     "def hb_reference(now_ns=None):"))
        result = comp.plan(self.target)
        self.assertEqual(result["failure_code"], "COMPONENT_KERNEL_HB_REFERENCE_UNSUPPORTED")
        self.six(result)

    def test_a_conflicting_binding_refuses(self):
        services = json.loads((self.target / "org-boundary/registry/services.json").read_text())
        services["services"].append({"service_id": "aact-e.intr-destination", "repository": "AaCT-E/other"})
        (self.target / "org-boundary/registry/services.json").write_text(json.dumps(services))
        result = comp.plan(self.target)
        self.assertEqual(result["failure_code"], "COMPONENT_BINDING_CONFLICT")
        self.six(result)


if __name__ == "__main__":
    unittest.main()
