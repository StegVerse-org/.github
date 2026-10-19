"""A temporary copy of this organization's ledger at a pinned tip, bound the way its ledger binding reads it.

merge_transfer.py organizations: the tip's tree in a temporary directory
(STEGVERSE_ORG_LEDGER_ROOT / STEGVERSE_REPO_LEDGER_ROOT are POSIX roots).
Git-store organizations (merge_transfer_gitstore.py, StegVerse-Labs and
GCAT-BCAT-Engine): the tip in a temporary bare repository on the declared ref,
bound as ``git+<dir>#<ref>[:<namespace>]``, as Lane D's tests bind it.
Receipts written here are NOT LEDGERED and NOT AUTHENTIC; nothing is pushed.
Git commits in the temporary repository carry a fixed identity and date.

The ledger is rebuilt from tests/fixtures/intr-path-ledger/snapshots/<tip>.json (the tip's tree, file for
file, and the raw commit objects of the pinned main merges), so a shallow checkout without the ledger ref
(StegVerse-Labs' suite ratchet) runs the same tests. The rebuilt tree must equal the snapshot's ledger_tree,
and, where the checkout holds the tip, the tip's own tree. The commit objects are made visible to the
checkout through GIT_ALTERNATE_OBJECT_DIRECTORIES for the ledger's life; the checkout is not written.

A git-store ledger uses org-contract.json's own organization_ledger declaration.
An organization whose test package declares a POSIX locus for a plain unittest
run (StegVerse-Labs tests/__init__.py -> tests/posix_ledger_locus) is held to
its declaration for the life of a git TempLedger, as its pytest marker
``repository_ledger_locus`` does; the POSIX declaration is restored on close.
"""
from __future__ import annotations

import base64
import importlib.machinery
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REF = "refs/stegverse/organization-ledger"
ENV_KEYS = ("STEGVERSE_ORG_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_GIT_DIR", "STEGVERSE_REPO_LEDGER_ROOT",
            "STEGVERSE_ORG_LEDGER_STORE", "STEGVERSE_ORG_LEDGER_GIT_REF", "STEGVERSE_ORG_LEDGER_GIT_REMOTE",
            "STEGVERSE_ORG_LEDGER_GIT_CUSTODY", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL", "GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE", "GIT_ALTERNATE_OBJECT_DIRECTORIES")
SNAPSHOTS = "tests/fixtures/intr-path-ledger/snapshots"
POSIX_LOCUS_SHIM = "tests.posix_ledger_locus.sitecustomize"


def _declared_locus_exec_module():
    """The loader's own exec_module when a test package replaced it to declare a POSIX locus, else None."""
    shim = sys.modules.get(POSIX_LOCUS_SHIM)
    original = getattr(shim, "_exec_module", None)
    loader = importlib.machinery.SourceFileLoader
    if original is not None and loader.exec_module is not original:
        return original
    return None


IDENTITY = {"GIT_AUTHOR_NAME": "temp-ledger", "GIT_AUTHOR_EMAIL": "temp-ledger@invalid",
            "GIT_COMMITTER_NAME": "temp-ledger", "GIT_COMMITTER_EMAIL": "temp-ledger@invalid",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+0000", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+0000"}


def _git(*args, data=None, env=None, text=True):
    return subprocess.run(["git", *args], input=data, env=env, check=True, capture_output=True, text=text).stdout


def load_snapshot(repo_root: Path | str, tip: str) -> dict:
    return json.loads((Path(repo_root) / SNAPSHOTS / (tip + ".json")).read_text())


def snapshot_files(snapshot: dict) -> dict[str, bytes]:
    return {path: (doc["text"].encode("utf-8") if "text" in doc else base64.b64decode(doc["base64"]))
            for path, doc in snapshot["files"].items()}


class TempLedger:
    def __init__(self, repo_root: Path | str, tip: str, namespace: str, git: bool):
        self.repo_root, self.namespace, self.git = str(repo_root), namespace, git
        snapshot = load_snapshot(repo_root, tip)
        assert snapshot["ledger_tip"] == tip, (snapshot["ledger_tip"], tip)
        self.dir = tempfile.TemporaryDirectory()
        self.saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
        self.restore_loader = None
        objects = Path(self.dir.name) / "objects.git"
        _git("init", "-q", "--bare", str(objects))
        for raw in snapshot["commits"].values():
            _git("--git-dir", str(objects), "hash-object", "-t", "commit", "-w", "--stdin",
                 data=base64.b64decode(raw), text=False)
        alternates = [str(objects / "objects")] + ([self.saved["GIT_ALTERNATE_OBJECT_DIRECTORIES"]]
                                                   if self.saved.get("GIT_ALTERNATE_OBJECT_DIRECTORIES") else [])
        held = subprocess.run(["git", "-C", self.repo_root, "rev-parse", "-q", "--verify", tip + "^{tree}"],
                              capture_output=True, text=True)
        if held.returncode == 0:
            assert held.stdout.strip() == snapshot["ledger_tree"], "snapshot is not the tip's tree"
        files = snapshot_files(snapshot)
        if git:
            original = _declared_locus_exec_module()
            if original is not None:
                self.restore_loader = importlib.machinery.SourceFileLoader.exec_module
                importlib.machinery.SourceFileLoader.exec_module = original
            self.root = Path(self.dir.name) / "ledger.git"
            _git("init", "-q", "--bare", str(self.root))
            env = {**os.environ, **IDENTITY, "GIT_INDEX_FILE": str(Path(self.dir.name) / "index")}
            for path, data in sorted(files.items()):
                blob = _git("--git-dir", str(self.root), "hash-object", "-w", "--stdin", data=data, text=False)
                _git("--git-dir", str(self.root), "update-index", "--add", "--cacheinfo",
                     "100644,%s,%s" % (blob.decode().strip(), path), env=env)
            tree = _git("--git-dir", str(self.root), "write-tree", env=env).strip()
            assert tree == snapshot["ledger_tree"], (tree, snapshot["ledger_tree"])
            commit = _git("--git-dir", str(self.root), "commit-tree", tree, "-m", "ledger snapshot " + tip,
                          env=env).strip()
            _git("--git-dir", str(self.root), "update-ref", REF, commit)
            self.tip = commit
            os.environ.update(IDENTITY)
            os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = "git+%s#%s" % (self.root, REF)
            os.environ["STEGVERSE_ORG_LEDGER_GIT_DIR"] = str(self.root)
            os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = "git+%s#%s:%s" % (self.root, REF, namespace)
        else:
            self.root = Path(self.dir.name) / "ledger"
            for path, data in files.items():
                target = self.root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            self.tip = tip
            os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = str(self.root)
            os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = str(self.root / namespace)
        os.environ["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = os.pathsep.join(alternates)

    def files(self) -> dict[str, bytes]:
        """Every document of the ledger as it now stands (the ref's tree, or the directory)."""
        if not self.git:
            return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*")
                    if p.is_file() and p.name != "inbound.json"}
        listed = subprocess.run(["git", "--git-dir", str(self.root), "ls-tree", "-r", REF],
                                check=True, capture_output=True, text=True).stdout
        out = {}
        for line in listed.splitlines():
            meta, path = line.split("\t", 1)
            out[path] = subprocess.run(["git", "--git-dir", str(self.root), "cat-file", "blob", meta.split()[2]],
                                       check=True, capture_output=True).stdout
        return out

    def close(self) -> None:
        if self.restore_loader is not None:
            importlib.machinery.SourceFileLoader.exec_module = self.restore_loader
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v
        self.dir.cleanup()
