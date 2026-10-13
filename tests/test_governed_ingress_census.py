"""Governed-ingress conformance census (StegVerse-org/.github#98), pinned.

Every surface in this repository that admits a manifest, a packet or a request
and produces a disposition is enumerated below, and the invariants the owner's
standing instruction names are asserted against each of them:

* processing capability and route are selected by the admitted manifest, never
  by the addressed row, the adapter, the transport or the environment;
* every attempted transition is dispositioned ALLOW, DENY or FAIL_CLOSED with a
  named failing predicate -- the two observation-only values (PENDING,
  NOTHING_PUBLISHED) appear only where the surface says an absence is not a
  transition;
* no runtime module reads a credential from the environment; an environment
  variable may name a ledger location and nothing else, and a credential that
  is present is a reason to refuse;
* Master Records gates nothing and is awaited by nothing;
* nothing waits on an external machine and nothing stays resident.

The one repair this census made is also pinned here: the governance endpoint
adapter re-read only the capability half of the processing pair, so a
governance manifest declared under a route the overlay does not bind was served
rather than refused, which the sibling task-registry adapter already refused.

Source validation only. Nothing here admits a transition, claims an authentic
runtime transition, or grants any authority.
"""
from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import tokenize
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "org-boundary/registry/services.json").read_text(encoding="utf-8"))
OVERLAY = json.loads((ROOT / "org-runtime/interlock-intr.json").read_text(encoding="utf-8"))
CONTRACT = json.loads((ROOT / "docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json").read_text(encoding="utf-8"))

#: The census: every governed entry surface, with the function that admits.
SURFACES = {
    "org-kernel/kernel.py": ("dispatch", "ingest_recorded", "consume_and_respond"),
    "org-boundary/runtime/process_boundary.py": ("main",),
    "org-boundary/runtime/manifest_selection.py": ("select_processing",),
    "org-boundary/runtime/node_standing.py": ("require",),
    "org-boundary/runtime/capability_ingress.py": ("receive",),
    "resident-runtime/organization_manifest_ingress.py": ("receive",),
    "resident-runtime/sdk_manifest_crossing.py": ("cross",),
    "resident-runtime/governance_endpoint.py": ("main",),
    "resident-runtime/remediation_endpoint.py": ("main", "bind"),
    "resident-runtime/task_registry_disclosure_endpoint.py": ("disclosure",),
    "resident-runtime/workspace_resource_consumer_adapter.py": ("main",),
    "resident-runtime/sdk_self_characterization_response.py": ("main",),
    "resident-runtime/governance_decision_return.py": ("return_decision", "return_on_consumption"),
    "resident-runtime/organization_egress_boundary.py": ("emit", "close"),
    "resident-runtime/peer_mesh_intake.py": ("intake",),
    "resident-runtime/governance_return_cycle.py": ("run",),
    "resident-runtime/federation_cycle.py": ("main",),
    "resident-runtime/submit_org_transition_to_master_records.py": ("release",),
    "resident-runtime/resident_executor.py": ("main",),
    "resident-runtime/run_sv002_self_characterization_roundtrip.py": ("submit",),
    "resident-runtime/sdk_self_characterization_egress.py": ("build_packet",),
    "resident-runtime/propagate_repository_receipts.py": ("propagate",),
    "resident-runtime/aggregate_repo_transition.py": ("append",),
    ".stegverse/transition-ledger/emit.py": ("append",),
}

#: Every runtime module the census scans at source level.
RUNTIME_MODULES = sorted(
    [p for p in (ROOT / "resident-runtime").glob("*.py")]
    + [p for p in (ROOT / "org-kernel").glob("*.py")]
    + [p for p in (ROOT / "org-boundary/runtime").glob("*.py")]
    + [p for p in (ROOT / ".stegverse/transition-ledger").glob("*.py")])

TRANSITION_DISPOSITIONS = {"ALLOW", "DENY", "FAIL_CLOSED"}
#: Observations, not transitions. CLOSURE_ALREADY_RECORDED is a returned answer
#: consumed again under an SDK that no longer reproduces its request: the
#: closure an earlier run recorded is reported, and nothing is appended.
OBSERVATION_DISPOSITIONS = {"PENDING", "NOTHING_PUBLISHED", "CLOSURE_ALREADY_RECORDED"}
#: The only environment variables a runtime module may read by name: each names
#: a ledger location and confers nothing.
LOCATION_VARIABLES = {"STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT",
                      "STEGVERSE_REPO_LEDGER_HOME"}
CREDENTIAL_VARIABLES = {"GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT", "GITHUB_PERSONAL_ACCESS_TOKEN",
                        "ACTIONS_RUNTIME_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "TV_HMAC_SIGNING_KEY"}

GOVERNANCE_ROUTE = "stegverse.route.canonical-governed.v1"
FOREIGN_ROUTE = "stegverse.route.not-bound-anywhere.v1"


def code_text(path):
    """A module's source with docstrings and comments masked, so prose that names a thing is not a read of it."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    masked = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                masked.update(range(body[0].lineno, body[0].end_lineno + 1))
    kept = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT or token.start[0] in masked:
            continue
        kept.append(token.string)
    return " ".join(kept)


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


selection = _load("census_manifest_selection", "org-boundary/runtime/manifest_selection.py")
node_standing = _load("census_node_standing", "org-boundary/runtime/node_standing.py")
kernel = _load("census_kernel", "org-kernel/kernel.py")


def adapter_rows():
    """Registry rows that select a processor and admit a declared pair."""
    return [row for row in REGISTRY["services"]
            if row.get("boundary_role") == "INTERNAL_ENDPOINT"
            and row.get("endpoint_adapter_disposition") == "ALLOW_DECLARED_ADAPTER"
            and row.get("admits_processing")]


def envelope(row, processing):
    """An ingress envelope addressed to `row`, declaring `processing` everywhere an adapter reads it."""
    manifest = {"processing": processing,
                "extensions": {"stegverse_governance_request": {"candidate": {"action": "census"}},
                               # A calculated remediation route entering here, crossing to
                               # StegHealer's organization over InTr egress and ingress.
                               "stegverse_remediation_fork_request": {"remediation_route": {
                                   "entry_organization": "StegVerse-org", "route_sha256": "census",
                                   "steghealer": {"organization": "StegVerse-Labs",
                                                  "service_id": "stegverse-labs.remediation"},
                                   "direct_route_to_steghealer": [
                                       {"from": "StegVerse-org", "to": "StegVerse-Labs",
                                        "crossing": "INTERLOCK_INTR_EGRESS"},
                                       {"from": "StegVerse-org", "to": "StegVerse-Labs",
                                        "crossing": "INTERLOCK_INTR_INGRESS"},
                                       {"from": "StegVerse-Labs", "to": "stegverse-labs.remediation",
                                        "crossing": "INTERNAL_ENDPOINT"}]}}}}
    return {"schema_version": "stegverse.intr.org-boundary.v1", "packet_id": "census-" + row["service_id"],
            "direction": "INGRESS", "origin": {"org": "StegVerse-org", "service": "stegverse-org.census"},
            "destination": {"org": REGISTRY["organization"], "service": row["service_id"]},
            "carrier": {"kind": "HB_DERIVED", "reference": "census"}, "intr_profile": "stegverse.intr.org-boundary.v1",
            "transition": {"reference": "census", "authority_effect": "NONE", "conditions": []},
            "payload": {"processing": processing, "manifest": manifest},
            "evidence": {}}


def run_adapter(row, processing):
    """Invoke the row's adapter the way process_boundary does: envelope in, result file out."""
    with tempfile.TemporaryDirectory() as work:
        envelope_path = Path(work) / "envelope.json"
        out = Path(work) / "out.json"
        envelope_path.write_text(json.dumps(envelope(row, processing)))
        completed = subprocess.run(
            [sys.executable, str(ROOT / row["endpoint_adapter"]), "--envelope", str(envelope_path), "--out", str(out)],
            cwd=ROOT, capture_output=True, text=True, timeout=120)
        return completed, out.is_file()


class CensusEnumerationTests(unittest.TestCase):
    def test_every_censused_surface_exists_and_defines_its_admitting_function(self):
        for relative, functions in SURFACES.items():
            path = ROOT / relative
            with self.subTest(surface=relative):
                self.assertTrue(path.is_file(), relative)
                defined = {node.name for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                           if isinstance(node, ast.FunctionDef)}
                for function in functions:
                    self.assertIn(function, defined, relative + "::" + function)

    def test_every_processing_adapter_in_the_registry_is_censused(self):
        for row in REGISTRY["services"]:
            adapter = row.get("endpoint_adapter")
            if adapter:
                with self.subTest(service=row["service_id"]):
                    self.assertIn(adapter, SURFACES)


class SelectionBasisTests(unittest.TestCase):
    """Processing is selected by the admitted manifest, never by identity."""

    def test_no_registry_row_processes_a_packet_that_declares_nothing(self):
        for row in REGISTRY["services"]:
            with self.subTest(service=row["service_id"]):
                if row.get("boundary_role") == "INTERNAL_ENDPOINT":
                    with self.assertRaises(SystemExit) as refused:
                        selection.select_processing(row, {"schema": "census.undeclared/v1"})
                    self.assertIn(selection.UNDECLARED_REFUSAL, str(refused.exception))
                else:
                    selected = selection.select_processing(row, {"schema": "census.undeclared/v1"})
                    self.assertEqual(selected["processing_selection"], selection.BOUNDARY_LOCAL)
                    self.assertFalse(selected["declared_capability_processed"])

    def test_an_adapter_row_processes_only_the_pair_it_admits(self):
        rows = adapter_rows()
        self.assertTrue(rows, "the registry admits processing on at least one adapter row")
        for row in rows:
            for pair in row["admits_processing"]:
                with self.subTest(service=row["service_id"], pair=pair):
                    selected = selection.select_processing(row, {"processing": dict(pair)})
                    self.assertEqual(selected["processing_selection"], selection.MANIFEST_DECLARED)
                    self.assertTrue(selected["declared_capability_processed"])
                    self.assertEqual(selected["route_admissibility"], selection.ROUTE_ADMISSIBILITY)
                    with self.assertRaises(SystemExit) as refused:
                        selection.select_processing(
                            row, {"processing": {"capability": pair["capability"], "route_id": FOREIGN_ROUTE}})
                    self.assertIn("declared-capability-route-binding-not-admitted", str(refused.exception))

    def test_every_processing_adapter_re_reads_the_pair_it_was_admitted_under(self):
        """An adapter that serves its capability under any route selects half of its own processing."""
        for row in adapter_rows():
            for pair in row["admits_processing"]:
                with self.subTest(service=row["service_id"], pair=pair):
                    served, written = run_adapter(row, dict(pair))
                    self.assertEqual(served.returncode, 0, served.stderr)
                    self.assertTrue(written)
                    refused, written = run_adapter(
                        row, {"capability": pair["capability"], "route_id": FOREIGN_ROUTE})
                    self.assertNotEqual(refused.returncode, 0, "served under an unadmitted route")
                    self.assertFalse(written)
                    self.assertIn("route", refused.stderr.strip().splitlines()[-1])

    def test_the_governance_adapter_refuses_a_route_the_overlay_does_not_bind_by_name(self):
        bindings = {entry["profile_id"]: entry
                    for entry in OVERLAY["egress"]["capability_destination_bindings"]}
        self.assertEqual(bindings["governance"]["route_id"], GOVERNANCE_ROUTE)
        row = next(r for r in REGISTRY["services"] if r["service_id"] == "stegverse-org.governance")
        refused, written = run_adapter(row, {"capability": "governance", "route_id": FOREIGN_ROUTE})
        self.assertNotEqual(refused.returncode, 0)
        self.assertFalse(written)
        self.assertEqual(refused.stderr.strip().splitlines()[-1],
                         "governance-endpoint-received-other-route:" + FOREIGN_ROUTE)
        # The bound route is read from the overlay, not restated in the adapter.
        source = (ROOT / "resident-runtime/governance_endpoint.py").read_text(encoding="utf-8")
        self.assertNotIn(GOVERNANCE_ROUTE, source)


class DispositionVocabularyTests(unittest.TestCase):
    def test_standing_dispositions_are_the_contracts_and_a_refusal_names_one(self):
        self.assertEqual(set(node_standing.dispositions(CONTRACT).values()), TRANSITION_DISPOSITIONS)
        with self.assertRaises(SystemExit) as refused:
            node_standing.require(CONTRACT, {"payload": {}})
        self.assertTrue(str(refused.exception).startswith("node-standing-fail_closed:"), str(refused.exception))

    def test_a_kernel_refusal_is_deny_or_fail_closed_only(self):
        for reason in ("unknown_service", "node_standing_refused:x", "endpoint_adapter_not_installed",
                       "endpoint_adapter_execution_failed:boom", "ledger_receipt_collision"):
            self.assertIn(kernel.refusal_disposition(reason), TRANSITION_DISPOSITIONS - {"ALLOW"}, reason)

    def test_every_disposition_literal_in_runtime_code_is_in_the_vocabulary(self):
        pattern = re.compile(r'"disposition"\s*:\s*"([A-Z_]+)"')
        for path in RUNTIME_MODULES:
            source = path.read_text(encoding="utf-8")
            for value in pattern.findall(source):
                with self.subTest(module=path.relative_to(ROOT).as_posix(), disposition=value):
                    if value in OBSERVATION_DISPOSITIONS:
                        # An observation is not a transition, and the surface says so.
                        self.assertIn("absence_is_not_a_transition", source)
                    else:
                        self.assertIn(value, TRANSITION_DISPOSITIONS)


class EnvironmentCredentialTests(unittest.TestCase):
    def test_runtime_modules_read_only_ledger_locations_from_the_environment(self):
        for path in RUNTIME_MODULES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                read = None
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ("getenv", "get") and node.args
                        and ast.unparse(node.func.value) in ("os", "os.environ")):
                    read = node.args[0]
                elif isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
                    read = node.slice
                if read is None:
                    continue
                with self.subTest(module=path.relative_to(ROOT).as_posix(), read=ast.unparse(read)):
                    if isinstance(read, ast.Constant):
                        self.assertIn(read.value, LOCATION_VARIABLES)
                    else:
                        # A non-constant read names a location variable passed in, or
                        # walks a refusal list; it is never a credential lookup.
                        self.assertNotIn(ast.unparse(read), CREDENTIAL_VARIABLES)

    def test_a_credential_variable_is_named_only_to_be_refused(self):
        refuser = _load("census_sv002", "resident-runtime/run_sv002_self_characterization_roundtrip.py")
        for path in RUNTIME_MODULES:
            named = {name for name in CREDENTIAL_VARIABLES if name in code_text(path)}
            if not named:
                continue
            with self.subTest(module=path.relative_to(ROOT).as_posix()):
                self.assertEqual(path.name, "run_sv002_self_characterization_roundtrip.py")
                self.assertTrue(named <= set(refuser.FORBIDDEN_CREDENTIAL_ENV))

    def test_a_credential_bearing_or_hosted_environment_is_refused_rather_than_used(self):
        base = {k: v for k, v in os.environ.items() if k not in CREDENTIAL_VARIABLES
                and k not in ("GITHUB_ACTIONS", "CI")}
        with tempfile.TemporaryDirectory() as work:
            args = ["--sdk-root", work, "--mesh-root", work, "--state-root", work]
            with_token = subprocess.run(
                [sys.executable, str(ROOT / "resident-runtime/run_sv002_self_characterization_roundtrip.py"), *args],
                cwd=ROOT, capture_output=True, text=True, env={**base, "GH_TOKEN": "x"}, timeout=120)
            self.assertNotEqual(with_token.returncode, 0)
            self.assertIn("credential-bearing", with_token.stderr)
            hosted = subprocess.run(
                [sys.executable, str(ROOT / "resident-runtime/resident_executor.py"),
                 "--mesh-root", work, "--node-state-root", work],
                cwd=ROOT, capture_output=True, text=True, env={**base, "GITHUB_ACTIONS": "true"}, timeout=120)
            self.assertNotEqual(hosted.returncode, 0)
            self.assertIn("hosted runtime prohibited", hosted.stderr)


class MasterRecordsAndWaitingTests(unittest.TestCase):
    def test_master_records_is_a_downstream_recorder_that_gates_and_delays_nothing(self):
        release = _load("census_release", "resident-runtime/submit_org_transition_to_master_records.py")
        refusal = release.ReleaseRefused("MESH_ROOT_SUPPLIED", "no --mesh-root").refusal
        self.assertEqual(refusal["disposition"], "DENY")
        self.assertEqual(refusal["scope"], "DOWNSTREAM_RELEASE_ONLY")
        self.assertIs(refusal["organization_transition_blocked"], False)
        self.assertIs(refusal["master_records_awaited"], False)
        self.assertIs(refusal["gates_organization_runtime_reality"], False)
        governance = next(entry for entry in OVERLAY["egress"]["capability_destination_bindings"]
                          if entry["profile_id"] == "governance")
        self.assertIs(governance["master_records_in_path"], False)
        self.assertIs(governance["awaits_the_decision"], False)
        self.assertIs(governance["always_on_receiver_required"], False)
        ingress = (ROOT / "resident-runtime/organization_manifest_ingress.py").read_text(encoding="utf-8")
        self.assertIn('"master_records_organization_record_observed": False', ingress)
        self.assertNotIn('"master_records_organization_record_observed": True', ingress)
        self.assertIn('"awaits_the_decision": False', ingress)

    def test_nothing_waits_on_an_external_machine_and_nothing_stays_resident(self):
        forbidden = re.compile(r"time\.sleep\(|while True|urllib\.request|http\.client|\brequests\.|socket\.|select\.select")
        for path in RUNTIME_MODULES:
            with self.subTest(module=path.relative_to(ROOT).as_posix()):
                self.assertIsNone(forbidden.search(path.read_text(encoding="utf-8")))
        executor = (ROOT / "resident-runtime/resident_executor.py").read_text(encoding="utf-8")
        self.assertIn("ONE_CYCLE_PER_INVOCATION", executor)

    def test_the_mesh_is_supplied_by_the_materializer_never_by_the_environment(self):
        with self.assertRaises(ValueError) as refused:
            kernel.mesh_store(None, env={"STEGVERSE_ORG_FEDERATION_ROOT": "/anywhere"})
        self.assertEqual(str(refused.exception), "host_environment_mesh_binding_forbidden")
        with self.assertRaises(ValueError) as refused:
            kernel.resolve_federation_root(None)
        self.assertEqual(str(refused.exception), "mesh_location_required_from_materializer")


if __name__ == "__main__":
    unittest.main()
