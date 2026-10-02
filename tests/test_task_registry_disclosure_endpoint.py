"""A manifest can ask this organization what it is working on, and get an answer.

Every earlier crossing in this repository either reached a boundary-local
diagnostic, which echoes and processes no declared capability, or was refused
because the addressed service admitted no processing at all. So nothing had
ever produced `declared_capability_processed: true`: the boundary could
transport a declaration and could refuse one, but no surface served one.

`stegverse-org.llm-adapter` now does. It admits exactly one pair --
`ecosystem_diagnostic` bound to `stegverse.route.ecosystem-diagnostic.v1`
-- and serves the committed task registry with its digest. A reader gets the
current generation rather than a copy pasted into a document, which is the
difference between provenance a machine verifies and provenance a person
mails.

These cases cover the whole path: the declared pair is served, the registry
that crosses back is the committed one by digest, the five-receipt chain
reconstructs, and every neighbouring declaration is refused -- a different
capability, a different route, no declaration at all, and a packet addressed
somewhere else.

Source validation only. Disclosure is not admission; nothing here claims a
task, advances a generation or admits a transition.
"""
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests/fixtures/sdk-manifests/task-registry-disclosure-to-llm-adapter.json"
REGISTRY = ROOT / "orchestration/task-registry.json"
RECEIPT_CHAIN = ["INGRESS_ACCEPTED", "DISPATCHED", "CONSUMED", "RESULT_BOUND", "EGRESS_EMITTED"]

CAPABILITY = "ecosystem_diagnostic"
ROUTE_ID = "stegverse.route.ecosystem-diagnostic.v1"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bridge = load("sdk_manifest_crossing", ROOT / "resident-runtime/sdk_manifest_crossing.py")
endpoint = load("task_registry_disclosure_endpoint",
                ROOT / "resident-runtime/task_registry_disclosure_endpoint.py")


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def payload(capability=CAPABILITY, route_id=ROUTE_ID):
    return {"manifest": {"processing": {"capability": capability, "route_id": route_id}}}


class CrossingServesTheRegistryTests(unittest.TestCase):
    """The end-to-end path, driven over the committed manifest."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text())
        cls.result = bridge.cross(cls.manifest, packet_id="task-registry-disclosure-test")
        cls.served = (cls.result["egress"]["payload"]["execution_result"]["application_result"])

    def test_the_declared_capability_was_actually_processed(self):
        """The assertion nothing in this repository could make before."""
        self.assertIs(self.result["crossing_completed"], True)
        self.assertEqual(self.result["processing_selection"], "MANIFEST_DECLARED")
        self.assertIs(self.result["declared_capability_processed"], True)
        self.assertEqual(self.result["declared_capability"], CAPABILITY)
        self.assertEqual(self.result["declared_route_id"], ROUTE_ID)

    def test_it_reached_the_llm_adapter_surface(self):
        self.assertEqual(self.result["declared_transition_surface"], "LLM_ADAPTER")
        self.assertEqual(self.result["resolved_service_id"], "stegverse-org.llm-adapter")

    def test_the_crossing_reconstructs_with_the_full_receipt_chain(self):
        self.assertIs(self.result["consumed"], True)
        self.assertEqual(self.result["reconstruction"], "RECONSTRUCTED")
        self.assertEqual(self.result["receipts"], RECEIPT_CHAIN)
        self.assertTrue(self.result["terminal_receipt_id"])

    def test_the_registry_that_crossed_back_is_the_committed_one(self):
        """A served registry that is not the committed registry is not disclosure."""
        committed = json.loads(REGISTRY.read_text())
        self.assertEqual(self.served["registry_sha256"], hashlib.sha256(canon(committed)).hexdigest())
        self.assertEqual(self.served["tasks"], committed["tasks"])
        self.assertEqual(self.served["active_goal"], committed["active_goal"])
        self.assertEqual(self.served["task_count"], len(committed["tasks"]))

    def test_it_serves_the_current_generation_not_a_snapshot(self):
        """Read at request time: a changed registry changes what is served."""
        before = self.served["registry_sha256"]
        committed = json.loads(REGISTRY.read_text())
        amended = {**committed, "tasks": committed["tasks"] + [{
            "task_id": "SVORG-DISCLOSURE-PROBE-000", "issue": 999999,
            "title": "probe", "status": "proposed", "workstream": "probe",
            "depends_on": [], "outputs": []}]}
        original = REGISTRY.read_text()
        try:
            REGISTRY.write_text(json.dumps(amended, indent=2) + "\n")
            again = endpoint.disclosure(payload())
        finally:
            REGISTRY.write_text(original)
        self.assertNotEqual(again["registry_sha256"], before)
        self.assertEqual(again["task_count"], self.served["task_count"] + 1)

    def test_the_result_claims_no_authority(self):
        self.assertEqual(self.served["authority_effect"], "NONE_DISCLOSURE_ONLY")
        self.assertIs(self.served["disclosure_is_not_admission"], True)
        self.assertIs(self.served["registry_is_work_intent_truth_not_runtime_proof"], True)
        self.assertEqual(self.result["authority_effect"], "NONE")

    def test_the_boundary_still_does_not_claim_it_resolved_the_route(self):
        self.assertEqual(self.result["route_admissibility"],
                         "NOT_RESOLVED_AT_BOUNDARY_ROUTE_OWNER_IS_SDK")


class OnlyTheDeclaredPairIsServedTests(unittest.TestCase):
    """An adapter that serves any capability selects its own processing."""

    def test_a_different_capability_is_refused(self):
        with self.assertRaises(SystemExit) as raised:
            endpoint.disclosure(payload(capability="governance"))
        self.assertIn("not-the-declared-capability:governance", str(raised.exception))

    def test_a_different_route_is_refused(self):
        with self.assertRaises(SystemExit) as raised:
            endpoint.disclosure(payload(route_id="stegverse.route.canonical-governed.v1"))
        self.assertIn("not-the-declared-route", str(raised.exception))

    def test_an_undeclared_payload_is_refused(self):
        """The boundary records identity selection; this surface will not serve it."""
        with self.assertRaises(SystemExit) as raised:
            endpoint.disclosure({"request": {"anything": True}})
        self.assertIn("requires-a-declared-capability", str(raised.exception))

    def test_a_declaration_nested_directly_in_the_payload_is_read(self):
        served = endpoint.disclosure({"processing": {"capability": CAPABILITY, "route_id": ROUTE_ID}})
        self.assertEqual(served["served_capability"], CAPABILITY)


class RegistryBindingTests(unittest.TestCase):
    """What the service row declares must be what the adapter serves."""

    @classmethod
    def setUpClass(cls):
        registry = json.loads((ROOT / "org-boundary/registry/services.json").read_text())
        cls.row = next(s for s in registry["services"]
                       if s["service_id"] == "stegverse-org.llm-adapter")

    def test_the_row_admits_exactly_the_pair_the_adapter_serves(self):
        self.assertEqual(self.row["admits_processing"],
                         [{"capability": CAPABILITY, "route_id": ROUTE_ID}])
        self.assertEqual(endpoint.CAPABILITY, CAPABILITY)
        self.assertEqual(endpoint.ROUTE_ID, ROUTE_ID)

    def test_the_row_names_this_adapter(self):
        self.assertEqual(self.row["endpoint_adapter"],
                         "resident-runtime/task_registry_disclosure_endpoint.py")
        self.assertTrue((ROOT / self.row["endpoint_adapter"]).is_file())

    def test_the_manifest_declares_the_pair_the_row_admits(self):
        manifest = json.loads(MANIFEST.read_text())
        self.assertEqual(manifest["processing"],
                         {"capability": CAPABILITY, "route_id": ROUTE_ID})
        self.assertEqual(manifest["completion"]["egress"]["final_stegverse_transition_surface"],
                         "LLM_ADAPTER")


if __name__ == "__main__":
    unittest.main()
