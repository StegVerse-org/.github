"""The repository chain is durable in its own subtree of the designated organization ledger ref.

`organization-ledger-transition.yml` materialized the repository ledger under
the runner's temporary directory, so every run opened a fresh chain at genesis
and the only way to reconstruct repository history was organization replay,
which `contract.json` `replay_rule` forbids (StegVerse-org/.github#118). The
organization ledger ref was the only designated durable location, and no
second ref may be named by assumption. So the repository chain now lives in a
subtree of that same ref: `git+<repo>#<ref>:<namespace>` opens a store that
sees only its own `HEAD.json` and `receipts/`, published by the same
compare-and-swap and the same fast-forward push.

These pin that: a namespaced locator parses and prints; a namespace may not
shadow a ledger key; both ledgers share one ref without colliding and the
organization's own integrity checks still pass; a chain written by one
materialization is the chain the next one extends; the readback walks the
repository chain through repository receipts alone and fails closed on a
break, a missing retention or an ingress receipt it does not hold; and the
contract and the workflow bind the root from the designated ref, not from
`runner.temp`.

Temporary repositories only. No location here is the organization's ledger.
Source validation only; no authority effect is claimed.
"""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ledger_store = _load("durable_ledger_store", "resident-runtime/ledger_store.py")
organization = _load("durable_org_append", "resident-runtime/aggregate_repo_transition.py")
repository = _load("durable_repo_emit", ".stegverse/transition-ledger/emit.py")
readback = _load("durable_readback", "resident-runtime/organization_ledger_readback.py")

REF = "refs/test/organization-ledger"
NAMESPACE = "repository-ledger/StegVerse-org/.github"
BEFORE = "sha256:" + "a" * 64
AFTER = "sha256:" + "b" * 64
EPOCH = 4400


def git(repository_path, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_DIR"] = str(repository_path)
    return subprocess.run(["git", *args], capture_output=True, check=True, env=env).stdout


def tree(repository_path, ref=REF):
    listed = git(repository_path, "ls-tree", "-r", "-z", "--name-only", ref)
    return {name for name in listed.decode().split("\0") if name}


class _OneRef(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.repo = Path(self._dir.name) / "ledger.git"
        self.organization_location = "git+" + str(self.repo) + "#" + REF
        self.repository_location = self.organization_location + ":" + NAMESPACE
        self.env = {"STEGVERSE_ORG_LEDGER_ROOT": self.organization_location,
                    "STEGVERSE_REPO_LEDGER_ROOT": self.repository_location}

    def repository_append(self, number):
        """One repository append, as one materialization performs it: a fresh store each time."""
        with mock.patch.dict(os.environ, self.env):
            return repository.append("durable-" + str(number), "TEST", BEFORE, AFTER,
                                     {"n": number}, "NONE", hb_epoch=EPOCH)

    def organization_consume(self, receipt):
        with mock.patch.dict(os.environ, self.env):
            return organization.append(receipt, "REPO_STATE_PROPAGATION", BEFORE, AFTER,
                                       {}, "NONE", hb_epoch=EPOCH)


class LocatorTests(_OneRef):
    def test_a_namespaced_locator_parses_and_prints_the_same(self):
        located = ledger_store.parse_locator(self.repository_location)
        self.assertEqual(located.ref, REF)
        self.assertEqual(located.namespace, NAMESPACE)
        self.assertEqual(str(located), "git+" + str(self.repo.resolve()) + "#" + REF + ":" + NAMESPACE)
        self.assertEqual(ledger_store.parse_locator(str(located)), located)
        store = ledger_store.open_store(located)
        self.assertEqual((store.ref, store.namespace), (REF, NAMESPACE))
        self.assertIsNone(ledger_store.parse_locator(self.organization_location).namespace)

    def test_a_namespace_is_a_normalized_relative_path_that_shadows_no_ledger_key(self):
        for namespace in ("", "/x", "x/", "a//b", "..", "a/../b", ".", "a/./b", "HEAD.json",
                          "receipts", "receipts/x", "source-receipts", "a:b", "a b"):
            with self.subTest(namespace):
                with self.assertRaises(ledger_store.LedgerLocatorInvalid):
                    ledger_store.parse_locator(self.organization_location + ":" + namespace)
        self.assertFalse(self.repo.exists())

    def test_the_locator_of_a_key_names_the_subtree(self):
        store = ledger_store.open_store(self.repository_location)
        self.assertEqual(store.locator(ledger_store.HEAD_KEY),
                         "git+" + str(self.repo) + "#" + REF + ":" + NAMESPACE + "/HEAD.json")


class OneRefTwoLedgersTests(_OneRef):
    def test_both_ledgers_share_the_ref_and_neither_sees_the_other(self):
        first = self.repository_append(1)
        consumed = self.organization_consume(first)
        self.assertEqual(tree(self.repo), {
            "HEAD.json",
            ledger_store.receipt_key(consumed["receipt_sha256"]),
            ledger_store.source_key(first["receipt_sha256"]),
            NAMESPACE + "/HEAD.json",
            NAMESPACE + "/" + ledger_store.receipt_key(first["receipt_sha256"]),
        })
        organization_store = ledger_store.open_store(self.organization_location)
        repository_store = ledger_store.open_store(self.repository_location)
        self.assertEqual(organization_store.get(ledger_store.HEAD_KEY)["receipt_sha256"], consumed["receipt_sha256"])
        self.assertEqual(repository_store.get(ledger_store.HEAD_KEY)["receipt_sha256"], first["receipt_sha256"])
        self.assertEqual(organization_store.list_prefix(ledger_store.RECEIPT_PREFIX),
                         {ledger_store.receipt_key(consumed["receipt_sha256"])})
        self.assertEqual(repository_store.list_prefix(ledger_store.RECEIPT_PREFIX),
                         {ledger_store.receipt_key(first["receipt_sha256"])})
        self.assertEqual(repository_store.list_prefix(ledger_store.SOURCE_PREFIX), set())
        # One ref, one history: every transaction is a commit on the same ref.
        self.assertEqual(len(git(self.repo, "rev-list", REF).split()), 2)
        self.assertEqual(git(self.repo, "for-each-ref", "--format=%(refname)").split(), [REF.encode()])

    def test_the_organizations_integrity_checks_still_pass_beside_the_subtree(self):
        # `_validate_existing_head` enumerates `receipts/` and `source-receipts/`
        # and refuses orphans; the repository subtree must be invisible to it.
        self.organization_consume(self.repository_append(1))
        self.organization_consume(self.repository_append(2))
        with mock.patch.dict(os.environ, self.env):
            store = ledger_store.open_store(organization.ledger_root())
            self.assertIsNotNone(organization._validate_existing_head(store))
        result = readback.readback(self.organization_location)
        self.assertEqual((result["disposition"], result["chain_length"]), ("ALLOW", 2))

    def test_the_chain_a_materialization_wrote_is_the_chain_the_next_one_extends(self):
        first = self.repository_append(1)
        self.assertIsNone(first["previous_receipt_sha256"])
        second = self.repository_append(2)
        third = self.repository_append(3)
        self.assertEqual(second["previous_receipt_sha256"], first["receipt_sha256"])
        self.assertEqual(third["previous_receipt_sha256"], second["receipt_sha256"])
        store = ledger_store.open_store(self.repository_location)
        chain = list(repository.chain(store, store.get(ledger_store.HEAD_KEY)))
        self.assertEqual([r["transition_id"] for r in chain], ["durable-3", "durable-2", "durable-1"])
        # An exact retry is answered from the durable chain, not minted again.
        with mock.patch.dict(os.environ, self.env):
            self.assertEqual(repository.append("durable-2", "TEST", BEFORE, AFTER, {"n": 2}, "NONE",
                                               hb_epoch=EPOCH, idempotent_on=("n",))["receipt_sha256"],
                             second["receipt_sha256"])


class RepositoryReadbackTests(_OneRef):
    def test_the_readback_walks_repository_receipts_alone_and_finds_them_retained(self):
        receipts = [self.repository_append(n) for n in (1, 2)]
        consumed = [self.organization_consume(r) for r in receipts]
        result = readback.readback(self.organization_location)
        chain = readback.repository_readback(self.organization_location, NAMESPACE, result)
        self.assertEqual(chain["chain_length"], 2)
        self.assertEqual(chain["genesis_receipt_sha256"], receipts[0]["receipt_sha256"])
        self.assertEqual(chain["head_receipt_sha256"], receipts[1]["receipt_sha256"])
        self.assertTrue(chain["every_receipt_retained_in_organization_ledger"])
        self.assertFalse(chain["replay_read_organization_receipts"])
        self.assertEqual(chain["location"], self.repository_location.replace(str(self.repo), str(self.repo.resolve())))
        # With an ingress result: the repository receipt it names is in the
        # chain and is the source the named organization receipt consumed.
        ingress = {"repository_receipt_sha256": receipts[1]["receipt_sha256"],
                   "organization_receipt_sha256": consumed[1]["receipt_sha256"]}
        result["ingress_organization_receipt_sha256"] = consumed[1]["receipt_sha256"]
        bound = readback.repository_readback(self.organization_location, NAMESPACE, result, ingress)
        self.assertTrue(bound["ingress_repository_receipt_in_chain"])
        self.assertEqual(bound["consumed_by_organization_receipt_sha256"], consumed[1]["receipt_sha256"])
        ingress["repository_receipt_sha256"] = receipts[0]["receipt_sha256"]
        with self.assertRaises(readback.ReadbackRefused) as refused:
            readback.repository_readback(self.organization_location, NAMESPACE, result, ingress)
        self.assertEqual(refused.exception.failed_predicate, "ORGANIZATION_RECEIPT_CONSUMES_THE_REPOSITORY_RECEIPT")
        ingress["repository_receipt_sha256"] = "sha256:" + "f" * 64
        with self.assertRaises(readback.ReadbackRefused) as refused:
            readback.repository_readback(self.organization_location, NAMESPACE, result, ingress)
        self.assertEqual(refused.exception.failed_predicate, "INGRESS_REPOSITORY_RECEIPT_IS_IN_THE_REPOSITORY_LEDGER")

    def test_an_empty_subtree_a_break_and_a_missing_retention_each_fail_closed(self):
        with self.assertRaises(readback.ReadbackRefused) as refused:
            readback.repository_readback(self.organization_location, NAMESPACE, {})
        self.assertEqual(refused.exception.failed_predicate, "REPOSITORY_LEDGER_HEAD_PRESENT")
        first = self.repository_append(1)
        with self.assertRaises(readback.ReadbackRefused) as refused:
            readback.repository_readback(self.organization_location, NAMESPACE, {})
        self.assertEqual(refused.exception.failed_predicate, "REPOSITORY_RECEIPT_RETAINED_IN_ORGANIZATION_LEDGER")
        self.organization_consume(first)
        second = self.repository_append(2)
        self.organization_consume(second)
        # Drop the genesis node from the subtree: the walk from HEAD breaks.
        path = NAMESPACE + "/" + ledger_store.receipt_key(first["receipt_sha256"])
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_DIR=str(self.repo), GIT_INDEX_FILE=str(Path(self._dir.name) / "index"),
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@invalid")
        subprocess.run(["git", "read-tree", REF], check=True, env=env, capture_output=True)
        subprocess.run(["git", "update-index", "--index-info"], input=("0 " + "0" * 40 + "\t" + path + "\n").encode(),
                       check=True, env=env, capture_output=True)
        broken_tree = subprocess.run(["git", "write-tree"], check=True, env=env, capture_output=True).stdout.decode().strip()
        commit = subprocess.run(["git", "commit-tree", broken_tree, "-p", REF, "-m", "break"], check=True,
                                env=env, capture_output=True).stdout.decode().strip()
        subprocess.run(["git", "update-ref", REF, commit], check=True, env=env, capture_output=True)
        with self.assertRaises(readback.ReadbackRefused) as refused:
            readback.repository_readback(self.organization_location, NAMESPACE, {})
        self.assertEqual(refused.exception.failed_predicate, "REPOSITORY_CHAIN_VERIFIES")
        # The organization chain is untouched by the break in the subtree.
        self.assertEqual(readback.readback(self.organization_location)["chain_length"], 2)


class BindingTests(unittest.TestCase):
    def test_the_contract_binds_the_repository_chain_into_the_designated_ref(self):
        contract = json.loads((ROOT / ".stegverse/transition-ledger/contract.json").read_text())
        org_contract = json.loads((ROOT / ".stegverse/transition-ledger/org-contract.json").read_text())
        location = contract["repository_ledger_location"]
        self.assertEqual(location["repository"], org_contract["organization_ledger_repository"])
        self.assertEqual(location["ref"], org_contract["organization_ledger_ref"])
        self.assertIs(location["new_ledger_root"], False)
        self.assertEqual(location["namespace"], "repository-ledger/" + contract["repository"])
        parsed = ledger_store.parse_locator("git+/checkout#" + location["ref"] + ":" + location["namespace"])
        self.assertEqual(parsed.namespace, location["namespace"])
        self.assertEqual(contract["replay_rule"], "REPOSITORY_REPLAY_MUST_NOT_REQUIRE_ORGANIZATION_OR_ECOSYSTEM_REPLAY")

    def test_the_transition_workflow_binds_the_root_from_the_contract_not_the_runner(self):
        workflow = (ROOT / ".github/workflows/organization-ledger-transition.yml").read_text()
        self.assertNotIn("runner.temp }}/repo-ledger", workflow)
        self.assertIn('export STEGVERSE_REPO_LEDGER_ROOT="git+$GITHUB_WORKSPACE#$LEDGER_REF:$REPO_LEDGER_NAMESPACE"', workflow)
        self.assertIn("repository_ledger_location", workflow)
        self.assertIn('--repository-namespace "$REPO_LEDGER_NAMESPACE"', workflow)
        # One push publishes both chains; no second ref is pushed.
        self.assertEqual(workflow.count("git push origin"), 1)


if __name__ == "__main__":
    unittest.main()
