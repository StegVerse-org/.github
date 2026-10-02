"""StegOS must not need a home directory.

StegOS lives on the network. A StegNode is where it takes entry or egress --
ephemeral, materializing at whatever point is needed, including on a physical
device at the boundary between the network and a KV. Neither is a host.

The kernel's docstring already claimed as much: *no GitHub, hosted scheduler,
provider, or carrier grants authority*. Its semantics held it too -- frames
content addressed, the packet digest recomputed on recovery, receipts hash
linked, the heartbeat an oscillator count rather than a clock read. Its state
did not. `federation_root()` resolved the mesh under `Path.home()`, the
outbox, consumption markers and work intake resolved under a repository
checkout, every one of them written with a bare `write_text`, and a directory
glob was the enumeration. The network-resident operating system required a
home directory and a checkout.

These cases drive the kernel entirely against supplied stores and assert the
federation round-trip completes without reaching for either, that the layout
is unchanged for a mesh or checkout that already exists, and that a node which
could only *derive* its mesh location says so instead of appearing equivalent
to one that was told.

Source validation only. No authority effect is claimed.
"""
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("kernel", ROOT / "org-kernel/kernel.py")
kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)
node_store = kernel.node_store_module

ORGANIZATION = "Kernel-Test"
SERVICE = "kernel-test.boundary-diagnostic"
CONTROL = "kernel-test.org-control"
REGISTRY = {"organization": ORGANIZATION, "services": [
    {"service_id": SERVICE, "repository": "Kernel-Test/.github",
     "boundary_role": "BOUNDARY_LOCAL_DIAGNOSTIC"},
    {"service_id": CONTROL, "repository": "Kernel-Test/.github",
     "boundary_role": "BOUNDARY_LOCAL_CONTROL",
     "accepts": ["ecosystem.work.request"]}]}
TICK = kernel.HB_ANCHOR_UNIX_NS + 1_000_000_000


class NodeFixture:
    """A node with a supplied mesh and a supplied state root, and no host."""

    def __init__(self, stack):
        import json
        self.node_root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.mesh_root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        (self.node_root / "org-boundary/registry").mkdir(parents=True)
        (self.node_root / "org-boundary/registry/services.json").write_text(json.dumps(REGISTRY))
        self.mesh = kernel.mesh_store(self.mesh_root)
        self.state = kernel.node_state_store(self.node_root)

    def packet(self, service=SERVICE, payload=None):
        return kernel.build_packet(
            origin_org="Peer", origin_service="peer.org-control",
            destination_org=ORGANIZATION, destination_service=service,
            payload=payload if payload is not None else {"probe": "ping"})


def fixture(case):
    from contextlib import ExitStack
    stack = ExitStack()
    case.addCleanup(stack.close)
    return NodeFixture(stack)


class FederationRoundTripTests(unittest.TestCase):
    def test_a_frame_published_to_a_supplied_mesh_is_found_and_consumed(self):
        node = fixture(self)
        published = kernel.publish_packet(node.packet(), root=node.mesh_root, now_ns=TICK)
        found = kernel.scan_addressed_frames(ORGANIZATION, store=node.mesh)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["frame"], published["frame"])
        result = kernel.ingest_frame(node.node_root, found[0]["frame"])
        self.assertEqual(result["status"], "CONSUMED")
        self.assertEqual(result["execution_result"]["reconstruction"]["status"], "RECONSTRUCTED")
        self.assertEqual([r["kind"] for r in result["execution_result"]["receipts"]],
                         ["INGRESS_ACCEPTED", "DISPATCHED", "CONSUMED",
                          "RESULT_BOUND", "EGRESS_EMITTED"])

    def test_a_frame_addressed_elsewhere_is_not_returned(self):
        node = fixture(self)
        other = kernel.build_packet(origin_org="Peer", origin_service="peer.org-control",
                                    destination_org="Somewhere-Else",
                                    destination_service="somewhere-else.org-control", payload={})
        kernel.publish_packet(other, root=node.mesh_root, now_ns=TICK)
        self.assertEqual(kernel.scan_addressed_frames(ORGANIZATION, store=node.mesh), [])

    def test_a_consumed_frame_is_not_offered_again(self):
        node = fixture(self)
        kernel.publish_packet(node.packet(), root=node.mesh_root, now_ns=TICK)
        found = kernel.scan_addressed_frames(ORGANIZATION, store=node.mesh)
        result = kernel.ingest_frame(node.node_root, found[0]["frame"])
        kernel.mark_federation_frame_seen(node.node_root, found[0]["path"],
                                         found[0]["frame"], result, store=node.state)
        seen = kernel.federation_seen_frame_names(node.node_root, store=node.state)
        self.assertEqual(seen, {found[0]["name"]})
        self.assertEqual(
            kernel.scan_addressed_frames(ORGANIZATION, store=node.mesh, seen=seen), [])

    def test_republishing_the_same_frame_is_idempotent(self):
        node = fixture(self)
        packet = node.packet()
        first = kernel.publish_packet(packet, root=node.mesh_root, now_ns=TICK)
        second = kernel.publish_packet(packet, root=node.mesh_root, now_ns=TICK)
        self.assertEqual(first["path"], second["path"])
        self.assertEqual(len(kernel.scan_addressed_frames(ORGANIZATION, store=node.mesh)), 1)

    def test_a_different_frame_at_a_held_key_fails_closed(self):
        node = fixture(self)
        published = kernel.publish_packet(node.packet(), root=node.mesh_root, now_ns=TICK)
        with self.assertRaises(ValueError) as raised:
            kernel.publish_frame({**published["frame"], "destination_org": "Other"},
                                 store=node.mesh)
        self.assertEqual(str(raised.exception), "federation_frame_write_once_collision")


class NodeStateNamespaceTests(unittest.TestCase):
    def test_the_outbox_records_a_published_frame_once(self):
        node = fixture(self)
        published = kernel.publish_packet(node.packet(), root=node.mesh_root, now_ns=TICK)
        first = kernel.persist_outbox(node.node_root, published["frame"], store=node.state)
        second = kernel.persist_outbox(node.node_root, published["frame"], store=node.state)
        self.assertEqual(first, second)
        with self.assertRaises(ValueError) as raised:
            kernel.persist_outbox(node.node_root,
                                  {**published["frame"], "destination_org": "Other"},
                                  store=node.state)
        self.assertEqual(str(raised.exception), "write_once_collision")

    def test_work_intake_is_queued_without_inferring_authority(self):
        node = fixture(self)
        packet = node.packet(service=CONTROL, payload={
            "communication_id": "c-1", "message_class": "ecosystem.work.request",
            "requested_action": "evaluate", "body": {}})
        intake = kernel.persist_work_request(node.node_root, packet, store=node.state)
        self.assertEqual(intake["state"], "QUEUED_FOR_LOCAL_ADMISSION_EVALUATION")
        self.assertIs(intake["execution_authority_inferred"], False)
        record = node.state.get(node_store.intake_key(packet["packet_id"], "c-1"))
        self.assertIs(record["carrier_grants_execution_authority"], False)

    def test_re_queuing_an_identical_intake_is_idempotent_and_a_changed_one_is_not(self):
        node = fixture(self)
        packet = node.packet(service=CONTROL, payload={
            "communication_id": "c-1", "message_class": "ecosystem.work.request", "body": {}})
        first = kernel.persist_work_request(node.node_root, packet, store=node.state)
        again = kernel.persist_work_request(node.node_root, packet, store=node.state)
        self.assertEqual(first["intake_ref"], again["intake_ref"])
        mutated = {**packet, "transition": {**packet["transition"], "reference": "changed"}}
        with self.assertRaises(ValueError) as raised:
            kernel.persist_work_request(node.node_root, mutated, store=node.state)
        self.assertEqual(str(raised.exception), "work_intake_write_once_collision")

    def test_each_node_namespace_stays_in_its_own_prefix(self):
        node = fixture(self)
        published = kernel.publish_packet(node.packet(), root=node.mesh_root, now_ns=TICK)
        found = kernel.scan_addressed_frames(ORGANIZATION, store=node.mesh)
        result = kernel.ingest_frame(node.node_root, found[0]["frame"])
        kernel.persist_outbox(node.node_root, published["frame"], store=node.state)
        kernel.mark_federation_frame_seen(node.node_root, found[0]["path"],
                                         found[0]["frame"], result, store=node.state)
        kernel.persist_work_request(node.node_root, node.packet(
            service=CONTROL, payload={"communication_id": "c-1", "body": {}}), store=node.state)
        for prefix in (node_store.NODE_OUTBOX_PREFIX, node_store.NODE_SEEN_PREFIX,
                       node_store.NODE_INTAKE_PREFIX):
            self.assertEqual(len(node.state.list_prefix(prefix)), 1, prefix)
        self.assertEqual(node.state.list_prefix(node_store.MESH_FRAME_PREFIX), [],
                         "mesh frames must not land in a node's own state")


class LayoutCompatibilityTests(unittest.TestCase):
    """An existing mesh or checkout must resolve to the same documents."""

    def test_a_frame_lands_where_the_kernel_wrote_it_before(self):
        node = fixture(self)
        published = kernel.publish_packet(node.packet(), root=node.mesh_root, now_ns=TICK)
        frame = published["frame"]
        digest = hashlib.sha256(
            (frame["packet_id"] + "|" + frame["frame_sha256"]).encode()).hexdigest()
        self.assertEqual(Path(published["path"]),
                         node.mesh_root / "frames.d" / (digest + ".json"))

    def test_node_documents_land_where_the_kernel_wrote_them_before(self):
        node = fixture(self)
        published = kernel.publish_packet(node.packet(), root=node.mesh_root, now_ns=TICK)
        found = kernel.scan_addressed_frames(ORGANIZATION, store=node.mesh)
        result = kernel.ingest_frame(node.node_root, found[0]["frame"])
        federation = node.node_root / "resident-runtime/federation"
        self.assertEqual(
            kernel.persist_outbox(node.node_root, published["frame"], store=node.state),
            federation / "outbox" / (hashlib.sha256(
                published["frame"]["packet_id"].encode()).hexdigest() + ".json"))
        self.assertEqual(
            kernel.mark_federation_frame_seen(node.node_root, found[0]["path"],
                                              found[0]["frame"], result, store=node.state),
            federation / "seen.d" / (hashlib.sha256(
                found[0]["name"].encode()).hexdigest() + ".json"))

    def test_the_dedup_identity_is_still_the_frame_name(self):
        """A marker written before state was addressed must still suppress."""
        node = fixture(self)
        kernel.publish_packet(node.packet(), root=node.mesh_root, now_ns=TICK)
        found = kernel.scan_addressed_frames(ORGANIZATION, store=node.mesh)
        name = found[0]["name"]
        node.state.put_once(node_store.seen_key(name), {
            "schema_version": "stegverse.federation-frame-consumption.v1",
            "frame_name": name, "status": "CONSUMED"})
        self.assertEqual(
            kernel.scan_addressed_frames(
                ORGANIZATION, store=node.mesh,
                seen=kernel.federation_seen_frame_names(node.node_root, store=node.state)),
            [])


class MeshProvenanceTests(unittest.TestCase):
    """A node that was told where the mesh is can be moved. One that guessed cannot."""

    def test_a_supplied_mesh_is_portable(self):
        node = fixture(self)
        report = kernel.node_state_provenance(node.mesh_root)
        self.assertEqual(report["mesh_provenance"], node_store.SUPPLIED)
        self.assertIs(report["mesh_portable"], True)
        self.assertEqual(report["authority_effect"], "NONE_REPORT_ONLY")

    def test_a_mesh_derived_from_the_home_directory_says_so(self):
        report = kernel.node_state_provenance(env={})
        self.assertEqual(report["mesh_provenance"], node_store.FROM_HOME_DIRECTORY)
        self.assertIs(report["mesh_portable"], False)

    def test_a_mesh_bound_from_the_environment_says_so(self):
        report = kernel.node_state_provenance(
            env={kernel.FEDERATION_ROOT_ENV: "/tmp/stegverse-mesh"})
        self.assertEqual(report["mesh_provenance"], node_store.FROM_ENVIRONMENT)
        self.assertIs(report["mesh_portable"], False)

    def test_resolving_the_root_returns_the_provenance_with_it(self):
        """Discarding the provenance is what made the dependency invisible."""
        path, provenance = kernel.resolve_federation_root({})
        self.assertEqual(provenance, node_store.FROM_HOME_DIRECTORY)
        self.assertEqual(kernel.federation_root({}), path)


if __name__ == "__main__":
    unittest.main()
