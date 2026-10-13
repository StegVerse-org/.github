"""Contract tests for source-only Ecosystem AI component reuse discovery."""
import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[1] / "orchestration" / "ecosystem_ai_reuse.py"
spec = importlib.util.spec_from_file_location("ecosystem_ai_reuse", MODULE)
reuse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reuse)


class ReuseDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.task = {"task_id": "EXISTING-REGISTRY-TASK-001"}
        self.inventory = [
            {"capability_id": "manifest.validate", "route_id": "sdk.validate", "runtime_installed": True},
            {"capability_id": "intr.dispatch", "route_id": "org.dispatch", "runtime_installed": False},
        ]

    def test_reuse_is_candidate_not_authority(self):
        result = reuse.discover_reuse(self.task, self.inventory, required_capabilities=["manifest.validate"])
        self.assertEqual(result["results"][0]["disposition"], "CANDIDATE_REUSE")
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["runtime_observed"])
        self.assertFalse(result["library_admission_granted"])
        self.assertFalse(result["results"][0]["candidates"][0]["execution_authorized"])

    def test_missing_and_offline_require_development_review(self):
        result = reuse.discover_reuse(self.task, self.inventory, required_capabilities=["intr.dispatch", "missing"])
        self.assertEqual([r["disposition"] for r in result["results"]],
                         ["CAPABILITY_DEVELOPMENT_REVIEW_REQUIRED"] * 2)

    def test_deterministic_and_no_inferred_requirements(self):
        a = reuse.discover_reuse(self.task, self.inventory, required_capabilities=["manifest.validate", "intr.dispatch"])
        b = reuse.discover_reuse(self.task, list(reversed(self.inventory)), required_capabilities=["intr.dispatch", "manifest.validate"])
        self.assertEqual(a, b)
        self.assertEqual(reuse.discover_reuse(self.task, self.inventory, required_capabilities=[])["results"], [])

    def test_invalid_task_rejected(self):
        with self.assertRaises(ValueError):
            reuse.discover_reuse({}, self.inventory, required_capabilities=[])


if __name__ == "__main__":
    unittest.main()
