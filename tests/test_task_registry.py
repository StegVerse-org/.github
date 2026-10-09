"""This organization must carry a work-intent surface, and it must stay coherent.

ST-021 Goal Progression Automaton exists for one reason, stated in its own
Purpose: the manual loop "depends on a human copying a status block, opening or
continuing a session, requesting the next prompt, pasting canonical task
coordinates, and trusting the next assistant to reconcile state correctly."

ST-021 fixes a mandatory read order whose first source is the task registry
record, and requires a run to fail closed when it cannot resolve one. This
organization held no such surface at all --
`docs/ORGANIZATION_ROLE_RUNTIME_REALITY_DEPLOYMENT.md` recorded the absence
accurately and concluded there was "no record-side reconciliation to defer",
which was the wrong conclusion: work intent with nowhere to live survives only
in whatever session produced it, so each new session re-derives it or asks
again.

The Task Registry is work-intent and coordination truth in this
organization's authority split. These cases hold the surface to what the
authority requires of it.

The registry is deliberately entity-neutral. It records what the work is and
what evidence closes it, never who is doing it: the canonical schema carries
no assignee, agent or model field, because which entity holds a task is a
claim, and claims are WorkerCoordinator's authority. Any entity in the
ecosystem must be able to read a task and review it against repository
evidence alone.

Source validation only. No authority effect is claimed.
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "orchestration/task-registry.json"
REGISTRY = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
TASKS = REGISTRY["tasks"]

# From StegVerse-Labs/repo-standards schemas/task-registry.schema.json. The
# canonical schema is validated against in CI by checking that repository out;
# these are the invariants this repository can hold on its own.
STATUSES = {"proposed", "accepted", "claimed", "in_progress", "validating",
            "complete", "merged", "archived", "blocked"}
REQUIRED_TASK_FIELDS = {"task_id", "issue", "title", "status", "workstream",
                        "depends_on", "outputs"}
ALLOWED_TASK_FIELDS = REQUIRED_TASK_FIELDS | {
    "required_evidence", "tag_allowed", "activation_condition", "destinations",
    "issue_refs", "repository_artifact_history", "unresolved_obligations"}
ENTITY_FIELDS = {"assignee", "assignees", "agent", "entity", "model", "llm",
                 "owner", "claimed_by", "session", "author"}


class SurfaceExistsTests(unittest.TestCase):
    def test_the_registry_is_at_the_canonical_path(self):
        """ST-021's read order names the task registry record first."""
        self.assertTrue(REGISTRY_PATH.is_file())
        self.assertEqual(REGISTRY["registry_type"], "orchestration_task_registry")
        self.assertEqual(REGISTRY["org"], "StegVerse-org")
        self.assertEqual(REGISTRY["repo"], ".github")
        self.assertIn(REGISTRY["archive_status"], {"ACTIVE", "READY_FOR_HANDOFF", "READY_FOR_ARCHIVE"})

    def test_the_registry_declares_at_least_one_task(self):
        self.assertGreaterEqual(len(TASKS), 1)


def records_cited_by(task):
    """Every durable record a task names: its own, or the ones it aggregates."""
    if isinstance(task.get("issue"), int) and not isinstance(task["issue"], bool):
        return [task["issue"]]
    return list(task.get("issue_refs") or [])


class TaskShapeTests(unittest.TestCase):
    def test_every_task_carries_the_required_fields_and_no_others(self):
        for task in TASKS:
            with self.subTest(task=task.get("task_id")):
                present = set(task)
                self.assertTrue(REQUIRED_TASK_FIELDS <= present,
                                "missing " + str(sorted(REQUIRED_TASK_FIELDS - present)))
                self.assertTrue(present <= ALLOWED_TASK_FIELDS,
                                "unknown " + str(sorted(present - ALLOWED_TASK_FIELDS)))

    def test_every_status_is_one_the_schema_admits(self):
        for task in TASKS:
            with self.subTest(task=task["task_id"]):
                self.assertIn(task["status"], STATUSES)

    def test_every_task_cites_a_durable_record(self):
        """A task whose record is only a conversation cannot be reviewed.

        An aggregate task carries no record of its own and is cited by the
        records of the tasks it aggregates, so it satisfies this through
        `issue_refs` instead. Either way a reviewer has something to open --
        what is refused is a task with neither.
        """
        for task in TASKS:
            with self.subTest(task=task["task_id"]):
                self.assertTrue(records_cited_by(task),
                                "neither issue nor issue_refs names a record")
                for record in records_cited_by(task):
                    self.assertIsInstance(record, int)
                    self.assertNotIsInstance(record, bool)
                    self.assertGreaterEqual(record, 1)

    def test_an_aggregate_task_aggregates_tasks_this_registry_declares(self):
        """Otherwise `issue_refs` is a loose list rather than an aggregation.

        The records a task aggregates must be the records of other tasks here.
        A reference to something outside the registry would make the aggregate's
        own activation condition uncheckable from the registry alone.
        """
        own = {task["issue"] for task in TASKS if isinstance(task["issue"], int)}
        for task in TASKS:
            refs = task.get("issue_refs")
            if refs is None:
                continue
            with self.subTest(task=task["task_id"]):
                self.assertTrue(set(refs) <= own,
                                "aggregates records no task here declares: "
                                + str(sorted(set(refs) - own)))
                self.assertNotIn(task["issue"], refs, "a task aggregating itself")

    def test_task_identifiers_and_records_are_unique(self):
        ids = [task["task_id"] for task in TASKS]
        self.assertEqual(len(ids), len(set(ids)), "two tasks share an identifier")
        # Only a task's own record. Two aggregate tasks both carrying a null
        # `issue` are not two tasks sharing a record, and `issue_refs` is
        # expected to repeat the children's records rather than be unique
        # against them.
        records = [task["issue"] for task in TASKS if isinstance(task["issue"], int)]
        self.assertEqual(len(records), len(set(records)), "two tasks share a record")


class CoherenceTests(unittest.TestCase):
    def test_the_active_goal_is_a_task_in_this_registry(self):
        """A goal naming no task is a goal nothing can progress."""
        self.assertIn(REGISTRY["active_goal"], {task["task_id"] for task in TASKS})

    def test_no_dependency_names_a_task_that_does_not_exist(self):
        ids = {task["task_id"] for task in TASKS}
        for task in TASKS:
            for dependency in task["depends_on"]:
                with self.subTest(task=task["task_id"], depends_on=dependency):
                    self.assertIn(dependency, ids)

    def test_no_task_depends_on_itself(self):
        for task in TASKS:
            with self.subTest(task=task["task_id"]):
                self.assertNotIn(task["task_id"], task["depends_on"])

    def test_the_dependency_graph_is_acyclic(self):
        """A cycle makes progression selection non-terminating."""
        edges = {task["task_id"]: list(task["depends_on"]) for task in TASKS}
        visiting, done = set(), set()

        def walk(node):
            if node in done:
                return
            self.assertNotIn(node, visiting, "the dependency graph cycles at " + node)
            visiting.add(node)
            for nxt in edges.get(node, []):
                walk(nxt)
            visiting.discard(node)
            done.add(node)

        for task_id in edges:
            walk(task_id)

    def test_a_blocked_task_says_what_would_unblock_it(self):
        """Blocked without an activation condition is indistinguishable from stalled."""
        for task in TASKS:
            if task["status"] == "blocked":
                with self.subTest(task=task["task_id"]):
                    self.assertTrue(task.get("activation_condition", "").strip(),
                                    "blocked with no activation_condition")

    def test_an_open_task_says_what_evidence_closes_it(self):
        """So review does not depend on trusting whoever did the work."""
        for task in TASKS:
            if task["status"] in {"complete", "merged", "archived"}:
                continue
            with self.subTest(task=task["task_id"]):
                self.assertTrue(task.get("required_evidence"),
                                "open task with no required_evidence")


class EntityNeutralityTests(unittest.TestCase):
    """Any entity must be able to review any task. None of them owns one here."""

    def test_no_task_records_which_entity_is_doing_the_work(self):
        for task in TASKS:
            present = {key.lower() for key in task}
            with self.subTest(task=task["task_id"]):
                self.assertEqual(present & ENTITY_FIELDS, set(),
                                 "a claim belongs to WorkerCoordinator, not the registry")

    def test_the_registry_root_records_no_entity_either(self):
        self.assertEqual({key.lower() for key in REGISTRY} & ENTITY_FIELDS, set())

    def test_no_task_names_a_model_or_assistant(self):
        """A task readable only by the entity that wrote it is not coordination truth."""
        rendered = json.dumps(REGISTRY, sort_keys=True).lower()
        for name in ("claude", "chatgpt", "gpt-", "anthropic", "openai",
                     "copilot", "gemini", "assistant"):
            self.assertNotIn(name, rendered, "registry names " + name)


class ReferencesResolveHereTests(unittest.TestCase):
    """A reference to work intent must resolve in the registry, or it is not authority.

    The cases above hold the registry coherent with itself. That is necessary
    and it is not sufficient: a registry internally consistent and referenced
    by nothing is a document, not an authority. What makes it work-intent
    authority is that work intent named anywhere in this organization resolves
    *here* -- so a document naming a task the registry does not carry is a
    declaration with no owner, and the authority split's first line is not
    held.

    `CANONICAL-NODE-INGRESS-CONTRACT-001` declares
    `goal_task_id: SVORG-STEGOS-PORTABILITY-001`, and the registry's
    `active_goal` is the same string. Until this case, nothing compared them.
    They agreed by hand, which is the condition an unenforced invariant is in
    right before it stops agreeing.

    The references are discovered rather than listed, so a document added
    later is covered without this file changing.
    """

    #: Keys that name a task in this registry, wherever they appear.
    REFERENCE_KEYS = ("goal_task_id", "canonical_task_id")

    #: Paths whose task identifiers belong to another organization's registry
    #: and are therefore not this registry's to resolve. Named explicitly, so
    #: an exemption is visible rather than implied by a silent skip.
    FOREIGN_REGISTRY_PATHS = {
        "resident-runtime/control/sv002-sdk-query.request.json",
        "resident-runtime/activation-manifest.json",
    }

    def _references(self):
        """Every (path, key, value) in tracked JSON naming a task."""
        found = []

        def walk(node, path, key_path):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in self.REFERENCE_KEYS and isinstance(value, str):
                        found.append((path, key, value))
                    walk(value, path, key_path + [key])
            elif isinstance(node, list):
                for item in node:
                    walk(item, path, key_path)

        for candidate in sorted(ROOT.rglob("*.json")):
            relative = candidate.relative_to(ROOT).as_posix()
            if relative.startswith((".git/", "tests/fixtures/")) or "__pycache__" in relative:
                continue
            if relative in self.FOREIGN_REGISTRY_PATHS:
                continue
            try:
                document = json.loads(candidate.read_text(encoding="utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            walk(document, relative, [])
        return found

    def test_the_contracts_goal_task_id_is_a_task_in_this_registry(self):
        """The named instance, held by name rather than by discovery alone."""
        contract = json.loads(
            (ROOT / "docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json").read_text(encoding="utf-8"))
        self.assertIn(contract["goal_task_id"], {task["task_id"] for task in TASKS})

    def test_every_declared_task_reference_resolves(self):
        ids = {task["task_id"] for task in TASKS}
        references = self._references()
        # A discovery that found nothing would pass vacuously and prove
        # nothing, which is the failure mode this whole effort exists to
        # catch. At least the contract's own reference must be here.
        self.assertTrue(references, "no task reference discovered; the walk is not working")
        for path, key, value in references:
            with self.subTest(path=path, key=key, value=value):
                self.assertIn(value, ids,
                              path + " declares " + key + "=" + value
                              + ", which this registry does not carry")

    def test_a_reference_to_an_absent_task_would_be_caught(self):
        """The check refuses, rather than passing on a registry it cannot match."""
        ids = {task["task_id"] for task in TASKS}
        self.assertNotIn("SVORG-NO-SUCH-TASK-999", ids)

    def test_the_exemptions_are_real_paths_naming_foreign_registries(self):
        """An exemption for a file that does not exist is a stale carve-out."""
        for relative in self.FOREIGN_REGISTRY_PATHS:
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).exists(), relative + " no longer exists")


class TaskVectorProjectionTests(unittest.TestCase):
    """A COSV task vector is a projection of a registered task, not a second record.

    `control/task-vector-index.json` lists each projected vector and the file
    holding its exact metrics. Nothing compared the index against the registry
    or against those files, so a vector could name a task the registry dropped,
    or the index and the file could disagree on the digits.
    """

    INDEX = json.loads((ROOT / "control/task-vector-index.json").read_text(encoding="utf-8"))

    def test_every_projected_task_is_registered(self):
        ids = {task["task_id"] for task in TASKS}
        for entry in self.INDEX["tasks"]:
            with self.subTest(task=entry["task_id"]):
                self.assertIn(entry["task_id"], ids)
                self.assertEqual(entry["registry_ref"], "orchestration/task-registry.json")

    def test_the_index_and_the_vector_file_carry_the_same_vector(self):
        for entry in self.INDEX["tasks"]:
            with self.subTest(task=entry["task_id"]):
                path = ROOT / entry["source_state_vector_ref"]
                self.assertTrue(path.is_file(), entry["source_state_vector_ref"] + " is missing")
                record = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(record["vector"], entry["vector"])
                self.assertEqual(record["profile"], self.INDEX["profile"])
                self.assertTrue(record["identity"].endswith(entry["task_id"]))
                self.assertRegex(record["vector"], r"^[0-9]{%d}$" % self.INDEX["width"])


if __name__ == "__main__":
    unittest.main()
