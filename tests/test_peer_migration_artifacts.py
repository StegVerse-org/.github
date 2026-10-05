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
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs/PEER_KERNEL_GENERATION_ADMISSION_MIGRATION_002.md"
PATCHES = {
    "Admissible-Existence": ROOT / "docs/migrations/admissible-existence.node-standing-gate.patch",
}
#: Owners that have applied it, and so have no patch here any more. A patch for
#: an applied target cannot apply, and would rot unnoticed as the target moved.
APPLIED = {"StegVerse-Labs": "5f14de9ac686b0b6b4f77ece31087a0e980b537b"}
#: The out-of-kernel caller the required-keyword change breaks. Both owners
#: carry it at this path; the patch must fix it, not merely mention it.
OUT_OF_KERNEL_CALLER = "resident-runtime/submit_org_transition_to_master_records.py"
#: Copied verbatim into each peer by the applier, so the record names a digest.
CANONICAL = (
    "org-boundary/runtime/node_standing.py",
    "docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json",
)
TOUCHED = {"org-kernel/kernel.py", "org-kernel/tests/test_kernel.py",
           "org-kernel/kernel-manifest.json", OUT_OF_KERNEL_CALLER}
#: The generation the gate produces. Not 1.4.0: this migration installs the
#: gate, not parity with this organization's 46-function kernel, and a number
#: claiming parity would be the same defect one layer up.
GATE_VERSION = "1.3.2"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RecordedPatchesTests(unittest.TestCase):
    def test_both_patches_are_recorded(self):
        for org, path in PATCHES.items():
            with self.subTest(org=org):
                self.assertTrue(path.is_file(), f"{org}: {path} is missing")
                self.assertGreater(path.stat().st_size, 0, f"{org}: patch is empty")

    def test_each_patch_touches_only_the_paths_it_claims(self):
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

    def test_each_patch_bumps_the_kernel_version(self):
        """Without this, a gated peer and an ungated one both report 1.3.1.

        Both generations shipped under the same number, so `kernel_required`
        could not tell them apart -- a declared limit that was not real.
        """
        for org, path in PATCHES.items():
            with self.subTest(org=org):
                self.assertIn(f'+  "kernel_version": "{GATE_VERSION}",', path.read_text(),
                              f"{org}: patch does not bump kernel_version to {GATE_VERSION}")

    def test_the_record_names_the_version_the_patches_produce(self):
        self.assertIn(GATE_VERSION, RECORD.read_text(),
                      f"the record does not name {GATE_VERSION}")

    def test_the_records_copy_steps_cover_every_tree_path_the_patch_depends_on(self):
        """The gap that actually bit: a dependency the record knew but nothing enforced.

        The patched kernel loads modules and contracts *from the dispatch root*,
        so a peer that applies the diff alone gets code that cannot run. Those
        paths are readable in the patch's own added lines, and the record's
        steps are readable here, so the two are checked against each other
        rather than trusted to agree. A future patch that adds a dependency
        without adding its copy step fails here.
        """
        record = RECORD.read_text()
        pattern = re.compile(r'"((?:org-boundary|org-kernel|docs)/[A-Za-z0-9_./-]+\.(?:py|json))"')
        for org, path in PATCHES.items():
            added = "\n".join(line[1:] for line in path.read_text().splitlines()
                               if line.startswith("+") and not line.startswith("+++"))
            depends = {m for m in pattern.findall(added)}
            # Paths the diff itself writes need no copy step; the rest must be
            # carried into the peer by an instruction the record states.
            depends -= TOUCHED
            self.assertTrue(depends, f"{org}: found no tree dependencies to check")
            for relative in sorted(depends):
                with self.subTest(org=org, path=relative):
                    # `in record` rather than assertIn: a failure should name
                    # the path, not print the whole record.
                    self.assertTrue(
                        relative in record,
                        f"{org}: the patch depends on {relative} and the record neither "
                        "carries it into the peer nor declares it already present there")

    def test_every_path_the_record_tells_the_applier_to_copy_exists_here(self):
        record = RECORD.read_text()
        pattern = re.compile(r'(?:org-boundary|docs)/[A-Za-z0-9_./-]+\.(?:py|json)')
        named = {m for m in pattern.findall(record)} - TOUCHED
        self.assertTrue(named, "the record names no file to copy")
        for relative in sorted(named):
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file(),
                                f"the record tells the applier to copy {relative}, "
                                "which does not exist here")

    def test_each_patch_fixes_every_out_of_kernel_caller_it_breaks(self):
        """A required keyword is only honest if its callers moved with it.

        `standing` became required on build_packet(), which breaks callers
        outside org-kernel. Both owners carry one. A patch that changes the
        signature and leaves a caller passing the old argument list ships a
        kernel whose gate is enforced where a test looks and a live script that
        cannot run -- which is this migration's own defect class, one layer
        down. So every build_packet call the patch *adds* outside org-kernel
        must pass standing, and the caller must actually be touched.
        """
        for org, path in PATCHES.items():
            text = path.read_text()
            with self.subTest(org=org):
                touched = set(re.findall(r"^diff --git a/(\S+) b/\1$", text,
                                         flags=re.MULTILINE))
                self.assertIn(OUT_OF_KERNEL_CALLER, touched,
                              f"{org}: patch makes standing required but does not "
                              f"touch {OUT_OF_KERNEL_CALLER}")
            hunk = self._hunk_for(text, OUT_OF_KERNEL_CALLER)
            added = "\n".join(line[1:] for line in hunk.splitlines()
                               if line.startswith("+") and not line.startswith("+++"))
            # `in` rather than assertIn throughout: a failure should name what
            # is missing, not print the whole hunk back at the reader.
            required = (
                ("build_packet(", "the caller hunk does not rewrite the call"),
                ("standing=standing",
                 "the caller still calls build_packet without passing standing"),
                ('"--standing",required=True',
                 "the caller does not require standing to be declared; a default "
                 "is the defaulting the contract forbids"),
                ('"predecessor" not in standing',
                 "the caller accepts standing with no predecessor key, which is "
                 "genesis assumed rather than stated"),
            )
            for fragment, why in required:
                with self.subTest(org=org, needs=fragment):
                    self.assertTrue(fragment in added, f"{org}: {why}")

    @staticmethod
    def _hunk_for(patch_text: str, relative: str) -> str:
        """The one file's section of a unified diff, header included."""
        parts = re.split(r"(?m)^(?=diff --git )", patch_text)
        for part in parts:
            if part.startswith(f"diff --git a/{relative} b/{relative}"):
                return part
        return ""

    def test_the_record_states_the_applied_state_per_peer(self):
        """The blanket claim went stale the moment one owner applied it.

        A document that says no peer runs the gate, while one does, is the
        same defect as a limit declared that is not real. This holds the
        record to the per-peer form and to naming the applied commit.
        """
        record = RECORD.read_text()
        for org, sha in APPLIED.items():
            with self.subTest(org=org):
                self.assertIn(sha, record,
                              f"the record does not name the commit {org} applied it at")
            retired = ROOT / "docs/migrations" / f"{org.lower()}.node-standing-gate.patch"
            with self.subTest(org=org, file=retired.name):
                self.assertFalse(retired.exists(),
                                 f"{org} applied it, so {retired.name} cannot still "
                                 "apply and must not be kept here")
        for org in PATCHES:
            with self.subTest(org=org):
                self.assertIn(org, record, f"the record does not name {org} as awaiting")

    def test_no_retired_patch_file_is_left_behind(self):
        recorded = {p.name for p in PATCHES.values()}
        on_disk = {p.name for p in (ROOT / "docs/migrations").glob("*.patch")}
        self.assertEqual(on_disk, recorded,
                         f"unrecorded patch files on disk: {sorted(on_disk - recorded)}")

    def test_every_sha_the_record_attributes_to_this_repository_is_real(self):
        """The guard the padded-SHA fix did not cover.

        That fix refused a hash padded with zeros. It did not refuse a hash
        that is simply invented, which is the same lie in a shape the pattern
        allows. Any 40-hex value the record attributes to this repository is
        checkable right here, so it is checked.
        """
        record = RECORD.read_text()
        mine = re.findall(r"StegVerse-org/\.github\s+([0-9a-f]{40})", record)
        self.assertTrue(mine, "the record names no StegVerse-org commit to verify")
        shallow = subprocess.run(["git", "rev-parse", "--is-shallow-repository"],
                                 cwd=ROOT, capture_output=True, text=True
                                 ).stdout.strip() == "true"
        for sha in mine:
            with self.subTest(sha=sha):
                found = subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"],
                                       cwd=ROOT, capture_output=True)
                if found.returncode == 0:
                    continue
                # Absent for one of two reasons, and they are not the same
                # finding. Saying which keeps the check from being read as a
                # false accusation, and keeps a truncated checkout from being
                # read as a clean pass.
                self.assertFalse(
                    shallow,
                    f"{sha} is not in this checkout, which is shallow, so whether "
                    "the record is honest cannot be determined here. Give the "
                    "workflow fetch-depth: 0 rather than leaving this unchecked")
                self.fail(f"the record names {sha} as a commit of this repository. "
                          "History here is complete and it is not in it")

    def test_no_sha_in_the_record_is_padded(self):
        record = RECORD.read_text()
        for sha in re.findall(r"\b([0-9a-f]{40})\b", record):
            with self.subTest(sha=sha):
                self.assertFalse(re.fullmatch(r"[0-9a-f]{7,8}0{32,33}", sha),
                                 f"{sha} looks like a short SHA padded with zeros")

    def test_the_record_does_not_claim_the_migration_was_applied_here(self):
        record = RECORD.read_text()
        self.assertIn("not_applied_here:   true", record)
        self.assertIn("A patch recorded here is not an applied patch.", record)
        self.assertIn("Standing admitted is not origin authenticated.", record)


if __name__ == "__main__":
    unittest.main()
