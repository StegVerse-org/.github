"""D7: a state-transition route with no declared processing service fails closed at the ingress.

When the manifest's published route binds
`stegverse.manifest_state_transition_runtime.execute_manifest` and no service's
`admits_processing` names the declared {capability, route_id}, the ingress
refuses it before the crossing could fall back to the `completion.egress`
surface. It is FAIL_CLOSED, stored and returned alike, because the gap is this
organization's missing configuration. Routes bound to another runtime and
manifests that only target the completion return keep the fallback. Every
refusal's disposition is the (failure_code, failed_predicate) row of
REFUSAL_DISPOSITIONS, the same value stored and returned.

The crossing's six fields are passed through by the ingress rather than being
overwritten with its generic predicate.

Ledger roots and the mesh are temporary per test.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

from stegverse import route_resolution

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "org-boundary/registry/services.json").read_text(encoding="utf-8"))
MANIFESTS = ROOT / "tests/fixtures/sdk-manifests"
GENESIS = json.loads((ROOT / "tests/fixtures/crossing-standing-genesis.json").read_text(encoding="utf-8"))
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
D7_CODE = "PROCESSING_SERVICE_NOT_DECLARED_FOR_CONSUMER_ROUTE"
D7_PREDICATE = "CONSUMER_ROUTE_RESOLVES_TO_A_DECLARED_PROCESSING_SERVICE"


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ingress = _load("organization_manifest_ingress_d7", "resident-runtime/organization_manifest_ingress.py")
d6 = _load("d6_far_side_registry_d7", "tests/fixtures/d6_far_side_registry.py")


def manifest(name="unadmitted-capability-to-llm-adapter"):
    return json.loads((MANIFESTS / (name + ".json")).read_text(encoding="utf-8"))


def on_route(value, route_id):
    """The same manifest declaring another published route, exactly as published."""
    published = route_resolution.PUBLISHED_ROUTES[route_id]
    value = copy.deepcopy(value)
    value["extensions"][route_resolution.ROUTE_DECLARATION_EXTENSION] = {
        field: published[field] for field in route_resolution._ROUTE_FIELDS}
    value["processing"] = {"capability": published["processor_capability"], "route_id": route_id}
    return value


class D7IngressTests(unittest.TestCase):
    LEDGER_ROOTS = ("STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT")

    def setUp(self):
        self._work = tempfile.TemporaryDirectory()
        self.addCleanup(self._work.cleanup)
        self.mesh = Path(self._work.name) / "mesh"
        previous = {name: os.environ.get(name) for name in self.LEDGER_ROOTS}
        for name in self.LEDGER_ROOTS:
            os.environ[name] = str(Path(self._work.name) / name.lower())
        self.addCleanup(lambda: [os.environ.pop(n, None) if v is None else os.environ.__setitem__(n, v)
                                 for n, v in previous.items()])

    def receive(self, value, registry=REGISTRY, standing=GENESIS):
        return ingress.receive(value, registry=registry, standing=standing,
                               packet_id="d7-test", hb_epoch=43, mesh_root=self.mesh)

    def receipts(self, variable, schema):
        root = Path(os.environ[variable])
        if not root.exists():
            return []
        return [json.loads(path.read_text(encoding="utf-8")) for path in root.rglob("*.json")
                if json.loads(path.read_text(encoding="utf-8")).get("schema") == schema]

    def refusal_pair(self):
        repository = [r for r in self.receipts("STEGVERSE_REPO_LEDGER_ROOT",
                                               "stegverse.repo-transition-receipt/v1")
                      if r["transition_class"] == ingress.REFUSED_CLASS]
        organization = [r for r in self.receipts("STEGVERSE_ORG_LEDGER_ROOT",
                                                 "stegverse.organization-transition-receipt/v1")
                        if (r.get("boundary_evidence") or {}).get("receiving_operation") == ingress.OPERATION_ID]
        self.assertEqual(len(repository), 1)
        self.assertEqual(len(organization), 1)
        return repository[0], organization[0]

    def test_d7_is_fail_closed_stored_and_returned_alike(self):
        out = self.receive(manifest())
        self.assertEqual(out["disposition"], "FAIL_CLOSED")
        self.assertEqual(out["refusal_stored_disposition"], "FAIL_CLOSED")
        self.assertEqual(out["failure_code"], D7_CODE)
        self.assertEqual(out["failed_predicate"], D7_PREDICATE)
        self.assertEqual(out["owning_existing_goal"], "INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001")
        for field in SIX_FIELDS:
            self.assertTrue(out.get(field), field)
        repository, organization = self.refusal_pair()
        record = repository["evidence"]
        self.assertEqual(record["disposition"], "FAIL_CLOSED")
        self.assertEqual(organization["boundary_evidence"]["disposition"], "FAIL_CLOSED")
        self.assertEqual(organization["boundary_evidence"]["failed_predicate"], D7_PREDICATE)
        for field in SIX_FIELDS:
            self.assertEqual(record[field], out[field], field)
        self.assertEqual(organization["repo_receipt_sha256"], repository["receipt_sha256"])
        self.assertEqual(out["refusal_repository_receipt_sha256"], repository["receipt_sha256"])
        self.assertEqual(out["refusal_organization_receipt_sha256"], organization["receipt_sha256"])

    def test_d7_never_reaches_the_crossing_or_the_egress_surface(self):
        out = self.receive(manifest())
        self.assertNotIn("crossing", out)
        self.assertNotIn("resolved_service_id", out)
        self.assertIs(out["received"], False)
        self.assertIs(out["organization_receipt_observed"], False)
        self.assertIn("completion.egress surface is not used", out["detail"])

    def test_d7_delivers_its_own_six_fields_on_the_calculated_route(self):
        out = self.receive(manifest())
        self.assertIs(out["disposition_delivered"], True)
        frames = list((self.mesh / "frames.d").glob("*.json"))
        self.assertEqual(len(frames), 1)

    def test_an_admitted_pair_far_side_refusal_passes_the_crossing_six_fields_through(self):
        """D6 through the ingress: the crossing's fields; a far side that did not complete is FAIL_CLOSED."""
        for case, expected in d6.fixture()["cases"].items():
            with self.subTest(case=case):
                self.setUp()
                out = self.receive(manifest(), registry=d6.registry_for(case))
                self.assertEqual(out["failure_code"], expected["expected_failure_code"])
                self.assertEqual(out["failed_predicate"], expected["expected_failed_predicate"])
                self.assertEqual(out["retry_entrypoint"], "resident-runtime/sdk_manifest_crossing.py::cross")
                for field in SIX_FIELDS:
                    self.assertEqual(out[field], out["crossing"][field], field)
                self.assertEqual(out["disposition"], "FAIL_CLOSED")
                self.assertEqual(out["refusal_stored_disposition"], "FAIL_CLOSED")
                repository, organization = self.refusal_pair()
                self.assertEqual(repository["evidence"]["disposition"], "FAIL_CLOSED")
                self.assertEqual(organization["boundary_evidence"]["disposition"], "FAIL_CLOSED")
                for field in SIX_FIELDS:
                    self.assertEqual(repository["evidence"][field], out[field], field)

    def test_a_matched_route_is_still_admitted(self):
        out = self.receive(manifest("task-registry-disclosure-to-llm-adapter"))
        self.assertEqual(out["disposition"], "ALLOW", out.get("detail"))

    def test_routes_bound_to_another_runtime_keep_the_surface_fallback(self):
        """native_source_math and customer_local_governance bind no execute_manifest of the state runtime."""
        for route_id in (route_resolution.NATIVE_SOURCE_MATH_ROUTE_ID,
                         route_resolution.CUSTOMER_LOCAL_GOVERNANCE_ROUTE_ID):
            with self.subTest(route_id=route_id):
                value = on_route(manifest(), route_id)
                self.assertNotEqual(route_resolution.route_from_manifest(value)["runtime_binding"],
                                    ingress.STATE_TRANSITION_RUNTIME_BINDING)
                self.assertIsNone(ingress.processing_service_precheck(value, REGISTRY))
                crossed = ingress.crossing_module.cross(value, registry=REGISTRY, standing=GENESIS,
                                                        packet_id="d7-fallback")
                self.assertEqual(crossed["resolved_service_id"], "stegverse-org.llm-adapter")

    def test_a_completion_return_only_manifest_keeps_the_surface_fallback(self):
        value = {key: item for key, item in manifest("governance-to-boundary-diagnostic").items()
                 if key != "processing"}
        self.assertIsNone(ingress.processing_service_precheck(value, REGISTRY))
        crossed = ingress.crossing_module.cross(value, registry=REGISTRY, standing=GENESIS,
                                                packet_id="d7-completion-return")
        self.assertEqual(crossed["resolved_service_id"], "stegverse-org.boundary-diagnostic")

    def test_a_declared_processing_row_clears_d7(self):
        registry = d6.registry_for("installed-adapter-refuses")
        self.assertIsNone(ingress.processing_service_precheck(manifest(), registry))

    def test_the_disposition_table_is_keyed_on_the_code_and_predicate_pair(self):
        """The shared table (d6-predicate-table): DENY for submission defects, FAIL_CLOSED otherwise."""
        generic = ingress.REFUSED_CLASS
        expected = {
            (D7_CODE, D7_PREDICATE): "FAIL_CLOSED",
            (generic, "ORGANIZATION_RESOLVES_ITS_OWN_INGRESS_DESTINATION"): "FAIL_CLOSED",
            (generic, "BOUNDARY_RECEIPT_CHAIN_RECONSTRUCTS_INDEPENDENTLY"): "FAIL_CLOSED",
            ("CROSSING_REQUIRES_MATERIALIZED_CAPABILITY_MAP", "CROSSING_IS_GIVEN_A_MATERIALIZED_CAPABILITY_MAP"): "FAIL_CLOSED",
            ("ORG_EXPOSES_NO_SUCH_TRANSITION_SURFACE", "DECLARED_SURFACE_RESOLVES_TO_EXACTLY_ONE_SERVICE"): "FAIL_CLOSED",
            ("TRANSITION_SURFACE_AMBIGUOUS_IN_REGISTRY", "DECLARED_SURFACE_RESOLVES_TO_EXACTLY_ONE_SERVICE"): "FAIL_CLOSED",
            ("PROCESSING_AMBIGUOUS_IN_REGISTRY", "DECLARED_PROCESSING_PAIR_IS_ADMITTED_BY_AT_MOST_ONE_SERVICE"): "FAIL_CLOSED",
            ("HB_EPOCH_NOT_SUPPLIED", "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH"): "FAIL_CLOSED",
            ("HB_EPOCH_INVALID", "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH"): "FAIL_CLOSED",
            ("FAR_SIDE_RECEIVER_UNAVAILABLE", "RESOLVED_SERVICE_HAS_AN_INSTALLED_ENDPOINT_ADAPTER"): "FAIL_CLOSED",
            ("FAR_SIDE_REFUSED_THE_CROSSING", "ADMITTED_CROSSING_REACHES_ITS_INTERNAL_ENDPOINT"): "FAIL_CLOSED",
            (generic, "CAPABILITY_IS_BOUND_TO_THIS_RECEIVING_OPERATION"): "DENY",
            (generic, "CROSSING_IS_DRIVABLE_FROM_THE_MANIFEST_AS_DECLARED"): "DENY",
            (generic, "ONE_TRANSITION_ID_BINDS_ONE_MANIFEST"): "DENY",
            ("MANIFEST_DECLARES_NO_EGRESS", "MANIFEST_DECLARES_COMPLETION_EGRESS"): "DENY",
            ("MANIFEST_DECLARES_NO_TRANSITION_SURFACE", "MANIFEST_DECLARES_A_FINAL_TRANSITION_SURFACE"): "DENY",
            ("MANIFEST_DECLARES_NON_INTR_TRANSPORT", "MANIFEST_DECLARES_INTERLOCK_INTR_TRANSPORT"): "DENY",
            ("MANIFEST_DECLARES_NO_FAR_SIDE_REQUIREMENT", "MANIFEST_DECLARES_FAR_SIDE_TRANSITION_REQUIREMENT"): "DENY",
            ("CROSSING_REQUIRES_DECLARED_STANDING", "CROSSING_STANDING_IS_DERIVED_FROM_THE_MANIFEST_OR_DECLARED"): "DENY",
            ("CROSSING_STANDING_MUST_DECLARE_THE_PREDECESSOR_KEY", "CROSSING_STANDING_DECLARES_THE_PREDECESSOR_KEY"): "DENY",
        }
        self.assertEqual(ingress.REFUSAL_DISPOSITIONS, expected)
        # Neither half is unique alone: the generic code spans DENY and
        # FAIL_CLOSED rows, and two crossing codes share one predicate.
        self.assertEqual({v for (code, _), v in expected.items() if code == generic}, {"DENY", "FAIL_CLOSED"})
        refusals = ingress.crossing_module.REFUSALS
        self.assertEqual(refusals["ORG_EXPOSES_NO_SUCH_TRANSITION_SURFACE"][0],
                         refusals["TRANSITION_SURFACE_AMBIGUOUS_IN_REGISTRY"][0])
        # Every crossing refusal has its own row, under its own predicate.
        for code, (predicate, *_rest) in refusals.items():
            self.assertIn((code, predicate), expected, code)

    def test_an_undeclared_pair_is_refused_fail_closed_under_its_own_code(self):
        fields = {"failure_code": "MANIFEST_DECLARES_NO_EGRESS", "failed_predicate": "SOME_OTHER_PREDICATE",
                  "required_evidence_or_repair": "repair", "retry_entrypoint": "entry",
                  "owning_existing_goal": "goal", "next_attempt": "next"}
        self.assertIsNone(ingress.refusal_disposition("MANIFEST_DECLARES_NO_EGRESS", "SOME_OTHER_PREDICATE"))
        disposition, out = ingress.declared_refusal(fields)
        self.assertEqual(disposition, "FAIL_CLOSED")
        self.assertEqual(out["failure_code"], "REFUSAL_DISPOSITION_NOT_DECLARED")
        self.assertEqual(out["failed_predicate"], "SOME_OTHER_PREDICATE")
        self.assertEqual(out["undeclared_refusal_failure_code"], "MANIFEST_DECLARES_NO_EGRESS")
        self.assertEqual(out["undeclared_refusal_failed_predicate"], "SOME_OTHER_PREDICATE")
        # Through the ingress: stored and returned alike, with the six fields.
        result = ingress._refused("SOME_OTHER_PREDICATE", "detail", manifest={"not": "a manifest"},
                                  hb_epoch=43, six_fields=fields)
        self.assertEqual(result["disposition"], "FAIL_CLOSED")
        self.assertEqual(result["refusal_stored_disposition"], "FAIL_CLOSED")
        self.assertEqual(result["failure_code"], "REFUSAL_DISPOSITION_NOT_DECLARED")
        repository, _organization = self.refusal_pair()
        self.assertEqual(repository["evidence"]["disposition"], "FAIL_CLOSED")
        self.assertEqual(repository["evidence"]["failure_code"], "REFUSAL_DISPOSITION_NOT_DECLARED")
        self.assertEqual(repository["evidence"]["undeclared_refusal_failure_code"], "MANIFEST_DECLARES_NO_EGRESS")

    def test_an_unresolvable_route_skips_the_precheck_and_the_derivation_refusal_fires(self):
        """Negative D7: no resolvable consumer route, so D7 is not claimed; the SDK derivation refusal stands."""
        value = manifest()
        del value["extensions"][route_resolution.ROUTE_DECLARATION_EXTENSION]
        self.assertIsNone(ingress.processing_service_precheck(value, REGISTRY))
        out = self.receive(value)
        self.assertEqual(out["failure_code"], ingress.REFUSED_CLASS)
        self.assertEqual(out["failed_predicate"], "ORGANIZATION_RESOLVES_ITS_OWN_INGRESS_DESTINATION")
        self.assertNotEqual(out["failed_predicate"], D7_PREDICATE)
        self.assertEqual(out["disposition"], "FAIL_CLOSED")
        self.assertEqual(out["refusal_stored_disposition"], "FAIL_CLOSED")
        for field in SIX_FIELDS:
            self.assertTrue(isinstance(out.get(field), str) and out[field].strip(), field)
        self.assertEqual(out["retry_entrypoint"], "resident-runtime/organization_manifest_ingress.py::receive")
        self.assertIn("ORGANIZATION_RESOLVES_ITS_OWN_INGRESS_DESTINATION", out["required_evidence_or_repair"])
        self.assertNotIn("crossing", out)
        repository, organization = self.refusal_pair()
        self.assertEqual(repository["evidence"]["disposition"], "FAIL_CLOSED")
        self.assertEqual(repository["evidence"]["failed_predicate"], "ORGANIZATION_RESOLVES_ITS_OWN_INGRESS_DESTINATION")
        self.assertEqual(organization["boundary_evidence"]["disposition"], "FAIL_CLOSED")


if __name__ == "__main__":
    unittest.main()
