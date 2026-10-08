"""The federation directory here is a projection of the canonical one, never a local list.

The canonical directory lives in StegVerse-Labs/.github. This organization's
org-boundary/registry/federation.json carries the canonical entries unchanged
plus the exact source they were projected from; it is updated only by
reprojection. These tests hold that: the committed projection verifies, an
edited entry and a locally added peer are both refused, and the peers the
crossings depend on resolve.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("federation_projection", ROOT / "org-boundary/runtime/federation_projection.py")
projection = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(projection)

DIRECTORY = json.loads((ROOT / "org-boundary/registry/federation.json").read_text(encoding="utf-8"))


class FederationProjectionTests(unittest.TestCase):
    def test_committed_directory_is_a_verified_projection_of_the_canonical_one(self):
        result = projection.verify(DIRECTORY)
        self.assertTrue(result["valid"], result)
        self.assertEqual(DIRECTORY["projection"]["source_repository"], "StegVerse-Labs/.github")
        self.assertRegex(DIRECTORY["projection"]["source_commit"], r"^[0-9a-f]{40}$")

    def test_an_entry_edited_after_projection_is_refused(self):
        edited = copy.deepcopy(DIRECTORY)
        edited["organizations"][0]["org_control_service"] = "tampered.org-control"
        result = projection.verify(edited)
        self.assertFalse(result["valid"])
        self.assertFalse(result["checks"]["entries_unchanged_since_projection"])

    def test_a_locally_added_peer_is_refused(self):
        added = copy.deepcopy(DIRECTORY)
        added["organizations"].append({"organization": "LOCAL-ONLY", "repository": "LOCAL-ONLY/.github",
                                       "org_control_service": "local-only.org-control", "kernel_required": "1.3.0",
                                       "transport_profile": "stegverse.intr.org-boundary.v1"})
        added["denominator"] = len(added["organizations"])
        self.assertFalse(projection.verify(added)["valid"])

    def test_a_directory_without_projection_provenance_is_refused(self):
        bare = {k: v for k, v in DIRECTORY.items() if k != "projection"}
        with self.assertRaises(SystemExit):
            projection.verify(bare)

    def test_peers_the_crossings_depend_on_are_present(self):
        rows = {row["organization"]: row for row in DIRECTORY["organizations"]}
        self.assertIn("SV-LLM", rows)
        self.assertEqual(rows["SV-LLM"]["org_control_service"], "sv-llm.org-control")
        self.assertIn("SV-011", rows)
        self.assertEqual(rows["SV-011"]["addressed_service"], "sv-011.boundary-diagnostic")
        self.assertIs(rows["SV-011"]["serves_an_organization_control_service"], False)
        self.assertEqual(DIRECTORY["denominator"], len(DIRECTORY["organizations"]))


if __name__ == "__main__":
    unittest.main()
