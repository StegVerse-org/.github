"""The transition workflow binds a designated mesh locator to what the run can publish.

StegVerse-org/.github#23 (SVORG-MESH-LOCATION-BINDING-001), lanes P23-B /
P118-B: the `workflow_dispatch` input `mesh_root` is parsed deterministically;
a malformed locator or one naming a repository this run holds no credentials for
is a six-field FAIL_CLOSED; a locator naming this repository is materialized on
the checkout, fetched before the transition and published (fast-forward only)
before the ledger ref. No mesh is designated here and nothing is written to any
real ref: temporary repositories only.
"""
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/organization-ledger-transition.yml"
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


binding = load("mesh_locator_binding_test", "resident-runtime/mesh_locator_binding.py")
kernel = load("mesh_binding_kernel_test", "org-kernel/kernel.py")


class LocatorParsing(unittest.TestCase):
    def test_a_well_formed_locator_splits_into_repository_and_qualified_ref(self):
        self.assertEqual(binding.parse_locator("git+StegVerse-org/.github#refs/stegverse/x"),
                         ("StegVerse-org/.github", "refs/stegverse/x"))
        self.assertEqual(binding.parse_locator("git+/tmp/mesh.git#refs/test/mesh"), ("/tmp/mesh.git", "refs/test/mesh"))

    def test_malformed_locators_are_refused_deterministically(self):
        for bad in ("", "StegVerse-org/.github#refs/x", "git+#refs/x", "git+repo", "git+repo#", "git+repo#main",
                    "git+repo#refs/x/", "git+repo#refs//x", "git+repo#refs/../x", "git+repo#refs/a b", "git+repo#refs/a:b"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    binding.parse_locator(bad)


class Binding(unittest.TestCase):
    SLUG = "StegVerse-org/.github"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / "checkout"
        self.workspace.mkdir()

    def bind(self, locator):
        return binding.bind(locator, repository_slug=self.SLUG, workspace=self.workspace)

    def test_a_locator_naming_this_repository_is_materialized_on_the_checkout(self):
        for repository in (self.SLUG, self.SLUG.lower(), ".", str(self.workspace)):
            with self.subTest(repository=repository):
                result = self.bind("git+" + repository + "#refs/stegverse/federation-mesh")
                self.assertEqual(result["disposition"], "ALLOW", result)
                self.assertEqual(result["publish_ref"], "refs/stegverse/federation-mesh")
                self.assertEqual(result["mesh_root"], "git+" + str(self.workspace) + "#refs/stegverse/federation-mesh")
                self.assertEqual(result["authority_effect"], "NONE_BINDING_ONLY")
                # The bound locator is one the kernel opens as a git-ref mesh.
                repository_path, _, ref = result["mesh_root"][4:].partition("#")
                self.assertEqual((Path(repository_path), ref), (self.workspace, result["publish_ref"]))

    def test_a_locator_naming_another_repository_is_refused_with_six_fields_and_no_credential(self):
        result = self.bind("git+StegVerse-Labs/.github#refs/stegverse/federation-mesh")
        self.assertEqual(result["disposition"], "FAIL_CLOSED")
        self.assertEqual(result["failure_code"], "MESH_REPOSITORY_NOT_MATERIALIZABLE_FROM_THIS_RUN")
        for field in SIX_FIELDS:
            self.assertTrue(result.get(field), field)
        self.assertEqual(result["owning_existing_goal"], "SVORG-MESH-LOCATION-BINDING-001")
        self.assertIn("none is inferred", result["required_evidence_or_repair"])
        self.assertNotIn("mesh_root", result)
        self.assertNotIn("publish_ref", result)

    def test_a_malformed_locator_is_refused_with_six_fields(self):
        for bad in ("refs/stegverse/x", "git+StegVerse-org/.github#main", "git+StegVerse-org/.github"):
            with self.subTest(bad=bad):
                result = self.bind(bad)
                self.assertEqual(result["disposition"], "FAIL_CLOSED")
                self.assertEqual(result["failure_code"], "MESH_LOCATOR_INVALID")
                for field in SIX_FIELDS:
                    self.assertTrue(result.get(field), field)

    def test_the_command_line_exits_closed_on_refusal_and_open_on_binding(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        refused = subprocess.run(
            ["python3", str(ROOT / "resident-runtime/mesh_locator_binding.py"), "--locator", "git+other/repo#refs/x",
             "--repository", self.SLUG, "--workspace", str(self.workspace)], capture_output=True, text=True, env=env)
        self.assertEqual(refused.returncode, 1)
        self.assertEqual(json.loads(refused.stdout)["disposition"], "FAIL_CLOSED")
        bound = subprocess.run(
            ["python3", str(ROOT / "resident-runtime/mesh_locator_binding.py"), "--locator",
             "git+" + self.SLUG + "#refs/stegverse/federation-mesh",
             "--repository", self.SLUG, "--workspace", str(self.workspace)], capture_output=True, text=True, env=env)
        self.assertEqual(bound.returncode, 0, bound.stderr)
        self.assertEqual(json.loads(bound.stdout)["publish_ref"], "refs/stegverse/federation-mesh")

    def test_the_bound_locator_is_a_mesh_the_kernel_materializes_and_a_peer_reads_back(self):
        subprocess.run(["git", "init", "-q", str(self.workspace)], check=True)
        result = self.bind("git+" + self.SLUG + "#refs/stegverse/federation-mesh")
        store = kernel.mesh_store(result["mesh_root"])
        self.assertEqual(store.kind, "GIT_REF")
        frame = {"packet_id": "p", "frame_sha256": "sha256:" + "c" * 64, "destination_org": "StegVerse-Labs"}
        key = kernel.node_store_module.frame_key(frame)
        store.put_once(key, frame)
        # The ref the workflow publishes is exactly where the frame landed.
        tip = subprocess.run(["git", "-C", str(self.workspace), "rev-parse", result["publish_ref"]],
                             capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(len(tip), 40)
        fresh = Path(self.temp.name) / "peer.git"
        subprocess.run(["git", "init", "-q", "--bare", str(fresh)], check=True)
        subprocess.run(["git", "--git-dir", str(fresh), "fetch", "-q", str(self.workspace),
                        "+" + result["publish_ref"] + ":" + result["publish_ref"]], check=True)
        peer = kernel.mesh_store("git+" + str(fresh) + "#" + result["publish_ref"])
        self.assertEqual(peer.get(key), frame)


class WorkflowBinding(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text()

    def test_mesh_root_is_a_required_dispatch_input_and_never_inferred(self):
        inputs = self.workflow.split("workflow_dispatch:")[1].split("permissions:")[0]
        self.assertRegex(inputs, r"mesh_root:\n\s+description: .*\n\s+required: true")
        self.assertNotIn("STEGVERSE_ORG_FEDERATION_ROOT", self.workflow)

    def test_dispatch_selects_only_committed_transition_request_paths(self):
        selection = self.workflow.split("Select committed transition requests")[1].split("- name:")[0]
        self.assertIn('.stegverse/transition-requests/*.json)', selection)
        self.assertIn('git ls-files --error-unmatch -- "$INPUT_REQUEST"', selection)
        self.assertIn('DISPATCH_REQUEST_OUTSIDE_COMMITTED_TRANSITION_REQUESTS', selection)
        self.assertIn('DISPATCH_REQUEST_NOT_COMMITTED', selection)
        self.assertIn('DISPATCH_REQUEST_PATH_INVALID', selection)
        self.assertIn('printf \'%s\\n\' "$INPUT_REQUEST"', selection)

    def test_dispatch_mesh_input_is_not_interpolated_into_shell_source(self):
        # GitHub input is data, never shell code; quotes and newlines in a
        # supplied locator must reach the binding validator without execution.
        receive = self.workflow.split("Receive each request")[1].split("- name:")[0]
        self.assertIn("INPUT_MESH_ROOT: ${{ github.event.inputs.mesh_root }}", receive)
        self.assertIn('mesh_root="$INPUT_MESH_ROOT"', receive)
        self.assertNotIn("mesh_root='${{ github.event.inputs.mesh_root }}'", receive)

    def test_the_receive_step_binds_the_locator_through_the_binding_module(self):
        self.assertIn("python resident-runtime/mesh_locator_binding.py", self.workflow)
        self.assertIn('--locator "$mesh_root" --repository "$GITHUB_REPOSITORY" --workspace "$GITHUB_WORKSPACE"', self.workflow)
        self.assertIn('git fetch --no-tags origin "+$mesh_ref:$mesh_ref"', self.workflow)
        self.assertIn('mesh_args=(--mesh-root "git+$GITHUB_WORKSPACE#$mesh_ref")', self.workflow)
        self.assertIn('echo "MESH_PUBLISH_REF=$mesh_ref" >> "$GITHUB_ENV"', self.workflow)

    def test_a_run_without_a_locator_still_reaches_the_ingress(self):
        # The refusal is the ingress's to record (mesh_location_required_from_materializer),
        # not this workflow's to pre-empt.
        receive = self.workflow.split("Receive each request")[1].split("- name:")[0]
        self.assertIn('${mesh_args[@]+"${mesh_args[@]}"}', receive)
        self.assertNotIn("MESH_LOCATION_REQUIRED", receive)

    def test_a_run_without_a_locator_defers_a_request_that_leaves_this_organization(self):
        # Recording it without a mesh would spend it: the emission would be refused
        # and a later dispatch with the mesh answered ALREADY_RECORDED.
        receive = self.workflow.split("Receive each request")[1].split("- name:")[0]
        defer = receive.split("[ ${#mesh_args[@]} -eq 0 ]")[1].split("continue")[0]
        self.assertIn("capability_destination_bindings", defer)
        self.assertIn('build_manifest") or {}).get("process") in bound', defer)
        self.assertIn("deferred $name", defer)
        self.assertLess(receive.index("deferred $name"), receive.index("organization_manifest_ingress.py"))

    def test_the_mesh_ref_is_published_before_the_ledger_ref_and_read_back_fresh(self):
        steps = re.findall(r"- name: (.+)", self.workflow)
        self.assertLess(steps.index("Publish the designated mesh ref (fast-forward only)"),
                        steps.index("Publish the ledger ref (fast-forward only)"))
        self.assertLess(steps.index("Read the organization and repository ledgers back from a fresh fetch"),
                        steps.index("Read the designated mesh ref back from a fresh fetch"))
        self.assertIn("MESH_REF_PUBLISH_RACE", self.workflow)
        self.assertIn('"$fresh" "$MESH_PUBLISH_REF"', self.workflow)


if __name__ == "__main__":
    unittest.main()
