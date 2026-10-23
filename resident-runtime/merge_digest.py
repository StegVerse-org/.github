#!/usr/bin/env python3
"""Main-change digest: every ledgered merge or main push is projected to its Goal (B3).

StegVerse-org/.github#160 issuecomment-6353130407 section 1.3 (B3), under
STEGVERSE-CANONICAL-WORK-COORDINATION-001. The consumer is
.github/workflows/organization-ledger-merge-digest.yml, triggered only by
``workflow_run`` of this repository's main-merge transfer writer
("Organization Ledger Main Merge Transfer", types [completed]). There is no
schedule, no dispatch, no pull_request writer, and no clock read: every line
comes from the writer run's own evidence and from receipts read back from the
published organization ledger ref.

Lowest supported operating mode: E0 (ecosystem only, no LLM). Nothing here
needs an LLM or a person to reach a terminal state; every projection that
cannot be made is a six-field FAIL_CLOSED carried in the digest itself.

  commits   the merges the writer run selected (its retained commits.txt), or the
            run's head commit when that evidence is absent. Prints one 40-hex
            sha per line.
  build     reads the verifier's results for those merges (ALLOW with receipt ids,
            or the six fields), the organization receipts they name (read back
            from the ledger git dir), and the observed pull requests, and writes
            one digest per receipt batch (one writer run = one ledger-head
            advance): JSON plus the Markdown comment body.

Projection 1 is a comment on the Goal issue the receipt's task binding names
(default StegVerse-org/.github#160); the workflow posts it only where its
GITHUB_TOKEN reaches (the same repository). A Goal issue in another repository
is a six-field FAIL_CLOSED until a TV/TVC-issued per-transition credential
exists; the digest is still in the run summary and artifact. Projection 2 (the
KV coordination folder) is a six-field FAIL_CLOSED until the KV custody path
settled on StegVerse-org/.github#163 (TVC#529, review item C4) is bound; the
KV file is written into the artifact for that path to carry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA = "stegverse.main-change-digest/v1"
OWNING_GOAL = "STEGVERSE-CANONICAL-WORK-COORDINATION-001"
DEFAULT_GOAL_ISSUE = "StegVerse-org/.github#160"
CONSUMER = ".github/workflows/organization-ledger-merge-digest.yml"
WRITER_NAME = "Organization Ledger Main Merge Transfer"
LOWEST_SUPPORTED_MODE = "E0"
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
GOAL_ISSUE = re.compile(r"^(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(?P<number>[1-9][0-9]*)$")
# Fields a receipt may use to bind its task's Goal issue; none is set today, so the default applies.
GOAL_BINDING_FIELDS = ("goal_issue", "owning_goal_issue", "task_binding")


def six(code: str, predicate: str, repair: str, retry: str, goal: str, next_attempt: str, **extra: Any) -> dict:
    return {"disposition": "FAIL_CLOSED", "failure_code": code, "failed_predicate": predicate,
            "required_evidence_or_repair": repair, "retry_entrypoint": retry, "owning_existing_goal": goal,
            "next_attempt": next_attempt, **extra}


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canon(value)).hexdigest()


def sealed(receipt: Any) -> bool:
    return (isinstance(receipt, dict) and isinstance(receipt.get("receipt_sha256"), str)
            and sha({k: v for k, v in receipt.items() if k != "receipt_sha256"}) == receipt["receipt_sha256"])


# -- which merges ------------------------------------------------------------

def selected_commits(results_dir: Path | None, head_sha: str) -> tuple[list[str], str]:
    """The writer run's selection, else its head commit. Malformed lines are dropped, never guessed."""
    if results_dir is not None and (results_dir / "commits.txt").is_file():
        listed = [c for c in (results_dir / "commits.txt").read_text(encoding="utf-8").split() if SHA40.match(c)]
        if listed:
            return list(dict.fromkeys(listed)), "WRITER_SELECTION"
    if not SHA40.match(head_sha or ""):
        raise ValueError("head_sha is not a 40-hex commit")
    return [head_sha], "WRITER_EVIDENCE_ABSENT_HEAD_ONLY"


# -- receipts ----------------------------------------------------------------

def read_receipt(git_dir: Path, ref: str, digest: Any) -> Any:
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        return None
    done = subprocess.run(["git", "--git-dir", str(git_dir), "show", f"{ref}:receipts/{digest[7:]}.json"],
                          capture_output=True)
    if done.returncode != 0:
        return None
    try:
        return json.loads(done.stdout)
    except ValueError:
        return None


def goal_issue_of(receipt: Any, default: str) -> tuple[str, str]:
    boundary = receipt.get("boundary_evidence") if isinstance(receipt, dict) else None
    for field in GOAL_BINDING_FIELDS:
        value = boundary.get(field) if isinstance(boundary, dict) else None
        if isinstance(value, dict):
            value = value.get("goal_issue")
        if isinstance(value, str) and GOAL_ISSUE.match(value):
            return value, "RECEIPT_TASK_BINDING"
    return default, "DEFAULT_GOAL_ISSUE"


def merge_kind(commit: str, pulls: Mapping[str, Any], parents: Mapping[str, int]) -> dict:
    numbers = [n for n in (pulls.get(commit) or []) if isinstance(n, int) and n > 0]
    if numbers:
        return {"merge_kind": "PULL_REQUEST", "pull_requests": sorted(set(numbers)), "observed_by": "commits/{sha}/pulls"}
    if commit in pulls:
        return {"merge_kind": "DIRECT_PUSH", "pull_requests": [], "observed_by": "commits/{sha}/pulls (none)",
                "parents": parents.get(commit)}
    return {"merge_kind": "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED", "pull_requests": [], "observed_by": None}


# -- the digest ----------------------------------------------------------------

def build(*, repository: str, head_sha: str, run_id: str, run_url: str, run_conclusion: str,
          commits: list[str], selection: str, results: Any, git_dir: Path | None, ref: str,
          pulls: Mapping[str, Any], parents: Mapping[str, int], default_goal_issue: str = DEFAULT_GOAL_ISSUE,
          kv_settled: bool = False) -> dict:
    by_commit = {}
    if isinstance(results, list):
        by_commit = {r.get("merge_commit"): r for r in results if isinstance(r, dict)}
    entries = []
    for commit in commits:
        result = by_commit.get(commit)
        entry: dict[str, Any] = {"repository": repository, "merged_head": commit, **merge_kind(commit, pulls, parents)}
        if not isinstance(result, dict):
            entry.update(six("MAIN_CHANGE_RECEIPT_NOT_VERIFIED", "EVERY_LEDGERED_MAIN_CHANGE_IS_PROJECTED_TO_ITS_GOAL",
                             "the verifier returned no result for this merge; the writer run's evidence is in its artifact",
                             CONSUMER + " (the next merge-transfer completion)", OWNING_GOAL,
                             "the next writer run re-selects every unreceipted merge (pending + pushed range)"))
            entry["goal_issue"], entry["goal_binding"] = default_goal_issue, "DEFAULT_GOAL_ISSUE"
        else:
            receipt = read_receipt(git_dir, ref, result.get("organization_receipt_sha256")) if git_dir else None
            entry["goal_issue"], entry["goal_binding"] = goal_issue_of(receipt, default_goal_issue)
            entry["receipt_id"] = result.get("organization_receipt_sha256")
            entry["repository_receipt_id"] = result.get("repository_receipt_sha256")
            entry["epoch"] = result.get("hb_epoch")
            if result.get("disposition") == "ALLOW":
                if receipt is not None and not sealed(receipt):
                    entry.update(six("MAIN_CHANGE_RECEIPT_NOT_SEALED", "PROJECTED_RECEIPT_IS_SEALED",
                                     "the organization receipt the verifier named does not reseal to its digest",
                                     CONSUMER, OWNING_GOAL, "re-read on the next ledger-head advance"))
                else:
                    entry["disposition"] = "ALLOW"
                    entry["receipt_read_back"] = receipt is not None
                    if isinstance(receipt, dict):
                        entry["epoch_derived_from_clock"] = (receipt.get("hb_reference") or {}).get("derived_from_clock")
            else:
                entry["disposition"] = result.get("disposition") or "FAIL_CLOSED"
                for field in SIX_FIELDS:
                    entry[field] = result.get(field)
        entries.append(entry)
    digest_id = sha({"repository": repository, "run_id": run_id, "entries": [
        [e["merged_head"], e.get("receipt_id"), e.get("disposition")] for e in entries]})
    targets = sorted({e["goal_issue"] for e in entries}) or [default_goal_issue]
    projections = []
    for target in targets:
        match = GOAL_ISSUE.match(target)
        if match and match.group("repo") == repository:
            projections.append({"projection": "GOAL_ISSUE_COMMENT", "target": target, "disposition": "ALLOW"})
        else:
            projections.append({"projection": "GOAL_ISSUE_COMMENT", "target": target, **six(
                "GOAL_ISSUE_CROSS_REPOSITORY_WRITE_CREDENTIAL_NOT_ISSUED",
                "EVERY_LEDGERED_MAIN_CHANGE_IS_PROJECTED_TO_ITS_GOAL",
                "a TV/TVC per-transition credential scoped to issues:write on " + str(target).split("#")[0]
                + " (credential issuance is a TV/TVC transition); until then this digest is in the run summary and artifact",
                CONSUMER + " (the next merge-transfer completion)", "TVC-GITHUB-REPOSITORY-OPERATION-BROKER-001",
                "the first completion after the credential is issued posts this digest", class_="B")})
    projections.append({"projection": "KV_COORDINATION_FOLDER", "target": "KV coordination folder: merge-digests/",
                        **({"disposition": "ALLOW"} if kv_settled else six(
                            "KV_DIGEST_CUSTODY_PATH_NOT_SETTLED", "MAIN_CHANGE_DIGEST_IS_IN_THE_KV_COORDINATION_FOLDER",
                            "bind the KV custody path settled on StegVerse-org/.github#163 (TVC#529, review item C4) as "
                            "the projection-2 writer; the KV file is in this run's artifact for it to carry",
                            CONSUMER, "TASK-REGISTRY-SOVEREIGN-KV-EVENT-CUSTODY-001",
                            "the first completion after the custody path is bound writes the file", class_="C"))})
    for p in projections:
        if "class_" in p:
            p["class"] = p.pop("class_")
    return {"schema": SCHEMA, "digest_id": digest_id, "repository": repository, "writer": WRITER_NAME,
            "writer_run_id": run_id, "writer_run_url": run_url, "writer_run_conclusion": run_conclusion,
            "writer_head_sha": head_sha, "selection": selection, "batch_boundary": "ONE_WRITER_RUN_ONE_LEDGER_HEAD_ADVANCE",
            "lowest_supported_mode": LOWEST_SUPPORTED_MODE, "clock_read": False, "authority_effect": "NONE_PROJECTION_ONLY",
            "owning_goal": OWNING_GOAL, "entries": entries, "projections": projections,
            "marker": "<!-- stegverse-main-change-digest " + digest_id + " -->"}


def markdown(digest: Mapping[str, Any], target: str | None = None) -> str:
    lines = [digest["marker"],
             f"**Main-change digest** `{digest['repository']}` — writer run [{digest['writer_run_id']}]({digest['writer_run_url']}) "
             f"({digest['writer_run_conclusion']}), lowest supported mode {digest['lowest_supported_mode']}, "
             f"authority NONE (projection only).", "",
             "| repo | change | merged head | receipt | epoch | disposition |", "|---|---|---|---|---|---|"]
    for e in digest["entries"]:
        if target is not None and e["goal_issue"] != target:
            continue
        change = (", ".join(f"PR #{n}" for n in e["pull_requests"]) if e["merge_kind"] == "PULL_REQUEST"
                  else e["merge_kind"])
        receipt = (e.get("receipt_id") or "—")[:19]
        if e.get("disposition") == "ALLOW":
            disposition = "ALLOW"
        else:
            disposition = e.get("disposition", "FAIL_CLOSED") + ": " + " / ".join(
                str(e.get(f)) for f in SIX_FIELDS)
        lines.append(f"| {e['repository']} | {change} | `{e['merged_head'][:12]}` | `{receipt}` | {e.get('epoch')} | {disposition} |")
    refused = [p for p in digest["projections"] if p.get("disposition") != "ALLOW"]
    if refused:
        lines += ["", "Projections not made (six fields):"]
        for p in refused:
            lines.append(f"- {p['projection']} → {p['target']}: " + " / ".join(str(p.get(f)) for f in SIX_FIELDS))
    lines += ["", f"Selection: {digest['selection']}; batch boundary: {digest['batch_boundary']}; digest `{digest['digest_id']}`."]
    return "\n".join(lines) + "\n"


def _load_json(path: Path | None, default: Any) -> Any:
    if path is None or not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("commits")
    c.add_argument("--results-dir", type=Path)
    c.add_argument("--head-sha", required=True)
    b = sub.add_parser("build")
    b.add_argument("--repository", required=True)
    b.add_argument("--head-sha", required=True)
    b.add_argument("--run-id", required=True)
    b.add_argument("--run-url", required=True)
    b.add_argument("--run-conclusion", required=True)
    b.add_argument("--results-dir", type=Path)
    b.add_argument("--verify-json", type=Path)
    b.add_argument("--pulls-json", type=Path)
    b.add_argument("--parents-json", type=Path)
    b.add_argument("--ledger-git-dir", type=Path)
    b.add_argument("--ledger-ref", default="refs/stegverse/organization-ledger")
    b.add_argument("--default-goal-issue", default=DEFAULT_GOAL_ISSUE)
    b.add_argument("--out-json", type=Path, required=True)
    b.add_argument("--out-dir", type=Path, required=True, help="one comment body per Goal issue, plus the KV file")
    args = parser.parse_args(argv)
    if args.command == "commits":
        commits, selection = selected_commits(args.results_dir, args.head_sha)
        print("\n".join(commits))
        print(selection, file=sys.stderr)
        return 0
    commits, selection = selected_commits(args.results_dir, args.head_sha)
    digest = build(repository=args.repository, head_sha=args.head_sha, run_id=args.run_id, run_url=args.run_url,
                   run_conclusion=args.run_conclusion, commits=commits, selection=selection,
                   results=_load_json(args.verify_json, None), git_dir=args.ledger_git_dir, ref=args.ledger_ref,
                   pulls=_load_json(args.pulls_json, {}), parents=_load_json(args.parents_json, {}),
                   default_goal_issue=args.default_goal_issue)
    args.out_json.write_text(json.dumps(digest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for p in digest["projections"]:
        if p["projection"] == "GOAL_ISSUE_COMMENT":
            name = "comment-" + re.sub(r"[^A-Za-z0-9]+", "-", p["target"]).strip("-") + ".md"
            (args.out_dir / name).write_text(markdown(digest, p["target"]), encoding="utf-8")
    kv = args.out_dir / "kv" / "merge-digests" / (args.repository.replace("/", "__") + "@" + args.head_sha + ".md")
    kv.parent.mkdir(parents=True, exist_ok=True)
    kv.write_text(markdown(digest), encoding="utf-8")
    print(markdown(digest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
