"""TEST_SUITE_BASELINE_REFRESH: the org main receipt refreshed on push to main, as a manifest transition
(StegVerse-org/.github#166 ENTERPRISE-HOST-PROVIDER-ERADICATION-001; ledger lane #162).

Lowest supported operating mode: E0. Stdlib only; no clock, no network, no secret. Declared by
``resident-runtime/test-suite-baseline-refresh.transition.json`` and triggered only by a push to main
(``.github/workflows/test-suite-baseline-refresh.yml``; no schedule, no dispatch, no polling). It forks nothing:

  1. the pinned StegVerse-Labs drift tool's ``detect`` receipts the main head (every set run once) through the
     B1 main-change receipt writer (``resident-runtime/main_change_receipt.py``, admitted only at its sha256);
  2. ``resident-runtime/drift_receipt_appender.py`` (admitted at its declared sha256) turns that receipt into a
     drift transition receipt and appends it to a scratch repository only, verified by fresh-fetch readback;
  3. this module binds the two into the refresh transition record, sealed by the writer's ``seal``: the new
     candidate main receipt, the committed receipt it would replace, and an admission that is FAIL_CLOSED
     pending genesis (six fields). The candidate is retained as an artifact; nothing is committed, pushed,
     dispatched or written to the organization ledger until the ledger admits the operation from genesis.
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

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = "resident-runtime/test-suite-baseline-refresh.transition.json"
WORKFLOW = ".github/workflows/test-suite-baseline-refresh.yml"
OPERATION = "TEST_SUITE_BASELINE_MAIN_RECEIPT_REFRESH"
SCHEMA = "stegverse.test-suite-baseline-refresh-receipt/v1"
DETECT_SCHEMA = "stegverse.test-suite-baseline-drift/v1"
DRIFT_SCHEMA = "stegverse.drift-transition-receipt/v1"
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
              "owning_existing_goal", "next_attempt")
GOAL = "StegVerse-org/.github#162 (organization ledger) / StegVerse-org/.github#166 ENTERPRISE-HOST-PROVIDER-ERADICATION-001"
ENTRYPOINT = f"resident-runtime/test_suite_baseline_refresh.py transition (per {DECLARATION}; on push to main: {WORKFLOW})"
FORBIDDEN_TRIGGERS = ("schedule", "workflow_dispatch", "repository_dispatch", "workflow_run", "pull_request_target")


def fail(code: str, predicate: str, repair: str, next_attempt: str) -> dict[str, str]:
    return {"disposition": "FAIL_CLOSED", "failure_code": code, "failed_predicate": predicate,
            "required_evidence_or_repair": repair, "retry_entrypoint": ENTRYPOINT, "owning_existing_goal": GOAL,
            "next_attempt": next_attempt}


def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_json(path: Path | str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def workflow_triggers(text: str) -> list[str]:
    """Top-level keys of the workflow's `on:` block (stdlib reading of the block form used in this repository)."""
    lines = text.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if re.match(r"^(on|\"on\"|'on'):\s*$", l))
    except StopIteration:
        return ["<on: not in block form>"]
    keys = []
    for line in lines[start + 1:]:
        if line and not line.startswith(" ") and not line.startswith("#"):
            break
        m = re.match(r"^  ([A-Za-z_]+):", line)
        if m:
            keys.append(m.group(1))
    return keys


def check_declaration(root: Path, declaration: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The declaration is this transition's, its pins are the files' bytes, its admission is FAIL_CLOSED with six
    fields, and its workflow triggers on push to main only."""
    def bad(why: str) -> dict[str, str]:
        return fail("TRANSITION_DECLARATION_MISMATCH", "REFRESH_RUNS_ONLY_UNDER_ITS_DECLARATION", why,
                    "re-run with the declaration of this transition")
    d = declaration if isinstance(declaration, Mapping) else None
    if d is None or d.get("operation") != OPERATION or d.get("schema") != "stegverse.transition-declaration/v1":
        return bad(f"supply {DECLARATION} (operation {OPERATION})")
    for key in ("writer", "appender"):
        pin = d.get("reuses", {}).get(key, {})
        path = root / str(pin.get("path"))
        if not path.is_file() or sha256_file(path) != pin.get("sha256"):
            return bad(f"reuses.{key} {pin.get('path')} must hash to its declared sha256")
    adm = d.get("admission", {})
    if adm.get("disposition") != "FAIL_CLOSED" or not all(adm.get(k) for k in SIX_FIELDS):
        return bad("the admission must be FAIL_CLOSED with all six fields until genesis")
    if any(d.get(k) != "NONE" for k in ("organization_ledger_effect", "registry_generation_effect", "authority_effect")):
        return bad("the declaration must claim no ledger, registry-generation or authority effect")
    trig = d.get("trigger", {})
    wf = root / str(trig.get("workflow"))
    if trig.get("event") != "push" or trig.get("branches") != ["main"] or not wf.is_file():
        return bad("the trigger must be a push to main through the declared workflow")
    text = wf.read_text(encoding="utf-8")
    triggers = workflow_triggers(text)
    if triggers != ["push"] or any(w in text for w in (*[f + ":" for f in FORBIDDEN_TRIGGERS], "cron")):
        return bad(f"the workflow must trigger on push only (found {triggers})")
    return None


def load_writer(root: Path, declaration: Mapping[str, Any]) -> ModuleType:
    pin = declaration["reuses"]["writer"]
    spec = importlib.util.spec_from_file_location("b1_main_change_receipt", root / pin["path"])
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def transition(root: Path, declaration: Mapping[str, Any], detect: Any, appended: Any, previous: Any,
               head: str, writer: ModuleType) -> dict[str, Any]:
    if not (isinstance(detect, Mapping) and detect.get("schema") == DETECT_SCHEMA and writer.seal_verifies(detect)):
        return fail("REFRESH_DETECT_RECEIPT_NOT_SEALED", "THE_CANDIDATE_MAIN_RECEIPT_IS_A_SEALED_DETECT_RECEIPT",
                    "supply the drift tool's detect receipt.json byte-for-byte", "re-run detect on the main head")
    if detect.get("head") != head:
        return fail("REFRESH_DETECT_RECEIPT_NOT_FOR_THIS_HEAD", "THE_CANDIDATE_MAIN_RECEIPT_IS_FOR_THE_PUSHED_HEAD",
                    f"the detect receipt names {detect.get('head')}, the pushed head is {head}", "re-run detect on the pushed head")
    receipts = appended.get("receipts") if isinstance(appended, Mapping) else None
    if not (isinstance(receipts, list) and len(receipts) == 1 and not appended.get("refusals")
            and not appended.get("refusal")):
        return fail("REFRESH_DRIFT_TRANSITION_NOT_RECEIPTED", "THE_APPENDER_RECEIPTED_EXACTLY_THIS_DETECT_RECEIPT",
                    "run drift_receipt_appender.py on the detect receipt (one payload, no refusal)", "re-run the appender")
    r = receipts[0]
    if not (r.get("schema") == DRIFT_SCHEMA and writer.seal_verifies(r) and r.get("commit") == head
            and r.get("payload", {}).get("receipt_sha256") == detect["receipt_sha256"]):
        return fail("REFRESH_DRIFT_TRANSITION_NOT_RECEIPTED", "THE_APPENDER_RECEIPTED_EXACTLY_THIS_DETECT_RECEIPT",
                    "the drift transition receipt must be sealed, for the pushed head, over this detect receipt",
                    "re-run the appender")
    if "verify" in appended and appended["verify"].get("disposition") != "ALLOW":
        return fail("REFRESH_SCRATCH_READBACK_FAILED", "THE_SCRATCH_APPEND_READS_BACK_SEALED",
                    "the appender's scratch dry run must read back", "re-run the dry run")
    prev = previous if isinstance(previous, Mapping) else {}
    adm = dict(declaration["admission"])
    body = {"schema": SCHEMA, "operation": OPERATION, "transition_declaration": DECLARATION,
            "lowest_supported_mode": "E0", "repository": detect.get("repository"), "head": head,
            "trigger": {"event": "push", "branch": "main", "workflow": WORKFLOW},
            "candidate_main_receipt": {"path": declaration["output"]["candidate"], "head": head,
                                       "receipt_sha256": detect["receipt_sha256"],
                                       "disposition": detect.get("disposition"),
                                       "failure_code": detect.get("failure_code"),
                                       "hb_epoch": detect.get("hb_epoch")},
            "replaces": {"path": declaration["output"]["candidate"], "head": prev.get("head"),
                         "receipt_sha256": prev.get("receipt_sha256"),
                         "seal_verifies": bool(prev) and writer.seal_verifies(prev)},
            "drift_transition_receipt_sha256": r["receipt_sha256"],
            "main_change_receipt_sha256": r.get("main_change_receipt_sha256"),
            "scratch_readback": (appended.get("verify") or {}).get("disposition", "NOT_RUN"),
            "reuses": {k: dict(v) for k, v in declaration["reuses"].items()},
            "admission": adm, "disposition": "FAIL_CLOSED", **{k: adm[k] for k in SIX_FIELDS},
            "published": "NONE", "organization_ledger_effect": "NONE", "authority_effect": "NONE"}
    return writer.seal(body)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="TEST_SUITE_BASELINE_REFRESH (E0)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--root", default=str(ROOT))
    c.add_argument("--declaration", default=None)
    t = sub.add_parser("transition")
    t.add_argument("--root", default=str(ROOT))
    t.add_argument("--declaration", default=None)
    t.add_argument("--head", default="HEAD")
    t.add_argument("--detect-receipt", required=True)
    t.add_argument("--appender-result", required=True)
    t.add_argument("--previous", required=True, help="the committed main receipt the candidate would replace")
    t.add_argument("--out", required=True)
    t.add_argument("--candidate-out", help="where the candidate main receipt is retained (an artifact path)")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    declaration = load_json(a.declaration or root / DECLARATION)
    refusal = check_declaration(root, declaration)
    if a.cmd == "check" or refusal is not None:
        result: dict[str, Any] = {"refusal": refusal} if refusal else {"disposition": "ALLOW", "declaration": "VALID",
                                                                        "admission": declaration["admission"]}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1 if refusal else 0
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", a.head + "^{commit}"],
                          capture_output=True, text=True).stdout.strip()
    detect = load_json(a.detect_receipt)
    record = transition(root, declaration, detect, load_json(a.appender_result), load_json(a.previous), head,
                        load_writer(root, declaration))
    Path(a.out).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    if record.get("schema") == SCHEMA and a.candidate_out:
        Path(a.candidate_out).write_text(json.dumps(detect, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: record.get(k) for k in ("disposition", *SIX_FIELDS, "receipt_sha256") if k in record},
                     sort_keys=True))
    return 0 if record.get("schema") == SCHEMA else 1


if __name__ == "__main__":
    sys.exit(main())
