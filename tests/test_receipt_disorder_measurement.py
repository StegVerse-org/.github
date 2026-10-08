"""This organization's receipt state, measured against RE's ten disorder classes.

`PO-RE-001` declares what disorder is and `PO-RE-002` admits a repair only if it
lowers the score without increasing any dimension, `hidden_disorder_tolerance`
being zero. Nothing here measured, so neither obligation could be applied.

All ten classes are observed, and that is the point rather than a detail: an
unobserved dimension is where hidden disorder hides, so a reduction proven over
a subset would admit a repair that fixed one dimension by breaking an unwatched
one. These assert that all ten are measured, that each reports what it counted,
and that the formula is not restated here -- RE scores.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# A peer is materialized as its own organization: its own kernel, emitters and
# ledgers. See tests/peer_organization.py.
_peer_spec = importlib.util.spec_from_file_location("peer_organization", ROOT / "tests/peer_organization.py")
peers = importlib.util.module_from_spec(_peer_spec)
_peer_spec.loader.exec_module(peers)
CONTRACT = "docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json"
PEER, PEER_CONTROL = "StegVerse-Labs", "stegverse-labs.org-control"
GENESIS = {"mode": "ESTABLISH_GENESIS", "node_ref": "disorder-test", "predecessor": None}


def _module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


disorder = _module("receipt_disorder_measurement",
                   "resident-runtime/receipt_disorder_measurement.py")
egress = _module("organization_egress_boundary",
                 "resident-runtime/organization_egress_boundary.py")
lineage = _module("receipt_lineage_projection",
                  "resident-runtime/receipt_lineage_projection.py")
repository_ledger = _module("repo_transition_emit", ".stegverse/transition-ledger/emit.py")
ledger_store = _module("ledger_store", "resident-runtime/ledger_store.py")
kernel = egress.kernel


class DisorderMeasurementTests(unittest.TestCase):
    LEDGER_ROOTS = ("STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT")

    def setUp(self):
        self._ledger = tempfile.TemporaryDirectory()
        self._previous = {name: os.environ.get(name) for name in self.LEDGER_ROOTS}
        for name in self.LEDGER_ROOTS:
            os.environ[name] = str(Path(self._ledger.name) / name.lower())
        self.addCleanup(self._restore)
        self.mesh = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.mesh, True)
        # The peer node's own consumption markers and work intake, supplied
        # by the test as a materializer would, never the peer's checkout.
        self.node_state = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.node_state, True)

    def _restore(self):
        for name, previous in self._previous.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
        self._ledger.cleanup()

    def peer_node(self):
        return peers.materialize(self, PEER, [{"service_id": PEER_CONTROL, "repository": PEER + "/.github",
                          "boundary_role": "BOUNDARY_LOCAL_CONTROL"}])

    def append_resolved(self, evidence, transition_id="INBOUND-SUBMISSION"):
        """Append one record that resolved a target, through the ledger's own writer."""
        return repository_ledger.append(
            transition_id, "ORGANIZATION_SDK_MANIFEST_INGRESS",
            "sha256:" + "a" * 64, "sha256:" + "b" * 64, evidence, "NONE", hb_epoch=32)

    def crossing(self, communication_id="disorder-1"):
        """A real inter-organization crossing: emitted, closed, and one refused."""
        emitted = egress.emit(PEER, {"message_class": "ecosystem.communication",
            "communication_id": communication_id, "subject": "disorder",
            "body": {"probe": True}}, standing=GENESIS, mesh_root=self.mesh, hb_epoch=32)
        self.peer_node().consume(mesh_root=self.mesh,
                                   node_state_root=self.node_state)
        egress.close(PEER, emitted["packet_id"], communication_id,
                     mesh_root=self.mesh, hb_epoch=32)
        egress.emit("Not-A-Declared-Peer", {"message_class": "ecosystem.communication",
            "communication_id": communication_id + "-refused", "body": {}},
            standing=GENESIS, mesh_root=self.mesh, hb_epoch=32)
        return emitted

    # --- all ten -----------------------------------------------------------

    def test_all_ten_declared_classes_are_measured(self):
        self.crossing()
        report = disorder.measure()
        self.assertEqual(set(report["classes"]), set(disorder.CLASSES))
        self.assertEqual(report["classes_observed"], 10)
        self.assertIs(report["all_ten_observed"], True)
        self.assertEqual(report["unobserved_dimensions"], [])

    def test_why_all_ten_rather_than_most(self):
        self.crossing()
        report = disorder.measure()
        self.assertIs(report["hidden_disorder_hides_in_an_unobserved_dimension"], True)
        self.assertEqual(sorted(report["observed_dimensions"]), sorted(disorder.CLASSES))

    def test_every_class_reports_what_it_counted(self):
        self.crossing()
        for name, row in disorder.measure()["classes"].items():
            with self.subTest(cls=name):
                self.assertTrue(row["counted"], name)
                self.assertIn("severity", row)
                self.assertGreaterEqual(row["severity"], 0.0)
                self.assertLessEqual(row["severity"], 1.0)
                if row.get("critical_binary"):
                    self.assertIn(row["severity"], (0.0, 1.0))
                    self.assertIn("population", row)
                else:
                    self.assertGreater(row["denominator"], 0, name)

    # --- the one dimension that is not zero --------------------------------

    def test_an_unattested_origin_is_measured_at_one(self):
        """Every inter-organization crossing's origin is asserted and unverified."""
        self.crossing()
        row = disorder.measure()["classes"]["unresolved_actor_identity"]
        self.assertEqual(row["severity"], 1.0)
        self.assertEqual(row["numerator"], row["denominator"])
        self.assertGreater(row["denominator"], 0)

    def test_the_far_side_reconstruction_measures_no_replay_divergence(self):
        """Recomputed terminal receipts agree, so the replay steps do not diverge."""
        self.crossing()
        row = disorder.measure()["classes"]["replay_divergence"]
        self.assertEqual(row["severity"], 0.0)
        self.assertEqual(row["denominator"], len(egress.FAR_SIDE_RECEIPT_KINDS))

    def test_a_closure_record_is_not_counted_as_an_ambiguous_target(self):
        """The population is records that resolved a destination, not every crossing.

        Taking every record that crossed a boundary counted a closure record as
        ambiguous for not repeating the resolution its emission already holds --
        a measurement artifact reported as disorder.
        """
        self.crossing()
        classes = disorder.measure()["classes"]
        self.assertEqual(classes["target_or_scope_ambiguity"]["severity"], 0.0)
        self.assertEqual(classes["policy_or_delegation_mismatch"]["severity"], 0.0)
        # One emission resolved a destination; the closure and the refusal did not.
        self.assertEqual(classes["target_or_scope_ambiguity"]["denominator"],
                         len(disorder.TARGET_SCOPE_FIELDS[disorder.PEER_DIRECTORY]))
        self.assertEqual(classes["policy_or_delegation_mismatch"]["denominator"], 3)

    def test_an_inbound_resolution_is_measured_against_the_overlay_not_the_directory(self):
        """Two resolution surfaces exist and they are not interchangeable.

        An inbound submission resolves a receiving operation from the capability
        overlay. It carries no peer address because it addressed no peer, and it
        is not mis-delegated for having resolved through the overlay. Measuring
        it against the peer directory's fields scored both classes 1.0 on every
        manifest submission -- a false finding, and the normal lane now that a
        bound capability has an address.
        """
        self.crossing()
        ingress = {
            "receiving_operation": "ORGANIZATION_SDK_MANIFEST_INGRESS",
            "profile_id": "sdk-manifest-ingress",
            "operation": "SUBMIT_MANIFEST",
            "processing_capability": "ecosystem_diagnostic",
            "route_id": "stegverse.route.ecosystem-diagnostic.v1",
            "destination_resolution_source": disorder.CAPABILITY_OVERLAY,
        }
        self.append_resolved(ingress)
        classes = disorder.measure()["classes"]
        self.assertEqual(classes["target_or_scope_ambiguity"]["severity"], 0.0)
        self.assertEqual(classes["policy_or_delegation_mismatch"]["severity"], 0.0)
        # Measured, not skipped: both populations grew by this record.
        self.assertEqual(
            classes["target_or_scope_ambiguity"]["denominator"],
            len(disorder.TARGET_SCOPE_FIELDS[disorder.PEER_DIRECTORY])
            + len(disorder.TARGET_SCOPE_FIELDS[disorder.CAPABILITY_OVERLAY]))
        self.assertEqual(classes["policy_or_delegation_mismatch"]["denominator"], 6)

    def test_a_resolution_through_an_undeclared_surface_is_a_finding(self):
        """Not an exemption: it resolved a target against something nothing declares."""
        self.crossing()
        self.append_resolved({"destination_resolution_source": "SOMEWHERE_UNDECLARED"})
        classes = disorder.measure()["classes"]
        self.assertGreater(classes["target_or_scope_ambiguity"]["severity"], 0.0)
        self.assertGreater(classes["policy_or_delegation_mismatch"]["severity"], 0.0)

    def test_a_submission_received_on_an_unbound_operation_is_a_mismatch(self):
        """The overlay is the delegation, so the bound operation is the only one."""
        self.crossing()
        self.append_resolved({
            "receiving_operation": "SOME_OTHER_OPERATION",
            "profile_id": "sdk-manifest-ingress",
            "operation": "SUBMIT_MANIFEST",
            "processing_capability": "ecosystem_diagnostic",
            "route_id": "stegverse.route.ecosystem-diagnostic.v1",
            "destination_resolution_source": disorder.CAPABILITY_OVERLAY,
        })
        classes = disorder.measure()["classes"]
        self.assertGreater(classes["policy_or_delegation_mismatch"]["severity"], 0.0)
        # The target fields are all present, so only the delegation is wrong.
        self.assertEqual(classes["target_or_scope_ambiguity"]["severity"], 0.0)

    # --- the measurements that catch real damage ---------------------------

    def test_a_receipt_that_does_not_recompute_is_conflicting_evidence(self):
        self.crossing()
        root = Path(os.environ["STEGVERSE_REPO_LEDGER_ROOT"])
        store = ledger_store.PosixLedgerStore(root)
        head = store.get(ledger_store.HEAD_KEY)["receipt_sha256"]
        key = ledger_store.receipt_key(head)
        store.put(key, {**store.get(key), "transition_class": "TAMPERED"})
        # The projection refuses the chain outright, which is the stronger
        # disposition: a measurement of a chain that does not verify would be
        # reporting on evidence it had already found false.
        #
        # Asserted against the class the measurement module actually loaded.
        # Each dynamic module load creates its own module object, so this
        # test's own copy of the projection declares a different
        # LineageRefused and would never match the one raised.
        with self.assertRaises(disorder.lineage.LineageRefused) as refused:
            disorder.measure()
        self.assertIn("RECEIPT_DOES_NOT_VERIFY_AGAINST_ITS_OWN_BODY",
                      str(refused.exception))

    def test_an_orphaned_receipt_is_conflicting_evidence(self):
        """A receipt the store holds that the chain's own HEAD cannot reach."""
        self.crossing()
        root = Path(os.environ["STEGVERSE_REPO_LEDGER_ROOT"])
        store = ledger_store.PosixLedgerStore(root)
        orphan = {"schema": "stegverse.repo-transition-receipt/v1",
                  "repository": "StegVerse-org/.github", "transition_id": "ORPHAN:1",
                  "transition_class": "ORPHAN", "predecessor_state_sha256": "sha256:" + "a" * 64,
                  "successor_state_sha256": "sha256:" + "b" * 64, "evidence": {},
                  "authority_effect": "NONE", "hb_reference": {"epoch": 32},
                  "previous_receipt_sha256": None}
        digest = repository_ledger.sha(orphan)
        store.put(ledger_store.receipt_key(digest), {**orphan, "receipt_sha256": digest})
        row = disorder.measure()["classes"]["conflicting_evidence"]
        self.assertGreater(row["severity"], 0.0)
        self.assertGreaterEqual(row["numerator"], 1)

    def test_a_receipt_asserting_authority_trips_the_critical_binary(self):
        self.crossing()
        root = Path(os.environ["STEGVERSE_REPO_LEDGER_ROOT"])
        store = ledger_store.PosixLedgerStore(root)
        head = store.get(ledger_store.HEAD_KEY)["receipt_sha256"]
        receipt = store.get(ledger_store.receipt_key(head))
        body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
        body["authority_effect"] = "EXECUTION"
        digest = repository_ledger.sha(body)
        store.put(ledger_store.receipt_key(digest), {**body, "receipt_sha256": digest})
        store.put(ledger_store.HEAD_KEY, {"repository": body["repository"],
                                          "receipt_sha256": digest})
        row = disorder.measure()["classes"]["sandbox_authority_confusion"]
        self.assertEqual(row["severity"], 1.0)
        self.assertIs(row["critical_binary"], True)

    def test_a_repair_population_that_is_empty_is_observed_at_zero(self):
        """Nothing to be wrong is a measurement, not a gap."""
        self.crossing()
        row = disorder.measure()["classes"]["repair_without_reentry"]
        self.assertEqual(row["severity"], 0.0)
        self.assertEqual(row["population"], 0)
        self.assertIs(row["empty_population_is_an_observation_not_a_gap"], True)
        self.assertIs(row["observed"], True)

    def test_stale_evidence_is_supersession_rather_than_a_clock(self):
        """A correction makes what it corrects no longer current. No window declared."""
        self.crossing()
        before = disorder.measure()["classes"]["stale_evidence"]
        self.assertEqual(before["severity"], 0.0)
        chain = lineage.repository_chain()
        repository_ledger.append(
            "TEST_CORRECTION:1", "TEST_CORRECTION", "sha256:" + "c" * 64,
            "sha256:" + "d" * 64,
            {"n": 1, lineage.CORRECTS_FIELD: chain[0]["receipt_sha256"]},
            "NONE", hb_epoch=32)
        after = disorder.measure()["classes"]["stale_evidence"]
        self.assertGreater(after["severity"], 0.0)
        self.assertEqual(after["numerator"], 1)

    # --- what this does not do ---------------------------------------------

    def test_the_formula_is_not_restated_here(self):
        """RE's contract owns D = sum(weight_i * severity_i) and the thresholds."""
        self.crossing()
        report = disorder.measure()
        self.assertIs(report["formula_is_not_restated_here"], True)
        self.assertIs(report["verdict_is_res_to_give_not_this_measurements"], True)
        for absent in ("score", "posture", "weights", "thresholds", "verdict"):
            self.assertNotIn(absent, report, absent)
        source = (ROOT / "resident-runtime/receipt_disorder_measurement.py").read_text(
            encoding="utf-8")
        for weight in ("0.18", "0.14", "0.12", "0.15", "0.4"):
            self.assertNotIn(weight, source, weight)

    def test_the_severity_map_is_what_res_scorer_consumes(self):
        self.crossing()
        report = disorder.measure()
        self.assertEqual(set(report["severity"]), set(disorder.CLASSES))
        for value in report["severity"].values():
            self.assertIsInstance(value, float)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_the_measurement_grants_nothing(self):
        self.crossing()
        self.assertEqual(disorder.measure()["authority_effect"], "NONE_MEASUREMENT_ONLY")

    def test_measuring_nothing_is_refused(self):
        with self.assertRaises(disorder.MeasurementRefused) as refused:
            disorder.measure()
        self.assertIn("NO_RECEIPTS_TO_MEASURE", str(refused.exception))


if __name__ == "__main__":
    unittest.main()
