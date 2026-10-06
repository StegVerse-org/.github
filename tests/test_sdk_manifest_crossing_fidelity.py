"""The SDK and the boundary must agree on where a manifest is bound.

Two independent readers of one field existed and nothing checked they agreed.
`stegverse.manifest_state_transition_runtime.manifest_declared_destination`
reads `completion.egress` on the SDK side; `sdk_manifest_crossing.declared_
destination` reads it on this boundary. If they ever disagree, a manifest
crosses to a surface other than the one its author declared -- and every
check on either side still passes, because each is self-consistent.

These cases also hold the committed fixtures to the installed SDK's own
contract. `tests/test_sdk_manifest_crossing.py` runs without the SDK, which is
what keeps the two repositories decoupled, but it means the fixtures could
drift into a shape the SDK no longer produces and the crossing would go on
being tested against a fiction. This module is where that is caught, and it is
why it is gated by the workflow that installs the SDK.

Requires the installed StegVerse SDK; it cannot run outside that workflow.

Source validation only. No authority effect is claimed.
"""
import importlib.util
import json
import unittest
from pathlib import Path

from stegverse.manifest_contract import validate_ingress_manifest
from stegverse.manifest_state_transition_runtime import manifest_declared_destination

ROOT = Path(__file__).resolve().parents[1]
# A crossing is ingress, so it declares its chain position. These fixtures are
# ingress manifests and carry none of their own, so the caller declares it;
# `predecessor` is present and null, which is explicit genesis.
GENESIS = {"mode": "ESTABLISH_GENESIS", "node_ref": "StegVerse-independent-evaluator",
           "predecessor": None}

FIXTURES = ROOT / "tests/fixtures/sdk-manifests"
REGISTRY = json.loads((ROOT / "org-boundary/registry/services.json").read_text())

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bridge = _load("sdk_manifest_crossing", ROOT / "resident-runtime/sdk_manifest_crossing.py")
builder = _load("sdk_manifest_fixture_build",
                ROOT / "tests/fixtures/sdk_manifest_fixture_build.py")


def fixtures():
    paths = sorted(FIXTURES.glob("*.json"))
    assert paths, "no SDK manifest fixtures to validate"
    return [(path.name, json.loads(path.read_text())) for path in paths]


class FixtureFidelityTests(unittest.TestCase):
    def test_every_fixture_still_validates_under_the_installed_sdk_contract(self):
        """A fixture the SDK would reject is not evidence of anything."""
        for name, manifest in fixtures():
            with self.subTest(fixture=name):
                validate_ingress_manifest(manifest)

    def test_canonicalization_preserves_the_declared_payload(self):
        for name, manifest in fixtures():
            with self.subTest(fixture=name):
                canonical = validate_ingress_manifest(manifest)
                self.assertEqual(canonical["payload"], manifest["payload"])


class DestinationAgreementTests(unittest.TestCase):
    """The invariant this module exists for."""

    def test_both_sides_read_the_same_declared_surface(self):
        for name, manifest in fixtures():
            with self.subTest(fixture=name):
                sdk = manifest_declared_destination(validate_ingress_manifest(manifest))
                boundary = bridge.declared_destination(manifest)
                self.assertIsNotNone(sdk, "the SDK reads no destination")
                self.assertEqual(sdk["final_stegverse_transition_surface"],
                                 boundary["surface"])
                self.assertEqual(sdk["transport"], boundary["transport"])
                self.assertEqual(sdk["far_side_transition_required"],
                                 boundary["far_side_transition_required"])

    def test_the_surface_both_sides_read_resolves_in_this_registry(self):
        """Agreement on an unroutable surface is agreement about nothing."""
        for name, manifest in fixtures():
            with self.subTest(fixture=name):
                sdk = manifest_declared_destination(validate_ingress_manifest(manifest))
                service = bridge.resolve_surface(
                    sdk["final_stegverse_transition_surface"], REGISTRY)
                self.assertEqual(service["repository"].split("/")[0], "StegVerse-org")


class FixtureDriftTests(unittest.TestCase):
    """Same arguments, same SDK, same bytes."""

    @classmethod
    def setUpClass(cls):
        cls.rebuilt = builder.rebuild()

    def test_the_committed_fixtures_are_what_the_sdk_builds_now(self):
        for name, manifest in self.rebuilt.items():
            with self.subTest(fixture=name):
                committed = (FIXTURES / (name + ".json")).read_text(encoding="utf-8")
                self.assertEqual(
                    committed, builder.rendered(manifest),
                    "run tests/fixtures/sdk_manifest_fixture_build.py --write")

    def test_the_spec_accounts_for_every_committed_fixture(self):
        """A fixture with no spec entry is one nothing can rebuild."""
        committed = {path.stem for path in FIXTURES.glob("*.json")}
        self.assertEqual(committed, set(self.rebuilt))


class LiveSdkManifestCrossingTests(unittest.TestCase):
    """Build a manifest with the installed SDK and carry it across, in one run.

    Nothing in the ecosystem exercised SDK output and boundary transport
    together, so a change on either side could break the join while every gate
    on both sides stayed green. This is that gate.
    """

    @classmethod
    def setUpClass(cls):
        cls.manifest = builder.rebuild()["governance-to-boundary-diagnostic"]

    def test_a_freshly_built_sdk_manifest_crosses_the_boundary(self):
        result = bridge.cross(self.manifest, registry=REGISTRY, standing=GENESIS, packet_id="live-sdk-manifest-crossing")
        self.assertIs(result["crossing_completed"], True)
        self.assertIs(result["consumed"], True)
        self.assertEqual(result["reconstruction"], "RECONSTRUCTED")
        self.assertEqual(len(result["receipts"]), 5)
        self.assertEqual(result["authority_effect"], "NONE")

    def test_the_manifest_the_sdk_built_is_the_manifest_that_arrived(self):
        result = bridge.cross(self.manifest, registry=REGISTRY, standing=GENESIS, packet_id="live-sdk-manifest-crossing")
        decision = (result["egress"]["payload"]["execution_result"]
                    ["application_result"])
        self.assertEqual(decision["governance_request_sha256"],
                         bridge.sha(self.manifest["extensions"]["stegverse_governance_request"]))
        self.assertEqual(result["manifest_sha256"], "sha256:" + bridge.sha(self.manifest))

    def test_the_sdk_declared_far_side_is_the_surface_that_was_crossed_to(self):
        canonical = validate_ingress_manifest(self.manifest)
        sdk = manifest_declared_destination(canonical)
        result = bridge.cross(self.manifest, registry=REGISTRY, standing=GENESIS, packet_id="live-sdk-manifest-crossing")
        self.assertEqual(result["declared_transition_surface"],
                         sdk["final_stegverse_transition_surface"])
        # The return surface is kept as declared; governance is processed where it is admitted.
        self.assertEqual(result["resolved_service_id"], "stegverse-org.governance")


if __name__ == "__main__":
    unittest.main()
