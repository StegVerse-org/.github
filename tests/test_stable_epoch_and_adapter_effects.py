"""Replayed effects reproduce rather than repeat, and every adapter declares its effect.

The design accepted for SDK-MANIFEST-ECOSYSTEM-TRANSITION-DISPOSITION-001 rests
correctness on two things instead of an exactly-once promise across separate
stores: every effect is either pure or written once under a deterministic key,
and the bytes of a replayed effect are identical. These cases hold both.

- Every registered endpoint adapter declares `endpoint_adapter_effect`. A pure
  adapter writes nothing but its result file; a node-state adapter writes only
  through the write-once store at the supplied node-state root.
- The SV002 response adapter wrote its record under the repository checkout
  with a bare write_text. It now writes once, atomically, at the supplied root,
  and refuses its write when none was supplied.
- A kernel answer is stamped with the epoch of the frame it answers, so
  consuming that frame again builds the same answer frame and publishing it is a
  no-op, not a second answer stamped by the host clock.
- The Master Records submitter took no mesh location, so it could not publish
  since the mesh became supplied-only; it now takes one, and stamps the frame
  with the epoch of the receipt it carries.

Source validation only. No authority effect is claimed.
"""
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "org-boundary/registry/services.json").read_text(encoding="utf-8"))
CONTRACT = "docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json"
GENESIS = {"mode": "ESTABLISH_GENESIS", "node_ref": "test-node", "predecessor": None}
EFFECTS = {"PURE", "NODE_STATE_WRITE_ONCE"}
RESPONSE_ADAPTER = ROOT / "resident-runtime/sdk_self_characterization_response.py"
SUBMITTER = ROOT / "resident-runtime/submit_org_transition_to_master_records.py"

spec = importlib.util.spec_from_file_location("kernel", ROOT / "org-kernel/kernel.py")
kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)

_peer_spec = importlib.util.spec_from_file_location("peer_organization", ROOT / "tests/peer_organization.py")
peers = importlib.util.module_from_spec(_peer_spec)
_peer_spec.loader.exec_module(peers)


def scratch(case):
    path = Path(tempfile.mkdtemp())
    case.addCleanup(shutil.rmtree, path, True)
    return path


class AdapterEffectClassificationTests(unittest.TestCase):
    def adapters(self):
        return [s for s in REGISTRY["services"] if s.get("endpoint_adapter")]

    def test_every_registered_endpoint_adapter_declares_its_effect(self):
        self.assertTrue(self.adapters())
        for service in self.adapters():
            with self.subTest(service=service["service_id"]):
                self.assertIn(service.get("endpoint_adapter_effect"), EFFECTS)

    def test_a_pure_adapter_writes_only_its_result_file(self):
        for service in self.adapters():
            if service["endpoint_adapter_effect"] != "PURE":
                continue
            with self.subTest(service=service["service_id"]):
                source = (ROOT / service["endpoint_adapter"]).read_text(encoding="utf-8")
                self.assertNotIn("put_once", source)
                for line in source.splitlines():
                    if "write_text(" in line or "write_bytes(" in line:
                        self.assertRegex(line, r"\b(args|a)\.out\.write_")
                self.assertIsNone(re.search(r"open\([^)]*['\"][wa]", source))

    def test_a_node_state_adapter_writes_through_the_write_once_store(self):
        for service in self.adapters():
            if service["endpoint_adapter_effect"] != "NODE_STATE_WRITE_ONCE":
                continue
            with self.subTest(service=service["service_id"]):
                source = (ROOT / service["endpoint_adapter"]).read_text(encoding="utf-8")
                self.assertIn("put_once", source)
                self.assertIn("node_state_location_required_from_materializer", source)


class SelfCharacterizationResponseTests(unittest.TestCase):
    def envelope(self, work, execution=None):
        packet = kernel.build_packet(
            origin_org="StegVerse-002", origin_service="stegverse-002.self-characterization",
            destination_org="StegVerse-org", destination_service="stegverse-org.stegverse-sdk",
            payload={"schema": "stegverse.org-endpoint-response/v1",
                     "response_to_packet_id": "request-1",
                     "request_manifest_sha256": "a" * 64,
                     "execution_result": execution or {"service_id": "stegverse-002.self-characterization",
                                                       "result": 1}},
            standing=GENESIS)
        path = work / "envelope.json"
        path.write_text(json.dumps(packet), encoding="utf-8")
        return path

    def run_adapter(self, envelope, out, node_state=None):
        command = [sys.executable, str(RESPONSE_ADAPTER), "--envelope", str(envelope), "--out", str(out)]
        if node_state is not None:
            command += ["--node-state-root", str(node_state)]
        return subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True)

    def test_the_record_is_written_once_at_the_supplied_node_state_only(self):
        work, node = scratch(self), scratch(self)
        checkout_before = sorted(p.name for p in (ROOT / "resident-runtime").iterdir())
        done = self.run_adapter(self.envelope(work), work / "out.json", node)
        self.assertEqual(done.returncode, 0, done.stderr)
        records = list((node / "self-characterization/responses").glob("*.json"))
        self.assertEqual([p.name for p in records], ["a" * 64 + ".json"])
        self.assertFalse((ROOT / "resident-runtime/self-characterization").exists())
        self.assertEqual(sorted(p.name for p in (ROOT / "resident-runtime").iterdir()), checkout_before)
        again = self.run_adapter(self.envelope(work), work / "out2.json", node)
        self.assertEqual(again.returncode, 0, again.stderr)

    def test_a_different_record_for_the_same_manifest_collides(self):
        work, node = scratch(self), scratch(self)
        self.assertEqual(self.run_adapter(self.envelope(work), work / "o.json", node).returncode, 0)
        other = self.envelope(work, {"service_id": "stegverse-002.self-characterization", "result": 2})
        refused = self.run_adapter(other, work / "o2.json", node)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("sdk-response-write-once-collision", refused.stderr)

    def test_without_supplied_node_state_the_write_is_refused(self):
        work = scratch(self)
        refused = self.run_adapter(self.envelope(work), work / "o.json")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("node_state_location_required_from_materializer", refused.stderr)
        self.assertFalse((work / "o.json").exists())

    def test_a_foreign_packet_is_refused_by_name_before_node_state_is_considered(self):
        work = scratch(self)
        packet = json.loads(self.envelope(work).read_text())
        packet["origin"]["org"] = "Someone-Else"
        path = work / "foreign.json"
        path.write_text(json.dumps(packet))
        refused = self.run_adapter(path, work / "o.json")
        self.assertIn("wrong-sdk-response-origin", refused.stderr)


class AnswerEpochTests(unittest.TestCase):
    ORG = "Epoch-Test"
    CONTROL = "epoch-test.org-control"

    def peer(self):
        return peers.materialize(self, self.ORG, [
            {"service_id": self.CONTROL, "repository": self.ORG + "/.github",
             "boundary_role": "BOUNDARY_LOCAL_CONTROL"}])

    def frames(self, mesh):
        return sorted((mesh / "frames.d").glob("*.json"))

    def test_an_answer_carries_the_epoch_of_the_frame_it_answers_and_replays_as_a_no_op(self):
        mesh, peer = scratch(self), self.peer()
        request = kernel.build_packet(
            origin_org="Origin", origin_service="origin.org-control",
            destination_org=self.ORG, destination_service=self.CONTROL,
            payload={"communication_id": "epoch-1", "message_class": "ecosystem.communication",
                     "subject": "s", "body": {}},
            standing=GENESIS)
        epoch = kernel.HB_ANCHOR_EPOCH + 1234
        kernel.publish_packet(request, root=mesh, epoch=epoch)
        first = peer.consume(mesh_root=mesh, node_state_root=scratch(self))
        answer = first[0]["response_publication"]["frame"]
        self.assertEqual(answer["heartbeat_reference"]["epoch"], epoch)
        self.assertIs(answer["heartbeat_reference"].get("derived_from_clock"), False)
        before = self.frames(mesh)
        # A node that lost its consumption marker consumes the frame again.
        again = peer.consume(mesh_root=mesh, node_state_root=scratch(self))
        self.assertEqual(again[0]["response_publication"]["frame"], answer)
        self.assertEqual(self.frames(mesh), before)

    def test_a_monitor_answer_carries_the_frame_epoch_and_replays_as_a_no_op(self):
        """N-CLOCK: the status a monitor answer embeds used to sample the host
        clock, so every re-answer was a different frame and a second answer."""
        mesh, peer = scratch(self), self.peer()
        request = kernel.build_packet(
            origin_org="Origin", origin_service="origin.org-control",
            destination_org=self.ORG, destination_service=self.CONTROL,
            payload={"communication_id": "monitor-1", "message_class": "ecosystem.monitor.request",
                     "subject": "s", "body": {}},
            standing=GENESIS)
        epoch = kernel.HB_ANCHOR_EPOCH + 4321
        kernel.publish_packet(request, root=mesh, epoch=epoch)
        first = peer.consume(mesh_root=mesh, node_state_root=scratch(self))
        status = first[0]["result"]["execution_result"]["application_result"]["monitor_status"]
        self.assertEqual(status["heartbeat_reference"]["epoch"], epoch)
        self.assertIs(status["heartbeat_reference"]["derived_from_clock"], False)
        self.assertNotIn("sampled_unix_ns", status["heartbeat_reference"])
        answer = first[0]["response_publication"]["frame"]
        before = self.frames(mesh)
        again = peer.consume(mesh_root=mesh, node_state_root=scratch(self))
        self.assertEqual(again[0]["response_publication"]["frame"], answer)
        self.assertEqual(self.frames(mesh), before)

    def test_a_local_status_read_is_labelled_as_a_clock_sample(self):
        status = kernel.resident_status(ROOT)
        self.assertIs(status["heartbeat_reference"]["derived_from_clock"], True)
        self.assertEqual(kernel.resident_status(ROOT, epoch=kernel.HB_ANCHOR_EPOCH + 1)
                         ["heartbeat_reference"]["derived_from_clock"], False)


class MasterRecordsSubmitterTests(unittest.TestCase):
    """Master Records records released organization batches downstream; it gates nothing."""

    SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
                  "retry_entrypoint", "owning_existing_goal", "next_attempt")

    @staticmethod
    def sealed(body):
        """An organization receipt as the append returns it: bound by its own digest."""
        canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return {**body, "receipt_sha256": "sha256:" + hashlib.sha256(canon).hexdigest()}

    def chain(self, length, epoch=kernel.HB_ANCHOR_EPOCH + 77):
        receipts, previous = [], None
        for index in range(length):
            receipts.append(self.sealed({
                "schema": "stegverse.organization-transition-receipt/v1",
                "organization": "StegVerse-org", "transition_id": f"T-{index}",
                "previous_receipt_sha256": previous,
                "hb_reference": kernel.hb_reference(epoch=epoch + index)}))
            previous = receipts[-1]["receipt_sha256"]
        return receipts

    def write(self, work, receipts):
        paths = []
        for index, receipt in enumerate(receipts):
            path = work / f"receipt-{index}.json"
            path.write_text(json.dumps(receipt))
            paths.append(path)
        standing = work / "standing.json"
        standing.write_text(json.dumps(GENESIS))
        return paths, standing

    def receipt(self, work):
        paths, standing = self.write(work, self.chain(1))
        return paths[0], standing

    def submit(self, receipts, standing, mesh=None):
        if not isinstance(receipts, list):
            receipts = [receipts]
        command = [sys.executable, str(SUBMITTER)]
        for receipt in receipts:
            command += ["--org-receipt", str(receipt)]
        command += ["--predecessor-ecosystem-state-sha256", "sha256:" + "1" * 64,
                    "--successor-ecosystem-state-sha256", "sha256:" + "2" * 64,
                    "--standing", str(standing)]
        if mesh is not None:
            command += ["--mesh-root", str(mesh)]
        return subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True)

    def published_frames(self, mesh):
        return [json.loads(path.read_text()) for path in (mesh / "frames.d").glob("*.json")] \
            if (mesh / "frames.d").exists() else []

    def assert_downstream_deny(self, completed, failure_code, mesh=None):
        """A failure to release is a six-field DENY that never blocks the organization transition."""
        self.assertEqual(completed.returncode, 3, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["disposition"], "DENY")
        self.assertEqual(result["failure_code"], failure_code)
        for field in self.SIX_FIELDS:
            self.assertTrue(result[field], field)
        self.assertIs(result["organization_transition_blocked"], False)
        self.assertIs(result["master_records_awaited"], False)
        self.assertIs(result["gates_organization_runtime_reality"], False)
        self.assertEqual(result["authority_effect"], "NONE")
        if mesh is not None:
            self.assertEqual(self.published_frames(mesh), [])

    def test_the_same_receipt_submitted_twice_publishes_one_frame_at_its_epoch(self):
        work, mesh = scratch(self), scratch(self)
        receipt, standing = self.receipt(work)
        first = self.submit(receipt, standing, mesh)
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.submit(receipt, standing, mesh)
        self.assertEqual(second.returncode, 0, second.stderr)
        frames = self.published_frames(mesh)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["heartbeat_reference"]["epoch"], kernel.HB_ANCHOR_EPOCH + 77)

    def test_without_a_mesh_location_nothing_is_published(self):
        work = scratch(self)
        receipt, standing = self.receipt(work)
        refused = self.submit(receipt, standing)
        self.assertIn("--mesh-root", refused.stderr)
        self.assert_downstream_deny(refused, "MASTER_RECORDS_RELEASE_MESH_LOCATION_NOT_SUPPLIED")

    def test_a_contiguous_segment_is_released_as_one_batch(self):
        work, mesh = scratch(self), scratch(self)
        receipts = self.chain(3)
        paths, standing = self.write(work, receipts)
        completed = self.submit(paths, standing, mesh)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["receipt_count"], 3)
        self.assertIs(result["organization_transition_blocked"], False)
        self.assertIs(result["master_records_awaited"], False)
        frames = self.published_frames(mesh)
        self.assertEqual(len(frames), 1)
        # Stamped with the segment head's epoch.
        self.assertEqual(frames[0]["heartbeat_reference"]["epoch"], kernel.HB_ANCHOR_EPOCH + 79)
        payload = kernel.recover_packet(frames[0])["payload"]
        self.assertEqual(payload["operation"], "RECORD_RELEASED_ORGANIZATION_BATCH")
        self.assertEqual(payload["recorder_role"], "RELEASED_ORGANIZATION_BATCH_RECEIPT_RECORDER")
        self.assertIs(payload["gates_organization_runtime_reality"], False)
        self.assertIs(payload["awaited_by_organization"], False)
        self.assertEqual(payload["released_batch"]["receipt_count"], 3)
        self.assertEqual(payload["released_batch"]["segment_head_receipt_sha256"], receipts[-1]["receipt_sha256"])

    def test_a_segment_with_a_gap_is_refused(self):
        work, mesh = scratch(self), scratch(self)
        receipts = self.chain(3)
        paths, standing = self.write(work, [receipts[0], receipts[2]])
        self.assert_downstream_deny(self.submit(paths, standing, mesh),
                                    "MASTER_RECORDS_RELEASE_SEGMENT_NOT_CONTIGUOUS", mesh)

    def test_a_receipt_not_as_appended_is_not_released(self):
        work, mesh = scratch(self), scratch(self)
        receipt = self.chain(1)[0]
        receipt["transition_id"] = "ALTERED"
        paths, standing = self.write(work, [receipt])
        self.assert_downstream_deny(self.submit(paths, standing, mesh),
                                    "MASTER_RECORDS_RELEASE_RECEIPT_DIGEST_MISMATCH", mesh)

    def test_a_foreign_receipt_is_refused(self):
        work, mesh = scratch(self), scratch(self)
        receipt = self.chain(1)[0]
        receipt["organization"] = "Elsewhere"
        paths, standing = self.write(work, [self.sealed({k: v for k, v in receipt.items() if k != "receipt_sha256"})])
        self.assert_downstream_deny(self.submit(paths, standing, mesh),
                                    "MASTER_RECORDS_RELEASE_RECEIPT_OWNER_MISMATCH", mesh)

if __name__ == "__main__":
    unittest.main()
