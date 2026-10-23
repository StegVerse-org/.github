"""Main-change receipt writer census and per-repository install patches (B1; StegVerse-org/.github#160
issuecomment-6353130407 section 1.3). Lowest supported operating mode: E0 (stdlib, no clock, no network).

Input: a JSON list of repositories ``{"repo", "default_branch", "workflows": [file names]}`` observed by whoever
runs the census (the TVC ICV census, TVC#520, is the canonical list; any listing with the same shape works).
A repository is ALLOW when it runs either the existing organization ledger writer
(``organization-ledger-merge-transfer.yml``) or the pinned caller of ``main-change-receipt.yml``; every other
repository is FAIL_CLOSED MAIN_CHANGE_RECEIPT_WRITER_NOT_INSTALLED with the six fields of the #160 B1 text,
and gets an install patch (one new file, ``git apply``-able) that pins the caller to ``--pin``.
Installing is a push to that repository's main, which this census never does.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "stegverse.main-change-receipt-writer-census/v1"
LOWEST_SUPPORTED_MODE = "E0"
EXISTING_WRITER = "organization-ledger-merge-transfer.yml"
CALLER = "main-change-receipt-caller.yml"
CALLER_PATH = ".github/workflows/" + CALLER
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def seal(body: Mapping[str, Any]) -> dict[str, Any]:
    clean = {k: v for k, v in body.items() if k != "result_sha256"}
    return {**clean, "result_sha256": "sha256:" + hashlib.sha256(canon(clean)).hexdigest()}


def caller_workflow(pin: str, writer_sha256: str) -> str:
    if not (SHA40.match(pin) and SHA256.match(writer_sha256)):
        raise ValueError("pin is a 40-hex commit and writer_sha256 a 64-hex digest")
    return f"""name: Main Change Receipt

# Every push to main is receipted (StegVerse-org/.github#160 B1). E0: no LLM, no clock, no secret beyond
# GITHUB_TOKEN. The writer is pinned by commit and by the sha256 of its bytes.
on:
  push:
    branches: [main]

permissions:
  contents: write

jobs:
  receipt:
    uses: StegVerse-org/.github/.github/workflows/main-change-receipt.yml@{pin}
    with:
      writer_ref: {pin}
      writer_sha256: {writer_sha256}
"""


def install_patch(pin: str, writer_sha256: str) -> str:
    lines = caller_workflow(pin, writer_sha256).splitlines()
    return "".join([f"diff --git a/{CALLER_PATH} b/{CALLER_PATH}\n", "new file mode 100644\n", "--- /dev/null\n",
                    f"+++ b/{CALLER_PATH}\n", f"@@ -0,0 +1,{len(lines)} @@\n"] + [f"+{l}\n" for l in lines])


def record(repo: Mapping[str, Any], patch_name: str | None) -> dict[str, Any]:
    wfs = set(repo.get("workflows") or [])
    branch = repo.get("default_branch")
    base = {"repository": repo["repo"], "default_branch": branch,
            "existing_writer_installed": EXISTING_WRITER in wfs, "pinned_caller_installed": CALLER in wfs}
    if base["existing_writer_installed"] or base["pinned_caller_installed"]:
        return {**base, "disposition": "ALLOW"}
    repair = f"add the pinned caller in that repo ({CALLER_PATH}; install patch {patch_name})"
    if branch != "main":
        repair += f"; the default branch is {branch}, so the caller observes main only until the default branch is main"
    return {**base, "disposition": "FAIL_CLOSED", "failure_code": "MAIN_CHANGE_RECEIPT_WRITER_NOT_INSTALLED",
            "failed_predicate": "REPO_MAIN_PUSH_EMITS_ORGANIZATION_MAIN_MERGE_TRANSFER",
            "required_evidence_or_repair": repair, "retry_entrypoint": "the repo's next push to main",
            "owning_existing_goal": "STEGVERSE-CANONICAL-WORK-COORDINATION-001", "next_attempt": "the census receipt flips to ALLOW"}


def census(repos: list[Mapping[str, Any]], pin: str, writer_sha256: str, source: Mapping[str, Any]) -> dict[str, Any]:
    patch = install_patch(pin, writer_sha256)
    patch_sha = hashlib.sha256(patch.encode()).hexdigest()
    records = [record(r, f"main-change-receipt-caller.{patch_sha[:12]}.patch") for r in sorted(repos, key=lambda r: r["repo"].lower())]
    by_org: dict[str, dict[str, int]] = {}
    for r in records:
        o = by_org.setdefault(r["repository"].split("/")[0], {"repositories": 0, "ALLOW": 0, "FAIL_CLOSED": 0})
        o["repositories"] += 1
        o[r["disposition"]] += 1
    return seal({"schema": SCHEMA, "lowest_supported_mode": LOWEST_SUPPORTED_MODE, "source": dict(source),
                 "writer_pin": {"repository": "StegVerse-org/.github", "commit": pin,
                                "workflow": ".github/workflows/main-change-receipt.yml",
                                "writer": "resident-runtime/main_change_receipt.py", "writer_sha256": writer_sha256},
                 "install_patch_sha256": patch_sha,
                 "totals": {"repositories": len(records), "ALLOW": sum(r["disposition"] == "ALLOW" for r in records),
                            "FAIL_CLOSED": sum(r["disposition"] == "FAIL_CLOSED" for r in records)},
                 "organizations": by_org, "records": records, "authority_effect": "NONE"})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="main-change receipt writer census (E0)")
    ap.add_argument("--repos", required=True)
    ap.add_argument("--pin", required=True)
    ap.add_argument("--writer-sha256", required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    raw = Path(a.repos).read_bytes()
    result = census(json.loads(raw), a.pin, a.writer_sha256,
                    {"file": Path(a.repos).name, "sha256": hashlib.sha256(raw).hexdigest()})
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "census.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (out / f"main-change-receipt-caller.{result['install_patch_sha256'][:12]}.patch").write_text(install_patch(a.pin, a.writer_sha256))
    print(json.dumps({"totals": result["totals"], "result_sha256": result["result_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
