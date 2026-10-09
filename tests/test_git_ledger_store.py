"""A ledger store on a git ref, held to the POSIX store's behaviour.

`GitLedgerStore` is the key-value sibling `ledger_store` was cut to admit: the
same keys and documents, one commit per transaction, published by `git
update-ref`'s atomic compare-and-swap. These regressions run against
temporary bare repositories only. They check parity with `PosixLedgerStore`
operation by operation, that a lost compare-and-swap publishes nothing, that
contended appenders leave one intact chain, that a chain broken in the ref is
detected, that receipts cannot be replaced, and that no store is selected and
nothing is written unless a location is supplied.

No location here is, or is named as, the organization's ledger. Source
validation only. No authority effect is claimed.
"""
import importlib.util
import json
import multiprocessing
import os
import subprocess
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ledger_store = _load("git_ledger_store", "resident-runtime/ledger_store.py")
organization = _load("git_org_append", "resident-runtime/aggregate_repo_transition.py")
repository = _load("git_repo_emit", ".stegverse/transition-ledger/emit.py")

REF = "refs/test/ledger"
LEDGER_VARIABLES = ("STEGVERSE_ORG_LEDGER_ROOT", "STEGVERSE_REPO_LEDGER_ROOT")
STATE_BEFORE = "sha256:" + "a" * 64
STATE_AFTER = "sha256:" + "b" * 64
DIGEST = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64
EPOCH = 4400


def git(repository_path, *args, stdin=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_DIR=str(repository_path), GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@invalid",
               GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@invalid")
    return subprocess.run(["git", *args], input=stdin, capture_output=True, check=True, env=env).stdout


def tree(repository_path, ref=REF):
    """Every path the ref's tree holds."""
    listed = git(repository_path, "ls-tree", "-r", "-z", "--name-only", ref)
    return {name for name in listed.decode().split("\0") if name}


def source_receipt(number):
    body = {"schema": "stegverse.repo-transition-receipt/v1",
            "repository": "StegVerse-org/StegVerse-SDK",
            "transition_id": "git-store-" + str(number)}
    return {**body, "receipt_sha256": organization.sha(body)}


def reachable(store):
    cursor = (store.get(ledger_store.HEAD_KEY) or {}).get("receipt_sha256")
    visited = []
    while cursor:
        if cursor in visited:
            raise AssertionError("cycle")
        visited.append(cursor)
        record = store.get(ledger_store.receipt_key(cursor))
        if record is None:
            raise AssertionError("missing receipt " + cursor)
        body = {k: v for k, v in record.items() if k != "receipt_sha256"}
        if organization.sha(body) != cursor:
            raise AssertionError("receipt does not hash to its address " + cursor)
        cursor = record.get("previous_receipt_sha256")
    return visited


def org_append_worker(locator, number, results):
    os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = locator
    try:
        organization.append(source_receipt(number), "REPO_STATE_PROPAGATION",
                            STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=EPOCH)
        results.put("OK")
    except Exception as error:
        results.put(type(error).__name__ + ":" + str(error))


class _Work(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.work = Path(self._dir.name)
        self.repo = self.work / "ledger.git"

    def git_store(self, ref=REF):
        store = ledger_store.GitLedgerStore(self.repo, ref)
        store.initialize()
        return store


class ParityWithPosixTests(_Work):
    """Every operation, run on both stores, answers the same."""

    def test_every_operation_answers_as_the_posix_store_does(self):
        posix = ledger_store.PosixLedgerStore(self.work / "posix")
        posix.initialize()
        git_store = self.git_store()
        head, receipt, source = ledger_store.HEAD_KEY, ledger_store.receipt_key(DIGEST), ledger_store.source_key(OTHER)
        steps = [
            ("get", (head,)), ("exists", (head,)), ("list_prefix", (ledger_store.RECEIPT_PREFIX,)),
            ("compare_and_swap", (head, None, {"receipt_sha256": DIGEST})),
            ("compare_and_swap", (head, None, {"receipt_sha256": OTHER})),
            ("put", (receipt, {"receipt_sha256": DIGEST, "nested": {"n": [1, 2]}})),
            ("get", (receipt,)), ("exists", (receipt,)),
            ("append_transaction", (ledger_store.receipt_key(OTHER), {"receipt_sha256": OTHER},
                                    {"receipt_sha256": "sha256:" + "c" * 64}, {"receipt_sha256": OTHER})),
            ("append_transaction", (ledger_store.receipt_key(OTHER), {"receipt_sha256": OTHER},
                                    {"receipt_sha256": DIGEST}, {"receipt_sha256": OTHER},
                                    {source: {"source": True}})),
            ("get", (head,)), ("get", (source,)),
            ("list_prefix", (ledger_store.RECEIPT_PREFIX,)), ("list_prefix", (ledger_store.SOURCE_PREFIX,)),
            ("list_prefix", ("absent/",)),
        ]
        for name, args in steps:
            with self.subTest(name, args=args):
                self.assertEqual(getattr(git_store, name)(*args), getattr(posix, name)(*args))

    def test_a_document_is_stored_as_the_bytes_a_posix_root_holds(self):
        posix = ledger_store.PosixLedgerStore(self.work / "posix")
        git_store = self.git_store()
        for store in (posix, git_store):
            store.put(ledger_store.HEAD_KEY, {"b": 2, "a": 1})
        self.assertEqual(git(self.repo, "cat-file", "blob", REF + ":HEAD.json"),
                         (self.work / "posix" / "HEAD.json").read_bytes())

    def test_head_and_receipts_land_at_the_keys_a_posix_root_uses(self):
        git_store = self.git_store()
        self.assertTrue(git_store.append_transaction(
            ledger_store.receipt_key(DIGEST), {"receipt_sha256": DIGEST}, None, {"receipt_sha256": DIGEST},
            {ledger_store.source_key(OTHER): {"source": True}}))
        self.assertEqual(tree(self.repo), {"HEAD.json", "receipts/" + "a" * 64 + ".json",
                                           "source-receipts/" + "b" * 64 + ".json"})

    def test_a_transaction_is_one_commit(self):
        git_store = self.git_store()
        git_store.append_transaction(ledger_store.receipt_key(DIGEST), {"receipt_sha256": DIGEST},
                                     None, {"receipt_sha256": DIGEST})
        git_store.append_transaction(ledger_store.receipt_key(OTHER), {"receipt_sha256": OTHER},
                                     {"receipt_sha256": DIGEST}, {"receipt_sha256": OTHER})
        self.assertEqual(git(self.repo, "rev-list", "--count", REF).strip(), b"2")

    def test_the_locator_names_the_repository_ref_and_key(self):
        git_store = self.git_store()
        locator = git_store.locator(ledger_store.receipt_key(DIGEST))
        self.assertEqual(locator, "git+" + str(self.repo) + "#" + REF + ":" + ledger_store.receipt_key(DIGEST))


class CompareAndSwapRaceTests(_Work):
    """Two writers that share only the repository: one wins the ref, one publishes nothing."""

    def test_a_writer_that_loses_the_ref_comparison_publishes_nothing(self):
        mine = self.git_store()
        competitor = ledger_store.GitLedgerStore(self.repo, REF)
        # A writer on another machine holds no lock this one can see.
        competitor.exclusive = nullcontext
        mine.put(ledger_store.receipt_key(DIGEST), {"receipt_sha256": DIGEST})
        mine.put(ledger_store.HEAD_KEY, {"receipt_sha256": DIGEST})
        theirs_key = ledger_store.receipt_key("sha256:" + "c" * 64)
        mine_key = ledger_store.receipt_key(OTHER)
        publish = mine._publish

        def interleaved(new, expected):
            # The competitor lands its append between our read and our publish.
            self.assertTrue(competitor.append_transaction(
                theirs_key, {"receipt_sha256": "sha256:" + "c" * 64},
                {"receipt_sha256": DIGEST}, {"receipt_sha256": "sha256:" + "c" * 64}))
            mine._publish = publish
            return publish(new, expected)

        mine._publish = interleaved
        won = mine.append_transaction(mine_key, {"receipt_sha256": OTHER},
                                      {"receipt_sha256": DIGEST}, {"receipt_sha256": OTHER})
        self.assertIs(won, False)
        self.assertEqual(mine.get(ledger_store.HEAD_KEY), {"receipt_sha256": "sha256:" + "c" * 64})
        self.assertNotIn(mine_key, tree(self.repo))
        self.assertIn(theirs_key, tree(self.repo))

    def test_a_stale_view_returns_false_and_leaves_the_ref_where_it_was(self):
        store = self.git_store()
        store.put(ledger_store.HEAD_KEY, {"receipt_sha256": DIGEST})
        before = git(self.repo, "rev-parse", REF)
        self.assertIs(store.append_transaction(ledger_store.receipt_key(OTHER), {"receipt_sha256": OTHER},
                                               None, {"receipt_sha256": OTHER}), False)
        self.assertIs(store.compare_and_swap(ledger_store.HEAD_KEY, None, {"receipt_sha256": OTHER}), False)
        self.assertEqual(git(self.repo, "rev-parse", REF), before)

    def test_a_ref_moved_by_an_unrelated_write_is_rebuilt_on_not_overwritten(self):
        mine = self.git_store()
        other = ledger_store.GitLedgerStore(self.repo, REF)
        mine.put(ledger_store.HEAD_KEY, {"receipt_sha256": DIGEST})
        publish = mine._publish

        def interleaved(new, expected):
            other.put("notes/unrelated.json", {"unrelated": True})
            mine._publish = publish
            return publish(new, expected)

        mine._publish = interleaved
        self.assertTrue(mine.append_transaction(ledger_store.receipt_key(OTHER), {"receipt_sha256": OTHER},
                                                {"receipt_sha256": DIGEST}, {"receipt_sha256": OTHER}))
        self.assertEqual(mine.get("notes/unrelated.json"), {"unrelated": True})
        self.assertEqual(mine.get(ledger_store.HEAD_KEY), {"receipt_sha256": OTHER})


class SerializedAppendTests(_Work):
    def test_concurrent_organization_appenders_leave_one_intact_chain(self):
        locator = "git+" + str(self.repo) + "#" + REF
        with multiprocessing.Manager() as manager:
            results = manager.Queue()
            processes = [multiprocessing.Process(target=org_append_worker, args=(locator, i, results))
                         for i in range(4)]
            for process in processes:
                process.start()
            for process in processes:
                process.join(60)
                self.assertEqual(process.exitcode, 0)
            self.assertEqual([results.get(timeout=5) for _ in processes], ["OK"] * 4)
        store = ledger_store.GitLedgerStore(self.repo, REF)
        visited = reachable(store)
        self.assertEqual(len(visited), 4)
        self.assertEqual(store.list_prefix(ledger_store.RECEIPT_PREFIX),
                         {ledger_store.receipt_key(digest) for digest in visited})
        self.assertEqual(len(store.list_prefix(ledger_store.SOURCE_PREFIX)), 4)
        # One commit per append: no write was lost and none was published twice.
        self.assertEqual(git(self.repo, "rev-list", "--count", REF).strip(), b"4")


class ChainBreakTests(_Work):
    def _replace_in_ref(self, key, document):
        """Edit the ref out of band, as a writer outside the store could; None drops the key."""
        if document is None:
            entry = "0 " + "0" * 40 + "\t" + key + "\n"
        else:
            blob = git(self.repo, "hash-object", "-w", "--stdin", stdin=json.dumps(document).encode())
            entry = "100644 " + blob.decode().strip() + "\t" + key + "\n"
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_DIR=str(self.repo), GIT_INDEX_FILE=str(self.work / "index"), GIT_AUTHOR_NAME="t",
                   GIT_AUTHOR_EMAIL="t@invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@invalid")
        run = lambda *a, stdin=None: subprocess.run(["git", *a], input=stdin, env=env, check=True,
                                                    capture_output=True).stdout.decode().strip()
        run("read-tree", REF)
        run("update-index", "--index-info", stdin=entry.encode())
        commit = run("commit-tree", "--no-gpg-sign", run("write-tree"), "-p", REF, "-m", "out of band")
        run("update-ref", REF, commit)

    def test_a_tampered_repository_receipt_is_detected_and_nothing_is_minted(self):
        store = self.git_store()
        first = repository.append("git-chain-1", "TEST", STATE_BEFORE, STATE_AFTER, {}, "NONE",
                                  hb_epoch=EPOCH, store=store)
        repository.append("git-chain-2", "TEST", STATE_BEFORE, STATE_AFTER, {}, "NONE",
                          hb_epoch=EPOCH, store=store)
        self._replace_in_ref(ledger_store.receipt_key(first["receipt_sha256"]),
                             {**first, "transition_id": "rewritten"})
        before = git(self.repo, "rev-parse", REF)
        with self.assertRaises(repository.RepoLedgerChainBreak) as raised:
            repository.append("git-chain-3", "TEST", STATE_BEFORE, STATE_AFTER, {}, "NONE",
                              hb_epoch=EPOCH, store=store)
        self.assertEqual(raised.exception.detail, "receipt_body_does_not_hash_to_its_address")
        self.assertEqual(git(self.repo, "rev-parse", REF), before)

    def test_a_tampered_organization_receipt_fails_closed(self):
        store = self.git_store()
        first = organization.append(source_receipt(1), "REPO_STATE_PROPAGATION", "GENESIS", STATE_AFTER,
                                    {}, "NONE", hb_epoch=EPOCH, store=store)
        self._replace_in_ref(ledger_store.receipt_key(first["receipt_sha256"]),
                             {**first, "authority_effect": "REWRITTEN"})
        with self.assertRaisesRegex(SystemExit, "ORG_LEDGER_HEAD_RECEIPT_HASH_MISMATCH"):
            organization.append(source_receipt(2), "REPO_STATE_PROPAGATION", "FROM_HEAD", STATE_AFTER,
                                {}, "NONE", hb_epoch=EPOCH, store=store)

    def test_a_receipt_dropped_from_the_ref_is_a_missing_node(self):
        store = self.git_store()
        first = repository.append("git-drop-1", "TEST", STATE_BEFORE, STATE_AFTER, {}, "NONE",
                                  hb_epoch=EPOCH, store=store)
        repository.append("git-drop-2", "TEST", STATE_BEFORE, STATE_AFTER, {}, "NONE",
                          hb_epoch=EPOCH, store=store)
        self._replace_in_ref(ledger_store.receipt_key(first["receipt_sha256"]), None)
        with self.assertRaises(repository.RepoLedgerChainBreak) as raised:
            repository.append("git-drop-3", "TEST", STATE_BEFORE, STATE_AFTER, {}, "NONE",
                              hb_epoch=EPOCH, store=store)
        self.assertEqual(raised.exception.detail, "missing_receipt")


class ReceiptImmutabilityTests(_Work):
    def test_a_receipt_cannot_be_replaced_with_different_content(self):
        store = self.git_store()
        for key in (ledger_store.receipt_key(DIGEST), ledger_store.source_key(DIGEST)):
            with self.subTest(key):
                store.put(key, {"receipt_sha256": DIGEST})
                before = git(self.repo, "rev-parse", REF)
                with self.assertRaisesRegex(ValueError, "ledger_receipt_collision"):
                    store.put(key, {"receipt_sha256": DIGEST, "edited": True})
                with self.assertRaisesRegex(ValueError, "ledger_receipt_collision"):
                    store.compare_and_swap(key, {"receipt_sha256": DIGEST}, {"edited": True})
                self.assertEqual(store.get(key), {"receipt_sha256": DIGEST})
                self.assertEqual(git(self.repo, "rev-parse", REF), before)

    def test_head_is_not_immutable(self):
        store = self.git_store()
        store.put(ledger_store.HEAD_KEY, {"receipt_sha256": DIGEST})
        store.put(ledger_store.HEAD_KEY, {"receipt_sha256": OTHER})
        self.assertEqual(store.get(ledger_store.HEAD_KEY), {"receipt_sha256": OTHER})

    def test_a_colliding_append_writes_nothing(self):
        store = self.git_store()
        key = ledger_store.receipt_key(DIGEST)
        store.append_transaction(key, {"receipt_sha256": DIGEST}, None, {"receipt_sha256": DIGEST})
        before = git(self.repo, "rev-parse", REF)
        with self.assertRaisesRegex(ValueError, "ledger_receipt_collision"):
            store.append_transaction(key, {"receipt_sha256": DIGEST, "edited": True},
                                     {"receipt_sha256": DIGEST}, {"receipt_sha256": OTHER})
        self.assertEqual(git(self.repo, "rev-parse", REF), before)

    def test_rewriting_the_same_receipt_bytes_is_not_a_new_commit(self):
        store = self.git_store()
        key = ledger_store.receipt_key(DIGEST)
        store.put(key, {"receipt_sha256": DIGEST})
        before = git(self.repo, "rev-parse", REF)
        store.put(key, {"receipt_sha256": DIGEST})
        self.assertEqual(git(self.repo, "rev-parse", REF), before)


class SuppliedLocationTests(_Work):
    """A store is chosen only by what is supplied; nothing is named by default."""

    def _unsupplied(self, home):
        env = {k: v for k, v in os.environ.items() if k not in LEDGER_VARIABLES + ("XDG_STATE_HOME",)}
        env["HOME"] = home
        return env

    def test_a_plain_path_still_opens_the_posix_store_resolved_as_before(self):
        located = ledger_store.parse_locator(str(self.work / "posix"))
        self.assertEqual(located, (self.work / "posix").resolve())
        self.assertIsInstance(ledger_store.open_store(located), ledger_store.PosixLedgerStore)

    def test_a_git_locator_opens_the_git_store(self):
        text = "git+" + str(self.repo) + "#" + REF
        located = ledger_store.parse_locator(text)
        self.assertEqual(str(located), "git+" + str(self.repo.resolve()) + "#" + REF)
        for supplied in (text, located):
            store = ledger_store.open_store(supplied)
            self.assertIsInstance(store, ledger_store.GitLedgerStore)
            self.assertEqual(store.ref, REF)

    def test_a_git_locator_must_name_both_a_repository_and_a_qualified_ref(self):
        for text in ("git+" + str(self.repo), "git+" + str(self.repo) + "#", "git+#" + REF,
                     "git+" + str(self.repo) + "#ledger", "git+" + str(self.repo) + "#refs/bad..ref"):
            with self.subTest(text):
                with self.assertRaises(ledger_store.LedgerLocatorInvalid):
                    ledger_store.parse_locator(text)
        with self.assertRaises(ledger_store.LedgerLocatorInvalid):
            ledger_store.GitLedgerStore(self.repo, "main")
        self.assertFalse(self.repo.exists())

    def test_an_unsupplied_location_still_fails_closed_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, self._unsupplied(home), clear=True):
            with self.assertRaises(organization.LedgerLocationRequired):
                organization.ledger_root()
            with self.assertRaisesRegex(ValueError, "ledger_location_required_from_materializer"):
                repository.lr()
            self.assertEqual(list(Path(home).iterdir()), [])
        self.assertEqual(list(self.work.iterdir()), [])

    def test_reading_a_location_that_was_never_initialized_creates_nothing(self):
        # Inside an enclosing repository, so discovery would have found the wrong one.
        subprocess.run(["git", "init", "--quiet", str(self.work)], check=True, capture_output=True)
        store = ledger_store.GitLedgerStore(self.repo, REF)
        self.assertIsNone(store.get(ledger_store.HEAD_KEY))
        self.assertFalse(store.exists(ledger_store.HEAD_KEY))
        self.assertEqual(store.list_prefix(ledger_store.RECEIPT_PREFIX), set())
        self.assertFalse(self.repo.exists())
        self.assertEqual(subprocess.run(["git", "-C", str(self.work), "for-each-ref"], check=True,
                                        capture_output=True).stdout, b"")

    def test_a_supplied_git_locator_is_honoured_by_both_ledger_roots(self):
        locator = "git+" + str(self.repo) + "#" + REF
        env = {"STEGVERSE_ORG_LEDGER_ROOT": locator, "STEGVERSE_REPO_LEDGER_ROOT": locator.replace(REF, REF + "-repo")}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(str(organization.ledger_root()), "git+" + str(self.repo.resolve()) + "#" + REF)
            receipt = organization.append(source_receipt(1), "REPO_STATE_PROPAGATION", "GENESIS",
                                          STATE_AFTER, {}, "NONE", hb_epoch=EPOCH)
            repo_receipt = repository.append("git-supplied-1", "TEST", STATE_BEFORE, STATE_AFTER, {}, "NONE",
                                             hb_epoch=EPOCH)
        org_store = ledger_store.GitLedgerStore(self.repo, REF)
        head = org_store.get(ledger_store.HEAD_KEY)
        self.assertEqual(head["receipt_sha256"], receipt["receipt_sha256"])
        self.assertTrue(head["receipt_path"].startswith("git+"))
        repo_head = ledger_store.GitLedgerStore(self.repo, REF + "-repo").get(ledger_store.HEAD_KEY)
        self.assertEqual(repo_head["receipt_sha256"], repo_receipt["receipt_sha256"])
        # Only the supplied repository was written: no working files, no other refs.
        self.assertEqual(sorted(p.name for p in self.work.iterdir()), ["ledger.git"])
        self.assertEqual(set(git(self.repo, "for-each-ref", "--format=%(refname)").decode().split()),
                         {REF, REF + "-repo"})

    def test_the_module_names_no_ledger_location_of_its_own(self):
        source = (ROOT / "resident-runtime/ledger_store.py").read_text()
        for default in ("refs/heads/", "refs/stegverse", "refs/ledger", "DEFAULT_REF", "DEFAULT_LOCATOR"):
            self.assertNotIn(default, source)


if __name__ == "__main__":
    unittest.main()
