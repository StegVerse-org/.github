"""merge_transfer_gitstore: the main-merge transfer verifier and writer over the git ledger store.

Every ledger here is a temp bare git repository whose ref is built from
tests/fixtures/merge-transfer-gitstore/ledger-snapshot.json, the pinned
published ledger tip blob for blob (the test asserts the rebuilt tree id is the
pinned ledger_tree). Nothing reads or writes the published ref, the checkout's
history beyond HEAD, or the network, so the suite runs the same in a shallow
checkout. Commits appended in these tests are SYNTHETIC_NOT_LEDGERED facts.

The same file runs in every organization that carries the module; the pin
names this organization's writer surface and real state.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:  # Under pytest, a suite that declares a POSIX ledger locus by default leaves this one on its own declaration.
    import pytest
    pytestmark = pytest.mark.repository_ledger_locus
except (ImportError, AttributeError):  # unittest alone (or a pytest stand-in) needs no marker
    pass

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/merge-transfer-gitstore"
PIN = json.loads((FIXTURE / "pin.json").read_text(encoding="utf-8"))
SNAPSHOT = json.loads((FIXTURE / PIN["snapshot"]).read_text(encoding="utf-8"))
WRITER = ROOT / ".github/workflows/organization-ledger-merge-transfer.yml"
VALIDATION = ROOT / ".github/workflows/merge-transfer-gitstore-validation.yml"
PENDING = ROOT / ".stegverse/merge-transfer/pending.json"
ENV_KEYS = ("STEGVERSE_ORG_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_GIT_DIR", "STEGVERSE_REPO_LEDGER_ROOT",
            "STEGVERSE_ORG_LEDGER_STORE", "STEGVERSE_ORG_LEDGER_GIT_REF", "STEGVERSE_ORG_LEDGER_GIT_REMOTE",
            "STEGVERSE_ORG_LEDGER_GIT_CUSTODY")
IDENTITY = {"GIT_AUTHOR_NAME": "merge-transfer-gitstore-test", "GIT_AUTHOR_EMAIL": "test@invalid",
            "GIT_COMMITTER_NAME": "merge-transfer-gitstore-test", "GIT_COMMITTER_EMAIL": "test@invalid",
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


g = load("merge_transfer_gitstore_under_test", "resident-runtime/merge_transfer_gitstore.py")

SYNTHETIC = {"merge_commit": "5e" * 20, "tree": "7e" * 20, "parents": ["a1" * 20, "b2" * 20],
             "subject": "Merge pull request #4242 from example/synthetic-not-ledgered"}


def reseal(receipt: dict) -> dict:
    body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    return {**body, "receipt_sha256": g.sha(body)}


def doc(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


class TempLedger:
    """A bare git repository holding the pinned ledger tree on the declared ref, bound as the writers read it."""

    def __init__(self, empty: bool = False):
        self.tmp = tempfile.TemporaryDirectory()
        self.git_dir = str(Path(self.tmp.name) / "ledger.git")
        self.ref, self.ns = PIN["ledger_ref"], PIN["repository_ledger_namespace"]
        subprocess.run(["git", "init", "-q", "--bare", self.git_dir], check=True)
        self.tree = None
        if not empty:
            self.write({path: text.encode("utf-8") for path, text in SNAPSHOT.items()})
            self.tree = self._git("rev-parse", self.ref + "^{tree}").strip()
        self.saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
        os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = "git+" + self.git_dir + "#" + self.ref
        os.environ["STEGVERSE_ORG_LEDGER_GIT_DIR"] = self.git_dir
        os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = "git+" + self.git_dir + "#" + self.ref + ":" + self.ns

    def _git(self, *args: str, data: bytes | None = None, env: dict | None = None) -> str:
        return subprocess.run(["git", "--git-dir", self.git_dir, *args], input=data, check=True,
                              capture_output=True, env={**os.environ, **IDENTITY, **(env or {})}).stdout.decode()

    def tip(self) -> str | None:
        done = subprocess.run(["git", "--git-dir", self.git_dir, "rev-parse", "--verify", "-q", self.ref],
                              capture_output=True, text=True)
        return done.stdout.strip() or None

    def write(self, changes: dict) -> None:
        index = str(Path(self.tmp.name) / "index")
        env = {"GIT_INDEX_FILE": index}
        tip = self.tip()
        if tip:
            self._git("read-tree", tip, env=env)
        else:
            self._git("read-tree", "--empty", env=env)
        for path, data in changes.items():
            if data is None:
                self._git("update-index", "--index-info", data=("0 " + "0" * 40 + "\t" + path + "\n").encode(),
                          env=env)
            else:
                oid = self._git("hash-object", "-w", "--stdin", data=data).strip()
                self._git("update-index", "--add", "--cacheinfo", "100644," + oid + "," + path, env=env)
        tree = self._git("write-tree", env=env).strip()
        commit = self._git("commit-tree", tree, *(["-p", tip] if tip else []), data=b"test ledger edit\n").strip()
        self._git("update-ref", self.ref, commit)

    def files(self) -> dict[str, bytes]:
        tip = self.tip()
        if not tip:
            return {}
        out = {}
        for line in self._git("ls-tree", "-r", tip).splitlines():
            meta, path = line.split("\t", 1)
            out[path] = subprocess.run(["git", "--git-dir", self.git_dir, "cat-file", "blob", meta.split()[2]],
                                       check=True, capture_output=True).stdout
        return out

    def read(self, path: str):
        return json.loads(self.files()[path])

    def put(self, path: str, value) -> None:
        self.write({path: doc(value)})

    def readers(self):
        return g.bind_readers(ROOT)

    def verify(self, repo=None, merge=None, mode="dual"):
        organization, repository = self.readers()
        return g.verify_merge_transfer(repo or PIN["repository"], merge or SYNTHETIC["merge_commit"],
                                       organization, repository, mode=mode)

    def close(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def repo_key(digest: str) -> str:
    return PIN["repository_ledger_namespace"] + "/" + g.receipt_key(digest)


class Pin(unittest.TestCase):
    def test_the_snapshot_rebuilds_the_pinned_ledger_tree(self):
        with TempLedger() as ledger:
            self.assertEqual(ledger.tree, PIN["ledger_tree"])

    def test_the_pin_names_this_repository_and_its_declared_ledger(self):
        self.assertEqual(PIN["repository"], g.repository())
        location = g.contract()["repository_ledger_location"]
        self.assertEqual((PIN["ledger_ref"], PIN["repository_ledger_namespace"]), (location["ref"], location["namespace"]))
        self.assertIsNone(g.facts_failure(PIN["real_commit"]))

    def test_the_writer_surface_is_the_pinned_one(self):
        self.assertEqual(g.WriterSurface(ROOT).kind, PIN["writer_surface"])


class RealState(unittest.TestCase):
    def test_the_pinned_main_commit_at_the_pinned_tip(self):
        with TempLedger() as ledger:
            for mode in g.MODES:
                result = ledger.verify(merge=PIN["real_commit"]["merge_commit"], mode=mode)
                self.assertEqual({"disposition": result["disposition"], "failure_code": result.get("failure_code")},
                                 PIN["real_state_at_ledger_tip"], mode)
                if result["disposition"] != "ALLOW":
                    for field in g.SIX_FIELDS:
                        self.assertTrue(result[field], field)


class Append(unittest.TestCase):
    def test_append_then_verified_then_an_idempotent_replay(self):
        with TempLedger() as ledger:
            before = ledger.files()
            head = json.loads(before[g.HEAD_KEY])
            head_receipt = json.loads(before[g.receipt_key(head["receipt_sha256"])])
            self.assertEqual(ledger.verify()["failure_code"], g.NOT_LEDGERED)
            result = g.append_merge_transfer(SYNTHETIC)
            self.assertEqual(result["disposition"], "ALLOW", result)
            self.assertEqual(result["writer_surface"], PIN["writer_surface"])
            self.assertFalse(result["replayed"])
            self.assertEqual(result["pull_request"], 4242)
            after = ledger.files()
            for name, data in before.items():  # append-only: only the two HEADs move
                if not name.endswith("HEAD.json"):
                    self.assertEqual(after[name], data, name)
            org = json.loads(after[g.receipt_key(result["organization_receipt_sha256"])])
            rep = json.loads(after[repo_key(result["repository_receipt_sha256"])])
            retained = json.loads(after[g.source_key(result["repository_receipt_sha256"])])
            self.assertTrue(g.sealed(org) and g.sealed(rep))
            self.assertEqual(retained, rep)
            self.assertEqual(org["repo_receipt_sha256"], rep["receipt_sha256"])
            self.assertEqual(dict(org["boundary_evidence"]), {
                "operation": g.OPERATION, "profile_id": g.PROFILE_ID, "disposition": "ALLOW",
                "communication_id": "main-merge-transfer:" + PIN["repository"] + "@" + SYNTHETIC["merge_commit"],
                "repository": PIN["repository"], "merge_commit": SYNTHETIC["merge_commit"]})
            self.assertEqual(rep["evidence"], g.merge_evidence(PIN["repository"], SYNTHETIC))
            self.assertEqual(rep["transition_id"], g.OPERATION + ":" + SYNTHETIC["merge_commit"])
            self.assertEqual(rep["transition_class"], g.OPERATION)
            self.assertEqual(org["hb_reference"]["epoch"], head_receipt["hb_reference"]["epoch"])
            self.assertIs(org["hb_reference"]["derived_from_clock"], False)
            self.assertIs(rep["hb_reference"]["derived_from_clock"], False)
            for mode in g.MODES:
                verified = ledger.verify(mode=mode)
                self.assertEqual((verified["disposition"], verified["transfer"]), ("ALLOW", "VERIFIED"), mode)
                self.assertEqual(verified["organization_receipt_sha256"], result["organization_receipt_sha256"])
            tip = ledger.tip()
            replay = g.append_merge_transfer(SYNTHETIC)
            self.assertEqual(replay["disposition"], "ALLOW", replay)
            self.assertTrue(replay["replayed"])
            self.assertEqual(replay["organization_receipt_sha256"], result["organization_receipt_sha256"])
            self.assertEqual(ledger.tip(), tip)

    def test_the_cli_reads_a_named_git_dir_and_not_the_environment(self):
        with TempLedger() as ledger:
            g.append_merge_transfer(SYNTHETIC)
            for k in ENV_KEYS:
                os.environ.pop(k, None)
            readers = g.bind_readers(ROOT, git_dir=ledger.git_dir, ref=ledger.ref)
            result = g.verify_merge_transfer(PIN["repository"], SYNTHETIC["merge_commit"], *readers)
            self.assertEqual(result["disposition"], "ALLOW", result)
            self.assertEqual(readers[0].tip, ledger.tip())

    def test_an_unbound_location_is_fail_closed_with_six_fields(self):
        saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
        try:
            unbound = g.bind_readers(ROOT)
            self.assertIsInstance(unbound, dict)
            self.assertEqual(unbound["failure_code"], g.LOCATION_UNBOUND)
            for field in g.SIX_FIELDS:
                self.assertTrue(unbound[field], field)
            self.assertEqual(g.append_merge_transfer(SYNTHETIC)["failure_code"], g.LOCATION_UNBOUND)
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


class Refusals(unittest.TestCase):
    def _six(self, result, code, disposition="FAIL_CLOSED"):
        self.assertEqual(result["disposition"], disposition, result)
        self.assertEqual(result["failure_code"], code, result)
        for field in g.SIX_FIELDS:
            self.assertTrue(result[field], field)

    def _appended(self, ledger):
        result = g.append_merge_transfer(SYNTHETIC)
        self.assertEqual(result["disposition"], "ALLOW", result)
        return g.receipt_key(result["organization_receipt_sha256"]), result["repository_receipt_sha256"]

    def _put_repo_receipt(self, ledger, digest, value, *, chain=True, retained=True):
        changes = {}
        if chain:
            changes[repo_key(digest)] = None if value is None else doc(value)
        if retained:
            changes[g.source_key(digest)] = None if value is None else doc(value)
        ledger.write(changes)

    def _rehead(self, ledger, org_key, org):
        org = reseal(org)
        head = ledger.read(g.HEAD_KEY)
        ledger.write({org_key: None, g.receipt_key(org["receipt_sha256"]): doc(org),
                      g.HEAD_KEY: doc({**head, "receipt_sha256": org["receipt_sha256"]})})

    def test_an_empty_ledger_has_no_epoch_source_and_nothing_is_written(self):
        with TempLedger(empty=True) as ledger:
            self._six(g.append_merge_transfer(SYNTHETIC), g.EPOCH_UNOBSERVED)
            self.assertIsNone(ledger.tip())
            self._six(ledger.verify(), g.NOT_LEDGERED)

    def test_a_clock_derived_or_unsealed_head_epoch_is_unobserved(self):
        for mutate in ("clock", "missing", "bool", "below_anchor", "string", "unsealed"):
            with TempLedger() as ledger:
                key = g.receipt_key(ledger.read(g.HEAD_KEY)["receipt_sha256"])
                receipt = ledger.read(key)
                if mutate == "clock":
                    receipt["hb_reference"]["derived_from_clock"] = True
                elif mutate == "missing":
                    receipt["hb_reference"].pop("epoch")
                elif mutate == "bool":
                    receipt["hb_reference"]["epoch"] = True
                elif mutate == "below_anchor":
                    receipt["hb_reference"]["epoch"] = 31
                elif mutate == "string":
                    receipt["hb_reference"]["epoch"] = str(receipt["hb_reference"]["epoch"])
                if mutate == "unsealed":
                    receipt["tampered"] = True
                    ledger.put(key, receipt)
                else:
                    ledger.put(key, reseal(receipt))
                tip = ledger.tip()
                self._six(g.append_merge_transfer(SYNTHETIC), g.EPOCH_UNOBSERVED)
                self.assertEqual(ledger.tip(), tip, mutate)

    def test_invalid_commit_facts_are_refused_before_any_read(self):
        for bad in ({}, {**SYNTHETIC, "merge_commit": "5e5e5e5e"}, {**SYNTHETIC, "parents": []},
                    {**SYNTHETIC, "tree": None}, {**SYNTHETIC, "subject": None}):
            self._six(g.append_merge_transfer(bad), g.FACTS_INVALID)

    def test_one_merge_commit_binds_one_transfer_receipt(self):
        with TempLedger() as ledger:
            self._appended(ledger)
            tip = ledger.tip()
            self._six(g.append_merge_transfer({**SYNTHETIC, "subject": "a different subject"}), g.COLLISION)
            self.assertEqual(ledger.tip(), tip)

    def test_present_evidence_that_contradicts_the_merge_is_deny(self):
        cases = {"other_merge": ("merge_commit", "0" * 40), "other_repository": ("repository", "SV-000/.github"),
                 "other_ref": ("ref", "refs/heads/feature"), "other_schema": ("schema", "stegverse.other/v1"),
                 "digest_not_carried": ("tree", "f" * 40)}
        for case, (field, value) in cases.items():
            with TempLedger() as ledger:
                _, digest = self._appended(ledger)
                rep = ledger.read(repo_key(digest))
                rep["evidence"][field] = value
                self._put_repo_receipt(ledger, digest, reseal(rep))  # both ledgers agree; sealed as another receipt
                for mode in g.MODES:
                    result = ledger.verify(mode=mode)
                    self._six(result, g.LINK_UNVERIFIED, "DENY")
                    self.assertIn(field if case != "digest_not_carried" else "digest", result["detail"], case)
        for case in ("link_to_another_repository_receipt", "org_receipt_names_another_repository",
                     "repository_receipt_sealed_as_another"):
            with TempLedger() as ledger:
                org_key, digest = self._appended(ledger)
                org = ledger.read(org_key)
                files = ledger.files()
                prefix = PIN["repository_ledger_namespace"] + "/" + g.RECEIPT_PREFIX
                others = [json.loads(v) for k, v in files.items() if k.startswith(prefix) and k != repo_key(digest)]
                others = [o for o in others if g.sealed(o) and g.source_key(o["receipt_sha256"]) in files]
                self.assertTrue(others)
                other = others[0]
                if case == "link_to_another_repository_receipt":
                    org["repo_receipt_sha256"] = other["receipt_sha256"]
                    self._rehead(ledger, org_key, org)
                elif case == "org_receipt_names_another_repository":
                    org["repository" if "repository" in org else "source_repository"] = "SV-000/.github"
                    self._rehead(ledger, org_key, org)
                else:
                    self._put_repo_receipt(ledger, digest, other)
                for mode in g.MODES:
                    self._six(ledger.verify(mode=mode), g.LINK_UNVERIFIED, "DENY")

    def test_absent_or_unsealed_evidence_is_fail_closed_not_ledgered(self):
        for case in ("repo_receipt_missing", "repo_receipt_unsealed", "org_receipt_unsealed", "other_repository",
                     "other_merge", "head_missing"):
            with TempLedger() as ledger:
                org_key, digest = self._appended(ledger)
                if case == "repo_receipt_missing":
                    self._put_repo_receipt(ledger, digest, None)
                elif case == "repo_receipt_unsealed":
                    rep = ledger.read(repo_key(digest))
                    rep["evidence"]["merge_commit"] = "0" * 40
                    self._put_repo_receipt(ledger, digest, rep)
                elif case == "org_receipt_unsealed":
                    org = ledger.read(org_key)
                    org["hb_reference"]["epoch"] += 1
                    ledger.put(org_key, org)
                elif case == "head_missing":
                    ledger.write({g.HEAD_KEY: None})
                repo = "SV-000/.github" if case == "other_repository" else None
                merge = "1" * 40 if case == "other_merge" else None
                for mode in g.MODES:
                    result = ledger.verify(repo=repo, merge=merge, mode=mode)
                    self._six(result, g.NOT_LEDGERED)
                    self.assertEqual(result["transfer"], "UNVERIFIED")


class DualLedger(unittest.TestCase):
    """Dual mode: the repository chain's receipt and the organization ledger's retained copy are one receipt."""

    def _divergent(self, mutate):
        with TempLedger() as ledger:
            result = g.append_merge_transfer(SYNTHETIC)
            digest = result["repository_receipt_sha256"]
            rep = ledger.read(repo_key(digest))
            mutate(ledger, digest, rep)
            return ledger.verify(mode="dual"), ledger.verify(mode="single")

    def _diverged(self, result):
        self.assertEqual((result["disposition"], result["failure_code"]), ("FAIL_CLOSED", g.DUAL_DIVERGENCE), result)
        self.assertEqual(result["transfer"], "UNVERIFIED")
        for field in g.SIX_FIELDS:
            self.assertTrue(result[field], field)

    def test_a_retained_copy_that_differs_is_divergence(self):
        def mutate(ledger, digest, rep):
            changed = copy.deepcopy(rep)
            changed["authority_effect"] = "OTHER"
            ledger.put(g.source_key(digest), reseal(changed))
        dual, single = self._divergent(mutate)
        self._diverged(dual)
        self.assertEqual(single["disposition"], "ALLOW")  # single mode reads the repository chain only

    def test_a_missing_retained_copy_is_divergence(self):
        dual, single = self._divergent(lambda ledger, digest, rep: ledger.write({g.source_key(digest): None}))
        self._diverged(dual)
        self.assertEqual(single["disposition"], "ALLOW")

    def test_a_repository_chain_copy_that_contradicts_alone_is_divergence_not_deny(self):
        def mutate(ledger, digest, rep):
            rep["evidence"]["merge_commit"] = "0" * 40
            ledger.put(repo_key(digest), reseal(rep))
        dual, single = self._divergent(mutate)
        self._diverged(dual)
        self.assertEqual((single["disposition"], single["failure_code"]), ("DENY", g.LINK_UNVERIFIED))

    def test_the_same_receipt_in_both_ledgers_with_other_bytes_is_not_divergence(self):
        def mutate(ledger, digest, rep):
            ledger.write({g.source_key(digest): json.dumps(rep, separators=(",", ":")).encode()})
        dual, single = self._divergent(mutate)
        self.assertEqual((dual["disposition"], single["disposition"]), ("ALLOW", "ALLOW"))


class Commits(unittest.TestCase):
    def test_commit_facts_are_read_from_the_commit_object(self):
        head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True, capture_output=True,
                              text=True).stdout.strip()
        facts = g.commit_facts("HEAD")
        self.assertEqual(facts["merge_commit"], head)
        self.assertIsNone(g.facts_failure(facts))

    def test_a_push_without_a_usable_before_carries_its_after_commit(self):
        head = g.commit_facts("HEAD")["merge_commit"]
        self.assertEqual(g.pushed_commits("0" * 40, head, None), [head])
        self.assertEqual(g.pushed_commits(head, head, None), [])

    def test_the_pending_manifest_is_this_repository_s(self):
        document = json.loads(PENDING.read_text(encoding="utf-8"))
        self.assertEqual((document["schema"], document["repository"]), (g.PENDING_SCHEMA, g.repository()))
        self.assertTrue(all(g.SHA40.fullmatch(row["merge_commit"]) for row in document["merges"]))


class WorkflowShape(unittest.TestCase):
    def test_the_writer_runs_only_on_push_to_main(self):
        text = WRITER.read_text(encoding="utf-8")
        on = text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(on.strip(), "push:\n    branches: [main]")
        self.assertNotIn("secrets.", text)
        self.assertIn("\npermissions:\n  contents: read\n", text)
        self.assertIn("    permissions:\n      contents: write\n", text)
        self.assertIn("concurrency:\n  group: organization-ledger\n  cancel-in-progress: false\n", text)
        self.assertNotRegex(text, r"git push[^\n]*\+")

    def test_the_validation_workflow_is_read_only_and_never_pushes(self):
        text = VALIDATION.read_text(encoding="utf-8")
        on = text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertTrue(on.lstrip().startswith("pull_request:"))
        for word in ("push:", "workflow_dispatch", "schedule", "repository_dispatch", "workflow_run"):
            self.assertNotIn(word, on)
        self.assertIn("\npermissions:\n  contents: read\n", text)
        self.assertNotIn("contents: write", text)
        self.assertNotIn("git push", text)
        self.assertNotIn("secrets.", text)
        self.assertNotIn("if:", text)


if __name__ == "__main__":
    unittest.main()
