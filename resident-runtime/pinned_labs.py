#!/usr/bin/env python3
"""The pinned StegVerse-Labs tool, loaded by sha256 (StegVerse-org/.github#166).

`.stegverse/test-suite-baseline/labs-tool-pin.json` names one StegVerse-Labs/.github commit and the sha256 of
every file this repository loads from it. One implementation is reused, not forked: a job fetches that commit
anonymously (`fetch`) and names the checkout in STEGVERSE_LABS_ROOT; `module()` imports a pinned file only after
its bytes match the pin. A missing root, a file that is not pinned, or a digest mismatch raises PinnedLabsUnavailable
carrying six fields -- it never falls back to another implementation and never skips.

    python3 resident-runtime/pinned_labs.py fetch --dest DIR      # anonymous fetch + sha256 check
    python3 resident-runtime/pinned_labs.py verify --root DIR     # sha256 check only

E0: stdlib only, no credential (the fetch clears any configured auth header), nothing published.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / ".stegverse/test-suite-baseline/labs-tool-pin.json"
ENV = "STEGVERSE_LABS_ROOT"
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
       "owning_existing_goal", "next_attempt")


class PinnedLabsUnavailable(RuntimeError):
    def __init__(self, failed_predicate: str, repair: str) -> None:
        self.item = {"failure_code": "PINNED_LABS_TOOL_UNAVAILABLE", "failed_predicate": failed_predicate,
                     "required_evidence_or_repair": repair,
                     "retry_entrypoint": f"python3 resident-runtime/pinned_labs.py fetch --dest DIR; {ENV}=DIR",
                     "owning_existing_goal": "StegVerse-org/.github#166 ENTERPRISE-HOST-PROVIDER-ERADICATION-001",
                     "next_attempt": "the next run with the pinned StegVerse-Labs commit checked out"}
        super().__init__(f"PINNED_LABS_TOOL_UNAVAILABLE {failed_predicate}: {repair}")


def pin() -> dict:
    return json.loads(PIN.read_text(encoding="utf-8"))


def verify(root: Path, record: dict | None = None) -> dict[str, str]:
    """sha256 of every pinned file under root; raises unless all match."""
    record = record or pin()
    got = {}
    for rel, want in sorted(record["files"].items()):
        path = root / rel
        if not path.is_file():
            raise PinnedLabsUnavailable("EVERY_PINNED_FILE_IS_PRESENT", f"{rel} is absent under {root}")
        got[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        if got[rel] != want:
            raise PinnedLabsUnavailable("EVERY_PINNED_FILE_MATCHES_ITS_SHA256",
                                        f"{rel}: sha256 {got[rel]} is not the pinned {want}")
    return got


def labs_root() -> Path:
    raw = os.environ.get(ENV)
    if not raw or not Path(raw).is_dir():
        raise PinnedLabsUnavailable("THE_PINNED_LABS_CHECKOUT_IS_NAMED",
                                    f"{ENV} names no directory; fetch the pinned commit "
                                    f"({pin()['repository']}@{pin()['commit']}) and set {ENV}")
    return Path(raw)


def path(rel: str) -> Path:
    """A pinned file's path under the checkout, after its sha256 (and every other pinned file's) matches."""
    record = pin()
    if rel not in record["files"]:
        raise PinnedLabsUnavailable("THE_FILE_IS_PINNED", f"{rel} is not in {PIN.relative_to(ROOT)}")
    root = labs_root()
    verify(root, record)
    return root / rel


def module(rel: str) -> ModuleType:
    where = path(rel)          # verified against the pin on every call; a cached module never bypasses the check
    name = "pinned_labs__" + Path(rel).stem + "__" + hashlib.sha256(str(where).encode()).hexdigest()[:12]
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, where)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def json_schema() -> ModuleType:
    """The pinned stdlib JSON Schema validator (StegVerse-Labs scripts/stdlib_json_schema.py)."""
    return module("scripts/stdlib_json_schema.py")


def fetch(dest: Path) -> dict[str, str]:
    record = pin()
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    run = lambda *a: subprocess.run(["git", "-C", str(dest), *a], check=True, env=env, capture_output=True, text=True)
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(dest)], check=True, env=env)
    run("-c", "http.https://github.com/.extraheader=", "fetch", "--no-tags", "--quiet", "--depth=1",
        record["url"], record["commit"])
    run("checkout", "-q", "FETCH_HEAD")
    head = run("rev-parse", "HEAD").stdout.strip()
    if head != record["commit"]:
        raise PinnedLabsUnavailable("THE_CHECKOUT_IS_THE_PINNED_COMMIT", f"fetched {head}, pinned {record['commit']}")
    return verify(dest, record)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch").add_argument("--dest", required=True)
    sub.add_parser("verify").add_argument("--root", required=True)
    a = ap.parse_args(argv)
    try:
        got = fetch(Path(a.dest)) if a.cmd == "fetch" else verify(Path(a.root))
    except PinnedLabsUnavailable as exc:
        print(json.dumps(exc.item, sort_keys=True))
        return 2
    for rel, digest in got.items():
        print(rel, digest)
    print(f"PINNED_LABS_TOOL={pin()['commit']} files={len(got)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
