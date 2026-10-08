"""A node's consumption markers and work intake live where it was told.

`consume_and_respond` used to record which frames it consumed, and
`persist_work_request` used to queue intake, under `resident-runtime/` inside
the repository checkout. Running a cycle therefore mutated committed space,
and its markers outlived the node that wrote them. The mesh and the ledgers are
already supplied by the materializer; this is the same rule for the node's own
state.

These cases assert that a node without a supplied state location consumes
nothing, that a work request is refused before any receipt implies it was
consumed, that every node-state write requires a supplied store, and that a
cycle over this organization's own checkout leaves its `resident-runtime/`
unchanged.

Source validation only. No authority effect is claimed.
"""
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json"
GENESIS = {"mode": "ESTABLISH_GENESIS", "node_ref": "test-node", "predecessor": None}

spec = importlib.util.spec_from_file_location("kernel", ROOT / "org-kernel/kernel.py")
kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)
node_store = kernel.node_store_module

_peer_spec = importlib.util.spec_from_file_location("peer_organization", ROOT / "tests/peer_organization.py")
peers = importlib.util.module_from_spec(_peer_spec)
_peer_spec.loader.exec_module(peers)

PEER = "Kernel-Peer"
CONTROL = "kernel-peer.org-control"
TICK = kernel.HB_ANCHOR_UNIX_NS + 1_000_000_000
REFUSED = "node_state_location_required_from_materializer"


def snapshot(directory):
    """Every file under `directory` with its bytes, so any change is visible."""
    if not directory.exists():
        return {}
    return {str(p.relative_to(directory)): p.read_bytes()
            for p in sorted(directory.rglob("*")) if p.is_file()}


class SuppliedNodeStateTests(unittest.TestCase):
    def setUp(self):
        self.mesh = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.mesh, True)
        self.state = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.state, True)
        self.node = peers.materialize(self, PEER, [
            {"service_id": CONTROL, "repository": PEER + "/.github",
             "boundary_role": "BOUNDARY_LOCAL_CONTROL"}])
        self.peer = self.node.root

    def node_state_in_checkout(self):
        """Markers, outbox or intake written under the peer's checkout. The
        peer carries its own emitters there, which are code, not node state."""
        return sorted(str(p.relative_to(self.peer)) for prefix in
                      ("resident-runtime/federation", "resident-runtime/control")
                      for p in (self.peer / prefix).rglob("*") if p.is_file())

    def packet(self, message_class, communication_id="c-1"):
        return kernel.build_packet(
            origin_org="Origin", origin_service="origin.org-control",
            destination_org=PEER, destination_service=CONTROL,
            payload={"communication_id": communication_id, "message_class": message_class,
                     "subject": "s", "body": {}},
            standing=GENESIS, packet_id=communication_id + ":" + message_class)

    def publish(self, message_class, communication_id="c-1"):
        return kernel.publish_packet(self.packet(message_class, communication_id),
                                     root=self.mesh, now_ns=TICK)

    def test_a_node_without_supplied_state_consumes_nothing(self):
        self.publish("ecosystem.communication")
        with self.assertRaises(ValueError) as raised:
            kernel.consume_and_respond(self.peer, mesh_root=self.mesh)
        self.assertEqual(str(raised.exception), REFUSED)
        self.assertEqual(len(kernel.scan_addressed_frames(PEER, root=self.mesh)), 1,
                         "the frame must still be offered: nothing consumed it")
        self.assertEqual(kernel.scan_addressed_frames("Origin", root=self.mesh), [],
                         "no answer may be published for a frame that was not consumed")
        self.assertEqual(self.node_state_in_checkout(), [])

    def test_markers_and_intake_go_to_the_supplied_state_only(self):
        self.publish("ecosystem.work.request")
        consumed = self.node.consume(mesh_root=self.mesh, node_state_root=self.state)
        self.assertEqual([row["result"]["status"] for row in consumed], ["CONSUMED"])
        intake = consumed[0]["result"]["execution_result"]["application_result"]["work_intake"]
        self.assertTrue(intake["intake_ref"].startswith(str(self.state.resolve())))
        store = kernel.addressed_node_state_store(self.state)
        self.assertEqual(len(store.list_prefix(node_store.NODE_SEEN_PREFIX)), 1)
        self.assertEqual(len(store.list_prefix(node_store.NODE_INTAKE_PREFIX)), 1)
        self.assertEqual(self.node_state_in_checkout(), [],
                         "a cycle must not write into the node's checkout")
        again = self.node.consume(mesh_root=self.mesh, node_state_root=self.state)
        self.assertEqual(again, [], "the supplied markers suppress re-consumption")

    def test_a_work_request_without_node_state_is_refused_before_any_receipt(self):
        with self.assertRaises(ValueError) as raised:
            kernel.dispatch(self.peer, self.packet("ecosystem.work.request"))
        self.assertEqual(str(raised.exception), REFUSED)
        self.assertEqual(self.node_state_in_checkout(), [])

    def test_classes_that_retain_nothing_still_dispatch_without_node_state(self):
        result = kernel.dispatch(self.peer, self.packet("ecosystem.communication"))
        self.assertIs(result["consumed"], True)
        self.assertEqual(self.node_state_in_checkout(), [])

    def test_consume_addressed_frames_routes_intake_to_supplied_state(self):
        self.publish("ecosystem.work.request")
        results = self.node.consume_addressed(mesh_root=self.mesh, node_state_root=self.state)
        self.assertEqual([row["result"]["status"] for row in results], ["CONSUMED"])
        store = kernel.addressed_node_state_store(self.state)
        self.assertEqual(len(store.list_prefix(node_store.NODE_INTAKE_PREFIX)), 1)
        self.assertEqual(self.node_state_in_checkout(), [])

    def test_every_node_state_write_requires_a_supplied_store(self):
        published = self.publish("ecosystem.communication")
        frame = published["frame"]
        calls = {
            "persist_outbox": lambda: kernel.persist_outbox(self.peer, frame),
            "persist_work_request": lambda: kernel.persist_work_request(
                self.peer, self.packet("ecosystem.work.request")),
            "mark_federation_frame_seen": lambda: kernel.mark_federation_frame_seen(
                self.peer, published["path"], frame, {"status": "CONSUMED"}),
            "federation_seen_frame_names": lambda: kernel.federation_seen_frame_names(self.peer),
        }
        for name, call in calls.items():
            with self.subTest(name), self.assertRaises(ValueError) as raised:
                call()
            self.assertEqual(str(raised.exception), REFUSED)
        self.assertEqual(self.node_state_in_checkout(), [])


class OrganizationCheckoutTests(unittest.TestCase):
    def test_a_cycle_over_this_checkout_leaves_its_resident_runtime_unchanged(self):
        mesh = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, mesh, True)
        state = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, state, True)
        organization = kernel.load_registry(ROOT)["organization"]
        control = kernel.organization_slug(organization) + ".org-control"
        kernel.publish_packet(kernel.build_packet(
            origin_org="Origin", origin_service="origin.org-control",
            destination_org=organization, destination_service=control,
            payload={"communication_id": "checkout-1", "message_class": "ecosystem.work.request",
                     "subject": "s", "body": {}},
            standing=GENESIS, packet_id="checkout-1:work"), root=mesh, now_ns=TICK)
        before = snapshot(ROOT / "resident-runtime")
        ledgers = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, ledgers, True)
        consumed = kernel.consume_and_respond(ROOT, mesh_root=mesh, node_state_root=state,
                                              repo_ledger_root=ledgers / "repo",
                                              org_ledger_root=ledgers / "org")
        self.assertEqual([row["result"]["status"] for row in consumed], ["CONSUMED"])
        self.assertEqual(snapshot(ROOT / "resident-runtime"), before)
        store = kernel.addressed_node_state_store(state)
        self.assertEqual(len(store.list_prefix(node_store.NODE_SEEN_PREFIX)), 1)
        self.assertEqual(len(store.list_prefix(node_store.NODE_INTAKE_PREFIX)), 1)


if __name__ == "__main__":
    unittest.main()
