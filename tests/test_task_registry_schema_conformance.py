"""The registry must validate against the owner's schema, and the copy must not drift.

`StegVerse-Labs/repo-standards` owns the orchestration task registry: ST-021
defines the progression automaton and `schemas/task-registry.schema.json`
defines the record.

Validating against the owner's file directly from this repository's CI is not
available. repo-standards is private and in another organization, so a
workflow in `StegVerse-org/.github` cannot check it out with the default token
-- the attempt fails with git exit code 128. The SDK manifest crossing gets to
check its contract out at a pin only because `StegVerse-org/StegVerse-SDK` is
public.

So the schema is vendored, which is a real compromise rather than a design
preference: a copy is exactly what drifts silently when the owner changes. It
is made detectable instead. `orchestration/schemas/PROVENANCE.json` records the
commit the copy was taken from and the digest it had, these cases check the
copy still has that digest, and the drift case compares the copy against the
owner's whenever repo-standards is reachable -- in a session that has it
attached, not here. That case skips rather than passes when it cannot look, so
a skip is never mistaken for agreement.

Source validation only. No authority effect is claimed.
"""
import hashlib
import json
import os
import subprocess
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "orchestration/task-registry.json").read_text(encoding="utf-8"))
PROVENANCE = json.loads((ROOT / "orchestration/schemas/PROVENANCE.json").read_text(encoding="utf-8"))
RECORD = PROVENANCE["vendored"][0]
VENDORED_PATH = ROOT / RECORD["path"]
SCHEMA = json.loads(VENDORED_PATH.read_text(encoding="utf-8"))


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def owner_root():
    """The owner's checkout, when a session has repo-standards attached."""
    root = os.environ.get("REPO_STANDARDS_ROOT")
    candidates = [Path(root)] if root else [ROOT.parent / "repo-standards"]
    for base in candidates:
        if (base / RECORD["source_path"]).is_file():
            return base
    return None


def owner_schema_path():
    """The owner's own file, when a session has repo-standards attached."""
    base = owner_root()
    return base / RECORD["source_path"] if base else None


def owner_blob(base, commit):
    """The schema as it stood at `commit` in the owner's history, or None.

    None means the commit is not in this checkout -- a shallow clone, or a
    commit that never reached the owner. The caller distinguishes the two.
    """
    shown = subprocess.run(
        ["git", "show", f"{commit}:{RECORD['source_path']}"],
        cwd=base, capture_output=True)
    return shown.stdout if shown.returncode == 0 else None


def commit_is_on_owner_default_branch(base, commit):
    """Whether `commit` is an ancestor of the owner's default branch here."""
    for ref in ("origin/main", "main"):
        resolved = subprocess.run(["git", "rev-parse", "--verify", ref],
                                  cwd=base, capture_output=True)
        if resolved.returncode != 0:
            continue
        reachable = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, ref],
            cwd=base, capture_output=True)
        return reachable.returncode == 0
    return None


class ConformanceTests(unittest.TestCase):
    def test_the_registry_validates_against_the_schema(self):
        jsonschema.validate(REGISTRY, SCHEMA)

    def test_the_schema_is_the_orchestration_task_registry(self):
        """Guard against validating happily against some other schema."""
        self.assertEqual(SCHEMA["title"], "StegVerse Orchestration Task Registry")
        self.assertEqual(SCHEMA["properties"]["registry_type"]["const"],
                         "orchestration_task_registry")

    def test_every_field_the_registry_uses_is_one_the_schema_defines(self):
        defined = set(SCHEMA["properties"]["tasks"]["items"]["properties"])
        for task in REGISTRY["tasks"]:
            with self.subTest(task=task["task_id"]):
                self.assertTrue(set(task) <= defined,
                                "not in the schema: " + str(sorted(set(task) - defined)))


class ProvenanceTests(unittest.TestCase):
    """A copy with no recorded origin is a copy nothing can check."""

    def test_the_copy_still_has_the_digest_that_was_recorded(self):
        self.assertEqual(digest(VENDORED_PATH.read_bytes()), RECORD["source_sha256"])

    def test_the_record_names_where_the_copy_came_from(self):
        self.assertEqual(RECORD["source_repository"], "StegVerse-Labs/repo-standards")
        self.assertEqual(RECORD["source_path"], "schemas/task-registry.schema.json")
        self.assertRegex(RECORD["source_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(PROVENANCE["authority_effect"], "NONE_COPY_ONLY")

    def test_the_record_says_why_a_copy_exists_at_all(self):
        """So the compromise stays visible rather than becoming the convention."""
        self.assertIn("private", PROVENANCE["why"])
        self.assertIn("128", PROVENANCE["why"])

    def test_the_schema_carries_no_entity_field(self):
        """Entity neutrality is a property of the canon, not a local choice."""
        task_properties = set(SCHEMA["properties"]["tasks"]["items"]["properties"])
        for name in ("assignee", "assignees", "agent", "entity", "model", "llm", "claimed_by"):
            self.assertNotIn(name, task_properties)


class OwnerDriftTests(unittest.TestCase):
    """Runs where the owner is reachable. Skips rather than passes where it is not."""

    @classmethod
    def setUpClass(cls):
        cls.base = owner_root()
        cls.path = owner_schema_path()
        if cls.path is None:
            raise unittest.SkipTest(
                "repo-standards is not reachable here; attach it to check the copy for drift")

    def test_the_copy_is_byte_identical_to_the_owners_schema(self):
        self.assertEqual(
            digest(self.path.read_bytes()), digest(VENDORED_PATH.read_bytes()),
            "the owner's schema has changed; re-vendor it and update PROVENANCE.json")

    def test_the_recorded_digest_is_the_owners_current_digest(self):
        self.assertEqual(digest(self.path.read_bytes()), RECORD["source_sha256"])

    def test_the_recorded_commit_really_carries_the_recorded_digest(self):
        """The digest alone cannot tell a merged pin from a branch-head one.

        Every other case here compares the copy against the owner's *working
        tree*, so a `source_commit` naming a branch that was never merged, or a
        commit that no longer exists, passes all of them. This reads the schema
        as it stood at the recorded commit.
        """
        commit = RECORD["source_commit"]
        blob = owner_blob(self.base, commit)
        if blob is None:
            self.skipTest(
                "commit %s is not in this checkout, so the pin cannot be read "
                "here; deepen the clone to check it" % commit[:12])
        self.assertEqual(digest(blob), RECORD["source_sha256"],
                         "source_commit does not carry source_sha256")

    def test_the_recorded_commit_is_on_the_owners_default_branch(self):
        """A pin to an unmerged branch head is a pin to something retractable.

        This is what went unnoticed once: the copy was taken from a pull
        request's head, every digest matched, and nothing said the commit was
        not yet canon. The record carried `pin_state` to say so by hand, which
        is exactly the kind of declaration a check should make unnecessary.

        It catches the pin while the branch is unmerged, which is when it
        matters. Once that branch merges, its head becomes an ancestor of the
        default branch, so afterwards this case cannot tell a branch-head pin
        from a merge-commit pin -- the digest case above is what still can.
        """
        commit = RECORD["source_commit"]
        if owner_blob(self.base, commit) is None:
            self.skipTest("commit %s is not in this checkout" % commit[:12])
        reachable = commit_is_on_owner_default_branch(self.base, commit)
        if reachable is None:
            self.skipTest("no main ref in this checkout to measure against")
        self.assertTrue(
            reachable,
            "source_commit %s is not on the owner's default branch. If it is a "
            "pull-request head, say so with pin_state and re-pin once it merges."
            % commit[:12])


if __name__ == "__main__":
    unittest.main()
