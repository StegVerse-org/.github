"""Every crossing this node consumes is recorded on the organization's ledgers.

N04: the federation cycle consumed and answered control, diagnostic and
internal-endpoint frames, and the kernel minted its own five boundary receipts
for each, but nothing reached the repository or organization ledger. A crossing
consumed and answered left the organization's runtime reality unchanged, while
`organization_scope_rule` requires every state transition occurring within the
organization to emit an organization receipt.

These cases drive the kernel against this organization's own checkout, with the
mesh, node state and both ledger roots supplied, and assert:

- a consumed crossing appends a repository receipt and the organization receipt
  that consumes it, before its answer is published or its frame marked;
- without both ledger locations nothing is consumed: the frame stays in the
  mesh, unanswered and unmarked;
- the emitters are this kernel's own repository's, and a dispatch root that is
  not that repository is refused;
- a failed organization append publishes no answer and writes no marker, and
  the next pass completes the chain once;
- consuming the same frame again returns the receipts already recorded;
- the resident cycle reports a missing ledger location as FAIL_CLOSED with a
  retry edge rather than aborting.

Source validation only. No authority effect is claimed.
"""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENESIS = {"mode": "ESTABLISH_GENESIS", "node_ref": "crossing-test", "predecessor": None}

spec = importlib.util.spec_from_file_location("kernel", ROOT / "org-kernel/kernel.py")
kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)
ORGANIZATION = kernel.load_registry(ROOT)["organization"]
CONTROL = kernel.organization_slug(ORGANIZATION) + ".org-control"


def scratch(case):
    path = Path(tempfile.mkdtemp())
    case.addCleanup(shutil.rmtree, path, True)
    return path


def receipts(root):
    directory = Path(root) / "receipts"
    return [json.loads(p.read_text()) for p in directory.glob("*.json")] if directory.is_dir() else []


class CrossingReceiptTests(unittest.TestCase):
    def setUp(self):
        self.mesh, self.node = scratch(self), scratch(self)
        ledgers = scratch(self)
        self.repo_ledger, self.org_ledger = ledgers / "repo", ledgers / "org"

    def publish(self, communication_id="crossing-1"):
        packet = kernel.build_packet(
            origin_org="Origin", origin_service="origin.org-control",
            destination_org=ORGANIZATION, destination_service=CONTROL,
            payload={"communication_id": communication_id, "message_class": "ecosystem.communication",
                     "subject": "s", "body": {}},
            standing=GENESIS, packet_id=communication_id + ":c")
        return kernel.publish_packet(packet, root=self.mesh, epoch=kernel.HB_ANCHOR_EPOCH + 500)

    def consume(self, **overrides):
        options = {"mesh_root": self.mesh, "node_state_root": self.node,
                   "repo_ledger_root": self.repo_ledger, "org_ledger_root": self.org_ledger}
        options.update(overrides)
        return kernel.consume_and_respond(ROOT, **options)

    def answers(self):
        return kernel.scan_addressed_frames("Origin", root=self.mesh)

    def test_a_consumed_crossing_is_recorded_at_both_levels(self):
        self.publish()
        consumed, = self.consume()
        self.assertEqual(consumed["result"]["status"], "CONSUMED")
        repository, = receipts(self.repo_ledger)
        organization, = receipts(self.org_ledger)
        self.assertEqual(repository["transition_class"], kernel.CROSSING_CONSUMED_CLASS)
        self.assertEqual(repository["evidence"]["packet_id"], "crossing-1:c")
        self.assertEqual(organization["repo_receipt_sha256"], repository["receipt_sha256"])
        self.assertEqual(organization["organization"], ORGANIZATION)
        self.assertEqual(consumed["organization_record"]["organization_receipt_sha256"],
                         organization["receipt_sha256"])
        self.assertEqual(len(self.answers()), 1)

    def test_without_both_ledger_locations_nothing_is_consumed(self):
        self.publish()
        for missing in ("repo_ledger_root", "org_ledger_root"):
            with self.subTest(missing=missing):
                with self.assertRaises(ValueError) as raised:
                    self.consume(**{missing: None})
                self.assertEqual(str(raised.exception), "ledger_location_required_from_materializer")
        self.assertEqual(len(kernel.scan_addressed_frames(ORGANIZATION, root=self.mesh)), 1)
        self.assertEqual(self.answers(), [])
        self.assertEqual(kernel.federation_seen_frame_names(
            ROOT, store=kernel.addressed_node_state_store(self.node)), set())

    def test_a_root_that_is_not_this_kernels_repository_is_refused(self):
        foreign = scratch(self)
        shutil.copytree(ROOT / "org-boundary", foreign / "org-boundary")
        with self.assertRaises(ValueError) as raised:
            kernel.consume_and_respond(foreign, mesh_root=self.mesh, node_state_root=self.node,
                                       repo_ledger_root=self.repo_ledger,
                                       org_ledger_root=self.org_ledger)
        self.assertEqual(str(raised.exception), "dispatch_root_is_not_this_kernels_organization")

    def test_a_failed_organization_append_answers_nothing_and_the_next_pass_completes_once(self):
        self.publish()
        organization_ledger = kernel._own_module(
            "crossing_organization_ledger", "resident-runtime/aggregate_repo_transition.py")
        original = organization_ledger.append
        calls = {"n": 0}

        def fails_once(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise organization_ledger.OrgLedgerAppendRefused("FAIL_CLOSED", "SIMULATED")
            return original(*args, **kwargs)

        organization_ledger.append = fails_once
        self.addCleanup(setattr, organization_ledger, "append", original)
        with self.assertRaises(organization_ledger.OrgLedgerAppendRefused):
            self.consume()
        self.assertEqual(len(receipts(self.repo_ledger)), 1)
        self.assertEqual(receipts(self.org_ledger), [])
        self.assertEqual(self.answers(), [])
        self.assertEqual(kernel.federation_seen_frame_names(
            ROOT, store=kernel.addressed_node_state_store(self.node)), set())

        consumed, = self.consume()
        self.assertEqual(len(receipts(self.repo_ledger)), 1)
        self.assertEqual(len(receipts(self.org_ledger)), 1)
        self.assertEqual(len(self.answers()), 1)
        self.assertIsNotNone(consumed["organization_record"])

    def test_consuming_the_same_frame_again_returns_the_recorded_receipts(self):
        """A node that lost its consumption marker consumes the frame again."""
        self.publish()
        first, = self.consume()
        again, = self.consume(node_state_root=scratch(self))
        self.assertEqual(first["organization_record"], again["organization_record"])
        self.assertEqual(len(receipts(self.repo_ledger)), 1)
        self.assertEqual(len(receipts(self.org_ledger)), 1)
        self.assertEqual(len(self.answers()), 1)

    def test_consume_addressed_frames_holds_the_same_custody(self):
        self.publish()
        with self.assertRaises(ValueError):
            kernel.consume_addressed_frames(ROOT, mesh_root=self.mesh)
        consumed, = kernel.consume_addressed_frames(
            ROOT, mesh_root=self.mesh, repo_ledger_root=self.repo_ledger,
            org_ledger_root=self.org_ledger)
        self.assertIsNotNone(consumed["organization_record"])
        self.assertEqual(len(receipts(self.org_ledger)), 1)


class FederationCycleCustodyTests(unittest.TestCase):
    VARIABLES = ("STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT", "STEGVERSE_REPO_LEDGER_HOME")

    def setUp(self):
        previous = {name: os.environ.pop(name, None) for name in self.VARIABLES}

        def restore():
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        self.addCleanup(restore)
        cspec = importlib.util.spec_from_file_location(
            "federation_cycle_custody", ROOT / "resident-runtime/federation_cycle.py")
        self.cycle = importlib.util.module_from_spec(cspec)
        cspec.loader.exec_module(self.cycle)

    def test_a_cycle_without_ledger_locations_fails_closed_and_consumes_nothing(self):
        mesh, node = scratch(self), scratch(self)
        packet = kernel.build_packet(
            origin_org="Origin", origin_service="origin.org-control",
            destination_org=ORGANIZATION, destination_service=CONTROL,
            payload={"communication_id": "cycle-1", "message_class": "ecosystem.communication",
                     "subject": "s", "body": {}},
            standing=GENESIS)
        kernel.publish_packet(packet, root=mesh, epoch=kernel.HB_ANCHOR_EPOCH + 9)
        report = self.cycle.main(mesh_root=mesh, node_state_root=node)
        self.assertEqual(report["frames_consumed"], 0)
        self.assertEqual(report["consumption"]["disposition"], "FAIL_CLOSED")
        self.assertEqual(report["consumption"]["failed_predicate"],
                         "LEDGER_LOCATION_REQUIRED_FROM_MATERIALIZER")
        self.assertEqual(report["consumption"]["retry_entrypoint"],
                         "resident-runtime/federation_cycle.py::main")
        self.assertEqual(len(kernel.scan_addressed_frames(ORGANIZATION, root=mesh)), 1)

    def test_a_cycle_with_supplied_ledgers_records_what_it_consumed(self):
        mesh, node, ledgers = scratch(self), scratch(self), scratch(self)
        packet = kernel.build_packet(
            origin_org="Origin", origin_service="origin.org-control",
            destination_org=ORGANIZATION, destination_service=CONTROL,
            payload={"communication_id": "cycle-2", "message_class": "ecosystem.communication",
                     "subject": "s", "body": {}},
            standing=GENESIS)
        kernel.publish_packet(packet, root=mesh, epoch=kernel.HB_ANCHOR_EPOCH + 10)
        report = self.cycle.main(mesh_root=mesh, node_state_root=node,
                                 repo_ledger_root=ledgers / "repo", org_ledger_root=ledgers / "org")
        self.assertEqual(report["frames_consumed"], 1)
        self.assertEqual(report["consumption"]["disposition"], "ALLOW")
        self.assertEqual(report["organization_receipts_recorded"], 1)
        self.assertEqual(len(receipts(ledgers / "org")), 1)


if __name__ == "__main__":
    unittest.main()
