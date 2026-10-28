"""Every `uses:` in .github/workflows is pinned to a full commit sha.

A tag such as `@v4` is mutable: whoever controls the action repository can
move it, and every workflow here then runs the moved code. A 40-hex sha
cannot move. Local actions (`./...`) are part of this checkout and are
excepted. The tag may stay as a trailing comment for readability.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<ref>[^#\s]+)")
PINNED = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def workflow_files():
    return sorted(p for p in WORKFLOWS.rglob("*") if p.suffix in (".yml", ".yaml"))


def unpinned_uses():
    found = []
    for path in workflow_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = USES.match(line)
            if not match:
                continue
            ref = match.group("ref").strip("'\"")
            if ref.startswith("./") or PINNED.match(ref):
                continue
            found.append(f"{path.relative_to(ROOT)}:{lineno}: {ref}")
    return found


def six_fields(violations):
    return {
        "failure_code": "WORKFLOW_ACTION_NOT_PINNED",
        "failed_predicate": "every `uses:` in .github/workflows/** names owner/repo@<40-hex sha> or a local ./ path; unpinned: "
        + "; ".join(violations),
        "required_evidence_or_repair": "replace each listed ref with owner/repo@<full commit sha> # <tag>, the sha being the commit the tag resolves to",
        "retry_entrypoint": "python -m unittest tests.test_workflow_action_pins -v",
        "owning_existing_goal": "M-P9 Remediation: workflow action pins",
        "next_attempt": "pin the listed refs, then rerun the retry_entrypoint",
    }


class WorkflowActionPinsTest(unittest.TestCase):
    def test_workflows_exist(self):
        self.assertTrue(workflow_files(), "no workflow files found under .github/workflows")

    def test_every_uses_is_pinned_to_a_sha(self):
        violations = unpinned_uses()
        self.assertEqual(violations, [], six_fields(violations))

    def test_guard_rejects_a_tag_and_admits_a_sha_and_a_local_path(self):
        def ref(line):
            return USES.match(line).group("ref").strip("'\"")

        self.assertIsNone(PINNED.match(ref("      - uses: actions/checkout@v4")))
        self.assertIsNotNone(
            PINNED.match(ref("      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4"))
        )
        self.assertTrue(ref("        uses: ./.github/actions/local").startswith("./"))


if __name__ == "__main__":
    unittest.main()
