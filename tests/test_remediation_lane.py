"""A non-ALLOW's remediation lane leaves this organization over InTr for its calculated route.

The SDK builds the fork (StegVerse-SDK `stegverse/remediation_fork.py`) with a
route calculated from where the need for remediation was recognized, the
manifested path and the direct route to StegHealer. This organization is the
route's entry: it receives the remediation manifest through its InTr ingress,
binds the next hop the route names (`resident-runtime/remediation_endpoint.py`)
and emits it through its InTr egress to StegVerse-Labs. Nothing here
classifies or decides. Ledger roots and the mesh are temporary per test.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

from stegverse.manifest_state_transition_runtime import derive_execution_request
from stegverse.remediation_fork import build_remediation_fork

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "org-boundary/registry/services.json").read_text())
FIXTURE = ROOT / "tests/fixtures/sdk-manifests/governance-to-llm-adapter.json"
GENESIS = json.loads((ROOT / "tests/fixtures/crossing-standing-genesis.json").read_text())


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ingress = _load("organization_manifest_ingress_lane", "resident-runtime/organization_manifest_ingress.py")
endpoint = _load("remediation_endpoint_under_test", "resident-runtime/remediation_endpoint.py")


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _non_allow(request, **overrides):
    deny = {"schema": "stegverse.sdk.manifest-profile-disposition/v1", "state": "DENY", "disposition": "DENY",
            "terminal": False, "evaluation_boundary": "SDK_MANIFEST_PROFILE_SOURCE_ONLY",
            "request_sha256": request["request_sha256"], "failed_predicate": "EXAMPLE_PREDICATE"}
    deny.update(overrides)
    return deny


class RemediationLaneTests(unittest.TestCase):
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
        self.original = derive_execution_request(json.loads(FIXTURE.read_text()), ingress.boundary())
        self.fork = build_remediation_fork(self.original, _non_allow(self.original), ingress.boundary())

    def frames_to(self, organization):
        return [frame for frame in (json.loads(p.read_text()) for p in (self.mesh / "frames.d").glob("*.json"))
                if frame["destination_org"] == organization]

    def receive(self, manifest):
        return ingress.receive(manifest, registry=REGISTRY, standing=GENESIS, packet_id="remediation-lane-test",
                               hb_epoch=41, mesh_root=self.mesh)

    def test_the_route_enters_here_and_leaves_over_intr_for_steghealers_organization(self):
        route = self.fork["remediation_route"]
        self.assertEqual(route["entry_organization"], "StegVerse-org")
        self.assertEqual([h["crossing"] for h in route["direct_route_to_steghealer"]],
                         ["INTERLOCK_INTR_INGRESS", "INTERLOCK_INTR_EGRESS", "INTERLOCK_INTR_INGRESS",
                          "INTERNAL_ENDPOINT"])
        out = self.receive(self.fork["remediation_manifest"])
        self.assertEqual(out["disposition"], "ALLOW", out)
        self.assertEqual(out["processing_capability"], "remediation")
        self.assertTrue(out["intr_admission_observed"])
        self.assertEqual(out["next_organization"], "StegVerse-Labs")
        self.assertEqual(out["next_service"], "stegverse-labs.remediation")
        self.assertEqual(out["remediation_route_sha256"], route["route_sha256"])
        self.assertFalse(out["classification_grants_authority"])
        self.assertTrue(out["emission_organization_receipt_sha256"])
        frames = self.frames_to("StegVerse-Labs")
        self.assertEqual(len(frames), 1)

    def test_one_lane_is_one_transition(self):
        first = self.receive(self.fork["remediation_manifest"])
        again = self.receive(copy.deepcopy(self.fork["remediation_manifest"]))
        self.assertEqual(first["organization_transition_id"], again["organization_transition_id"])
        self.assertTrue(again["transition_replayed"])

    def test_the_endpoint_follows_the_calculated_route_and_refuses_anything_else(self):
        manifest = copy.deepcopy(self.fork["remediation_manifest"])
        bound = endpoint.bind(manifest)
        self.assertEqual(bound["next_organization"], "StegVerse-Labs")
        self.assertFalse(bound["classifier_imported_in_this_organization"])
        elsewhere = copy.deepcopy(manifest)
        elsewhere["extensions"][endpoint.REQUEST_EXTENSION]["remediation_route"]["entry_organization"] = "Other"
        with self.assertRaises(SystemExit):
            endpoint.bind(elsewhere)
        bypass = copy.deepcopy(manifest)
        hops = bypass["extensions"][endpoint.REQUEST_EXTENSION]["remediation_route"]["direct_route_to_steghealer"]
        bypass["extensions"][endpoint.REQUEST_EXTENSION]["remediation_route"]["direct_route_to_steghealer"] = [
            h for h in hops if h["crossing"] != "INTERLOCK_INTR_INGRESS" or h["from"] == "SDK"]
        with self.assertRaises(SystemExit):
            endpoint.bind(bypass)
        other = copy.deepcopy(manifest)
        other["extensions"][endpoint.REQUEST_EXTENSION]["remediation_route"]["steghealer"]["service_id"] = "x.y"
        with self.assertRaises(SystemExit):
            endpoint.bind(other)

    def test_a_redirected_route_is_refused_at_ingress_and_nothing_is_emitted(self):
        manifest = copy.deepcopy(self.fork["remediation_manifest"])
        manifest["extensions"]["stegverse_remediation_fork_request"]["remediation_route"][
            "direct_route_to_steghealer"][-1]["to"] = "somewhere-else"
        out = self.receive(manifest)
        self.assertNotEqual(out["disposition"], "ALLOW")
        self.assertFalse((self.mesh / "frames.d").exists() and self.frames_to("StegVerse-Labs"))

    def test_the_overlay_declares_remediation_once_and_the_registry_serves_it(self):
        bindings = [b for b in ingress.boundary()["egress"]["capability_destination_bindings"]
                    if b["profile_id"] == "remediation"]
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0]["destination_service"], "stegverse-labs.remediation")
        self.assertFalse(bindings[0]["classification_grants_authority"])
        served = [s for s in REGISTRY["services"]
                  if {"capability": "remediation", "route_id": "stegverse.route.governed-remediation.v1"}
                  in (s.get("admits_processing") or [])]
        self.assertEqual([s["service_id"] for s in served], ["stegverse-org.remediation"])


if __name__ == "__main__":
    unittest.main()
