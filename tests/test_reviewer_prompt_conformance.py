"""Every command we tell an external reviewer to run still runs.

The two reviewer prompts are the artifact an outside party actually receives.
They were correct when written and nothing held them there: no workflow matched
a documentation change, so a rename, a moved entry point or a dropped
subcommand could break a documented command and the repository would stay
green while the reviewer discovered it. That is the defect class these prompts
ask a reviewer to hunt, sitting in the artifact handed to them -- and one of
them already records an earlier revision that sent a reviewer at an HTTP route
existing nowhere in this repository.

So the commands are extracted from the prompts and executed. Not paraphrased
and not re-implemented here: the literal indented block is dedented and handed
to a shell, exactly as a reviewer would paste it, because a conformance case
that ran its own idea of the command would prove the idea rather than the
document.

Every command runs against a clean checkout containing only tracked files.
A reviewer clones; they do not get a working tree, so neither does this.

Source validation only. No authority effect is claimed.
"""
from __future__ import annotations

import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROMPTS = (
    "docs/EXTERNAL_REVIEWER_TASK_REGISTRY_PROMPT.md",
    "docs/EXTERNAL_REVIEWER_NODE_STANDING_PROMPT.md",
)

#: A block opens on an indented line starting with one of these.
OPENERS = ("python3 ", "git ", "cd ")

#: Blocks that fetch the repository are what produces the checkout the others
#: run in, so they are recorded rather than executed. Named explicitly: a
#: silent skip is how a command stops being checked without anyone deciding.
NOT_EXECUTED_HERE = ("git clone",)


def command_blocks(text: str) -> list[str]:
    """The indented command blocks of a prompt, dedented, in document order."""
    blocks, current = [], []
    for line in text.split("\n"):
        if line.startswith("    ") and (current or line[4:].startswith(OPENERS)):
            current.append(line[4:])
            continue
        if current:
            blocks.append("\n".join(current).rstrip())
            current = []
    if current:
        blocks.append("\n".join(current).rstrip())
    return blocks


class PromptConformanceTests(unittest.TestCase):
    """What the prompts tell a reviewer to run is what this runs."""

    @classmethod
    def setUpClass(cls):
        # The reviewer's view: tracked files only, no working-tree leftovers.
        cls._tmp = tempfile.TemporaryDirectory()
        cls.checkout = Path(cls._tmp.name)
        listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                                capture_output=True, check=True)
        names = [name for name in listed.stdout.decode().split("\0") if name]
        archive = cls.checkout / "_tracked.tar"
        with tarfile.open(archive, "w") as bundle:
            for name in names:
                bundle.add(ROOT / name, arcname=name)
        with tarfile.open(archive) as bundle:
            bundle.extractall(cls.checkout)
        archive.unlink()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_block(self, block: str):
        return subprocess.run(["bash", "-c", block], cwd=self.checkout,
                              capture_output=True, text=True, timeout=300)

    def test_the_extractor_finds_the_commands_it_is_meant_to(self):
        # A conformance case that extracted nothing would pass while checking
        # nothing, which is the vacuous shape this repository refuses.
        total = sum(len(command_blocks((ROOT / name).read_text(encoding="utf-8")))
                    for name in PROMPTS)
        self.assertGreaterEqual(total, 5, "no command blocks extracted from the prompts")

    def test_every_documented_command_succeeds(self):
        executed = 0
        for name in PROMPTS:
            for block in command_blocks((ROOT / name).read_text(encoding="utf-8")):
                if any(marker in block for marker in NOT_EXECUTED_HERE):
                    continue
                with self.subTest(prompt=name, block=block.split("\n")[0][:70]):
                    result = self.run_block(block)
                    self.assertEqual(
                        result.returncode, 0,
                        name + " documents a command that fails:\n" + block
                        + "\n--- stdout ---\n" + result.stdout
                        + "\n--- stderr ---\n" + result.stderr)
                    executed += 1
        self.assertGreater(executed, 0, "no documented command was executed")

    def test_the_clone_step_is_recorded_rather_than_silently_dropped(self):
        found = [block for name in PROMPTS
                 for block in command_blocks((ROOT / name).read_text(encoding="utf-8"))
                 if any(marker in block for marker in NOT_EXECUTED_HERE)]
        self.assertTrue(found, "the prompts no longer document how to get the repository")
        for block in found:
            with self.subTest(block=block.split("\n")[0][:70]):
                self.assertIn("StegVerse-org/.github", block)


class PromptClaimTests(unittest.TestCase):
    """Specific statements the prompts make about what a reviewer will see."""

    def prompt(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_the_task_registry_prompt_names_a_dependency_honestly(self):
        # One suite is standard library and one imports jsonschema unguarded.
        # A reviewer told otherwise would read an import error as a finding.
        text = self.prompt("docs/EXTERNAL_REVIEWER_TASK_REGISTRY_PROMPT.md")
        self.assertIn("jsonschema", text)
        conformance = (ROOT / "tests/test_task_registry_schema_conformance.py").read_text()
        self.assertIn("import jsonschema", conformance)
        registry = (ROOT / "tests/test_task_registry.py").read_text()
        self.assertNotIn("import jsonschema", registry)

    def test_the_entity_neutrality_claim_matches_the_schema(self):
        import json
        schema = json.loads((ROOT / "orchestration/schemas/task-registry.schema.json")
                            .read_text(encoding="utf-8"))
        item = schema["properties"]["tasks"]["items"]
        self.assertIs(item["additionalProperties"], False)
        for named in ("assignee", "agent", "model", "owner", "session", "worker_claim"):
            with self.subTest(field=named):
                self.assertNotIn(named, item["properties"])

    #: This file is excluded from the claim-surface search below, by name.
    #: A case asserting that a string appears nowhere necessarily contains the
    #: string, so it matches itself the moment it is tracked -- which is how
    #: this passed locally while untracked and failed in CI on the first run.
    #: The exemption is named rather than pattern-matched so it stays visible,
    #: and a separate case fails if it ever stops being needed.
    SELF = "tests/test_reviewer_prompt_conformance.py"

    def claim_surface_hits(self):
        hits = subprocess.run(
            ["git", "grep", "-l", "-E", r"worker_claim|WorkerCoordinator",
             "--", "*.py", "*.json"],
            cwd=ROOT, capture_output=True, text=True)
        return {line for line in hits.stdout.split("\n") if line}

    def test_the_no_claim_surface_statement_is_still_true(self):
        """The prompt tells a reviewer they will find no claim surface."""
        found = self.claim_surface_hits() - {self.SELF}
        # The task vector names WorkerCoordinator only to disclaim it ("not a
        # WorkerCoordinator claim or fence"); it carries no claim.
        self.assertEqual(found, {
            "control/task-vectors/SVORG-STEGOS-PORTABILITY-001.json",
            # LLM-org artifacts mention WorkerCoordinator only to preserve the
            # same separation: participating LLMs receive no claim authority.
            "control/task-vector-index.json",
            "data/llm-org-foundation.json",
            "data/organization-role-runtime-reality-deployment.json",
            "tests/test_organization_role_runtime_reality_deployment.py",
            "tests/test_task_registry.py",
        }, "a claim surface appeared or a declaration moved; the prompt now misleads")

    def test_the_self_exemption_is_still_needed(self):
        """A carve-out that stopped being necessary would sit here unnoticed."""
        self.assertIn(self.SELF, self.claim_surface_hits(),
                      self.SELF + " no longer matches; drop the exemption")

    def test_both_prompts_say_which_invariant_they_are(self):
        # The collision that sent a reviewer to the wrong surface is recorded
        # in both documents, not silently resolved in one.
        for name in PROMPTS:
            with self.subTest(prompt=name):
                self.assertIn("Which invariant this is, and which it is not",
                              self.prompt(name))

    def test_no_command_a_reviewer_runs_reaches_a_host(self):
        """Checked on the commands, not the prose.

        The node-standing prompt quotes the retired
        `GET/POST https://<HOST>/api/node-standing` on purpose, in the section
        recording why it was wrong. A check that forbade the string anywhere
        would force that record to be deleted to stay green -- which would
        erase the finding to satisfy the test for it.
        """
        for name in PROMPTS:
            for block in command_blocks(self.prompt(name)):
                with self.subTest(prompt=name, block=block.split("\n")[0][:70]):
                    self.assertNotIn("http://", block)
                    self.assertNotIn("https://", block.replace(
                        "https://github.com/StegVerse-org/.github", ""))

    def test_the_retired_route_stays_recorded(self):
        """The failure is kept, not quietly dropped once it was fixed."""
        text = self.prompt("docs/EXTERNAL_REVIEWER_NODE_STANDING_PROMPT.md")
        self.assertIn("/api/node-standing", text)
        self.assertIn("No such route exists anywhere in this repository", text)


if __name__ == "__main__":
    unittest.main()
