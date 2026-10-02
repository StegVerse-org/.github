"""Source regressions for the heartbeat reference as an oscillator count.

The heartbeat declares `progression_dependency: OSCILLATOR_ONLY` wherever it
appears -- in the organization boundary contract, in every InTr envelope, and
in the carrier frame itself. The kernel nevertheless derived the epoch by
dividing a wall-clock reading by the heartbeat period, so the host clock was
load-bearing: an NTP step moves or reverses the epoch, two nodes with skewed
clocks assign different epochs to one event, and the sampled nanosecond
reading was hashed into the frame digest, leaving the frame unreproducible.

These tests pin the supplied-tick path, the explicit marking of a
clock-derived reference, and validation of the reference on recovery.

Source validation only. No runtime observation and no authority effect is
claimed.
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("kernel", ROOT / "org-kernel/kernel.py")
kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)

EPOCH = kernel.HB_ANCHOR_EPOCH + 4_096


def packet(packet_id="hb-packet-001"):
    return {
        "schema_version": kernel.PACKET_SCHEMA,
        "packet_id": packet_id,
        "direction": "INGRESS",
        "origin": {"org": "Peer", "service": "peer.boundary-diagnostic"},
        "destination": {"org": "StegVerse-org", "service": "stegverse-org.boundary-diagnostic"},
        "carrier": {"kind": "HB_DERIVED", "reference": "canonical"},
        "intr_profile": kernel.PACKET_SCHEMA,
        "transition": {"reference": "diagnostic", "authority_effect": "NONE"},
        "payload": {"probe": "ping"},
        "evidence": {k: None for k in ("ingress_receipt", "dispatch_receipt",
                                       "consumption_receipt", "egress_receipt",
                                       "reconstruction_reference")},
    }


class SuppliedTickTests(unittest.TestCase):
    def test_a_supplied_epoch_reads_no_clock(self):
        ref = kernel.hb_reference(epoch=EPOCH)
        self.assertEqual(ref["epoch"], EPOCH)
        self.assertEqual(ref["heartbeat_id"], "HB:" + str(EPOCH))
        self.assertIs(ref["derived_from_clock"], False)
        self.assertNotIn("sampled_unix_ns", ref)
        self.assertEqual(ref["progression_dependency"], "OSCILLATOR_ONLY")

    def test_a_clock_derived_reference_says_so(self):
        """Deriving from a host clock is permitted but must never be silent."""
        sample = kernel.HB_ANCHOR_UNIX_NS + 40_960_000_000
        ref = kernel.hb_reference(sample)
        self.assertIs(ref["derived_from_clock"], True)
        self.assertEqual(ref["sampled_unix_ns"], sample)

    def test_a_tick_and_a_sample_are_not_both_accepted(self):
        with self.assertRaises(ValueError):
            kernel.hb_reference(kernel.HB_ANCHOR_UNIX_NS, epoch=EPOCH)

    def test_an_epoch_before_the_anchor_is_refused(self):
        for bad in (kernel.HB_ANCHOR_EPOCH - 1, -1, True, "32", 32.0):
            with self.subTest(repr(bad)):
                with self.assertRaises(ValueError):
                    kernel.hb_reference(epoch=bad)


class FrameReproducibilityTests(unittest.TestCase):
    def test_same_packet_at_same_tick_yields_the_same_frame_digest(self):
        """Replay determinism: the frame digest is recomputable from the packet
        and the tick, with nothing sampled from the environment in between."""
        first = kernel.carrier_frame(packet(), epoch=EPOCH)
        second = kernel.carrier_frame(packet(), epoch=EPOCH)
        self.assertEqual(first["frame_sha256"], second["frame_sha256"])
        self.assertEqual(first, second)

    def test_a_clock_derived_frame_is_not_reproducible(self):
        """States the cost of the fallback rather than hiding it: two samples a
        heartbeat period apart give different frames for the same packet."""
        base = kernel.HB_ANCHOR_UNIX_NS + 40_960_000_000
        first = kernel.carrier_frame(packet(), now_ns=base)
        second = kernel.carrier_frame(packet(), now_ns=base + kernel.HB_PERIOD_NS)
        self.assertNotEqual(first["frame_sha256"], second["frame_sha256"])

    def test_a_different_tick_changes_the_frame(self):
        self.assertNotEqual(
            kernel.carrier_frame(packet(), epoch=EPOCH)["frame_sha256"],
            kernel.carrier_frame(packet(), epoch=EPOCH + 1)["frame_sha256"],
        )

    def test_a_supplied_tick_frame_round_trips(self):
        frame = kernel.carrier_frame(packet(), epoch=EPOCH)
        self.assertEqual(kernel.recover_packet(frame), packet())


class ReferenceValidationTests(unittest.TestCase):
    def _resigned(self, mutate):
        """Re-sign after tampering, so the heartbeat check is what rejects it
        rather than the frame digest."""
        frame = kernel.carrier_frame(packet(), epoch=EPOCH)
        mutate(frame["heartbeat_reference"])
        frame.pop("frame_sha256")
        frame["frame_sha256"] = kernel.sha(frame)
        return frame

    def test_recovery_rejects_an_incoherent_reference_in_a_validly_signed_frame(self):
        cases = {
            "heartbeat_id disagrees with epoch":
                lambda r: r.__setitem__("heartbeat_id", "HB:999999"),
            "generation disagrees with epoch":
                lambda r: r.__setitem__("generation", r["epoch"] + 1),
            "epoch precedes the anchor":
                lambda r: r.update({"epoch": 1, "generation": 1, "heartbeat_id": "HB:1"}),
            "frequency is not the reference frequency":
                lambda r: r.__setitem__("frequency_hz", 50),
            "progression is not oscillator-only":
                lambda r: r.__setitem__("progression_dependency", "WALL_CLOCK"),
        }
        for label, mutate in cases.items():
            with self.subTest(label):
                frame = self._resigned(mutate)
                # the tampering is invisible to the digest checks
                self.assertEqual(frame["frame_sha256"], kernel.sha(
                    {k: v for k, v in frame.items() if k != "frame_sha256"}))
                with self.assertRaises(ValueError):
                    kernel.recover_packet(frame)

    def test_a_missing_reference_is_refused(self):
        frame = kernel.carrier_frame(packet(), epoch=EPOCH)
        del frame["heartbeat_reference"]
        frame.pop("frame_sha256")
        frame["frame_sha256"] = kernel.sha(frame)
        with self.assertRaises(ValueError):
            kernel.recover_packet(frame)


if __name__ == "__main__":
    unittest.main()
