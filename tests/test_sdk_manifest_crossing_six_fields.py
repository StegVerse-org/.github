"""D6: every non-ALLOW crossing result carries the six fields.

`sdk_manifest_crossing.cross` used to refuse with a bare `SystemExit` code and
return a far-side result with no repair, retry or goal. Each refusal now raises
`CrossingRefused` (still a `SystemExit`, same message) carrying the six fields,
and the far-side result carries them inline. An unavailable receiver resolves to
DURABLE_QUEUE_OR_EVENT_EPHEMERAL_MATERIALIZATION; nothing waits or polls.

Stdlib only, like the module under test: no SDK is imported here.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "org-boundary/registry/services.json").read_text(encoding="utf-8"))
MANIFESTS = ROOT / "tests/fixtures/sdk-manifests"
GENESIS = json.loads((ROOT / "tests/fixtures/crossing-standing-genesis.json").read_text(encoding="utf-8"))
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


crossing = _load("sdk_manifest_crossing_six_fields", "resident-runtime/sdk_manifest_crossing.py")
d6 = _load("d6_far_side_registry", "tests/fixtures/d6_far_side_registry.py")


def manifest(name="unadmitted-capability-to-llm-adapter"):
    return json.loads((MANIFESTS / (name + ".json")).read_text(encoding="utf-8"))


class SixFieldAssertions(unittest.TestCase):
    def assert_six_fields(self, carrier):
        for field in SIX_FIELDS:
            self.assertIsInstance(carrier.get(field), str, field)
            self.assertTrue(carrier[field].strip(), field)
        self.assertEqual(carrier["owning_existing_goal"], "INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001")
        self.assertEqual(carrier["retry_entrypoint"], "resident-runtime/sdk_manifest_crossing.py::cross")


class CodeOnlyRefusalsCarrySixFieldsTests(SixFieldAssertions):
    """Each code that used to be a bare SystemExit, triggered through `cross`."""

    def refusal(self, value, *, registry=None, standing=GENESIS):
        with self.assertRaises(SystemExit) as raised:
            crossing.cross(value, registry=REGISTRY if registry is None else registry,
                           standing=standing, packet_id="d6-refusal")
        self.assertIsInstance(raised.exception, crossing.CrossingRefused)
        return raised.exception

    def egress(self, **changes):
        value = manifest()
        egress = dict(value["completion"]["egress"])
        for key, change in changes.items():
            if change is None:
                egress.pop(key, None)
            else:
                egress[key] = change
        value["completion"] = {**value["completion"], "egress": egress}
        return value

    def test_every_declared_refusal_code_has_a_predicate_and_a_repair(self):
        for code, (predicate, repair) in crossing.REFUSALS.items():
            with self.subTest(code=code):
                fields = crossing.refusal_fields(code, "detail")
                self.assert_six_fields(fields)
                self.assertEqual(fields["failure_code"], code)
                self.assertEqual(fields["failed_predicate"], predicate)
                self.assertIn(repair, fields["required_evidence_or_repair"])

    def test_each_refusal_path_raises_its_own_six_fields(self):
        surface = copy.deepcopy(REGISTRY)
        surface["services"].append({**next(s for s in REGISTRY["services"]
                                           if s["service_id"] == "stegverse-org.boundary-diagnostic"),
                                    "repository": "duplicate"})
        processing = copy.deepcopy(REGISTRY)
        for service in processing["services"]:
            if service["service_id"] in ("stegverse-org.tvc", "stegverse-org.demo-sandbox"):
                service["admits_processing"] = [manifest()["processing"]]
        no_egress = manifest()
        no_egress["completion"] = {key: value for key, value in no_egress["completion"].items()
                                   if key != "egress"}
        diagnostic = manifest("governance-to-boundary-diagnostic")
        diagnostic_processing = {key: value for key, value in diagnostic.items() if key != "processing"}
        cases = {
            "CROSSING_REQUIRES_MATERIALIZED_CAPABILITY_MAP": dict(value=manifest(), registry=[]),
            "MANIFEST_DECLARES_NO_EGRESS": dict(value=no_egress),
            "MANIFEST_DECLARES_NO_TRANSITION_SURFACE": dict(
                value=self.egress(final_stegverse_transition_surface=" ")),
            "MANIFEST_DECLARES_NON_INTR_TRANSPORT": dict(value=self.egress(transport="HTTP")),
            "MANIFEST_DECLARES_NO_FAR_SIDE_REQUIREMENT": dict(
                value=self.egress(far_side_transition_required=None)),
            "ORG_EXPOSES_NO_SUCH_TRANSITION_SURFACE": dict(
                value={**self.egress(final_stegverse_transition_surface="NO_SUCH_SURFACE"),
                       "processing": {"capability": "none", "route_id": "none"}}),
            "TRANSITION_SURFACE_AMBIGUOUS_IN_REGISTRY": dict(value=diagnostic_processing, registry=surface),
            "PROCESSING_AMBIGUOUS_IN_REGISTRY": dict(value=manifest(), registry=processing),
            "CROSSING_REQUIRES_DECLARED_STANDING": dict(value=manifest(), standing=None),
            "CROSSING_STANDING_MUST_DECLARE_THE_PREDECESSOR_KEY": dict(
                value=manifest(), standing={"mode": "ESTABLISH_GENESIS", "node_ref": "t"}),
        }
        self.assertEqual(set(cases), set(crossing.REFUSALS), "every refusal code is exercised")
        for code, arguments in cases.items():
            with self.subTest(code=code):
                exc = self.refusal(arguments.pop("value"), **arguments)
                self.assertEqual(exc.code, code)
                self.assertTrue(str(exc).startswith(code), str(exc))
                self.assert_six_fields(exc.refusal)
                self.assertEqual(exc.refusal["failure_code"], code)

    def test_the_cli_still_exits_with_the_code_it_always_had(self):
        exc = self.refusal(self.egress(transport="HTTP"))
        self.assertEqual(str(exc), "MANIFEST_DECLARES_NON_INTR_TRANSPORT:HTTP")


class FarSideResultCarriesSixFieldsTests(SixFieldAssertions):
    """The far-side branch (L194-206 at 10d14104), live through the D6 fixture."""

    def run_case(self, case):
        expected = d6.fixture()["cases"][case]
        result = crossing.cross(manifest(), registry=d6.registry_for(case),
                                standing=GENESIS, packet_id="d6-" + case)
        self.assertIs(result["crossing_completed"], False)
        self.assertEqual(result["resolved_service_id"], expected["admit_on_service"])
        self.assertIs(result["endpoint_adapter_installed"], expected["expected_endpoint_adapter_installed"])
        self.assertEqual(result["disposition"], "FAIL_CLOSED")
        self.assert_six_fields(result)
        self.assertEqual(result["failure_code"], expected["expected_failure_code"])
        self.assertEqual(result["failed_predicate"], expected["expected_failed_predicate"])
        self.assertIn(result["far_side_disposition"], result["required_evidence_or_repair"])
        self.assertEqual(result["receiver_unavailable_disposition"],
                         "DURABLE_QUEUE_OR_EVENT_EPHEMERAL_MATERIALIZATION")
        self.assertIs(result["awaits_the_receiver"], False)
        self.assertEqual(result["authority_effect"], "NONE_CROSSING_ATTEMPT_ONLY")
        return result, expected

    def test_an_unavailable_receiver_resolves_to_the_durable_queue(self):
        result, expected = self.run_case("receiver-unavailable")
        self.assertTrue(result["next_attempt"].startswith(expected["expected_next_attempt_prefix"]))
        self.assertIn("nothing waits or polls", result["next_attempt"])

    def test_an_installed_adapter_refusing_an_admitted_pair_names_its_refusal(self):
        self.run_case("installed-adapter-refuses")

    def test_the_surface_fallback_far_side_refusal_carries_the_six_fields(self):
        """`cross` keeps its surface fallback; the ingress, not `cross`, applies D7."""
        result = crossing.cross(manifest(), registry=REGISTRY, standing=GENESIS, packet_id="d6-fallback")
        self.assertIs(result["crossing_completed"], False)
        self.assertEqual(result["resolved_service_id"], "stegverse-org.llm-adapter")
        self.assert_six_fields(result)
        self.assertEqual(result["failure_code"], "FAR_SIDE_REFUSED_THE_CROSSING")

    def test_a_completed_crossing_carries_none_of_the_refusal_fields(self):
        result = crossing.cross(manifest("task-registry-disclosure-to-llm-adapter"), registry=REGISTRY,
                                standing=GENESIS, packet_id="d6-allow")
        self.assertIs(result["crossing_completed"], True)
        for field in SIX_FIELDS + ("disposition", "receiver_unavailable_disposition"):
            self.assertNotIn(field, result, field)


if __name__ == "__main__":
    unittest.main()
