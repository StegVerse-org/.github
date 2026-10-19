"""The resident executor is one cycle per materialization; SV002 is a manifest-bound submission.

The executor used to loop forever, polling every second under a systemd unit
with Restart=always, and to run the SV002 roundtrip, which searched the host
for checkouts, drove StegVerse-002's federation cycle from here and could
switch to a hosted gateway. Now one invocation runs one federation cycle over
the mesh and node state it was given and exits; the SV002 query is published
on the supplied mesh as an InTr packet and the receiver consumes it on its own
materialization. Nothing waits, polls or is always on.

Source validation only. No authority effect is claimed.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXECUTOR = ROOT / "resident-runtime/resident_executor.py"
SUBMISSION = ROOT / "resident-runtime/run_sv002_self_characterization_roundtrip.py"
HOSTED = ("GITHUB_ACTIONS", "CI", "RENDER", "VERCEL", "CF_PAGES", "CLOUDFLARE_WORKERS")
CREDENTIALS = ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT", "GITHUB_PERSONAL_ACCESS_TOKEN",
               "ACTIONS_RUNTIME_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN")


def node_env(work, **extra):
    """An environment for a node materialization: no hosted markers, nothing from the host home."""
    env = {k: v for k, v in os.environ.items()
           if k not in HOSTED + CREDENTIALS and not k.startswith("STEGVERSE_") and k != "XDG_STATE_HOME"}
    env.update({"HOME": work, "PYTHONDONTWRITEBYTECODE": "1",
                "STEGVERSE_ORG_LEDGER_ROOT": str(Path(work) / "org-ledger"),
                "STEGVERSE_REPO_LEDGER_ROOT": str(Path(work) / "repo-ledger")}, **extra)
    return env


def fake_sdk(root):
    """An SDK bootstrap that returns a valid frozen request built from this repository's fixtures."""
    path = Path(root) / "stegverse/external_interlock_bootstrap.py"
    path.parent.mkdir(parents=True)
    path.write_text(textwrap.dedent(f"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("egress_fixtures", {str(ROOT / "tests/test_sdk_self_characterization_egress.py")!r})
        fixtures = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixtures)
        def build_sv002_first_interlock_request(authority_ref):
            return fixtures.request(fixtures.generic_manifest())
    """))


class ResidentMaterializationTests(unittest.TestCase):
    def test_the_executor_neither_loops_nor_runs_the_sv002_roundtrip(self):
        source = EXECUTOR.read_text(encoding="utf-8")
        for absent in ("while True", "time.sleep", "--poll-seconds", "consume_sv002_once",
                       "run_sv002_self_characterization_roundtrip.py\"", "--once"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, source)

    def test_no_always_on_unit_or_hosted_gateway_remains(self):
        for retired in ("resident-runtime/systemd/stegverse-org-resident.service",
                        "resident-runtime/federation_gateway_transport.py",
                        "resident-runtime/activate_org_federation_gateway.py",
                        "resident-runtime/activation-requests/org-federation-gateway.json"):
            with self.subTest(retired=retired):
                self.assertFalse((ROOT / retired).exists())
        manifest = json.loads((ROOT / "resident-runtime/activation-manifest.json").read_text())
        self.assertNotIn("persistent_executor", manifest)
        self.assertEqual(manifest["ephemeral_materialization"]["mode"], "ONE_CYCLE_PER_INVOCATION")
        self.assertIs(manifest["ephemeral_materialization"]["loop_or_poll"], False)
        self.assertIs(manifest["startup_one_shot"]["run_by_resident_executor"], False)

    def test_one_invocation_runs_one_cycle_and_records_in_supplied_node_state(self):
        with tempfile.TemporaryDirectory() as work:
            mesh, state = Path(work) / "mesh", Path(work) / "state"
            mesh.mkdir()
            # Every location the cycle's transitions need is supplied, so ALLOW
            # here is the cycle's own outcome, not a summary over a refusal.
            env = node_env(work, STEGVERSE_REPO_LEDGER_HOME=str(Path(work) / "repo-ledger-home"))
            completed = subprocess.run([sys.executable, "-B", str(EXECUTOR), "--mesh-root", str(mesh),
                                        "--node-state-root", str(state), "--hb-epoch", "4096"],
                                       capture_output=True, text=True, env=env, cwd=work, timeout=180)
            self.assertEqual(completed.returncode, 0, completed.stderr[-800:])
            record = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(record["materialization"], "ONE_CYCLE_PER_INVOCATION")
            self.assertEqual(record["disposition"], "ALLOW")
            self.assertEqual(record["failed_transitions"], [])
            self.assertIsNone(record["failed_predicate"])
            self.assertEqual(record["federation_cycle"]["transport"], "INTERLOCK_INTR_SUPPLIED_MESH")
            self.assertTrue((state / "resident-runtime/resident-executor.latest.json").is_file())
            self.assertFalse((ROOT / "resident-runtime/state/resident-executor.latest.json").exists())

    def test_a_cycle_whose_transitions_fail_closed_is_not_reported_as_allowed(self):
        # The cycle exits 0 after recording each transition's own disposition.
        # Without the ledger locations both of its transitions fail closed, and
        # the executor must say so rather than summarise the run as ALLOW.
        with tempfile.TemporaryDirectory() as work:
            mesh, state = Path(work) / "mesh", Path(work) / "state"
            mesh.mkdir()
            env = {k: v for k, v in node_env(work).items() if "LEDGER" not in k}
            completed = subprocess.run([sys.executable, "-B", str(EXECUTOR), "--mesh-root", str(mesh),
                                        "--node-state-root", str(state), "--hb-epoch", "4096"],
                                       capture_output=True, text=True, env=env, cwd=work, timeout=180)
            record = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(completed.returncode, 2, completed.stderr[-800:])
            self.assertEqual(record["disposition"], "FAIL_CLOSED")
            self.assertEqual(record["failed_predicate"], "FEDERATION_CYCLE_TRANSITION_NOT_ALLOWED")
            self.assertIsNone(record["error"])
            failed = {row["transition"]: row for row in record["failed_transitions"]}
            self.assertEqual(set(failed), {"consumption", "repository_propagation"})
            for row in failed.values():
                self.assertEqual(row["disposition"], "FAIL_CLOSED")
                self.assertEqual(row["failed_predicate"], "LEDGER_LOCATION_REQUIRED_FROM_MATERIALIZER")
                self.assertTrue(row["retry_entrypoint"])
            self.assertEqual(record["federation_cycle"]["consumption"]["disposition"], "FAIL_CLOSED")
            written = json.loads((state / "resident-runtime/resident-executor.latest.json").read_text())
            self.assertEqual(written["disposition"], "FAIL_CLOSED")

    def test_the_sv002_query_is_published_on_the_supplied_mesh_and_nothing_else_runs(self):
        with tempfile.TemporaryDirectory() as work:
            sdk, mesh, state = Path(work) / "sdk", Path(work) / "mesh", Path(work) / "sv002"
            fake_sdk(sdk)
            mesh.mkdir()
            completed = subprocess.run([sys.executable, "-B", str(SUBMISSION), "--sdk-root", str(sdk),
                                        "--mesh-root", str(mesh), "--state-root", str(state)],
                                       capture_output=True, text=True, env=node_env(work), cwd=work, timeout=180)
            self.assertEqual(completed.returncode, 0, completed.stderr[-800:])
            receipt = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(receipt["disposition"], "ALLOW")
            self.assertEqual(receipt["transport"], "INTERLOCK_INTR_SUPPLIED_MESH")
            self.assertIs(receipt["awaits_the_receiver"], False)
            self.assertEqual(len(list((mesh / "frames.d").glob("*.json"))), 1)
            self.assertNotIn("target_cycle", receipt)
            self.assertFalse((Path(work) / ".stegverse").exists())

    def test_the_sv002_submission_without_sdk_source_fails_closed_by_name(self):
        with tempfile.TemporaryDirectory() as work:
            mesh = Path(work) / "mesh"
            mesh.mkdir()
            completed = subprocess.run([sys.executable, "-B", str(SUBMISSION), "--sdk-root", str(Path(work) / "none"),
                                        "--mesh-root", str(mesh), "--state-root", str(Path(work) / "sv002")],
                                       capture_output=True, text=True, env=node_env(work), cwd=work, timeout=180)
            self.assertEqual(completed.returncode, 1)
            receipt = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(receipt["failed_predicate"], "STEGVERSE_SDK_SOURCE_SUPPLIED")
            self.assertIs(receipt["consequence_committed"], False)
            self.assertFalse((mesh / "frames.d").exists())


if __name__ == "__main__":
    unittest.main()
