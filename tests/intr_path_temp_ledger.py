"""A temporary copy of this organization's ledger at a pinned tip, bound the way its ledger binding reads it.

merge_transfer.py organizations: the tip's tree in a temporary directory
(STEGVERSE_ORG_LEDGER_ROOT / STEGVERSE_REPO_LEDGER_ROOT are POSIX roots).
Git-store organizations (merge_transfer_gitstore.py, StegVerse-Labs and
GCAT-BCAT-Engine): the tip in a temporary bare repository on the declared ref,
bound as ``git+<dir>#<ref>[:<namespace>]``, as Lane D's tests bind it.
Receipts written here are NOT LEDGERED and NOT AUTHENTIC; nothing is pushed.
Git commits in the temporary repository carry a fixed identity and date.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

REF = "refs/stegverse/organization-ledger"
ENV_KEYS = ("STEGVERSE_ORG_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_GIT_DIR", "STEGVERSE_REPO_LEDGER_ROOT",
            "STEGVERSE_ORG_LEDGER_STORE", "STEGVERSE_ORG_LEDGER_GIT_REF", "STEGVERSE_ORG_LEDGER_GIT_REMOTE",
            "STEGVERSE_ORG_LEDGER_GIT_CUSTODY", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL", "GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE")
IDENTITY = {"GIT_AUTHOR_NAME": "temp-ledger", "GIT_AUTHOR_EMAIL": "temp-ledger@invalid",
            "GIT_COMMITTER_NAME": "temp-ledger", "GIT_COMMITTER_EMAIL": "temp-ledger@invalid",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+0000", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+0000"}


class TempLedger:
    def __init__(self, repo_root: Path | str, tip: str, namespace: str, git: bool):
        self.repo_root, self.tip, self.namespace, self.git = str(repo_root), tip, namespace, git
        self.dir = tempfile.TemporaryDirectory()
        self.saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
        if git:
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
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v
        self.dir.cleanup()
