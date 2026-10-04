#!/usr/bin/env python3
"""The recorded peer migration patches stay well-formed and self-consistent.

Migration 002 records two patches this organization cannot apply itself. A patch
nobody here can run is exactly the kind of artifact that rots unnoticed, so what
*is* checkable locally is checked: that each patch is a unified diff, that it
touches only the two kernel paths it claims, that the canonical files it tells
the applier to copy still exist at the digests the record names, and that the
record's own claims about the gate are still the ones the patches carry.

It cannot check that a patch applies to the peer's current head -- that needs
the peer's tree, which this organization cannot attach. That boundary is stated
in the record rather than papered over here.
"""

from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs/PEER_KERNEL_GENERATION_ADMISSION_MIGRATION_002.md"
PATCHES = {
    "StegVerse-Labs": ROOT / "docs/migrations/stegverse-labs.node-standing-gate.patch",
    "Admissible-Existence": ROOT / "docs/migrations/admissible-existence.node-standing-gate.patch",
}
#: Copied verbatim into each peer by the applier, so the record names a digest.
CANONICAL = (
    "org-boundary/runtime/node_standing.py",
    "docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json",
)
TOUCHED = {"org-kernel/kernel.py", "org-kernel/tests/test_kernel.py"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RecordedPatchesTests(unittest.TestCase):
    def test_both_patches_are_recorded(self):
        for org, path in PATCHES.items():
            with self.subTest(org=org):
                self.assertTrue(path.is_file(), f"{org}: {path} is missing")
                self.assertGreater(path.stat().st_size, 0, f"{org}: patch is empty")

    def test_each_patch_touches_only_the_two_kernel_paths(self):
        for org, path in PATCHES.items():
            with self.subTest(org=org):
                touched = set(re.findall(r"^diff --git a/(\S+) b/\1$", path.read_text(),
                                         flags=re.MULTILINE))
                self.assertEqual(touched, TOUCHED,
                                 f"{org}: patch touches {sorted(touched)}")

    def test_each_patch_installs_the_gate_rather_than_only_mentioning_it(self):
        #: The three moving parts of the gate, as added lines. A patch that
        #: merely names node_standing in a comment would pass a looser check.
        required = (
            "+def node_standing(root:Path):",
            "+    standing_module=node_standing(root)",
            '+        raise ValueError("node_standing_refused:"+str(refused)) from None',
        )
        for org, path in PATCHES.items():
            text = path.read_text()
            for line in required:
                with self.subTest(org=org, line=line):
                    self.assertIn(line, text, f"{org}: patch does not add {line!r}")

    def test_each_patch_makes_standing_a_required_keyword(self):
        for org, path in PATCHES.items():
            with self.subTest(org=org):
                self.assertIn("+                 payload:dict[str,Any], standing:dict[str,Any],",
                              path.read_text(),
                              f"{org}: build_packet does not require standing")

    def test_each_patch_carries_the_honest_limit_into_the_peer_regression(self):
        #: Finding 002 narrowed the claim to admission, not origin
        #: authentication. If a future revision of these patches dropped these
        #: assertions, the peer would gain a gate and lose the record of what
        #: the gate does not do.
        asserted = (
            'caller_editable_origin_established_identity"] is False',
            'structural_standing_is_authenticated_standing"] is False',
            'standing_authority_effect"]=="NONE_STANDING_ONLY"',
        )
        for org, path in PATCHES.items():
            text = path.read_text()
            for line in asserted:
                with self.subTest(org=org, line=line):
                    self.assertIn(line, text, f"{org}: patch drops {line!r}")

    def test_the_canonical_files_exist_at_the_digests_the_record_names(self):
        record = RECORD.read_text()
        for relative in CANONICAL:
            with self.subTest(file=relative):
                path = ROOT / relative
                self.assertTrue(path.is_file(), f"{relative} is missing")
                self.assertIn(digest(path), record,
                              f"{relative} changed; Migration 002 names a stale digest")

    def test_the_record_does_not_claim_the_migration_was_applied(self):
        record = RECORD.read_text()
        self.assertIn("not_applied_here:   true", record)
        self.assertIn("A patch recorded here is not an applied patch.", record)
        self.assertIn("Standing admitted is not origin authenticated.", record)


if __name__ == "__main__":
    unittest.main()
