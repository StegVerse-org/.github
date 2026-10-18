"""RESIDENT_RUNTIME_CONVERGENCE: one manifest-driven transition, every non-ALLOW with six fields.

Fixtures are synthetic trees in a temporary directory. Nothing here reads the
network or writes a durable ledger: the one append test points the repository
ledger at a temporary root.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "resident_runtime_convergence", ROOT / "resident-runtime/resident_runtime_convergence.py")
conv = importlib.util.module_from_spec(_spec)
sys.modules["resident_runtime_convergence"] = conv
_spec.loader.exec_module(conv)

SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair",
       "retry_entrypoint", "owning_existing_goal", "next_attempt")

MODULE = '''"""Fixture egress module."""
import importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
OWNER_REPOSITORY = "StegVerse-org/.github"
_spec = importlib.util.spec_from_file_location("dep", ROOT / "lib/dep.py")
dep = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(dep)


def close():
    # A missing response is a six-field refusal, never PENDING.
    return {"disposition": "FAIL_CLOSED", "value": dep.VALUE}
'''
DEP = "VALUE = 7\n"
TEST = '''import importlib.util, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("m", ROOT / "resident-runtime/egress.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class T(unittest.TestCase):
    def test_close(self):
        self.assertEqual(m.close()["disposition"], "FAIL_CLOSED")
'''
WORKFLOW = "name: fixture\non:\n  workflow_dispatch:\njobs: {}\n"
FILES = {"module": "resident-runtime/egress.py", "tests": "tests/test_fx.py",
         "workflow": ".github/workflows/fx.yml"}


def write(root: Path, files: dict[str, str]) -> None:
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="convergence-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = self.tmp / "baseline"
        write(self.base, {FILES["module"]: MODULE, FILES["tests"]: TEST,
                          FILES["workflow"]: WORKFLOW, "lib/dep.py": DEP, "tests/__init__.py": ""})
        self.target = self.tmp / "target"
        self.out = self.tmp / "out"

    def manifest(self, before: dict[str, str] | None = None, reconciled=()) -> Path:
        files = {}
        for role, path in FILES.items():
            data = (self.base / path).read_bytes()
            files[role] = {"path": path, "sha256": hashlib.sha256(data).hexdigest(),
                           "git_blob_sha": conv.git_blob_sha(data)}
        if before is None:
            before = {p: (hashlib.sha256((self.target / p).read_bytes()).hexdigest()
                          if (self.target / p).is_file() else "ABSENT") for p in FILES.values()}
        manifest = {
            "schema": conv.MANIFEST_SCHEMA, "owning_existing_goal": "StegVerse-org/.github#166",
            "baseline": {"repository": "StegVerse-org/.github", "commit": "0" * 40, "files": files},
            "parameters": [{"path": FILES["module"],
                            "baseline_line": 'OWNER_REPOSITORY = "StegVerse-org/.github"',
                            "template": 'OWNER_REPOSITORY = "{repository}"'}],
            "org_owned_closure_patterns": [r"org-runtime/.*\.json"],
            "test_modules": ["tests.test_fx"],
            "targets": {"Fixture-Org": {"repository": "Fixture-Org/.github", "commit": "1" * 40,
                                        "before_sha256": before,
                                        "reconciled_hunk_sha256": list(reconciled)}},
        }
        path = self.tmp / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def run_converge(self, manifest: Path, **kw):
        return conv.converge(manifest, "Fixture-Org", self.target, self.base, self.out, **kw)

    def codes(self, result):
        return [r["failure_code"] for r in result["refusals"]]

    def assertSixFields(self, result):
        for refusal in result["refusals"]:
            self.assertEqual(refusal["disposition"], conv.FAIL_CLOSED)
            for field in SIX:
                self.assertTrue(refusal.get(field), (field, refusal))


class ConvergenceTransition(Fixture):
    def target_like_baseline(self, module=MODULE):
        write(self.target, {FILES["module"]: module.replace("StegVerse-org/.github", "Fixture-Org/.github"),
                            "lib/dep.py": DEP, "tests/__init__.py": ""})

    def test_parameter_only_drift_converges_and_the_tests_pass(self):
        self.target_like_baseline()
        result = self.run_converge(self.manifest())
        self.assertEqual(result["disposition"], conv.ALLOW, result["refusals"])
        self.assertTrue(result["tests"]["passed"])
        module = next(f for f in result["files"] if f["role"] == "module")
        self.assertTrue(module["already_converged"])
        # The declared parameter is the only difference from the baseline bytes.
        self.assertEqual(module["after_normalized_sha256"], module["baseline_sha256"])
        converged = (self.out / "Fixture-Org/converged" / FILES["module"]).read_text()
        self.assertIn('OWNER_REPOSITORY = "Fixture-Org/.github"', converged)
        # A dry run never touches the target checkout.
        self.assertFalse((self.target / FILES["tests"]).exists())

    def test_org_specific_behaviour_is_fail_closed_not_deleted(self):
        extra = MODULE + '\n\ndef fixture_org_bilateral_match():\n    return "Fixture-Org"\n'
        self.target_like_baseline(extra)
        result = self.run_converge(self.manifest())
        self.assertEqual(result["disposition"], conv.FAIL_CLOSED)
        self.assertIn(conv.ORG_SPECIFIC, self.codes(result))
        self.assertSixFields(result)
        refusal = next(r for r in result["refusals"] if r["failure_code"] == conv.ORG_SPECIFIC)
        self.assertIn("fixture_org_bilateral_match", refusal["detail"]["new_top_level_definitions"])
        hunk = next(h for h in result["hunks"] if h["class"] == conv.ORG_SPECIFIC_HUNK)
        # Reconciling that exact hunk, by its digest, is what lets convergence proceed.
        result = self.run_converge(self.manifest(reconciled=[hunk["hunk_sha256"]]))
        self.assertEqual(result["disposition"], conv.ALLOW, result["refusals"])

    def test_apply_never_writes_across_an_unreconciled_refusal(self):
        extra = MODULE + '\n\ndef fixture_org_only():\n    return 1\n'
        self.target_like_baseline(extra)
        result = self.run_converge(self.manifest(), apply=True)
        self.assertFalse(result["applied"])
        self.assertIn("fixture_org_only", (self.target / FILES["module"]).read_text())

    def test_apply_writes_the_rendered_bytes_on_allow(self):
        self.target_like_baseline()
        result = self.run_converge(self.manifest(), apply=True)
        self.assertEqual(result["disposition"], conv.ALLOW, result["refusals"])
        self.assertTrue(result["applied"])
        self.assertEqual((self.target / FILES["tests"]).read_text(), TEST)

    def test_comment_only_drift_does_not_need_reconciling(self):
        self.target_like_baseline(MODULE.replace("# A missing response", "# Organization note.\n    # A missing response"))
        result = self.run_converge(self.manifest())
        self.assertNotIn(conv.ORG_SPECIFIC, self.codes(result))
        self.assertTrue(any(h["class"] == conv.COSMETIC for h in result["hunks"]))

    def test_a_target_that_moved_since_the_manifest_is_fail_closed(self):
        self.target_like_baseline()
        result = self.run_converge(self.manifest(before={p: "0" * 64 for p in FILES.values()}))
        self.assertIn(conv.TARGET_DRIFTED, self.codes(result))
        self.assertSixFields(result)

    def test_a_baseline_not_at_its_pin_is_fail_closed(self):
        self.target_like_baseline()
        manifest = self.manifest()
        (self.base / FILES["module"]).write_text(MODULE + "# moved\n")
        result = self.run_converge(manifest)
        self.assertIn(conv.BASELINE_MISMATCH, self.codes(result))

    def test_an_absent_closure_file_is_fail_closed_and_the_tests_say_why(self):
        self.target_like_baseline()
        (self.target / "lib/dep.py").unlink()
        result = self.run_converge(self.manifest())
        self.assertIn(conv.CLOSURE_ABSENT, self.codes(result))
        self.assertIn(conv.TESTS_FAILED, self.codes(result))
        refusal = next(r for r in result["refusals"] if r["failure_code"] == conv.CLOSURE_ABSENT)
        self.assertEqual(refusal["detail"]["absent"], ["lib/dep.py"])
        self.assertSixFields(result)

    def test_evidence_is_bytes_with_digests(self):
        self.target_like_baseline()
        result = self.run_converge(self.manifest())
        evidence = self.out / "Fixture-Org/evidence"
        for name, value in result["evidence_manifest"].items():
            self.assertEqual(hashlib.sha256((evidence / name).read_bytes()).hexdigest(), value)
        self.assertEqual(result["evidence_manifest_sha256"], conv.sha(result["evidence_manifest"]))

    def test_an_undeclared_organization_is_fail_closed(self):
        self.target_like_baseline()
        result = conv.converge(self.manifest(), "Nobody", self.target, self.base, self.out)
        self.assertEqual(self.codes(result), [conv.ORG_NOT_DECLARED])
        self.assertSixFields(result)


class Receipt(Fixture):
    def test_the_receipt_body_has_the_repository_ledger_shape(self):
        write(self.target, {FILES["module"]: MODULE.replace("StegVerse-org", "Fixture-Org"),
                            "lib/dep.py": DEP, "tests/__init__.py": ""})
        manifest = self.manifest()
        result = self.run_converge(manifest)
        body = conv.receipt_body(json.loads(manifest.read_text()), "Fixture-Org", result, 40)
        contract = ROOT / ".stegverse/transition-ledger/contract.json"
        required = (json.loads(contract.read_text())["required_fields"] if contract.is_file() else
                    ["repository", "transition_id", "transition_class", "predecessor_state_sha256",
                     "successor_state_sha256", "evidence", "authority_effect"])
        for field in required:
            if field in ("hb_reference", "previous_receipt_sha256"):
                continue  # minted by the emitter at append time
            self.assertIn(field, body)
        self.assertEqual(body["schema"], conv.RECEIPT_SCHEMA)
        self.assertEqual(body["transition_class"], conv.CONVERGED_CLASS)
        self.assertEqual(body["authority_effect"], "NONE")

    def test_a_refusal_is_recorded_too_and_its_successor_is_its_predecessor(self):
        write(self.target, {FILES["module"]: MODULE, "tests/__init__.py": ""})
        manifest = self.manifest()
        result = self.run_converge(manifest)
        body = conv.receipt_body(json.loads(manifest.read_text()), "Fixture-Org", result, 40)
        self.assertEqual(body["transition_class"], conv.REFUSED_CLASS)
        self.assertEqual(body["predecessor_state_sha256"], body["successor_state_sha256"])

    def test_no_epoch_no_append(self):
        self.assertEqual(conv.epoch_refusal(None, "g")["failure_code"], conv.HB_EPOCH_NOT_SUPPLIED)
        self.assertEqual(conv.epoch_refusal(3, "g")["failure_code"], conv.HB_EPOCH_INVALID)
        self.assertEqual(conv.epoch_refusal(True, "g")["failure_code"], conv.HB_EPOCH_INVALID)
        self.assertIsNone(conv.epoch_refusal(40, "g"))

    @unittest.skipUnless((ROOT / ".stegverse/transition-ledger/emit.py").is_file(), "no repository emitter")
    def test_append_goes_through_the_repository_emitter_to_a_supplied_root(self):
        write(self.target, {FILES["module"]: MODULE.replace("StegVerse-org", "Fixture-Org"),
                            "lib/dep.py": DEP, "tests/__init__.py": ""})
        manifest = self.manifest()
        result = self.run_converge(manifest)
        body = conv.receipt_body(json.loads(manifest.read_text()), "Fixture-Org", result, 40)
        previous = os.environ.get("STEGVERSE_REPO_LEDGER_ROOT")
        os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = str(self.tmp / "repo-ledger")
        try:
            receipt = conv.append_receipt(body, ROOT)
            again = conv.append_receipt(body, ROOT)
        finally:
            if previous is None:
                os.environ.pop("STEGVERSE_REPO_LEDGER_ROOT")
            else:
                os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = previous
        self.assertEqual(receipt["transition_class"], conv.CONVERGED_CLASS)
        self.assertTrue(receipt["receipt_sha256"].startswith("sha256:"))
        self.assertEqual(again["receipt_sha256"], receipt["receipt_sha256"])  # idempotent on retry


class Standard(unittest.TestCase):
    def test_the_component_reaches_no_network_and_no_session_gate(self):
        source = (ROOT / "resident-runtime/resident_runtime_convergence.py").read_text()
        for forbidden in ("urllib", "socket", "http.client", "requests", "AI_SESSION_GATE", "time.time("):
            self.assertNotIn(forbidden, source)

    def test_the_workflow_is_dispatch_only(self):
        workflow = (ROOT / ".github/workflows/resident-runtime-convergence-validation.yml").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        for trigger in ("schedule:", "cron", "push:", "pull_request:"):
            self.assertNotIn(trigger, workflow)

    def test_the_repository_manifest_validates(self):
        manifest = conv.load_manifest(ROOT / conv.DEFAULT_MANIFEST)
        self.assertEqual(manifest["baseline"]["repository"], "StegVerse-org/.github")
        self.assertEqual(len(manifest["targets"]), 6)
        for target in manifest["targets"].values():
            self.assertEqual(len(target["commit"]), 40)
        for parameter in manifest["parameters"]:
            self.assertIn("{repository}", parameter["template"])
