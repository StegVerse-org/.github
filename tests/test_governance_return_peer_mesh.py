"""A deciding organization's answer, published on its own mesh ref, is taken in and returned here.

StegVerse-org/.github#118 / StegVerse-Labs/.github#3099 / StegVerse-SDK#465
(SDK-MR-A-VALIDATION-CUSTODY-001). A run holds credentials for its own
repository only, so StegVerse-Labs answers on a mesh ref of its own and this
organization reads it: resident-runtime/peer_mesh_intake.py places every
verified frame addressed here on this organization's designated mesh, write
once, and resident-runtime/governance_return_cycle.py consumes it and returns
the decision. Temporary repositories only; nothing here designates a mesh or
touches a real ref. The far side is played by the kernel functions every
boundary runs, as in tests/test_governance_inter_org_route.py.
"""
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "org-boundary/registry/services.json").read_text())
GENESIS = json.loads((ROOT / "tests/fixtures/crossing-standing-genesis.json").read_text())
FIXTURE = ROOT / "tests/fixtures/sdk-manifests/governance-to-task-registry-disclosure.json"
LEDGER_REF = "refs/stegverse/organization-ledger"
MESH_REF = "refs/test/federation-mesh"
DECIDER = "StegVerse-Labs"
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ingress = _load("peer_return_ingress", "resident-runtime/organization_manifest_ingress.py")
intake = _load("peer_return_intake", "resident-runtime/peer_mesh_intake.py")
cycle = _load("peer_return_cycle", "resident-runtime/governance_return_cycle.py")
readback = _load("peer_return_readback", "resident-runtime/organization_ledger_readback.py")
egress = _load("peer_return_egress", "resident-runtime/organization_egress_boundary.py")
acceptance = _load("peer_return_acceptance", "resident-runtime/governance_return_acceptance.py")
kernel = intake.kernel
NAMESPACE = json.loads((ROOT / ".stegverse/transition-ledger/contract.json").read_text())["repository_ledger_location"]["namespace"]


def bare(path):
    subprocess.run(["git", "init", "-q", "--bare", str(path)], check=True)
    return path


class PeerAnswerReturned(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        tmp = Path(self.temp.name)
        self.ledger = bare(tmp / "ledger.git")
        self.own = "git+" + str(bare(tmp / "own-mesh.git")) + "#" + MESH_REF
        self.peer_git = bare(tmp / "peer-mesh.git")
        self.peer = "git+" + str(self.peer_git) + "#" + MESH_REF
        self.previous = {n: os.environ.get(n) for n in ("STEGVERSE_ORG_LEDGER_ROOT", "STEGVERSE_REPO_LEDGER_ROOT")}
        os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = "git+" + str(self.ledger) + "#" + LEDGER_REF
        os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = os.environ["STEGVERSE_ORG_LEDGER_ROOT"] + ":" + NAMESPACE

        def restore():
            for name, value in self.previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        self.addCleanup(restore)
        self.emitted = ingress.receive(json.loads(FIXTURE.read_text()), registry=REGISTRY, standing=GENESIS,
                                       packet_id="peer-return", hb_epoch=46, mesh_root=self.own)
        self.assertEqual(self.emitted["disposition"], "ALLOW", self.emitted)

    def frames(self, locator, organization=None):
        store = kernel.mesh_store(locator)
        out = {key: store.get(key) for key in store.list_prefix(kernel.node_store_module.MESH_FRAME_PREFIX)}
        return {k: f for k, f in out.items() if organization is None or f["destination_org"] == organization}

    def answer_on_the_peer_mesh(self, disposition="DENY"):
        """The deciding organization reads this mesh and answers on its own ref."""
        peer = kernel.mesh_store(self.peer)
        for key, frame in self.frames(self.own, DECIDER).items():
            peer.put_once(key, frame)
        frame = next(iter(self.frames(self.own, DECIDER).values()))
        packet = kernel.recover_packet(frame)
        body = packet["payload"]["body"]
        chain, previous = [], None
        for kind in egress.FAR_SIDE_RECEIPT_KINDS:
            receipt = kernel.receipt(kind, packet["packet_id"], packet["destination"]["service"],
                                     previous, {"payload_hash": kernel.sha(packet["payload"])})
            chain.append(receipt["receipt_id"])
            previous = receipt["receipt_id"]
        decision = {"schema": "stegverse.org-governance-decision/v1", "service_id": "stegverse-labs.governance",
                    "deciding_organization": DECIDER, "decision_authority": "stegcore.steggate.evaluate_admissibility",
                    "sdk_request_sha256": body["sdk_request_sha256"],
                    "governance_request_sha256": body["governance_request_sha256"],
                    "disposition": disposition, "reason": "signal.inputs_incomplete",
                    "organization_receipt_sha256": "sha256:" + "d" * 64, "authority_effect": "NONE_DECISION_ONLY"}
        response = kernel.build_control_response(
            packet, {"application_result": decision, "reconstruction": {"terminal_receipt_id": chain[-1]}})
        epoch = frame["heartbeat_reference"]["epoch"]
        kernel.publish_packet(response, root=self.peer, epoch=epoch)
        return packet

    def return_cycle(self, name):
        return cycle.run(mesh_root=self.own, node_state_root=Path(self.temp.name) / name)

    def ledger_tip(self):
        return subprocess.run(["git", "--git-dir", str(self.ledger), "rev-parse", LEDGER_REF],
                              capture_output=True, text=True, check=True).stdout.strip()

    def test_the_answer_is_taken_in_and_the_decision_returned_and_read_back(self):
        request = self.answer_on_the_peer_mesh()
        taken = intake.intake(self.peer, own_mesh_root=self.own)
        self.assertEqual(taken["disposition"], "ALLOW", taken)
        self.assertEqual([row["message_class"] for row in taken["taken"]], ["ecosystem.work.ack"])
        self.assertEqual(taken["already_present"], [])
        result = self.return_cycle("node")
        self.assertEqual(len(result["governance_returns"]), 1, result)
        returned = result["governance_returns"][0]
        self.assertEqual((returned["disposition"], returned["decision_returned"], returned["governance_disposition"]),
                         ("ALLOW", True, "DENY"))
        self.assertEqual(returned["closure_transition_class"], "ORGANIZATION_EGRESS_CLOSED")
        self.assertEqual(returned["governance_request_packet_id"], request["packet_id"])
        organization = readback.readback(os.environ["STEGVERSE_ORG_LEDGER_ROOT"])
        repository = readback.repository_readback(os.environ["STEGVERSE_ORG_LEDGER_ROOT"], NAMESPACE, organization)
        self.assertEqual(organization["disposition"], "ALLOW")
        classes = [c["transition_class"] for c in repository["chain"]]
        self.assertIn("ORGANIZATION_EGRESS_CLOSED", classes)
        self.assertTrue(repository["every_receipt_retained_in_organization_ledger"])

    def test_a_replayed_answer_returns_the_closure_already_recorded(self):
        self.answer_on_the_peer_mesh()
        intake.intake(self.peer, own_mesh_root=self.own)
        first = self.return_cycle("node-a")["governance_returns"][0]
        tip = self.ledger_tip()
        # A re-dispatch materializes fresh node state, so the answer is consumed again.
        again = intake.intake(self.peer, own_mesh_root=self.own)
        self.assertEqual((again["taken"], len(again["already_present"])), ([], 1))
        second = self.return_cycle("node-b")["governance_returns"][0]
        self.assertEqual(self.ledger_tip(), tip, "a replayed answer appended to the ledger")
        self.assertEqual((second["disposition"], second["governance_disposition"]),
                         (first["disposition"], first["governance_disposition"]))

    def test_a_returned_answer_replayed_under_another_sdk_is_observed_not_refused(self):
        # The pin moved after the return: this SDK no longer reproduces the request.
        import stegverse.manifest_state_transition_runtime as runtime
        derive = runtime.derive_execution_request

        def another_sdk(manifest, boundary):
            return {**derive(manifest, boundary), "request_sha256": "sha256:" + "0" * 64}

        self.answer_on_the_peer_mesh()
        intake.intake(self.peer, own_mesh_root=self.own)
        first = self.return_cycle("node-a")["governance_returns"][0]
        self.assertEqual(first["disposition"], "ALLOW", first)
        tip = self.ledger_tip()
        intake.intake(self.peer, own_mesh_root=self.own)
        with mock.patch.object(runtime, "derive_execution_request", another_sdk):
            result = self.return_cycle("node-b")
            status = cycle.main(["--mesh-root", self.own, "--node-state-root",
                                 str(Path(self.temp.name) / "node-c")])
        replayed = result["governance_returns"][0]
        self.assertEqual(self.ledger_tip(), tip, "a replayed answer appended to the ledger")
        self.assertEqual(replayed["disposition"], "CLOSURE_ALREADY_RECORDED", replayed)
        self.assertEqual((replayed["closure_transition_class"], replayed["closure_organization_receipt_sha256"]),
                         ("ORGANIZATION_EGRESS_CLOSED", first["closure_organization_receipt_sha256"]))
        self.assertIsNone(replayed["failed_predicate"])
        self.assertEqual(status, 0, "an observed replay failed the run")

    def test_an_unreturned_answer_under_another_sdk_still_fails_closed(self):
        import stegverse.manifest_state_transition_runtime as runtime
        derive = runtime.derive_execution_request

        def another_sdk(manifest, boundary):
            return {**derive(manifest, boundary), "request_sha256": "sha256:" + "0" * 64}

        self.answer_on_the_peer_mesh()
        intake.intake(self.peer, own_mesh_root=self.own)
        with mock.patch.object(runtime, "derive_execution_request", another_sdk):
            returned = self.return_cycle("node")["governance_returns"][0]
        self.assertEqual((returned["disposition"], returned["failed_predicate"]),
                         ("FAIL_CLOSED", "RETAINED_MANIFEST_REPRODUCES_THE_RECORDED_REQUEST"))
        organization = readback.readback(os.environ["STEGVERSE_ORG_LEDGER_ROOT"])
        repository = readback.repository_readback(os.environ["STEGVERSE_ORG_LEDGER_ROOT"], NAMESPACE, organization)
        self.assertNotIn("ORGANIZATION_EGRESS_CLOSED", [c["transition_class"] for c in repository["chain"]])

    def test_frames_not_addressed_here_are_left_on_the_peer(self):
        self.answer_on_the_peer_mesh()
        before = set(self.frames(self.own))
        taken = intake.intake(self.peer, own_mesh_root=self.own)
        added = set(self.frames(self.own)) - before
        self.assertEqual(len(added), 1)
        self.assertTrue(all(self.frames(self.own)[k]["destination_org"] == "StegVerse-org" for k in added))
        self.assertEqual(len(taken["taken"]), 1)

    def test_a_frame_whose_key_does_not_address_it_is_refused_and_nothing_is_placed(self):
        self.answer_on_the_peer_mesh()
        peer = kernel.mesh_store(self.peer)
        key, frame = next(iter(self.frames(self.peer, "StegVerse-org").items()))
        peer.put_once(kernel.node_store_module.MESH_FRAME_PREFIX + "0" * 64 + ".json", frame)
        before = set(self.frames(self.own))
        refused = intake.intake(self.peer, own_mesh_root=self.own)
        self.assertEqual(refused["disposition"], "FAIL_CLOSED")
        for field in SIX_FIELDS:
            self.assertTrue(refused.get(field), field)
        self.assertIn("PEER_FRAME_KEY_DOES_NOT_ADDRESS_ITS_CONTENT", [f["finding"] for f in refused["findings"]])
        self.assertEqual(set(self.frames(self.own)), before)

    def test_a_tampered_frame_does_not_recover_and_is_refused(self):
        self.answer_on_the_peer_mesh()
        key, frame = next(iter(self.frames(self.peer, "StegVerse-org").items()))
        tampered = dict(frame, packet_base64=frame["packet_base64"][:-8] + "AAAAAAA=")
        # Same key as the genuine frame (it addresses packet_id and frame_sha256),
        # so it is published alone, on a peer ref of its own.
        other = "git+" + str(bare(Path(self.temp.name) / "tampering-peer.git")) + "#" + MESH_REF
        kernel.mesh_store(other).put_once(key, tampered)
        refused = intake.intake(other, own_mesh_root=self.own)
        self.assertEqual(refused["disposition"], "FAIL_CLOSED")
        self.assertEqual(refused["failure_code"], "PEER_MESH_FRAME_REFUSED")

    def test_a_collision_with_a_held_frame_is_refused_not_overwritten(self):
        self.answer_on_the_peer_mesh()
        key, frame = next(iter(self.frames(self.peer, "StegVerse-org").items()))
        own = kernel.mesh_store(self.own)
        own.put_once(key, dict(frame, channel="something-else"))
        refused = intake.intake(self.peer, own_mesh_root=self.own)
        self.assertEqual(refused["disposition"], "FAIL_CLOSED")
        self.assertIn("PEER_FRAME_COLLIDES_WITH_A_HELD_FRAME", [f["finding"] for f in refused["findings"]])
        self.assertEqual(own.get(key)["channel"], "something-else")

    def test_a_peer_that_published_nothing_is_an_observation(self):
        observed = intake.intake(self.peer, own_mesh_root=self.own)
        self.assertEqual(observed["disposition"], "NOTHING_PUBLISHED")
        self.assertIs(observed["absence_is_not_a_transition"], True)
        self.assertEqual(self.return_cycle("node")["governance_returns"], [])

    def test_a_malformed_peer_locator_is_refused_with_six_fields(self):
        for bad in ("refs/test/x", "git+" + str(self.peer_git) + "#main", "git+#refs/x"):
            with self.subTest(bad=bad):
                refused = intake.intake(bad, own_mesh_root=self.own)
                self.assertEqual(refused["failure_code"], "PEER_MESH_LOCATOR_INVALID")
                for field in SIX_FIELDS:
                    self.assertTrue(refused.get(field), field)

    # StegVerse-org/.github#98, census after #129/#131: the intake's git calls
    # inherit no credential, refuse rather than raise, and tolerate a writer
    # that placed the same frame between the presence check and the put.

    def _git_calls(self, failing=None):
        """Run the real git, recording each call's env; a call whose argv holds
        `failing` is answered with a nonzero status instead of running."""
        real, calls = subprocess.run, []

        def run(args, **kwargs):
            calls.append((list(args), kwargs.get("env")))
            if failing and failing in args:
                return subprocess.CompletedProcess(args, 128, stdout="", stderr="fatal: couldn't find remote ref (moved)\n")
            return real(args, **kwargs)
        return mock.patch.object(intake.subprocess, "run", side_effect=run), calls

    def test_the_anonymous_read_inherits_no_git_variable_from_the_host(self):
        self.answer_on_the_peer_mesh()
        injected = {"GIT_ASKPASS": "/nonexistent/askpass", "GIT_SSH_COMMAND": "false",
                    "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "stegverse.injected", "GIT_CONFIG_VALUE_0": "1"}
        patched, calls = self._git_calls()
        with mock.patch.dict(os.environ, injected), patched:
            taken = intake.intake(self.peer, own_mesh_root=self.own)
        self.assertEqual(taken["disposition"], "ALLOW", taken)
        remote = [(args, env) for args, env in calls if args[0] == "git" and ("ls-remote" in args or "fetch" in args)]
        self.assertEqual(len(remote), 2, [a for a, _ in calls])
        for args, env in remote:
            self.assertIsNotNone(env, args)
            self.assertEqual({k for k in env if k.startswith("GIT_")}, {"GIT_TERMINAL_PROMPT"}, args)
            self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
            for name in injected:
                self.assertNotIn(name, env)

    def test_a_fetch_that_fails_after_listing_is_a_refusal_and_nothing_is_placed(self):
        self.answer_on_the_peer_mesh()
        before = set(self.frames(self.own))
        patched, _ = self._git_calls(failing="fetch")
        with patched:
            refused = intake.intake(self.peer, own_mesh_root=self.own)
        self.assertEqual(refused["disposition"], "FAIL_CLOSED", refused)
        self.assertEqual(refused["failure_code"], "PEER_MESH_FETCH_FAILED")
        for field in SIX_FIELDS:
            self.assertTrue(refused.get(field), field)
        self.assertIn("couldn't find remote ref", refused["detail"])
        self.assertEqual((refused["taken"], refused["authority_effect"]), ([], "NONE_REFUSAL_ONLY"))
        self.assertEqual(set(self.frames(self.own)), before)

    def test_a_ref_that_does_not_resolve_after_fetching_is_a_refusal(self):
        self.answer_on_the_peer_mesh()
        patched, _ = self._git_calls(failing="rev-parse")
        with patched:
            refused = intake.intake(self.peer, own_mesh_root=self.own)
        self.assertEqual(refused["failure_code"], "PEER_MESH_REF_RESOLUTION_FAILED")
        for field in SIX_FIELDS:
            self.assertTrue(refused.get(field), field)
        self.assertEqual(refused["taken"], [])

    def test_a_frame_placed_concurrently_under_its_own_key_is_already_present(self):
        self.answer_on_the_peer_mesh()
        store_class = type(kernel.mesh_store(self.own))
        real, raised = store_class.put_once, []

        def racing_put_once(store, key, value):
            real(store, key, value)  # another writer placed the same frame first ...
            if not raised:
                raised.append(key)
                raise kernel.node_store_module.WriteOnceCollision(key)  # ... and this put sees it
            return key
        with mock.patch.object(store_class, "put_once", racing_put_once):
            taken = intake.intake(self.peer, own_mesh_root=self.own)
        self.assertEqual(taken["disposition"], "ALLOW", taken)
        self.assertEqual(taken["taken"], [])
        self.assertEqual([row["key"] for row in taken["already_present"]], raised)
        self.assertIsNotNone(self.frames(self.own).get(raised[0]))

    def test_any_other_failure_of_the_put_is_not_swallowed(self):
        self.answer_on_the_peer_mesh()
        store_class = type(kernel.mesh_store(self.own))
        with mock.patch.object(store_class, "put_once", side_effect=RuntimeError("mesh_git_ref_cas_retry_exhausted")):
            with self.assertRaises(RuntimeError):
                intake.intake(self.peer, own_mesh_root=self.own)


    # End-to-end acceptance: resident-runtime/governance_return_acceptance.py wires
    # the SDK verifier to a fresh-fetch readback of the deciding ledger. The deciding
    # organization is played by a ledger this test controls, so an ALLOW below
    # proves the wiring only, never a production decision.

    def returned(self):
        self.answer_on_the_peer_mesh()
        intake.intake(self.peer, own_mesh_root=self.own)
        result = self.return_cycle("node")
        return {"schema": "stegverse.organization-governance-return-readback/v1",
                "returns": result["governance_returns"]}

    def test_a_return_whose_deciding_receipt_is_on_the_published_ledger_is_accepted(self):
        document = self.returned()
        sender = readback.readback(os.environ["STEGVERSE_ORG_LEDGER_ROOT"])
        [row] = document["returns"]
        # Stand in for the deciding organization: a receipt on a ledger read back fresh.
        row["deciding_organization_receipt_sha256"] = row["closure_organization_receipt_sha256"]
        deciding = "git+" + str(self.ledger) + "#" + LEDGER_REF
        result = acceptance.accept(deciding, return_readback=document, sender_readback=sender)
        self.assertEqual(result["disposition"], "ALLOW", result)
        [accepted] = result["acceptances"]
        self.assertEqual((accepted["disposition"], accepted["end_to_end_acceptance"]), ("ALLOW", True), accepted)
        self.assertEqual(result["end_to_end_acceptance"], [row["governance_request_packet_id"]])
        self.assertTrue(result["verifier_source"].endswith("stegverse/governance_return_evidence.py"))
        self.assertEqual(result["authority_effect"], "NONE_VERIFICATION_ONLY")

    def test_an_unpublished_deciding_ledger_is_not_completion(self):
        document = self.returned()
        sender = readback.readback(os.environ["STEGVERSE_ORG_LEDGER_ROOT"])
        absent = "git+" + str(bare(Path(self.temp.name) / "deciding.git")) + "#" + LEDGER_REF
        result = acceptance.accept(absent, return_readback=document, sender_readback=sender)
        [accepted] = result["acceptances"]
        self.assertEqual((result["deciding_tip"], accepted["disposition"]), (None, "FAIL_CLOSED"))
        self.assertEqual(accepted["failed_predicate"], "DECIDING_ORGANIZATION_LEDGER_READBACK_PRESENT")
        for field in SIX_FIELDS:
            self.assertTrue(accepted[field], field)
        self.assertEqual(result["end_to_end_acceptance"], [])

    def test_a_malformed_deciding_ledger_locator_is_refused_with_six_fields(self):
        result = acceptance.accept("not-a-locator", return_readback={}, sender_readback={})
        self.assertEqual((result["disposition"], result["failure_code"]), ("FAIL_CLOSED", "DECIDING_LEDGER_LOCATOR_INVALID"))
        for field in SIX_FIELDS:
            self.assertTrue(result[field], field)


class ReturnCycleCustodyRefusals(unittest.TestCase):
    """governance_return_cycle refuses custody with the six fields federation_cycle uses."""

    LEDGERS = ("STEGVERSE_ORG_LEDGER_ROOT", "STEGVERSE_REPO_LEDGER_ROOT")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.mesh = Path(self.temp.name) / "mesh"
        self.mesh.mkdir()

    def assert_six_fields(self, document):
        self.assertEqual(document["disposition"], "FAIL_CLOSED", document)
        for field in SIX_FIELDS:
            self.assertTrue(document.get(field), field)
        self.assertIs(document["consequence_committed"], False)
        self.assertEqual(document["retry_entrypoint"], "resident-runtime/governance_return_cycle.py::run")
        self.assertEqual((document["frames_seen"], document["governance_returns"]), (0, []))
        self.assertEqual(document["authority_effect"], "NONE_REFUSAL_ONLY")

    def test_without_a_mesh_location_the_cycle_refuses_with_six_fields_instead_of_exiting(self):
        refused = cycle.run(mesh_root=None, node_state_root=Path(self.temp.name) / "node")
        self.assert_six_fields(refused)
        self.assertEqual(refused["failed_predicate"], "MESH_LOCATION_REQUIRED_FROM_MATERIALIZER")
        # federation_cycle exits on the same input; its code is 1, as this cycle's main reports.
        with self.assertRaises(SystemExit) as exited:
            cycle.cycle.main(mesh_root=None, node_state_root=Path(self.temp.name) / "node")
        self.assertEqual(exited.exception.code, "MESH_LOCATION_REQUIRED_FROM_MATERIALIZER")

    def test_without_ledger_locations_the_cycle_refuses_as_federation_cycle_does(self):
        cleared = {name: "" for name in self.LEDGERS}
        with mock.patch.dict(os.environ, cleared):
            for name in self.LEDGERS:
                os.environ.pop(name)
            refused = cycle.run(mesh_root=self.mesh, node_state_root=Path(self.temp.name) / "node")
            with mock.patch.object(cycle.cycle.PR, "propagate_all", return_value={
                    "repositories_declared": 0, "repositories_present": 0,
                    "receipts_propagated": 0, "receipts_already_carried": 0}), \
                    mock.patch("builtins.print"):
                federation = cycle.cycle.main(mesh_root=self.mesh, node_state_root=Path(self.temp.name) / "node-f")
        self.assert_six_fields(refused)
        self.assertEqual(refused["failed_predicate"], "LEDGER_LOCATION_REQUIRED_FROM_MATERIALIZER")
        consumption = federation["consumption"]
        self.assertEqual(consumption["disposition"], "FAIL_CLOSED")
        for field in SIX_FIELDS + ("consequence_committed",):
            if field != "retry_entrypoint":
                self.assertEqual(refused[field], consumption[field], field)
        self.assertEqual(consumption["retry_entrypoint"], "resident-runtime/federation_cycle.py::main")

    def test_the_typed_refusal_from_the_kernel_is_the_same_document_and_exit_code_one(self):
        typed = ValueError("ledger_location_required_from_materializer")
        out = Path(self.temp.name) / "out.json"
        with mock.patch.object(cycle.K, "consume_and_respond", side_effect=typed), mock.patch("builtins.print"):
            status = cycle.main(["--mesh-root", str(self.mesh), "--node-state-root", str(Path(self.temp.name) / "node"),
                                 "--out", str(out)])
        self.assertEqual(status, 1)
        self.assert_six_fields(json.loads(out.read_text()))
        with mock.patch.object(cycle.K, "consume_and_respond", side_effect=ValueError("something_else")):
            with self.assertRaises(ValueError):
                cycle.run(mesh_root=self.mesh, node_state_root=Path(self.temp.name) / "node")


class ReturnWorkflowShape(unittest.TestCase):
    """The governance-return writer job binds, takes in, returns, publishes and reads back in that order.

    G17: organization-governance-return.yml is job governance-return of
    .github/workflows/organization-ledger-writer.yml.
    """

    def setUp(self):
        from tests.workflow_surface import writer_job
        self.workflow = writer_job("governance-return")
        self.steps = re.findall(r"- name: (.+)", self.workflow)

    def test_both_locators_are_required_dispatch_inputs(self):
        # G17 removed workflow_dispatch: dispatched locators are FAIL_CLOSED pending
        # (six fields, registry); a committed return request supplies both on push.
        from tests.workflow_surface import registry
        head = self.workflow.split("\njobs:\n", 1)[0]
        self.assertNotIn("workflow_dispatch:", head)
        self.assertNotIn("pull_request", head)
        pending = [r for r in registry()["fail_closed_pending"] if "peer_mesh" in r["surface"]]
        self.assertEqual(len(pending), 1)
        for name in ("DISPATCH_MESH_ROOT", "DISPATCH_PEER_MESH"):
            self.assertIn(name, self.workflow)

    def test_the_order_is_bind_intake_return_publish_mesh_publish_ledger_read_back(self):
        order = ["Bind the designated mesh to this run",
                 "Take in the frames the deciding organization published for this organization",
                 "Consume and return each governance decision",
                 "Publish the designated mesh ref (fast-forward only)",
                 "Publish the ledger ref (fast-forward only)",
                 "Read the ledgers and the mesh back from a fresh fetch"]
        self.assertEqual([self.steps.index(name) for name in order], sorted(self.steps.index(name) for name in order))
        self.assertIn("python resident-runtime/mesh_locator_binding.py", self.workflow)
        self.assertIn("group: organization-ledger", self.workflow)

    def test_acceptance_is_verified_after_the_readback_on_a_pinned_sdk_and_never_gates_the_run(self):
        order = ["Read the ledgers and the mesh back from a fresh fetch", "Checkout the SDK acceptance verifier",
                 "Verify each return against the deciding organization's published ledger", "Retain the run's evidence"]
        self.assertEqual([self.steps.index(name) for name in order], sorted(self.steps.index(name) for name in order))
        checkout = self.workflow.split("- name: Checkout the SDK acceptance verifier")[1].split("- name:")[0]
        self.assertRegex(checkout, r"ref: [0-9a-f]{40}\n")
        self.assertIn("persist-credentials: false", checkout)
        step = self.workflow.split("- name: Verify each return against the deciding organization's published ledger")[1].split("- name:")[0]
        self.assertIn("continue-on-error: true", step)
        self.assertIn('--sdk-path "$GITHUB_WORKSPACE/sdk-acceptance"', step)

    def test_the_sdk_is_the_one_the_governance_route_validates(self):
        # The default is the pin every workflow here uses; an explicit sdk_ref
        # names the exact commit an earlier request was received under.
        pin = re.findall(r"repository: StegVerse-org/StegVerse-SDK\n\s+ref: \$\{\{ env.RETURN_SDK_REF \|\| '([0-9a-f]{40})' \}\}",
                         self.workflow)
        # The workflows that receive a request (and validate that path) pin the
        # SDK the return defaults to, so a request is returned on the SDK it was
        # received under.
        pins = set()
        from tests.workflow_surface import catalog_groups, writer_job
        pins.update(re.findall(r"repository: StegVerse-org/StegVerse-SDK\n\s+ref: ([0-9a-f]{40})",
                               writer_job("ledger-transition")))
        for name in ("governance-inter-org-route-validation.yml", "organization-manifest-ingress-validation.yml"):
            for group in catalog_groups(name):
                if group["runner"].get("x_repository") == "StegVerse-org/StegVerse-SDK":
                    pins.add(group["runner"]["x_ref"])
        self.assertEqual(len(pin), 1)
        self.assertEqual(pins, set(pin), "the receiving and validating workflows pin the SDK the return defaults to")
        self.assertIn("SDK_REF_IS_AN_EXACT_COMMIT", self.workflow)


if __name__ == "__main__":
    unittest.main()
