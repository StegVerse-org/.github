"""A crossing this boundary refuses is recorded, not thrown.

Every attempted boundary ends ALLOW, DENY or FAIL_CLOSED, and the disposition is
retained. A refused crossing used to leave `consume_and_respond` by exception:
recorded nowhere, and stopping every frame queued behind it.

- A deterministic refusal (standing, unknown service, undeclared or unadmitted
  processing, no installed adapter) is DENY: recorded at both levels and marked,
  so it is not offered again.
- Anything else (an adapter that failed to execute) is FAIL_CLOSED: recorded at
  both levels with a retry edge, left unmarked, offered again on the next pass,
  and recorded once however many passes see it.
- A crossing refused and later admitted is two transitions, not one.
- A refusal does not stop the frames behind it.

Source validation only. No authority effect is claimed.
"""
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_peer_spec = importlib.util.spec_from_file_location("peer_organization", ROOT / "tests/peer_organization.py")
peers = importlib.util.module_from_spec(_peer_spec)
_peer_spec.loader.exec_module(peers)

PEER = "Refusal-Peer"
CONTROL = "refusal-peer.org-control"
ENDPOINT = "refusal-peer.endpoint"
ROUTE = "stegverse.route.ecosystem-diagnostic.v1"
GENESIS = {"mode": "ESTABLISH_GENESIS", "node_ref": "refusal-test", "predecessor": None}
FAILING_ADAPTER = "raise SystemExit('adapter-unavailable')\n"
WORKING_ADAPTER = ("import argparse, json\nfrom pathlib import Path\n"
                   "ap=argparse.ArgumentParser(); ap.add_argument('--envelope'); ap.add_argument('--out')\n"
                   "a=ap.parse_args(); Path(a.out).write_text(json.dumps({'ok': True}))\n")


def scratch(case):
    path = Path(tempfile.mkdtemp())
    case.addCleanup(shutil.rmtree, path, True)
    return path


class RefusedCrossingTests(unittest.TestCase):
    def setUp(self):
        self.peer = peers.materialize(self, PEER, [
            {"service_id": CONTROL, "repository": PEER + "/.github",
             "boundary_role": "BOUNDARY_LOCAL_CONTROL"},
            {"service_id": ENDPOINT, "repository": PEER + "/.github",
             "boundary_role": "INTERNAL_ENDPOINT", "endpoint_adapter": "adapter.py",
             "endpoint_adapter_disposition": "ALLOW_DECLARED_ADAPTER",
             "admits_processing": [{"capability": "ecosystem_diagnostic", "route_id": ROUTE}]}])
        (self.peer.root / "adapter.py").write_text(FAILING_ADAPTER)
        self.mesh, self.node = scratch(self), scratch(self)
        self.k = self.peer.kernel

    def publish(self, service, payload, standing=GENESIS, packet_id=None):
        packet = self.k.build_packet(origin_org="Origin", origin_service="origin.org-control",
                                     destination_org=PEER, destination_service=service,
                                     payload=payload, standing=standing, packet_id=packet_id)
        self.k.publish_packet(packet, root=self.mesh, epoch=self.k.HB_ANCHOR_EPOCH + 700)
        return packet

    def consume(self):
        return self.peer.consume(mesh_root=self.mesh, node_state_root=self.node)

    def by_class(self, transition_class):
        return [r for r in self.peer.receipts("repo") if r.get("transition_class") == transition_class]

    def offered(self):
        seen = self.k.federation_seen_frame_names(self.peer.root,
                                                  store=self.k.addressed_node_state_store(self.node))
        return self.k.scan_addressed_frames(PEER, root=self.mesh, seen=seen)

    def test_a_standing_refusal_is_recorded_as_deny_and_marked(self):
        broken = dict(GENESIS)
        del broken["predecessor"]
        self.publish(CONTROL, {"message_class": "ecosystem.communication", "communication_id": "r1"},
                     standing=broken, packet_id="refused-1")
        refused, = self.consume()
        self.assertEqual(refused["result"]["status"], "REFUSED")
        self.assertEqual(refused["result"]["disposition"], "DENY")
        self.assertIn("node_standing_refused", refused["result"]["failed_predicate"])
        repository, = self.by_class(self.k.CROSSING_REFUSED_CLASS)
        self.assertEqual(repository["evidence"]["disposition"], "DENY")
        organization, = self.peer.receipts("org")
        self.assertEqual(organization["repo_receipt_sha256"], repository["receipt_sha256"])
        self.assertIsNone(refused["response_publication"])
        self.assertEqual(self.offered(), [])

    def test_undeclared_processing_is_recorded_as_deny(self):
        self.publish(ENDPOINT, {"request": {}}, packet_id="undeclared-1")
        refused, = self.consume()
        self.assertEqual(refused["result"]["disposition"], "DENY")
        self.assertIn("PROCESSING_SELECTED_ONLY_BY_ADMITTED_PROCESSING_CAPABILITY_AND_ROUTE_ID",
                      refused["result"]["failed_predicate"])

    def test_an_adapter_that_fails_to_execute_is_fail_closed_retried_and_recorded_once(self):
        self.publish(ENDPOINT, {"processing": {"capability": "ecosystem_diagnostic", "route_id": ROUTE}},
                     packet_id="adapter-1")
        first, = self.consume()
        self.assertEqual(first["result"]["disposition"], "FAIL_CLOSED")
        self.assertIsNone(first["seen_marker"])
        self.assertEqual(len(self.offered()), 1)
        second, = self.consume()
        self.assertEqual(second["organization_record"], first["organization_record"])
        refused, = self.by_class(self.k.CROSSING_REFUSED_CLASS)
        self.assertEqual(refused["evidence"]["retry_entrypoint"],
                         "org-kernel/kernel.py::consume_and_respond")

    def test_a_crossing_refused_then_admitted_is_two_transitions(self):
        self.publish(ENDPOINT, {"processing": {"capability": "ecosystem_diagnostic", "route_id": ROUTE}},
                     packet_id="adapter-2")
        self.consume()
        (self.peer.root / "adapter.py").write_text(WORKING_ADAPTER)
        admitted, = self.consume()
        self.assertEqual(admitted["result"]["status"], "CONSUMED")
        self.assertEqual(len(self.by_class(self.k.CROSSING_REFUSED_CLASS)), 1)
        self.assertEqual(len(self.by_class(self.k.CROSSING_CONSUMED_CLASS)), 1)
        self.assertEqual(len(self.peer.receipts("org")), 2)
        self.assertEqual(self.offered(), [])

    def test_a_refusal_does_not_stop_the_frames_behind_it(self):
        self.publish("refusal-peer.not-registered", {"x": 1}, packet_id="unknown-1")
        self.publish(CONTROL, {"message_class": "ecosystem.communication", "communication_id": "ok"},
                     packet_id="ok-1")
        results = self.consume()
        statuses = sorted((r["result"].get("packet_id") or r["result"]["packet"]["packet_id"],
                           r["result"]["status"]) for r in results)
        self.assertEqual(statuses, [("ok-1", "CONSUMED"), ("unknown-1", "REFUSED")])
        unknown = next(r for r in results if r["result"]["status"] == "REFUSED")
        self.assertEqual(unknown["result"]["disposition"], "DENY")
        self.assertEqual(len(self.peer.receipts("org")), 2)


if __name__ == "__main__":
    unittest.main()
