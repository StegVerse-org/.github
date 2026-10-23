"""DRIFT_RECEIPT_APPENDER: manifest-declared transition for StegVerse-Labs/.github#3317 drift payloads
(StegVerse-org/.github#166 ENTERPRISE-HOST-PROVIDER-ERADICATION-001; parent #160; ledger lane #162).

Lowest supported operating mode: E0. Stdlib only; no clock, no network, no secret. Declared by
``resident-runtime/drift-receipt-appender.transition.json`` (operation TEST_SUITE_BASELINE_DRIFT) and built on
the B1 main-change receipt writer (``resident-runtime/main_change_receipt.py``, loaded from a path and admitted
only at its pinned sha256):

  1. the payload (stegverse.test-suite-baseline-drift/v1 from ``detect`` or stegverse.test-suite-pr-disposition/v1
     from ``pr``) must verify under the writer's seal, carry a supplied hb_epoch, and carry all six fields when
     its disposition is not ALLOW;
  2. the writer's ``observe`` receipts the payload's head commit (head^1..head) in the payload's repository;
  3. the drift transition receipt binds payload, main-change receipt and writer pin, sealed by the writer's
     ``seal``; its admission is FAIL_CLOSED pending genesis (six fields) until the organization ledger admits
     the operation from genesis;
  4. ``dry-run`` appends with the writer's ``append`` onto ``refs/stegverse/test-suite-baseline-drift`` of a
     scratch repository only (a repository with any remote configured is refused) and verifies by readback.

It never writes, pushes or dispatches the organization ledger or any published ref.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

SCHEMA = "stegverse.drift-transition-receipt/v1"
OPERATION = "TEST_SUITE_BASELINE_DRIFT"
PAYLOAD_SCHEMAS = ("stegverse.test-suite-baseline-drift/v1", "stegverse.test-suite-pr-disposition/v1")
DRIFT_REF = "refs/stegverse/test-suite-baseline-drift"
WRITER_PATH = "resident-runtime/main_change_receipt.py"
WRITER_SHA256 = "884168399f8ac54309aac86af6ab34481635de54426f635bb2229eb5073e2ebf"
MANIFEST = "resident-runtime/drift-receipt-appender.transition.json"
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
GOAL = "StegVerse-org/.github#162 (organization ledger) / StegVerse-org/.github#166 ENTERPRISE-HOST-PROVIDER-ERADICATION-001"
ENTRYPOINT = "resident-runtime/drift_receipt_appender.py receipt (per the transition declaration " + MANIFEST + ")"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
EPOCH = re.compile(r"^(?:3[2-9]|[4-9][0-9]|[1-9][0-9]{2,})$")


def fail(code: str, predicate: str, repair: str, next_attempt: str, retry: str = ENTRYPOINT, goal: str = GOAL) -> dict[str, str]:
    return {"disposition": "FAIL_CLOSED", "failure_code": code, "failed_predicate": predicate,
            "required_evidence_or_repair": repair, "retry_entrypoint": retry, "owning_existing_goal": goal,
            "next_attempt": next_attempt}


ADMISSION_PENDING_GENESIS = fail(
    "DRIFT_RECEIPT_APPENDER_ADMISSION_PENDING_GENESIS", "APPENDER_TRANSITION_IS_ADMITTED_FROM_ORGANIZATION_LEDGER_GENESIS",
    "the organization ledger declares its genesis (ORG_LEDGER_GENESIS_NOT_DECLARED in aggregate_repo_transition) and "
    "admits operation TEST_SUITE_BASELINE_DRIFT from it; until then the receipt is produced and retained, never appended "
    "to the organization ledger", "the first drift payload after genesis admits TEST_SUITE_BASELINE_DRIFT")


def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_writer(path: Path | str, expected: str = WRITER_SHA256) -> tuple[ModuleType | None, dict[str, Any] | None]:
    path = Path(path)
    if not path.is_file():
        return None, fail("B1_WRITER_UNREADABLE", "B1_WRITER_IS_PRESENT_AT_ITS_PIN",
                          f"supply {WRITER_PATH} of StegVerse-org/.github at sha256 {expected}", "re-run with --writer")
    digest = sha256_file(path)
    if digest != expected:
        return None, {**fail("B1_WRITER_NOT_AT_PIN", "B1_WRITER_IS_PRESENT_AT_ITS_PIN",
                             f"the writer must hash to {expected}; re-pin the declaration through a reviewed change",
                             "re-run with the pinned writer"), "observed_sha256": digest}
    spec = importlib.util.spec_from_file_location("b1_main_change_receipt", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, None


def load_manifest(path: Path | str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None, fail("TRANSITION_DECLARATION_UNREADABLE", "APPENDER_RUNS_ONLY_UNDER_ITS_DECLARATION",
                          f"supply {MANIFEST}", "re-run with --manifest")
    if doc.get("operation") != OPERATION or doc.get("writer", {}).get("sha256") != WRITER_SHA256 \
            or doc.get("output", {}).get("ref") != DRIFT_REF:
        return None, fail("TRANSITION_DECLARATION_MISMATCH", "APPENDER_RUNS_ONLY_UNDER_ITS_DECLARATION",
                          "the declaration's operation, writer pin and output ref must match this appender",
                          "re-run with the declaration of this appender")
    return doc, None


def check_payload(writer: ModuleType, payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping) or payload.get("schema") not in PAYLOAD_SCHEMAS:
        return fail("DRIFT_PAYLOAD_SCHEMA_NOT_ACCEPTED", "PAYLOAD_IS_A_TEST_SUITE_BASELINE_DRIFT_RECORD",
                    "supply the detect receipt or pr disposition of scripts/test_suite_baseline_drift.py",
                    "re-run with a drift payload")
    if not writer.seal_verifies(payload):
        return fail("DRIFT_PAYLOAD_SEAL_DOES_NOT_VERIFY", "PAYLOAD_RECEIPT_SHA256_VERIFIES_UNDER_THE_B1_SEAL",
                    "supply the payload byte-for-byte as the drift run retained it", "re-run with the retained payload")
    if not (isinstance(payload.get("head"), str) and SHA40.match(payload["head"])) or not payload.get("repository"):
        return fail("DRIFT_PAYLOAD_HEAD_UNNAMED", "PAYLOAD_NAMES_ITS_REPOSITORY_AND_HEAD_COMMIT",
                    "the payload must name repository and a full head commit", "re-run with a complete payload")
    if not (isinstance(payload.get("hb_epoch"), str) and EPOCH.match(payload["hb_epoch"])):
        return fail("HB_EPOCH_SOURCE_UNOBSERVED", "EPOCH_IS_SUPPLIED_NEVER_READ_FROM_A_CLOCK",
                    "the drift run must read hb_epoch from the organization ledger head", "the next drift payload with a supplied epoch")
    if payload.get("disposition") != "ALLOW" and not all(payload.get(k) for k in SIX_FIELDS):
        return fail("DRIFT_PAYLOAD_SIX_FIELDS_INCOMPLETE", "EVERY_NON_ALLOW_PAYLOAD_CARRIES_SIX_FIELDS",
                    "the drift run must emit all six fields on a non-ALLOW disposition", "re-run the drift job")
    return None


def receipt(root: Path | str, payload: Mapping[str, Any], writer: ModuleType, writer_ref: str) -> dict[str, Any]:
    head = payload["head"]
    if subprocess.run(["git", "-C", str(root), "cat-file", "-e", head + "^{commit}"], capture_output=True).returncode:
        return fail("DRIFT_PAYLOAD_HEAD_NOT_IN_REPOSITORY", "B1_WRITER_OBSERVES_THE_PAYLOAD_HEAD",
                    f"--root must hold {payload['repository']} commit {head} (fetch it, depth 2)", "re-run with the commit present")
    parent = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet", head + "^1"],
                            capture_output=True, text=True).stdout.strip()
    pin = {"repository": "StegVerse-org/.github", "path": WRITER_PATH, "ref": writer_ref, "sha256": WRITER_SHA256}
    main_change = writer.observe(root, repository=payload["repository"], before=parent, after=head, writer=pin)[-1]
    items = [*main_change["items"], ADMISSION_PENDING_GENESIS]
    body = {"schema": SCHEMA, "operation": OPERATION, "lowest_supported_mode": "E0",
            "transition_declaration": MANIFEST, "repository": payload["repository"],
            "commit": head, "committer_time_recorded": main_change["committer_time_recorded"],
            "payload": {"schema": payload["schema"], "receipt_sha256": payload["receipt_sha256"],
                        "disposition": payload["disposition"], "failure_code": payload.get("failure_code"),
                        "base": payload.get("base"), "head": head},
            "main_change_receipt": main_change, "main_change_receipt_sha256": main_change["receipt_sha256"],
            "hb_epoch": payload["hb_epoch"], "writer": pin,
            "admission": dict(ADMISSION_PENDING_GENESIS), "items": items, "disposition": "FAIL_CLOSED",
            "first_item": {k: ADMISSION_PENDING_GENESIS[k] for k in SIX_FIELDS},
            "organization_ledger_effect": "NONE", "authority_effect": "NONE"}
    return writer.seal(body)


def scratch_refusal(root: Path | str) -> dict[str, Any] | None:
    remotes = subprocess.run(["git", "-C", str(root), "remote"], capture_output=True, text=True)
    if remotes.returncode or remotes.stdout.strip():
        return fail("DRY_RUN_TARGET_NOT_SCRATCH", "DRY_RUN_APPENDS_ONLY_TO_A_SCRATCH_REPOSITORY",
                    "the dry run appends only into a repository with no remote configured (a scratch copy)",
                    "re-run against a scratch copy", retry="resident-runtime/drift_receipt_appender.py dry-run")
    return None


def verify(root: Path | str, writer: ModuleType, receipts: list[Mapping[str, Any]], ref: str = DRIFT_REF) -> dict[str, Any]:
    problems = []
    for r in receipts:
        shown = subprocess.run(["git", "-C", str(root), "show", f"{ref}:{writer.receipt_path(r['commit'])}"],
                               capture_output=True, text=True)
        doc = json.loads(shown.stdout) if shown.returncode == 0 else None
        if not (doc and writer.seal_verifies(doc) and doc.get("schema") == SCHEMA and doc == dict(r)):
            problems.append(r["commit"])
    if problems:
        return {**fail("DRIFT_TRANSITION_RECEIPT_NOT_READ_BACK", "EVERY_APPENDED_RECEIPT_READS_BACK_SEALED",
                       "re-run the dry run; an appended receipt is answered from the ref", "re-run the dry run",
                       retry="resident-runtime/drift_receipt_appender.py dry-run"), "problems": problems}
    return {"disposition": "ALLOW", "ref": ref, "verified": [r["commit"] for r in receipts]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DRIFT_RECEIPT_APPENDER (E0)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("receipt", "dry-run"):
        p = sub.add_parser(name)
        p.add_argument("--root", required=True, help="git repository holding the payload's head commit")
        p.add_argument("--payload", required=True, action="append")
        p.add_argument("--writer", default=str(Path(__file__).with_name("main_change_receipt.py")))
        p.add_argument("--writer-ref", required=True)
        p.add_argument("--manifest", default=str(Path(__file__).with_name("drift-receipt-appender.transition.json")))
        p.add_argument("--out", required=True)
        if name == "dry-run":
            p.add_argument("--scratch", required=True, help="scratch repository (no remote) receiving the append")
            p.add_argument("--fresh", help="empty repository the scratch ref is fetched into for verification")
    a = ap.parse_args(argv)
    writer, refusal = load_writer(a.writer)
    if refusal is None:
        _, refusal = load_manifest(a.manifest)
    result: dict[str, Any]
    if refusal is not None:
        result = {"refusal": refusal}
    else:
        receipts, refusals = [], []
        for path in a.payload:
            try:
                payload = json.loads(Path(path).read_text())
            except (OSError, ValueError):
                payload = None
            bad = check_payload(writer, payload)
            if bad is None and any(r["commit"] == payload["head"] for r in receipts):
                bad = fail("DRIFT_PAYLOAD_HEAD_REPEATED", "ONE_DRIFT_TRANSITION_RECEIPT_PER_HEAD_PER_RUN",
                           "supply one payload per head commit in a run", "re-run with one payload per head")
            r = bad if bad else receipt(a.root, payload, writer, a.writer_ref)
            if r.get("schema") == SCHEMA:
                receipts.append(r)
            else:
                refusals.append({**r, "payload_path": path})
        result = {"receipts": receipts, "refusals": refusals}
        if a.cmd == "dry-run" and not refusals:
            refusal = scratch_refusal(a.scratch)
            if refusal:
                result["refusal"] = refusal
            else:
                result["append"] = writer.append(a.scratch, receipts, ref=DRIFT_REF)
                result["replay"] = writer.append(a.scratch, receipts, ref=DRIFT_REF)
                target = a.scratch
                if a.fresh:
                    subprocess.run(["git", "-C", a.fresh, "fetch", "-q", a.scratch, f"+{DRIFT_REF}:{DRIFT_REF}"], check=True)
                    target = a.fresh
                result["verify"] = verify(target, writer, receipts)
    Path(a.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    blocked = result.get("refusal") or result.get("refusals") or result.get("verify", {}).get("disposition") == "FAIL_CLOSED" \
        or (result.get("replay") or {}).get("appended")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
