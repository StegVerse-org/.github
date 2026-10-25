"""The transition workflow binds a designated mesh locator to what the run can publish.

StegVerse-org/.github#23 (SVORG-MESH-LOCATION-BINDING-001), lanes P23-B /
P118-B: the `workflow_dispatch` input `mesh_root` is parsed deterministically;
a malformed locator or one naming a repository this run holds no credentials for
is a six-field FAIL_CLOSED; a locator naming this repository is materialized on
the checkout, fetched before the transition and published (fast-forward only)
before the ledger ref. No mesh is designated here and nothing is written to any
real ref: temporary repositories only.
"""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# G17: the transition and return writers are jobs of the organization ledger writer.

def _job(name):
    from tests.workflow_surface import writer_job
    return writer_job(name)


WORKFLOW = ROOT / ".github/workflows/organization-ledger-writer.yml"
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
        self.workflow = _job("ledger-transition")

    def test_mesh_root_is_a_request_mode_dispatch_input_and_never_inferred(self):
        # mesh_root is an input of the committed-request mode (the self-closure
        # mode is retired by Rigel's rule, 2026-10-25: no InTr hop inside one organization). That mode takes it from the
        # dispatch or from the committed request, never from the runner.
        # G17 removed workflow_dispatch: a dispatched mesh_root is FAIL_CLOSED
        # pending in the registry; the committed request supplies it on push.
        from tests.workflow_surface import registry
        self.assertNotIn("workflow_dispatch:", self.workflow.split("\njobs:\n", 1)[0])
        self.assertTrue([p for p in registry()["fail_closed_pending"] if "mesh_root" in p["surface"]
                         or "self-closure" in p["surface"]])
        self.assertIn('--dispatch-mesh-root "$mesh_root"', self.workflow)
        self.assertNotIn("STEGVERSE_ORG_FEDERATION_ROOT", self.workflow)

    def test_dispatch_selects_only_committed_transition_request_paths(self):
        selection = self.workflow.split("Select committed transition requests")[1].split("- name:")[0]
        self.assertIn('.stegverse/transition-requests/*.json)', selection)
        self.assertIn('git ls-files --error-unmatch -- "$INPUT_REQUEST"', selection)
        self.assertIn('DISPATCH_REQUEST_OUTSIDE_COMMITTED_TRANSITION_REQUESTS', selection)
        self.assertIn('DISPATCH_REQUEST_NOT_COMMITTED', selection)
        self.assertIn('DISPATCH_REQUEST_PATH_INVALID', selection)
        self.assertIn('DISPATCH_REQUEST_CONTROL_CHARACTER', selection)
        self.assertIn('all(32 <= ord(c) <= 126 for c in p)', selection)
        self.assertNotIn("*'\\n'*)", selection)
        self.assertIn("*../*|*/../*|*' '*)", selection)
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
        self.assertIn("inputs.request_process(request) in bound", defer)
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


class ManifestDirectedRunInputs(unittest.TestCase):
    """Every ACTION is by manifest: the committed request supplies the run's inputs; no dispatch is required."""

    def setUp(self):
        self.inputs = load("manifest_directed_run_inputs", "resident-runtime/manifest_directed_run_inputs.py")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _write(self, relative, document):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document if isinstance(document, str) else json.dumps(document))
        return str(path)

    def _six(self, result):
        self.assertEqual(result["disposition"], "FAIL_CLOSED")
        for field in SIX_FIELDS:
            self.assertTrue(result[field], field)

    def test_a_committed_request_supplies_the_mesh_without_a_dispatch(self):
        request = self._write("r1.json", {"mesh_root": "git+StegVerse-org/.github#refs/stegverse/mesh"})
        result = self.inputs.transition_mesh_root("", [request])
        self.assertEqual(result["disposition"], "ALLOW")
        self.assertEqual(result["mesh_root"], "git+StegVerse-org/.github#refs/stegverse/mesh")
        self.assertEqual(result["source"], "COMMITTED_TRANSITION_REQUEST")

    def test_a_request_declaring_no_mesh_leaves_it_empty_and_the_request_deferred(self):
        result = self.inputs.transition_mesh_root("", [self._write("r1.json", {"request_id": "x"})])
        self.assertEqual((result["disposition"], result["mesh_root"], result["source"]), ("ALLOW", "", "NONE_DECLARED"))

    def test_a_dispatched_mesh_is_used_unchanged(self):
        request = self._write("r1.json", {"mesh_root": "git+other#refs/x"})
        result = self.inputs.transition_mesh_root("git+.#refs/stegverse/mesh", [request])
        self.assertEqual((result["mesh_root"], result["source"]), ("git+.#refs/stegverse/mesh", "WORKFLOW_DISPATCH"))

    def test_conflicting_declared_meshes_fail_closed(self):
        a = self._write("a.json", {"mesh_root": "git+.#refs/a"})
        b = self._write("b.json", {"mesh_root": "git+.#refs/b"})
        self._six(self.inputs.transition_mesh_root("", [a, b]))

    def test_a_declared_mesh_cannot_inject_an_environment_line(self):
        self._six(self.inputs.transition_mesh_root("", [self._write("a.json", {"mesh_root": "git+.#refs/a\nX=1"})]))
        self._six(self.inputs.transition_mesh_root("", [self._write("b.json", {"mesh_root": 7})]))

    def _return_request(self, **overrides):
        document = {"schema": self.inputs.RETURN_REQUEST_SCHEMA, "owning_existing_goal": "SDK-MR-A-VALIDATION-CUSTODY-001",
                    "mesh_root": "git+.#refs/stegverse/mesh", "peer_mesh": "git+StegVerse-Labs/.github#refs/stegverse/mesh"}
        document.update(overrides)
        return self._write(".stegverse/governance-return-requests/R1.json", document)

    def test_a_committed_return_request_supplies_every_return_input(self):
        path = self._return_request(sdk_ref="e" * 40)
        relative = os.path.relpath(path, self.root)
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            result = self.inputs.governance_return_inputs({}, [relative])
        finally:
            os.chdir(cwd)
        self.assertEqual(result["disposition"], "ALLOW")
        self.assertEqual(result["peer_mesh"], "git+StegVerse-Labs/.github#refs/stegverse/mesh")
        self.assertEqual(result["sdk_ref"], "e" * 40)
        self.assertEqual(result["deciding_ledger"], "")
        self.assertTrue(result["source"].startswith("COMMITTED_RETURN_REQUEST:"))

    def _resolve(self, path, dispatch=None):
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            return self.inputs.governance_return_inputs(dispatch or {}, [os.path.relpath(path, self.root)] if path else [])
        finally:
            os.chdir(cwd)

    def test_a_return_needs_exactly_one_committed_request_or_a_dispatch(self):
        self._six(self._resolve(None))
        dispatched = self._resolve(None, {"mesh_root": "git+.#refs/m", "peer_mesh": "git+p#refs/m"})
        self.assertEqual((dispatched["disposition"], dispatched["source"]), ("ALLOW", "WORKFLOW_DISPATCH"))

    def test_an_invalid_return_request_fails_closed(self):
        self._six(self._resolve(self._return_request(schema="other")))
        self._six(self._resolve(self._return_request(peer_mesh="")))
        self._six(self._resolve(self._return_request(sdk_ref="main")))
        self._six(self._resolve(self._return_request(deciding_ledger="git+x#refs/l\nX=1")))

    def test_both_runtime_workflows_resolve_their_inputs_through_the_committed_request(self):
        transition = _job("ledger-transition")
        receive = transition.split("Receive each request")[1].split("- name:")[0]
        self.assertIn("manifest_directed_run_inputs.py transition-mesh", receive)
        self.assertLess(receive.index("transition-mesh"), receive.index("mesh_locator_binding.py"))
        ret = _job("governance-return")
        from tests.workflow_surface import registry
        trigger = next(j for j in registry()["writer_jobs"] if j["job"] == "governance-return")["paths"]
        self.assertIn(".stegverse/governance-return-requests/**", trigger)
        steps = re.findall(r"- name: (.+)", ret)
        self.assertLess(steps.index("Resolve this run's inputs from the committed return request or the dispatch"),
                        steps.index("Bind the designated mesh to this run"))
        self.assertNotIn("${{ github.event.inputs.mesh_root }}\n", ret.split("Bind the designated mesh to this run")[1])


class CommittedTransitionManifest(unittest.TestCase):
    """A committed request submits build_manifest arguments or an exact, already-built manifest.

    The SDK Manifest Builder and the ingress-derived canonical digest are passed
    in by the run; here stdlib stand-ins with the same contract are passed, so
    this boundary test needs no SDK checkout.
    """

    def setUp(self):
        self.inputs = load("manifest_directed_run_inputs_manifest", "resident-runtime/manifest_directed_run_inputs.py")
        self.arguments = {"process": "governance", "data": {"x": 1}, "processor_request": {"candidate": {}},
                          "source_framework": "committed-manifest-test", "source_output_id": "committed-1"}

    @staticmethod
    def build(**arguments):
        if "process" not in arguments:
            raise TypeError("process is required")
        return {"processing": {"capability": arguments["process"]},
                "payload": arguments.get("data"), "source_output_id": arguments.get("source_output_id")}

    @staticmethod
    def canonical_of(manifest):
        if not isinstance(manifest.get("processing"), dict):
            raise ValueError("manifest has no processing")
        return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def resolve(self, request):
        return self.inputs.committed_manifest(request, build=self.build, canonical_of=self.canonical_of)

    def _six(self, result, predicate):
        self.assertEqual((result["disposition"], result["failed_predicate"]), ("FAIL_CLOSED", predicate))
        for field in SIX_FIELDS:
            self.assertTrue(result[field], field)

    def test_build_manifest_arguments_are_built_by_the_pinned_sdk(self):
        result = self.resolve({"request_id": "r", "build_manifest": self.arguments})
        self.assertEqual((result["disposition"], result["source"]), ("ALLOW", "BUILT_BY_PINNED_SDK"))
        self.assertEqual(self.inputs.request_process({"build_manifest": self.arguments}), "governance")

    def test_an_exact_manifest_is_submitted_unchanged_when_it_reproduces_its_digest(self):
        manifest = self.build(**self.arguments)
        expected = self.canonical_of(manifest)
        result = self.resolve({"request_id": "r", "manifest": manifest, "expected_canonical_manifest_sha256": expected})
        self.assertEqual((result["disposition"], result["source"]), ("ALLOW", "EXACT_COMMITTED_MANIFEST"))
        self.assertEqual(result["manifest"], manifest)
        self.assertEqual(result["canonical_manifest_sha256"], expected)
        self.assertEqual(self.inputs.request_process({"manifest": manifest}), "governance")

    def test_an_exact_manifest_that_does_not_reproduce_its_digest_is_refused(self):
        manifest = self.build(**self.arguments)
        self._six(self.resolve({"request_id": "r", "manifest": manifest, "expected_canonical_manifest_sha256": "0" * 64}),
                  "EXACT_MANIFEST_REPRODUCES_ITS_CANONICAL_DIGEST")

    def test_an_exact_manifest_must_name_its_digest(self):
        manifest = self.build(**self.arguments)
        for expected in (None, "sha256:" + "0" * 64, "A" * 64):
            with self.subTest(expected=expected):
                self._six(self.resolve({"request_id": "r", "manifest": manifest,
                                        "expected_canonical_manifest_sha256": expected}),
                          "EXACT_MANIFEST_NAMES_ITS_CANONICAL_DIGEST")

    def test_an_altered_exact_manifest_is_refused(self):
        manifest = self.build(**self.arguments)
        expected = self.canonical_of(manifest)
        manifest["declared_intent"] = "something else"
        result = self.resolve({"request_id": "r", "manifest": manifest, "expected_canonical_manifest_sha256": expected})
        self.assertEqual(result["disposition"], "FAIL_CLOSED")

    def test_a_request_carries_exactly_one_manifest_form(self):
        manifest = self.build(**self.arguments)
        for request in ({"request_id": "r"},
                        {"request_id": "r", "build_manifest": self.arguments, "manifest": manifest}):
            with self.subTest(keys=sorted(request)):
                self._six(self.resolve(request), "REQUEST_CARRIES_EXACTLY_ONE_MANIFEST_FORM")

    def test_the_ledger_transition_run_resolves_its_manifest_here(self):
        workflow = _job("ledger-transition")
        self.assertIn("inputs.committed_manifest(request, build=build_manifest, canonical_of=canonical_of)", workflow)
        self.assertIn("inputs.request_process(request) in bound", workflow)
        self.assertNotIn('request["build_manifest"] and request["standing"]', workflow)


if __name__ == "__main__":
    unittest.main()
