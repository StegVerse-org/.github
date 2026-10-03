"""Source regressions for a complete Interlock/InTr organization crossing.

The transport, the kernel and the boundary processor were each present and each
individually sound, but no test drove a packet the whole way across the
boundary, so the contract between them was never checked. These tests drive
ingress -> execution -> egress through the registry's boundary-local diagnostic
service, which needs no endpoint adapter and writes nothing outside a temporary
directory.

Nothing here claims runtime observation, InTr delivery between live
organizations, or any authority effect.
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSPORT = ROOT / "org-boundary/runtime/intr_transport.py"
RUN_ONCE = ROOT / "resident-runtime/run_once.py"
DIAGNOSTIC = "stegverse-org.boundary-diagnostic"
ORGANIZATION = "StegVerse-org"

spec = importlib.util.spec_from_file_location("intr_transport", TRANSPORT)
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)

# Ingress requires canonical node standing, so a crossing declares its chain
# position. `predecessor` is present and null: explicit genesis, not a default.
GENESIS = {"mode": "ESTABLISH_GENESIS", "node_ref": "test-node", "predecessor": None}

RECEIPT_KINDS = ["INGRESS_ACCEPTED", "DISPATCHED", "CONSUMED", "RESULT_BOUND", "EGRESS_EMITTED"]


def ingress_packet(service=DIAGNOSTIC, packet_id="intr-crossing-001", standing=None):
    envelope = transport.build_ingress(
        {"org": "StegVerse-Labs", "service": "stegverse-labs.org-control"},
        {"org": ORGANIZATION, "service": service},
        {"probe": "crossing"},
        "canonical",
        "intr:transition:" + packet_id,
        packet_id=packet_id,
    )
    if standing is False:
        return envelope
    return {**envelope, "standing": standing or GENESIS}


class CrossingContractTests(unittest.TestCase):
    """The shape the boundary processor requires is enforced at the boundary."""

    def test_endpoints_must_be_objects_carrying_org_and_service(self):
        cases = {
            "origin as bare string": ("origin", "StegVerse-Labs"),
            "destination as bare string": ("destination", ORGANIZATION),
            "destination missing service": ("destination", {"org": ORGANIZATION}),
            "origin missing org": ("origin", {"service": "peer.svc"}),
            "destination service blank": ("destination", {"org": ORGANIZATION, "service": "  "}),
        }
        for label, (key, value) in cases.items():
            with self.subTest(label):
                packet = ingress_packet()
                packet[key] = value
                with self.assertRaises(ValueError):
                    transport.validate_org_crossing(packet, "INGRESS")

    def test_a_wellformed_packet_validates(self):
        self.assertTrue(transport.validate_org_crossing(ingress_packet(), "INGRESS"))

    def test_wrong_direction_and_profile_are_rejected(self):
        self.assertRaises(ValueError, transport.validate_org_crossing, ingress_packet(), "EGRESS")
        packet = ingress_packet()
        packet["intr_profile"] = "stegverse.organization-intr-envelope/v1"
        self.assertRaises(ValueError, transport.validate_org_crossing, packet, "INGRESS")


class CrossingRoundTripTests(unittest.TestCase):
    def _run_once(self, packet, cwd):
        """Drive run_once.py from `cwd` to prove it does not depend on one."""
        with tempfile.TemporaryDirectory() as work:
            ingress = Path(work) / "ingress.json"
            egress = Path(work) / "egress.json"
            ingress.write_text(json.dumps(packet, indent=2, sort_keys=True))
            completed = subprocess.run(
                [sys.executable, str(RUN_ONCE), "--ingress", str(ingress), "--egress", str(egress)],
                cwd=str(cwd), capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 0,
                             "run_once failed from " + str(cwd) + ": " + completed.stderr)
            return json.loads(completed.stdout.splitlines()[-1]), json.loads(egress.read_text())

    def test_ingress_crosses_to_egress_with_a_bound_receipt_chain(self):
        summary, egress = self._run_once(ingress_packet(), ROOT)
        self.assertEqual(summary["status"], "PASS")
        self.assertTrue(summary["consumed"])
        self.assertEqual(summary["reconstruction"], "RECONSTRUCTED")
        self.assertEqual(summary["egress_packet_id"], summary["packet_id"] + ":egress")
        # The egress envelope is itself a valid crossing in the other direction,
        # and reverses the route rather than restating it.
        self.assertTrue(transport.validate_org_crossing(egress, "EGRESS"))
        self.assertEqual(egress["origin"]["org"], ORGANIZATION)
        self.assertEqual(egress["destination"]["org"], "StegVerse-Labs")
        self.assertEqual(egress["payload"]["request_packet_id"], summary["packet_id"])
        for slot in ("ingress_receipt", "dispatch_receipt", "consumption_receipt",
                     "egress_receipt", "reconstruction_reference"):
            self.assertTrue(egress["evidence"][slot], slot + " unbound")

    def test_crossing_does_not_depend_on_the_working_directory(self):
        """run_once.py addressed the boundary processor relatively, so it only
        worked from the repository root."""
        for label, cwd in (("repository root", ROOT), ("resident-runtime", ROOT / "resident-runtime")):
            with self.subTest(label):
                summary, _ = self._run_once(
                    ingress_packet(packet_id="intr-crossing-cwd-" + label.split()[0]), cwd)
                self.assertEqual(summary["status"], "PASS")

    def test_unknown_destination_service_fails_closed(self):
        with tempfile.TemporaryDirectory() as work:
            ingress = Path(work) / "ingress.json"
            ingress.write_text(json.dumps(ingress_packet(service="stegverse-org.not-registered")))
            completed = subprocess.run(
                [sys.executable, str(RUN_ONCE), "--ingress", str(ingress),
                 "--egress", str(Path(work) / "egress.json")],
                cwd=str(ROOT), capture_output=True, text=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse((Path(work) / "egress.json").exists())


class AdapterFailureReportingTests(unittest.TestCase):
    def test_an_adapter_failure_names_its_own_reason(self):
        """The boundary reported one opaque message for every adapter failure,
        which made a routing mismatch indistinguishable from a crash."""
        packet = ingress_packet(service="stegverse-org.stegverse-sdk", packet_id="intr-adapter-001")
        with tempfile.TemporaryDirectory() as work:
            envelope = Path(work) / "envelope.json"
            envelope.write_text(json.dumps(packet))
            completed = subprocess.run(
                [sys.executable, str(ROOT / "org-boundary/runtime/process_boundary.py"),
                 "--envelope", str(envelope), "--out", str(Path(work) / "execution.json")],
                cwd=str(ROOT), capture_output=True, text=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            message = (completed.stderr or "") + (completed.stdout or "")
            self.assertIn("endpoint-adapter-execution-failed", message)
            self.assertIn("wrong-sdk-response-origin", message)


if __name__ == "__main__":
    unittest.main()
