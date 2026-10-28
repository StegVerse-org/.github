"""kernel.hb_reference has no clock-sample path: hb_reference(now_ns=<sample>) is refused.

#196 removed the no-argument clock fallback. This removes the remaining path, where
a caller-sampled now_ns produced derived_from_clock true. Under StegVerse-Labs/.github#3290's
marker vocabulary, a sampled clock value is CLOCK and never a supplied epoch (HB_EPOCH_INVALID),
and no epoch comes from a clock. Receipts and frames are byte-deterministic in the supplied
epoch (#167 comment 6372442705, item 6).
"""
import importlib.util, inspect, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ns_kernel", ROOT / "org-kernel/kernel.py")
kernel = importlib.util.module_from_spec(spec); spec.loader.exec_module(kernel)
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair",
       "retry_entrypoint", "owning_existing_goal", "next_attempt")
SAMPLE = kernel.HB_ANCHOR_UNIX_NS + 40_960_000_000
EPOCH = kernel.HB_ANCHOR_EPOCH + 4096


def packet():
    return {"schema_version": "stegverse.intr.org-boundary.v1", "packet_id": "no-sample-1", "direction": "INGRESS",
            "origin": {"org": "Peer", "service": "peer.boundary-diagnostic"},
            "destination": {"org": "Kernel-Test", "service": "kernel-test.boundary-diagnostic"},
            "carrier": {"kind": "HB_DERIVED", "reference": "canonical"}, "intr_profile": "stegverse.intr.org-boundary.v1",
            "transition": {"reference": "diagnostic", "authority_effect": "NONE"}, "payload": {"probe": "ping"},
            "standing": {"mode": "ESTABLISH_GENESIS", "node_ref": "kernel-test-node", "predecessor": None},
            "evidence": {k: None for k in ("ingress_receipt", "dispatch_receipt", "consumption_receipt",
                                           "egress_receipt", "reconstruction_reference")}}


class NoSamplePathTests(unittest.TestCase):
    def assertSampleRefused(self, caught):
        refusal = caught.exception.refusal
        for field in SIX:
            self.assertTrue(refusal[field], field)
        self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
        self.assertEqual(refusal["failure_code"], "HB_EPOCH_INVALID")
        self.assertEqual(refusal["failed_predicate"], "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH")
        self.assertIs(refusal["consequence_committed"], False)

    def test_a_caller_sample_is_refused_six_field_and_derives_nothing(self):
        for call in (lambda: kernel.hb_reference(SAMPLE), lambda: kernel.hb_reference(now_ns=SAMPLE),
                     lambda: kernel.hb_reference(kernel.HB_ANCHOR_UNIX_NS - 1)):
            with self.assertRaises(kernel.HbEpochSampledClock) as caught:
                call()
            self.assertSampleRefused(caught)

    def test_a_sample_with_an_epoch_is_refused_as_a_sample(self):
        with self.assertRaises(kernel.HbEpochSampledClock) as caught:
            kernel.hb_reference(SAMPLE, epoch=EPOCH)
        self.assertSampleRefused(caught)

    def test_no_reference_carries_derived_from_clock_true(self):
        ref = kernel.hb_reference(epoch=EPOCH)
        self.assertIs(ref["derived_from_clock"], False)
        self.assertNotIn("sampled_unix_ns", ref)
        source = inspect.getsource(kernel.hb_reference)
        self.assertNotIn('"derived_from_clock":True', source)
        self.assertNotIn("sampled_unix_ns", source)

    def test_no_clock_is_read_on_any_path(self):
        with mock.patch.object(kernel, "datetime", wraps=kernel.datetime) as clock:
            for call in (lambda: kernel.hb_reference(SAMPLE), lambda: kernel.hb_reference()):
                with self.assertRaises(ValueError):
                    call()
            kernel.hb_reference(epoch=EPOCH)
        clock.now.assert_not_called()

    def test_frames_are_byte_deterministic_in_the_supplied_epoch(self):
        a, b = kernel.carrier_frame(packet(), epoch=EPOCH), kernel.carrier_frame(packet(), epoch=EPOCH)
        self.assertEqual(kernel.canon(a), kernel.canon(b))
        self.assertNotEqual(a["frame_sha256"], kernel.carrier_frame(packet(), epoch=EPOCH + 1)["frame_sha256"])

    def test_carrier_frame_and_publish_refuse_a_sample_and_write_nothing(self):
        with self.assertRaises(kernel.HbEpochSampledClock):
            kernel.carrier_frame(packet(), now_ns=SAMPLE)
        with tempfile.TemporaryDirectory() as mesh:
            with self.assertRaises(kernel.HbEpochSampledClock):
                kernel.publish_packet(packet(), root=Path(mesh), now_ns=SAMPLE)
            self.assertEqual(list(Path(mesh).rglob("*.json")), [])

    def test_consume_and_respond_refuses_a_sample_before_consuming(self):
        with tempfile.TemporaryDirectory() as work:
            with mock.patch.object(kernel, "addressed_node_state_store") as node_state:
                with self.assertRaises(kernel.HbEpochSampledClock):
                    kernel.consume_and_respond(Path(work), mesh_root=Path(work), node_state_root=Path(work),
                                               now_ns=SAMPLE)
            node_state.assert_not_called()


if __name__ == "__main__":
    unittest.main()
