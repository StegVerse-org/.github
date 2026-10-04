"""Repository transitions reach the organization chain, in order and exactly once.

`organization_scope_rule` is that every transition occurring within the
organization emits an organization receipt. Repositories appended their own and
nothing carried them up, so the organization's record began at its own boundary.

Nothing here is a crossing: the repositories are inside this organization, so no
boundary is crossed and no Interlock/InTr is involved. These tests assert that
the propagation preserves repository order, verifies each receipt before
carrying it, and is a no-op on a second run -- the three properties that make
the organization chain readable as a record of what actually happened.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "StegVerse-org/LLM-adapter"
ORGANIZATION_RECEIPT = "stegverse.organization-transition-receipt/v1"


def _module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


propagation = _module("propagate_repository_receipts",
                      "resident-runtime/propagate_repository_receipts.py")
organization_ledger = _module("aggregate_repo_transition",
                              "resident-runtime/aggregate_repo_transition.py")


class RepositoryPropagationTests(unittest.TestCase):
    def setUp(self):
        self._state = tempfile.TemporaryDirectory()
        state = Path(self._state.name)
        self._previous = {name: os.environ.get(name) for name in
                          ("STEGVERSE_REPO_LEDGER_HOME", "STEGVERSE_ORG_LEDGER_ROOT")}
        os.environ["STEGVERSE_REPO_LEDGER_HOME"] = str(state / "repo-ledgers")
        os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = str(state / "org")
        self.repository_root = state / "repo-ledgers" / REPOSITORY
        self.organization_root = state / "org"
        self.addCleanup(self._restore)

    def _restore(self):
        for name, previous in self._previous.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
        self._state.cleanup()

    def repository_receipt(self, transition_id, previous=None, sequence=1):
        """A repository receipt written the way a repository emitter writes one."""
        body = {"schema": "stegverse.repo-transition-receipt/v1",
                "repository": REPOSITORY,
                "transition_id": transition_id,
                "transition_class": "NODE_INGRESS_ADMITTED",
                "predecessor_state_sha256": "sha256:" + f"{sequence:064d}",
                "successor_state_sha256": "sha256:" + f"{sequence + 1:064d}",
                "evidence": {"transition_id": transition_id},
                "authority_effect": "NONE",
                "hb_reference": {"epoch": 32 + sequence, "progression_dependency": "OSCILLATOR_ONLY"},
                "ordering": "OSCILLATOR_HEARTBEAT_EPOCH_ONLY",
                "previous_receipt_sha256": previous}
        digest = organization_ledger.sha(body)
        receipt = {**body, "receipt_sha256": digest}
        receipts = self.repository_root / "receipts"
        receipts.mkdir(parents=True, exist_ok=True)
        (receipts / (digest.split(":", 1)[1] + ".json")).write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        (self.repository_root / "HEAD.json").write_text(json.dumps(
            {"repository": REPOSITORY, "receipt_sha256": digest}, indent=2, sort_keys=True) + "\n")
        return receipt

    def organization_chain(self):
        """Organization receipts in chain order, genesis first."""
        receipts = {}
        for path in (self.organization_root / "receipts").glob("*.json"):
            receipt = json.loads(path.read_text())
            if receipt.get("schema") == ORGANIZATION_RECEIPT:
                receipts[receipt["receipt_sha256"]] = receipt
        head_path = self.organization_root / "HEAD.json"
        if not head_path.is_file():
            return []
        ordered, cursor = [], json.loads(head_path.read_text())["receipt_sha256"]
        while cursor in receipts:
            ordered.append(receipts[cursor])
            cursor = receipts[cursor]["previous_receipt_sha256"]
        ordered.reverse()
        return ordered

    def test_a_repository_transition_reaches_the_organization_chain(self):
        receipt = self.repository_receipt("NODE_INGRESS_ADMITTED:one")
        result = propagation.propagate(REPOSITORY, hb_epoch=32)
        self.assertIs(result["repository_ledger_present"], True)
        self.assertEqual(len(result["propagated"]), 1)
        chain = self.organization_chain()
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0]["source_repository"], REPOSITORY)
        self.assertEqual(chain[0]["repo_receipt_sha256"], receipt["receipt_sha256"])
        self.assertEqual(chain[0]["repo_transition_id"], "NODE_INGRESS_ADMITTED:one")
        self.assertEqual(chain[0]["org_transition_class"], "REPO_STATE_PROPAGATION")

    def test_order_on_the_organization_chain_is_the_repository_order(self):
        """The organization must not imply a sequence the repository never had."""
        first = self.repository_receipt("NODE_INGRESS_ADMITTED:first", sequence=1)
        second = self.repository_receipt("NODE_INGRESS_ADMITTED:second",
                                         previous=first["receipt_sha256"], sequence=2)
        third = self.repository_receipt("NODE_INGRESS_ADMITTED:third",
                                        previous=second["receipt_sha256"], sequence=3)
        propagation.propagate(REPOSITORY, hb_epoch=32)
        self.assertEqual([entry["repo_transition_id"] for entry in self.organization_chain()],
                         ["NODE_INGRESS_ADMITTED:first", "NODE_INGRESS_ADMITTED:second",
                          "NODE_INGRESS_ADMITTED:third"])
        self.assertEqual([entry["repo_receipt_sha256"] for entry in self.organization_chain()],
                         [first["receipt_sha256"], second["receipt_sha256"],
                          third["receipt_sha256"]])

    def test_a_second_run_carries_nothing_and_fails_nothing(self):
        """Idempotent by reading what the chain already carries, not by a marker."""
        self.repository_receipt("NODE_INGRESS_ADMITTED:once")
        first = propagation.propagate(REPOSITORY, hb_epoch=32)
        second = propagation.propagate(REPOSITORY, hb_epoch=32)
        self.assertEqual(len(first["propagated"]), 1)
        self.assertEqual(second["propagated"], [])
        self.assertEqual(len(second["skipped"]), 1)
        self.assertEqual(len(self.organization_chain()), 1)

    def test_a_new_transition_after_propagation_is_carried_and_the_old_is_not(self):
        first = self.repository_receipt("NODE_INGRESS_ADMITTED:earlier", sequence=1)
        propagation.propagate(REPOSITORY, hb_epoch=32)
        self.repository_receipt("NODE_INGRESS_ADMITTED:later",
                                previous=first["receipt_sha256"], sequence=2)
        result = propagation.propagate(REPOSITORY, hb_epoch=33)
        self.assertEqual([entry["repository_transition_id"] for entry in result["propagated"]],
                         ["NODE_INGRESS_ADMITTED:later"])
        self.assertEqual(result["skipped"], [first["receipt_sha256"]])
        self.assertEqual(len(self.organization_chain()), 2)

    def test_a_receipt_that_does_not_verify_never_reaches_the_organization(self):
        """Unverified evidence on the organization chain is worse than none."""
        receipt = self.repository_receipt("NODE_INGRESS_ADMITTED:tampered")
        path = (self.repository_root / "receipts"
                / (receipt["receipt_sha256"].split(":", 1)[1] + ".json"))
        tampered = json.loads(path.read_text())
        tampered["transition_class"] = "SOMETHING_ELSE"
        path.write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n")
        with self.assertRaises(SystemExit) as refused:
            propagation.propagate(REPOSITORY, hb_epoch=32)
        self.assertIn("REPOSITORY_LEDGER_RECEIPT_HASH_MISMATCH", str(refused.exception))
        self.assertEqual(self.organization_chain(), [])

    def test_an_absent_repository_ledger_is_not_a_failure(self):
        """A capability that did not materialize here has nothing to carry."""
        result = propagation.propagate("StegVerse-org/telemetry", hb_epoch=32)
        self.assertIs(result["repository_ledger_present"], False)
        self.assertEqual(result["propagated"], [])
        self.assertEqual(self.organization_chain(), [])

    def test_the_repositories_in_scope_come_from_the_service_registry(self):
        """A list written in the propagation step would be a second answer."""
        declared = propagation.declared_repositories()
        registry = json.loads((ROOT / "org-boundary/registry/services.json").read_text())
        expected = sorted({service["repository"] for service in registry["services"]
                           if str(service.get("repository", "")).startswith("StegVerse-org/")})
        self.assertEqual(declared, expected)
        self.assertIn(REPOSITORY, declared)

    def test_the_sweep_names_no_repository_and_reports_what_it_carried(self):
        self.repository_receipt("NODE_INGRESS_ADMITTED:swept")
        result = propagation.propagate_all(hb_epoch=32)
        self.assertEqual(result["receipts_propagated"], 1)
        self.assertEqual(result["repositories_present"], 1)
        self.assertEqual(result["repositories_declared"], len(propagation.declared_repositories()))
        self.assertEqual(result["authority_effect"], "NONE_PROPAGATION_ONLY")

    def test_propagation_records_that_it_crossed_no_boundary(self):
        """Intra-organization: the InTr hop is organization to Master Records."""
        self.repository_receipt("NODE_INGRESS_ADMITTED:intra")
        result = propagation.propagate(REPOSITORY, hb_epoch=32)
        self.assertIs(result["crossed_an_organization_boundary"], False)
        self.assertIs(result["interlock_intr_involved"], False)
        evidence = self.organization_chain()[0]["boundary_evidence"]
        self.assertIs(evidence["crossed_an_organization_boundary"], False)
        self.assertIs(evidence["interlock_intr_involved"], False)
        self.assertEqual(evidence["propagated_by"],
                         "resident-runtime/propagate_repository_receipts.py")


if __name__ == "__main__":
    unittest.main()


#: The directory the resident cycle writes its own consumption state into. It
#: is not repository content: the node state root is told to the node, so a run
#: leaves nothing behind in the checkout, and the propagation workflow asserts
#: exactly that.
#:
#: Scoped to what that assertion covers and no wider. `resident-runtime/control`
#: looks similar and is not the same thing -- it carries a declared one-shot
#: request that `resident_executor.py` and the SV-002 roundtrip both read, so it
#: is content, and a guard sweeping it in would refuse the repository's own
#: input.
RUNTIME_STATE_PATHS = ("resident-runtime/federation",)


class NoRuntimeStateIsTrackedTests(unittest.TestCase):
    """A run's own state is not repository content, and must not be committed.

    The propagation workflow already asserts that a cycle leaves nothing behind
    in the checkout. What it could not see is an artifact committed *before* it
    runs: a `seen.d` consumption marker reached `main` in f2ee1df, which made
    that assertion fail on every branch from then on, and the workflow's own
    path filter did not watch the directory the artifact landed in -- so the
    check that catches it never ran on the change that caused it.

    This case closes that: it reads the git index rather than the filesystem,
    so a committed artifact fails here, locally, on any path that runs this
    module.
    """

    def tracked_under(self, prefix):
        listed = subprocess.run(["git", "ls-files", "--", prefix],
                                cwd=ROOT, capture_output=True, text=True)
        if listed.returncode != 0:
            self.skipTest("not a git checkout, so the index cannot be read")
        return [line for line in listed.stdout.splitlines() if line.strip()]

    def test_no_resident_runtime_state_is_tracked(self):
        for prefix in RUNTIME_STATE_PATHS:
            with self.subTest(prefix=prefix):
                self.assertEqual(
                    self.tracked_under(prefix), [],
                    prefix + " holds a run's own state; committing it makes the "
                    "cycle's 'leaves nothing behind' assertion fail on every branch")

    def test_the_declared_one_shot_request_is_still_content(self):
        """The guard is narrow on purpose, and this is what it must not sweep in."""
        self.assertEqual(
            self.tracked_under("resident-runtime/control/sv002-sdk-query.request.json"),
            ["resident-runtime/control/sv002-sdk-query.request.json"])

    def test_the_check_reads_the_index_rather_than_the_filesystem(self):
        """An uncommitted local run is not a committed artifact.

        Demonstrated without writing into the checkout. This module runs in CI
        *before* the step asserting the cycle left nothing behind, so a case
        that created `resident-runtime/federation` to prove a point would break
        the assertion it exists to protect -- and a cleanup that failed would
        break it silently.
        """
        self.assertEqual(self.tracked_under("resident-runtime/federation/seen.d"), [])
        self.assertEqual(self.tracked_under("resident-runtime/no-such-path"), [])

    def test_this_module_leaves_the_runtime_state_directory_absent(self):
        """Whatever else these cases do, the next CI step depends on this."""
        for prefix in RUNTIME_STATE_PATHS:
            with self.subTest(prefix=prefix):
                self.assertFalse(
                    (ROOT / prefix).exists(),
                    prefix + " exists in the checkout after this module ran; the "
                    "propagation workflow's next step asserts it does not")

