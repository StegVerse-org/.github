"""Processing must be selected by the admitted manifest, not by who is addressed.

`SDK-GENERIC-MANIFEST-ECOSYSTEM-INVARIANT-005` completion predicate 5 requires
that "regression tests detect capability/route mismatch and direct
identity-driven routing shortcuts". These are those tests.

Before this suite the boundary had no such detection to regress. It resolved
the registry row for `destination.service` and dispatched on that row's
`boundary_role` and `endpoint_adapter`; `process_boundary.py`, `kernel.py` and
`sdk_manifest_crossing.py` referenced `processing.capability` and
`processing.route_id` exactly zero times between them. Any manifest declaring
any capability was processed by whichever adapter the addressed row named.

Two refusals are asserted here that are easy to mistake for one. A capability
the service does not admit at all is refused. So is a capability the service
*does* admit, declared under a route it does not admit for that capability --
the invariant binds the two, and admitting the halves separately is not
admitting the pair.

What this suite does not assert is that a declared route is installed. The
route table and the capability-to-processor binding belong to
`StegVerse-org/StegVerse-SDK`; this boundary holds no copy and must not grow
one. Each result records that route admissibility was not resolved here, and
these cases assert that record is present, so a passing crossing cannot be read
as the boundary having proven an installed route.

Source validation only. Selection is not admission; nothing here grants
authority.
"""
import importlib.util
import json
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "manifest_selection", ROOT / "org-boundary/runtime/manifest_selection.py")
selection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selection)

KSPEC = importlib.util.spec_from_file_location("org_kernel", ROOT / "org-kernel/kernel.py")
K = importlib.util.module_from_spec(KSPEC)
KSPEC.loader.exec_module(K)

GOVERNANCE_ROUTE = "stegverse.route.canonical-governed.v1"
DIAGNOSTIC_ROUTE = "stegverse.route.ecosystem-diagnostic.v1"

ADAPTER = textwrap.dedent("""
    import argparse, json
    from pathlib import Path
    ap=argparse.ArgumentParser(); ap.add_argument("--envelope"); ap.add_argument("--out"); a=ap.parse_args()
    Path(a.out).write_text(json.dumps({"ok":True}))
""")


def service(**overrides):
    row = {"service_id": "target.endpoint",
           "boundary_role": "INTERNAL_ENDPOINT",
           "endpoint_adapter": "adapter.py"}
    row.update(overrides)
    return row


def manifest(capability, route_id=None, *, wrapped=False):
    processing = {}
    if capability is not None:
        processing["capability"] = capability
    if route_id is not None:
        processing["route_id"] = route_id
    payload = {"processing": processing}
    return {"manifest": payload} if wrapped else payload


class ManifestDeclaredSelectionTests(unittest.TestCase):
    """A declared pair the service admits selects the processing."""

    def test_admitted_capability_and_route_pair_is_manifest_selected(self):
        row = service(admits_processing=[{"capability": "governance", "route_id": GOVERNANCE_ROUTE}])
        result = selection.select_processing(row, manifest("governance", GOVERNANCE_ROUTE))
        self.assertEqual(result["processing_selection"], "MANIFEST_DECLARED")
        self.assertEqual(result["declared_capability"], "governance")
        self.assertEqual(result["declared_route_id"], GOVERNANCE_ROUTE)
        self.assertIs(result["declared_capability_processed"], True)

    def test_a_manifest_nested_under_manifest_is_read_the_same_way(self):
        """The payload may be a manifest or carry one; neither is privileged."""
        row = service(admits_processing=[{"capability": "governance", "route_id": GOVERNANCE_ROUTE}])
        result = selection.select_processing(row, manifest("governance", GOVERNANCE_ROUTE, wrapped=True))
        self.assertEqual(result["processing_selection"], "MANIFEST_DECLARED")

    def test_selection_never_reports_resolving_route_admissibility(self):
        """Route installation is the SDK's to decide, so a PASS must not imply it."""
        row = service(admits_processing=[{"capability": "governance", "route_id": GOVERNANCE_ROUTE}])
        result = selection.select_processing(row, manifest("governance", GOVERNANCE_ROUTE))
        self.assertEqual(result["route_admissibility"], "NOT_RESOLVED_AT_BOUNDARY_ROUTE_OWNER_IS_SDK")

    def test_whitespace_is_not_a_declaration(self):
        row = service(admits_processing=[{"capability": "governance", "route_id": GOVERNANCE_ROUTE}])
        with self.assertRaises(SystemExit) as raised:
            selection.select_processing(row, manifest("   ", GOVERNANCE_ROUTE))
        self.assertIn("manifest-declares-processing-without-capability", str(raised.exception))


class CapabilityRouteMismatchTests(unittest.TestCase):
    """Predicate 5, first half: capability/route mismatch must be detected."""

    def test_capability_the_service_does_not_admit_is_refused(self):
        row = service(admits_processing=[{"capability": "ecosystem_diagnostic", "route_id": DIAGNOSTIC_ROUTE}])
        with self.assertRaises(SystemExit) as raised:
            selection.select_processing(row, manifest("governance", GOVERNANCE_ROUTE))
        self.assertIn("declared-capability-not-admitted-by-service:governance", str(raised.exception))

    def test_admitted_capability_under_unadmitted_route_is_refused(self):
        """Both names are admitted -- but not as this pair, which is the mismatch.

        This is the case a capability-only check would wave through: the
        capability is genuinely admitted, and the route is genuinely admitted
        for a different capability. Processing the one under the other is the
        route substitution the invariant forbids.
        """
        row = service(admits_processing=[
            {"capability": "governance", "route_id": GOVERNANCE_ROUTE},
            {"capability": "ecosystem_diagnostic", "route_id": DIAGNOSTIC_ROUTE},
        ])
        with self.assertRaises(SystemExit) as raised:
            selection.select_processing(row, manifest("governance", DIAGNOSTIC_ROUTE))
        self.assertIn("declared-capability-route-binding-not-admitted:governance@" + DIAGNOSTIC_ROUTE,
                      str(raised.exception))

    def test_capability_declared_with_no_route_is_refused(self):
        """The owner contract requires a non-empty route_id, so half a pair selects nothing."""
        row = service(admits_processing=[{"capability": "governance", "route_id": GOVERNANCE_ROUTE}])
        with self.assertRaises(SystemExit) as raised:
            selection.select_processing(row, manifest("governance"))
        self.assertIn("manifest-declares-capability-without-route:governance", str(raised.exception))

    def test_service_declaring_no_admitted_processing_admits_nothing(self):
        with self.assertRaises(SystemExit) as raised:
            selection.select_processing(service(), manifest("governance", GOVERNANCE_ROUTE))
        self.assertIn("service-declares-no-admitted-processing:target.endpoint", str(raised.exception))

    def test_a_bare_capability_string_is_not_a_wildcard_route(self):
        """An incomplete admission is refused rather than read as admitting any route."""
        row = service(admits_processing=["governance"])
        with self.assertRaises(SystemExit) as raised:
            selection.select_processing(row, manifest("governance", GOVERNANCE_ROUTE))
        self.assertIn("service-admitted-processing-entry-not-a-binding", str(raised.exception))

    def test_an_admitted_binding_missing_its_route_is_refused(self):
        row = service(admits_processing=[{"capability": "governance"}])
        with self.assertRaises(SystemExit) as raised:
            selection.select_processing(row, manifest("governance", GOVERNANCE_ROUTE))
        self.assertIn("service-admitted-processing-binding-incomplete", str(raised.exception))


class IdentityShortcutDetectionTests(unittest.TestCase):
    """Predicate 5, second half: identity-driven routing shortcuts must be detected."""

    def test_undeclared_processing_on_an_internal_endpoint_is_recorded_as_identity_selected(self):
        row = service(admits_processing=[{"capability": "governance", "route_id": GOVERNANCE_ROUTE}])
        result = selection.select_processing(row, {"request": {"anything": True}})
        self.assertEqual(result["processing_selection"], "IDENTITY_SELECTED_NO_MANIFEST_DECLARATION")
        self.assertEqual(result["identity_selected_by"], "adapter.py")
        self.assertIsNone(result["declared_capability"])
        self.assertIs(result["declared_capability_processed"], False)

    def test_the_shortcut_names_the_adapter_that_selected_instead_of_the_manifest(self):
        """Recording which adapter selected is what makes the shortcut auditable."""
        row = service(endpoint_adapter="resident-runtime/some_adapter.py")
        result = selection.select_processing(row, {"request": {}})
        self.assertEqual(result["identity_selected_by"], "resident-runtime/some_adapter.py")

    def test_an_empty_payload_is_not_treated_as_a_declaration(self):
        for payload in (None, {}, [], "manifest"):
            with self.subTest(payload=payload):
                result = selection.select_processing(service(), payload)
                self.assertEqual(result["processing_selection"], "IDENTITY_SELECTED_NO_MANIFEST_DECLARATION")

    def test_a_malformed_declaration_does_not_fall_through_to_the_shortcut(self):
        """Declaring `processing` badly must fail closed, not quietly become undeclared."""
        with self.assertRaises(SystemExit):
            selection.select_processing(
                service(admits_processing=[]), {"processing": {"route_id": GOVERNANCE_ROUTE}})


class BoundaryLocalSelectionTests(unittest.TestCase):
    """A boundary-local surface is the processor, so it selects nothing."""

    def test_a_declaration_crossing_to_a_diagnostic_is_not_reported_as_processed(self):
        row = {"service_id": "target.diag", "boundary_role": "BOUNDARY_LOCAL_DIAGNOSTIC"}
        result = selection.select_processing(row, manifest("governance", GOVERNANCE_ROUTE))
        self.assertEqual(result["processing_selection"], "BOUNDARY_LOCAL_NO_PROCESSOR_SELECTED")
        self.assertEqual(result["declared_capability"], "governance")
        self.assertIs(result["declared_capability_processed"], False)

    def test_a_boundary_local_surface_is_not_asked_what_it_admits(self):
        """Nothing is selected there, so an absent admission list refuses nothing."""
        row = {"service_id": "target.control", "boundary_role": "BOUNDARY_LOCAL_CONTROL"}
        result = selection.select_processing(row, manifest("governance", GOVERNANCE_ROUTE))
        self.assertEqual(result["processing_selection"], "BOUNDARY_LOCAL_NO_PROCESSOR_SELECTED")


class DispatchRecordsSelectionTests(unittest.TestCase):
    """The record must reach the dispatch result, not stay inside the module."""

    def root(self, row):
        root = Path(tempfile.mkdtemp())
        (root / "org-boundary/registry").mkdir(parents=True)
        (root / "org-boundary/runtime").mkdir(parents=True)
        (root / "org-boundary/registry/services.json").write_text(
            json.dumps({"organization": "Target-Org", "services": [row]}))
        for name in ("process_boundary.py", "manifest_selection.py"):
            shutil.copy2(ROOT / "org-boundary/runtime" / name, root / "org-boundary/runtime" / name)
        self.addCleanup(shutil.rmtree, root)
        return root

    def packet(self, service_id, payload):
        return K.build_packet(origin_org="Source-Org", origin_service="source.sdk",
                              destination_org="Target-Org", destination_service=service_id,
                              payload=payload)

    def test_an_internal_endpoint_result_carries_the_manifest_selection(self):
        row = service(admits_processing=[{"capability": "governance", "route_id": GOVERNANCE_ROUTE}])
        root = self.root(row)
        (root / "adapter.py").write_text(ADAPTER)
        result = K.dispatch(root, self.packet("target.endpoint", manifest("governance", GOVERNANCE_ROUTE)))
        self.assertEqual(result["processing_selection"], "MANIFEST_DECLARED")
        self.assertEqual(result["declared_route_id"], GOVERNANCE_ROUTE)

    def test_an_unadmitted_pair_leaves_no_receipt_chain_at_all(self):
        """A refused crossing must not leave receipts implying it was consumed."""
        row = service(admits_processing=[{"capability": "governance", "route_id": GOVERNANCE_ROUTE}])
        root = self.root(row)
        (root / "adapter.py").write_text(ADAPTER)
        with self.assertRaisesRegex(ValueError, "declared-capability-route-binding-not-admitted"):
            K.dispatch(root, self.packet("target.endpoint", manifest("governance", DIAGNOSTIC_ROUTE)))

    def test_a_diagnostic_result_records_that_nothing_processed_the_declaration(self):
        row = {"service_id": "target.diag", "boundary_role": "BOUNDARY_LOCAL_DIAGNOSTIC"}
        root = self.root(row)
        result = K.dispatch(root, self.packet("target.diag", manifest("governance", GOVERNANCE_ROUTE)))
        self.assertEqual(result["processing_selection"], "BOUNDARY_LOCAL_NO_PROCESSOR_SELECTED")
        self.assertIs(result["declared_capability_processed"], False)
        self.assertEqual(result["application_result"]["echo"], manifest("governance", GOVERNANCE_ROUTE))

    def test_a_root_with_no_selection_module_fails_closed(self):
        """A boundary that cannot say how processing was selected must not dispatch."""
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        (root / "org-boundary/registry").mkdir(parents=True)
        (root / "org-boundary/registry/services.json").write_text(json.dumps(
            {"organization": "Target-Org",
             "services": [{"service_id": "target.diag", "boundary_role": "BOUNDARY_LOCAL_DIAGNOSTIC"}]}))
        with self.assertRaisesRegex(ValueError, "org_boundary_manifest_selection_missing"):
            K.dispatch(root, self.packet("target.diag", {"hello": "world"}))


class LiveRegistryTests(unittest.TestCase):
    """What this organization's own registry currently admits, stated honestly."""

    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads((ROOT / "org-boundary/registry/services.json").read_text())

    def test_no_service_yet_declares_an_admitted_capability_route_binding(self):
        """The current state, asserted so it cannot drift unnoticed.

        No surface in this organization has declared a capability bound to a
        route that it admits. That is the remaining gap, not a passing
        condition: `stegverse-org.llm-adapter` -- the surface the SDK's own
        default manifest declares -- carries neither an endpoint adapter nor an
        admitted binding. When one is declared, this case must be replaced with
        coverage of that binding rather than left asserting a gap that closed.
        """
        declared = [s["service_id"] for s in self.registry["services"]
                    if s.get("admits_processing")]
        self.assertEqual(declared, [])

    def test_any_declared_admission_is_a_complete_binding(self):
        """Holds now by vacuity, and refuses a half-declaration the moment one lands."""
        for row in self.registry["services"]:
            if "admits_processing" not in row:
                continue
            with self.subTest(service=row["service_id"]):
                # Raises on a bare capability string or an incomplete pair.
                selection.admitted_bindings(row)

    def test_no_live_internal_endpoint_silently_admits_everything(self):
        """An INTERNAL_ENDPOINT with no admission list must refuse, not default open."""
        endpoints = [s for s in self.registry["services"]
                     if s.get("boundary_role") == "INTERNAL_ENDPOINT"]
        self.assertTrue(endpoints, "registry exposes no internal endpoint")
        for row in endpoints:
            with self.subTest(service=row["service_id"]):
                with self.assertRaises(SystemExit):
                    selection.select_processing(row, manifest("governance", GOVERNANCE_ROUTE))

    def test_the_boundary_local_surfaces_declare_no_admission_they_never_consult(self):
        """A boundary-local row is the processor; an admission list there is inert."""
        for row in self.registry["services"]:
            if not str(row.get("boundary_role", "")).startswith("BOUNDARY_LOCAL"):
                continue
            with self.subTest(service=row["service_id"]):
                self.assertNotIn("admits_processing", row)


if __name__ == "__main__":
    unittest.main()
