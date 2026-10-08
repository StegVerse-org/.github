"""Federation uses the declared carrier only; the host environment cannot select a gateway.

federation_cycle, ecosystem_control and sdk_self_characterization_egress used
to switch to a hosted HTTPS gateway whenever STEGVERSE_ORG_FEDERATION_GATEWAY_URL
was set. The manifest determines the destination and the carrier is
org-kernel publish_packet over the mesh the node was materialized with, so each
now uses that carrier whatever the environment says, and refuses when no mesh
is supplied.

Source validation only. No authority effect is claimed.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CALLERS = ("resident-runtime/federation_cycle.py", "resident-runtime/ecosystem_control.py",
           "resident-runtime/sdk_self_characterization_egress.py")
GATEWAY_ENV = "STEGVERSE_ORG_FEDERATION_GATEWAY_URL"


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(script, *args, env_extra=None, home):
    env = {k: v for k, v in os.environ.items() if k != GATEWAY_ENV}
    env.update({"HOME": home, GATEWAY_ENV: "https://gateway.invalid"}, **(env_extra or {}))
    return subprocess.run([sys.executable, "-B", str(ROOT / script), *args],
                          capture_output=True, text=True, env=env, cwd=home, timeout=120)


class NoHostedGatewayRouteTests(unittest.TestCase):
    def test_no_normative_caller_loads_the_gateway_or_reads_its_variable(self):
        for relative in CALLERS:
            source = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(caller=relative):
                self.assertNotIn("federation_gateway_transport", source)
                self.assertNotIn(GATEWAY_ENV, source)

    def test_the_activation_manifest_declares_the_kernel_carrier_and_no_gateway(self):
        manifest = json.loads((ROOT / "resident-runtime/activation-manifest.json").read_text())
        self.assertEqual(manifest["federation_carrier"], "org-kernel/kernel.py::publish_packet")
        self.assertEqual(manifest["federation_mesh_location"], "SUPPLIED_BY_MATERIALIZER")
        self.assertEqual(manifest["hosted_gateway_route"], "NONE")
        for retired in ("federation_gateway_transport", "federation_gateway_url_env",
                        "federation_gateway_required_for_cross_host", "federation_network_route"):
            self.assertNotIn(retired, manifest)

    def test_a_federation_cycle_with_the_gateway_variable_set_still_uses_the_supplied_mesh(self):
        with tempfile.TemporaryDirectory() as work:
            mesh, state = Path(work) / "mesh", Path(work) / "state"
            mesh.mkdir()
            env = {"STEGVERSE_ORG_LEDGER_ROOT": str(Path(work) / "org-ledger"),
                   "STEGVERSE_REPO_LEDGER_ROOT": str(Path(work) / "repo-ledger")}
            completed = _run("resident-runtime/federation_cycle.py", "--mesh-root", str(mesh),
                             "--node-state-root", str(state), env_extra=env, home=work)
            self.assertEqual(completed.returncode, 0, completed.stderr[-800:])
            receipt = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(receipt["transport"], "INTERLOCK_INTR_SUPPLIED_MESH")

    def test_a_federation_cycle_without_a_mesh_refuses_rather_than_using_a_gateway(self):
        with tempfile.TemporaryDirectory() as work:
            completed = _run("resident-runtime/federation_cycle.py", "--node-state-root",
                             str(Path(work) / "state"), home=work)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("MESH_LOCATION_REQUIRED_FROM_MATERIALIZER", completed.stderr)

    def test_ecosystem_control_sends_over_the_supplied_mesh_and_refuses_without_one(self):
        with tempfile.TemporaryDirectory() as work:
            mesh = Path(work) / "mesh"
            mesh.mkdir()
            standing = str(ROOT / "tests/fixtures/crossing-standing-genesis.json")
            sent = _run("resident-runtime/ecosystem_control.py", "--mesh-root", str(mesh), "send-message",
                        "--subject", "carrier", "--body-json", "{}", "--communication-id", "carrier-test",
                        "--standing", standing, home=work)
            self.assertEqual(sent.returncode, 0, sent.stderr[-800:])
            self.assertGreater(json.loads(sent.stdout)["published_count"], 0)
            self.assertTrue(list((mesh / "frames.d").glob("*.json")))
            refused = _run("resident-runtime/ecosystem_control.py", "send-message", "--subject", "carrier",
                           "--body-json", "{}", "--standing", standing, home=work)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("mesh_location_required_from_materializer", refused.stderr)


if __name__ == "__main__":
    unittest.main()
