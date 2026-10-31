"""H36: independent negative tests for the receive and close phases of the one-way InTr hop.

INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001 (StegVerse-Labs/.github#2897, StegVerse-org/.github#162).
Evidence class LAB: the destination is ``test_intr_hop``'s fabricated ``Hop-Peer-Fixture`` checkout and every
ledger is a temporary git ref. Each case takes a genuine frame produced by ``send`` (or a genuine answer
produced by ``receive``), changes exactly one field of the recovered packet, re-frames it with the kernel's own
``carrier_frame`` at the supplied epoch (so the frame and packet digests verify and only the predicate under
test can refuse it), and runs the phase in its own process.

Every refusal must be non-ALLOW with the six fields, name the expected predicate, and append nothing to the
refusing side's ledgers.
"""
from __future__ import annotations

import base64
import copy
import gzip
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_intr_hop import (  # noqa: E402  (shared fabricated-peer fixture)
    FIXTURE, FIXTURE_SLUG, ROOT, Side, assert_six_fields, frame_file, registry, slug, stamp_fixture)

_spec = importlib.util.spec_from_file_location("h36_kernel", ROOT / "org-kernel/kernel.py")
kernel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kernel)


def canon(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def decode(text: str) -> dict:
    return json.loads(gzip.decompress(base64.b64decode(text.encode("ascii"))))


def encode(frame: dict) -> str:
    return base64.b64encode(gzip.compress(canon(frame), mtime=0)).decode("ascii")


def reframe(frame_text: str, mutate, epoch: int) -> str:
    """Recover the genuine packet, change one thing, and frame it again exactly as the kernel would."""
    packet = copy.deepcopy(kernel.recover_packet(decode(frame_text)))
    mutate(packet)
    rebuilt = kernel.carrier_frame(packet, epoch=epoch)
    kernel.recover_packet(copy.deepcopy(rebuilt))   # the forged frame is internally consistent
    return encode(rebuilt)


class H36PhaseRefusals(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.home = Path(tempfile.mkdtemp(prefix="intr-hop-h36-"))
        cls.peer_root = stamp_fixture(cls.home / "peer")
        cls.organization = registry(ROOT)["organization"]
        cls.slug = slug(cls.organization)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.home, ignore_errors=True)

    def sides(self, name: str):
        base = self.home / name
        return Side(ROOT, base / "sender"), Side(self.peer_root, base / "destination")

    def sent(self, sender: Side, destination: Side, cid: str, epoch: int) -> dict:
        code, sent = sender.run("send", "--destination-slug", FIXTURE_SLUG, "--communication-id", cid,
                                "--hb-epoch", str(epoch), "--peer-root", str(destination.root))
        self.assertEqual(code, 0, sent)
        return sent

    def refused(self, side: Side, result: tuple[int, dict], predicate: str, before: list) -> None:
        code, body = result
        self.assertNotEqual(code, 0, body)
        assert_six_fields(self, body)
        self.assertEqual(body["failed_predicate"], predicate, body)
        self.assertEqual(side.chain(repository=True), before, "a refusal appended to the ledger")

    # -- receive ---------------------------------------------------------------------------------------------

    def test_receive_refuses_each_misaddressed_or_misclassed_frame(self) -> None:
        cases = (
            ("FRAME_IS_ADDRESSED_TO_THIS_ORGANIZATION",
             lambda p: p["destination"].__setitem__("org", self.organization)),
            ("FRAME_IS_ADDRESSED_TO_THIS_INTR_DESTINATION",
             lambda p: p["destination"].__setitem__("service", FIXTURE_SLUG + ".not-intr-destination")),
            ("FRAME_CROSSED_AN_ORGANIZATION_BOUNDARY",
             lambda p: p["origin"].__setitem__("org", FIXTURE)),
            ("FRAME_CROSSED_AN_ORGANIZATION_BOUNDARY",
             lambda p: p["origin"].__setitem__("org", None)),
            ("FRAME_CARRIES_THE_RESPONDED_REQUEST_CLASS",
             lambda p: p["payload"].__setitem__("message_class", "ecosystem.communication.ack")),
            ("FRAME_CARRIES_THE_RESPONDED_REQUEST_CLASS",
             lambda p: p["payload"].__setitem__("message_class", "ecosystem.other")),
        )
        for i, (predicate, mutate) in enumerate(cases):
            with self.subTest(predicate=predicate, case=i):
                sender, destination = self.sides("recv-%d" % i)
                sent = self.sent(sender, destination, "intr-hop:%s:%s:h36-r%d" % (self.slug, FIXTURE_SLUG, i), 9000)
                forged = reframe(sent["frame"], mutate, 9000)
                result = destination.run("receive", "--frame-file", frame_file(forged),
                                         "--origin-slug", self.slug, "--hb-epoch", "9001")
                self.refused(destination, result, predicate, [])

    def test_receive_refuses_an_undecodable_or_tampered_frame(self) -> None:
        sender, destination = self.sides("recv-bytes")
        sent = self.sent(sender, destination, "intr-hop:%s:%s:h36-bytes" % (self.slug, FIXTURE_SLUG), 9100)
        result = destination.run("receive", "--frame-file", frame_file("not base64 !!"),
                                 "--origin-slug", self.slug, "--hb-epoch", "9101")
        self.refused(destination, result, "FRAME_IS_GZIP_BASE64_JSON", [])
        tampered = decode(sent["frame"])
        tampered["destination_org"] = self.organization          # changed without re-framing
        result = destination.run("receive", "--frame-file", frame_file(encode(tampered)),
                                 "--origin-slug", self.slug, "--hb-epoch", "9101")
        self.refused(destination, result, "FRAME_RECOVERS_TO_ITS_PACKET", [])

    def test_genuine_frame_still_arrives_after_the_refusals(self) -> None:
        sender, destination = self.sides("recv-control")
        sent = self.sent(sender, destination, "intr-hop:%s:%s:h36-ok" % (self.slug, FIXTURE_SLUG), 9200)
        code, arrived = destination.run("receive", "--frame-file", frame_file(sent["frame"]),
                                        "--origin-slug", self.slug, "--hb-epoch", "9201")
        self.assertEqual(code, 0, arrived)
        self.assertEqual([r["transition_class"] for r in destination.chain(repository=True)],
                         ["ORGANIZATION_INTR_DESTINATION_INGRESS"])

    # -- close -----------------------------------------------------------------------------------------------

    def arrived(self, name: str, n: int):
        sender, destination = self.sides(name)
        cid = "intr-hop:%s:%s:h36-c%d" % (self.slug, FIXTURE_SLUG, n)
        sent = self.sent(sender, destination, cid, 9300 + 10 * n)
        code, arrived = destination.run("receive", "--frame-file", frame_file(sent["frame"]),
                                        "--origin-slug", self.slug, "--hb-epoch", str(9301 + 10 * n))
        self.assertEqual(code, 0, arrived)
        return sender, cid, arrived

    def test_close_refuses_each_misdirected_or_misclassed_answer_before_recording(self) -> None:
        cases = (
            ("ANSWER_IS_ADDRESSED_TO_THIS_ORGANIZATION",
             lambda p: p["destination"].__setitem__("org", FIXTURE), None),
            ("ANSWER_CARRIES_THE_RESPONDED_REQUEST_CLASS",
             lambda p: p["payload"].__setitem__("message_class", "ecosystem.communication"), None),
            ("ANSWER_CAME_FROM_THE_DISPATCHED_DESTINATION",
             lambda p: None, "some-other-peer"),
            ("THIS_ORGANIZATION_RECORDED_THE_EMISSION_IT_CLOSES",
             lambda p: p["payload"].setdefault("body", {}).__setitem__("request_packet_id", "pkt-never-emitted"), None),
        )
        for i, (predicate, mutate, slug_override) in enumerate(cases):
            with self.subTest(predicate=predicate):
                sender, cid, arrived = self.arrived("close-%d" % i, i)
                before = sender.chain(repository=True)
                self.assertEqual([r["transition_class"] for r in before], ["ORGANIZATION_EGRESS_EMITTED"])
                answer = reframe(arrived["frame"], mutate, 9302 + 10 * i)
                result = sender.run("close", "--frame-file", frame_file(answer),
                                    "--destination-slug", slug_override or FIXTURE_SLUG,
                                    "--communication-id", cid, "--hb-epoch", str(9302 + 10 * i))
                self.refused(sender, result, predicate, before)

    def test_far_side_refusal_is_recorded_as_a_refused_closure_not_a_closure(self) -> None:
        sender, cid, arrived = self.arrived("close-far-deny", 9)

        def deny(p):
            body = p["payload"].setdefault("body", {})
            body.setdefault("application_result", {}).setdefault("receiving_operation_result", {})["disposition"] = "DENY"
        answer = reframe(arrived["frame"], deny, 9392)
        code, closed = sender.run("close", "--frame-file", frame_file(answer), "--destination-slug", FIXTURE_SLUG,
                                  "--communication-id", cid, "--hb-epoch", "9392")
        self.assertNotEqual(code, 0, closed)
        assert_six_fields(self, closed)
        self.assertIs(closed["closed"], False)
        self.assertIn("FAR_SIDE_INTR_DESTINATION_ACKNOWLEDGED_THIS_COMMUNICATION", closed["closure_findings"])
        classes = [r["transition_class"] for r in sender.chain(repository=True)]
        self.assertEqual(classes[0], "ORGANIZATION_EGRESS_EMITTED")
        self.assertNotIn("ORGANIZATION_EGRESS_CLOSED", classes)


if __name__ == "__main__":
    unittest.main()
