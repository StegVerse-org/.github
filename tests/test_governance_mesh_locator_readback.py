"""A governance request on a git-ref mesh: emitted when the mesh is supplied, refused with six fields when not.

StegVerse-org/.github#23 / #118 (lanes P23-B, P118-B). Post-designation fixtures
against temporary repositories only: the same governance manifest is received by
the ingress with both ledgers on one git ref (the repository chain in its own
subtree) and (a) a materializer-supplied git-ref mesh, where it is emitted to
StegVerse-Labs and its frame is read back by an independent materialization of the
mesh ref; (b) no mesh, where the emission is refused with all six fields and the
refusal is recorded on both chains. Both chains read back from a fresh fetch in
both cases. Nothing here designates a mesh.
"""
import importlib.util
import json
import multiprocessing
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "org-boundary/registry/services.json").read_text())
GENESIS = json.loads((ROOT / "tests/fixtures/crossing-standing-genesis.json").read_text())
FIXTURE = ROOT / "tests/fixtures/sdk-manifests/governance-to-llm-adapter.json"
LEDGER_REF = "refs/stegverse/organization-ledger"
MESH_REF = "refs/test/federation-mesh"
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ingress = _load("mesh_readback_ingress", "resident-runtime/organization_manifest_ingress.py")
readback = _load("mesh_readback_readback", "resident-runtime/organization_ledger_readback.py")
kernel = _load("mesh_readback_kernel", "org-kernel/kernel.py")
NAMESPACE = json.loads((ROOT / ".stegverse/transition-ledger/contract.json").read_text())["repository_ledger_location"]["namespace"]


def bare(path):
    subprocess.run(["git", "init", "-q", "--bare", str(path)], check=True)
    return path


def fresh_fetch(source, destination, ref):
    bare(destination)
    subprocess.run(["git", "--git-dir", str(destination), "fetch", "-q", str(source), "+" + ref + ":" + ref], check=True)
    return destination


def _put_once(args):
    locator, frame = args
    store = kernel.mesh_store(locator)
    try:
        return store.put_once(kernel.node_store_module.frame_key(frame), frame)
    except kernel.node_store_module.WriteOnceCollision:
        return "collision"


class GovernanceOnAGitRefMesh(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = bare(Path(self.temp.name) / "ledger.git")
        self.previous = {name: os.environ.get(name) for name in ("STEGVERSE_ORG_LEDGER_ROOT", "STEGVERSE_REPO_LEDGER_ROOT")}
        os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = "git+" + str(self.ledger) + "#" + LEDGER_REF
        os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = os.environ["STEGVERSE_ORG_LEDGER_ROOT"] + ":" + NAMESPACE

        def restore():
            for name, value in self.previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        self.addCleanup(restore)

    def receive(self, mesh_root, packet_id):
        manifest = json.loads(FIXTURE.read_text())
        manifest["source_output_id"] = manifest["source_output_id"] + "-" + packet_id
        return ingress.receive(manifest, registry=REGISTRY, standing=GENESIS, packet_id=packet_id,
                               hb_epoch=46, mesh_root=mesh_root), manifest

    def chains(self, result, manifest):
        fresh = fresh_fetch(self.ledger, Path(self.temp.name) / ("fresh-" + result["organization_transition_id"][-8:] + ".git"), LEDGER_REF)
        location = "git+" + str(fresh) + "#" + LEDGER_REF
        organization = readback.readback(location, ingress_result=result, manifest=manifest)
        repository = readback.repository_readback(location, NAMESPACE, organization, ingress_result=result)
        return organization, repository

    def test_with_a_supplied_git_ref_mesh_the_request_leaves_and_a_peer_reads_its_frame(self):
        mesh = bare(Path(self.temp.name) / "mesh.git")
        result, manifest = self.receive("git+" + str(mesh) + "#" + MESH_REF, "mesh-supplied")
        self.assertEqual(result["disposition"], "ALLOW", result)
        self.assertEqual(result["emission_transition_class"], "ORGANIZATION_EGRESS_EMITTED")
        self.assertEqual(result["governance_decision_state"], "REQUESTED_OF_DECIDING_ORGANIZATION")
        self.assertEqual(result["receiver_unavailable_disposition"], "DURABLE_QUEUE_OR_EVENT_EPHEMERAL_MATERIALIZATION")
        # A peer that materializes later reads the frame from a fresh fetch of the mesh ref.
        peer_mesh = fresh_fetch(mesh, Path(self.temp.name) / "peer-mesh.git", MESH_REF)
        peer = kernel.mesh_store("git+" + str(peer_mesh) + "#" + MESH_REF)
        frames = [peer.get(key) for key in peer.list_prefix(kernel.node_store_module.MESH_FRAME_PREFIX)]
        self.assertEqual([frame["destination_org"] for frame in frames], ["StegVerse-Labs"])
        self.assertEqual(frames[0]["packet_id"], result["governance_request_packet_id"])
        # Both chains read back from a fresh fetch of the ledger ref.
        organization, repository = self.chains(result, manifest)
        self.assertEqual(organization["disposition"], "ALLOW", organization)
        self.assertEqual(organization["chain_length"], 2)
        self.assertEqual(repository["chain_length"], 2)
        self.assertEqual([c["transition_class"] for c in repository["chain"]],
                         ["ORGANIZATION_SDK_MANIFEST_INGRESS", "ORGANIZATION_EGRESS_EMITTED"])
        self.assertTrue(repository["every_receipt_retained_in_organization_ledger"])

    def test_without_a_mesh_the_emission_is_refused_with_six_fields_and_recorded_on_both_chains(self):
        result, manifest = self.receive(None, "mesh-absent")
        self.assertEqual(result["disposition"], "FAIL_CLOSED")
        self.assertEqual(result["failure_code"], "GOVERNANCE_REQUEST_NOT_EMITTED")
        self.assertEqual(result["failed_predicate"], "PACKET_IS_BUILDABLE_AND_PUBLISHABLE_AS_DECLARED")
        self.assertEqual(result["detail"], "mesh_location_required_from_materializer")
        self.assertEqual(result["governance_decision_state"], "REQUEST_NOT_EMITTED")
        for field in SIX_FIELDS:
            self.assertTrue(result.get(field), field)
        organization, repository = self.chains(result, manifest)
        self.assertEqual(organization["disposition"], "ALLOW", organization)
        self.assertEqual([c["transition_class"] for c in repository["chain"]],
                         ["ORGANIZATION_SDK_MANIFEST_INGRESS", "ORGANIZATION_EGRESS_REFUSED"])
        self.assertTrue(repository["every_receipt_retained_in_organization_ledger"])
        self.assertEqual(repository["consumed_by_organization_receipt_sha256"], result["organization_receipt_sha256"])

    def test_two_materializations_placing_the_same_frame_leave_one_frame(self):
        mesh = bare(Path(self.temp.name) / "mesh-race.git")
        locator = "git+" + str(mesh) + "#" + MESH_REF
        frame = {"packet_id": "race", "frame_sha256": "sha256:" + "d" * 64, "destination_org": "StegVerse-Labs"}
        with multiprocessing.get_context("fork").Pool(2) as pool:
            outcomes = pool.map(_put_once, [(locator, frame)] * 2)
        key = kernel.node_store_module.frame_key(frame)
        self.assertEqual(outcomes, [key, key])
        store = kernel.mesh_store(locator)
        self.assertEqual(store.list_prefix(kernel.node_store_module.MESH_FRAME_PREFIX), [key])
        with self.assertRaises(kernel.node_store_module.WriteOnceCollision):
            store.put_once(key, {**frame, "destination_org": "elsewhere"})


if __name__ == "__main__":
    unittest.main()
