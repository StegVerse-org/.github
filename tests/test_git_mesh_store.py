"""Regression tests for the materializer-supplied durable Git-ref mesh."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

store_module = load("mesh_store_test", "org-kernel/node_store.py")
kernel = load("mesh_kernel_test", "org-kernel/kernel.py")

class GitMeshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "mesh.git"
        subprocess.run(["git", "init", "--bare", "-q", str(self.repo)], check=True)
        self.locator = "git+" + str(self.repo) + "#refs/test/mesh"

    def test_write_once_and_readback_from_independent_materialization(self):
        first = kernel.mesh_store(self.locator)
        frame = {"packet_id": "p", "frame_sha256": "sha256:" + "a" * 64}
        key = store_module.frame_key(frame)
        self.assertEqual(first.put_once(key, frame), key)
        self.assertEqual(first.put_once(key, frame), key)
        second = kernel.mesh_store(self.locator)
        self.assertEqual(second.get(key), frame)
        self.assertIn(key, second.list_prefix(store_module.MESH_FRAME_PREFIX))
        with self.assertRaises(store_module.WriteOnceCollision):
            second.put_once(key, {"different": True})
        self.assertEqual(first.get(key), frame)

    def test_explicit_location_only(self):
        with self.assertRaisesRegex(ValueError, "mesh_location_required"):
            kernel.mesh_store()
        with self.assertRaisesRegex(ValueError, "mesh_git_locator_invalid"):
            kernel.mesh_store("git+missing-ref")
        with self.assertRaisesRegex(ValueError, "host_environment_mesh_binding_forbidden"):
            kernel.mesh_store(self.locator, env={})
        provenance = kernel.node_state_provenance(self.locator)
        self.assertEqual(provenance["mesh_provenance"], "SUPPLIED")
        self.assertEqual(provenance["store_kind"], "GIT_REF")
        self.assertTrue(provenance["mesh_portable"])

if __name__ == "__main__":
    unittest.main()
