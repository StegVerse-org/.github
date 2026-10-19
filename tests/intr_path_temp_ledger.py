"""A temporary copy of this organization's ledger at a pinned tip, bound the way its ledger binding reads it.

merge_transfer.py organizations: the tip's tree in a temporary directory
(STEGVERSE_ORG_LEDGER_ROOT / STEGVERSE_REPO_LEDGER_ROOT are POSIX roots).
Git-store organizations (merge_transfer_gitstore.py, StegVerse-Labs and
GCAT-BCAT-Engine): the tip in a temporary bare repository on the declared ref,
bound as ``git+<dir>#<ref>[:<namespace>]``, as Lane D's tests bind it.
Receipts written here are NOT LEDGERED and NOT AUTHENTIC; nothing is pushed.
Git commits in the temporary repository carry a fixed identity and date.

A git-store ledger uses org-contract.json's own organization_ledger declaration.
An organization whose test package declares a POSIX locus for a plain unittest
run (StegVerse-Labs tests/__init__.py -> tests/posix_ledger_locus) is held to
its declaration for the life of a git TempLedger, as its pytest marker
``repository_ledger_locus`` does; the POSIX declaration is restored on close.
"""
from __future__ import annotations

import importlib.machinery
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REF = "refs/stegverse/organization-ledger"
ENV_KEYS = ("STEGVERSE_ORG_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_GIT_DIR", "STEGVERSE_REPO_LEDGER_ROOT",
            "STEGVERSE_ORG_LEDGER_STORE", "STEGVERSE_ORG_LEDGER_GIT_REF", "STEGVERSE_ORG_LEDGER_GIT_REMOTE",
            "STEGVERSE_ORG_LEDGER_GIT_CUSTODY", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL", "GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE")
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


class TempLedger:
    def __init__(self, repo_root: Path | str, tip: str, namespace: str, git: bool):
        self.repo_root, self.tip, self.namespace, self.git = str(repo_root), tip, namespace, git
        self.dir = tempfile.TemporaryDirectory()
        self.saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
        self.restore_loader = None
        if git:
            original = _declared_locus_exec_module()
            if original is not None:
                self.restore_loader = importlib.machinery.SourceFileLoader.exec_module
                importlib.machinery.SourceFileLoader.exec_module = original
            self.root = Path(self.dir.name) / "ledger.git"
            subprocess.run(["git", "init", "-q", "--bare", str(self.root)], check=True)
            subprocess.run(["git", "-C", self.repo_root, "push", "-q", str(self.root), tip + ":" + REF], check=True,
                           capture_output=True)
            os.environ.update(IDENTITY)
            os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = "git+%s#%s" % (self.root, REF)
            os.environ["STEGVERSE_ORG_LEDGER_GIT_DIR"] = str(self.root)
            os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = "git+%s#%s:%s" % (self.root, REF, namespace)
        else:
            self.root = Path(self.dir.name)
            subprocess.run("git -C '%s' archive %s | tar -x -C '%s'" % (self.repo_root, tip, self.root),
                           shell=True, check=True)
            os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = str(self.root)
            os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = str(self.root / namespace)

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
