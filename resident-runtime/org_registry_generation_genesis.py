#!/usr/bin/env python3
"""``ORG_REGISTRY_GENERATION_GENESIS``: declare the organization registry's genesis generation by manifest transition.

This is the provisional E1 resolution of class C joint item Q-ORG-REGISTRY-GENERATION
(data/sv-merge-admission/provisional-resolutions.json). The C-review is PENDING, and a later
Claude or ChatGPT review receipt supersedes it.

The #3266 base-state readback for StegVerse-org/.github is FAIL_CLOSED REGISTRY_GENERATION_NOT_DECLARED,
because orchestration/task-registry.json declares no generation. Editing the registry is not the
repair. Instead, one sealed organization-ledger receipt binds generation 0 to the exact registry blob
that a sealed readback observed. SV_CHANGE_ADMISSION_GENESIS then reads from_registry_generation 0
from that receipt (E0 evidence once ledgered) and appends at 1.

E0 checks, in order. Each refusal carries the six fields and ``lowest_supported_mode`` E0, and writes nothing:
  1. REGISTRY_GENERATION_RESOLUTION_IS_RECORDED: the resolution exists with a C-review record. At E0
     the review receipt must be a sha256 (a PENDING review needs E1; it degrades, never stops).
  2. READBACK_OBSERVES_THE_UNDECLARED_REGISTRY: a sealed, well-shaped #3266 readback for this
     repository that is FAIL_CLOSED REGISTRY_GENERATION_NOT_DECLARED and names the registry blob.
  3. REGISTRY_GENERATION_NOT_ALREADY_DECLARED: verify-first. The same blob replays ALLOW. A different
     blob is DENY: a genesis is declared once, and later generations come from appends.
  4. HB_EPOCH_IS_THE_LEDGER_HEAD_EPOCH: the epoch is the organization ledger head's, never a clock.
  5. REGISTRY_GENERATION_GENESIS_APPEND_COMPLETES_AT_BOTH_LEVELS (``append`` only).
Stdlib only. No clock, no credential, no registry edit.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]


def _module(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mt = _module("merge_transfer_for_admission_genesis", ROOT / "resident-runtime" / "merge_transfer.py")
ap = _module("admission_predicate_for_admission_genesis", ROOT / "resident-runtime" / "admission_predicate.py")
ingress = mt.ingress
sha = ingress.sha

QUESTION = "Q-ORG-REGISTRY-GENERATION"
OPERATION = "ORG_REGISTRY_GENERATION_GENESIS"
TRANSITION_CLASS = "ORG_REGISTRY_GENERATION_GENESIS_APPEND"
PROFILE_ID = "org-ledger-writer"
EVIDENCE_SCHEMA = "stegverse.org-registry-generation-genesis-evidence/v1"
RESULT_SCHEMA = "stegverse.org-registry-generation-genesis-result/v1"
RESOLUTIONS_FILE = ROOT / "data" / "sv-merge-admission" / "provisional-resolutions.json"
GOAL = "StegVerse-org/.github#164 (Lane C: Q-ORG-REGISTRY-GENERATION provisional E1, C-review PENDING)"
ENTRYPOINT = "resident-runtime/org_registry_generation_genesis.py append --base-state-receipt <readback.json> --mode E1"
SHA256_REF = re.compile(r"sha256:[0-9a-f]{64}\Z")
GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
ALLOW, DENY, FAIL_CLOSED = "ALLOW", "DENY", "FAIL_CLOSED"
MODES = ("E0", "E1", "E2", "E3")
SIX_FIELDS = mt.SIX_FIELDS

_E0 = "E0 is the floor: mechanical over the resolution record, a sealed readback and the organization chain"
PREDICATES = {p: {"lowest_supported_mode": "E0", "E0": e0, "E1": _E0 + "; a PENDING C-review is enough", "E2": _E0, "E3": _E0,
                  "degraded_to_E0": d} for p, e0, d in (
    ("REGISTRY_GENERATION_RESOLUTION_IS_RECORDED", "the resolution names this registry with genesis_generation an integer >= 0 and a C-review record",
     "at E0 only a filled review receipt (sha256) admits the resolution; a PENDING one is FAIL_CLOSED PROVISIONAL_RESOLUTION_NOT_ADMITTED_AT_E0"),
    ("READBACK_OBSERVES_THE_UNDECLARED_REGISTRY", "a sealed, well-shaped #3266 readback for this repository, FAIL_CLOSED REGISTRY_GENERATION_NOT_DECLARED, naming the registry blob", "same check"),
    ("REGISTRY_GENERATION_NOT_ALREADY_DECLARED", "verify-first over the organization chain", "same check"),
    ("HB_EPOCH_IS_THE_LEDGER_HEAD_EPOCH", "the organization ledger head carries a supplied epoch", "same check"),
    ("REGISTRY_GENERATION_GENESIS_APPEND_COMPLETES_AT_BOTH_LEVELS", "the repository and organization receipts both exist and are sealed", "same check"),
    ("REGISTRY_GENERATION_GENESIS_IS_LEDGERED", "a sealed ORG_REGISTRY_GENERATION_GENESIS organization receipt for the blob", "same check"))}


class Refused(Exception):
    def __init__(self, out: dict[str, Any]):
        super().__init__(out["failure_code"]); self.out = out


def refusal(code: str, predicate: str, repair: str, next_attempt: str, *, disposition: str = FAIL_CLOSED, **extra: Any) -> dict[str, Any]:
    assert predicate in PREDICATES, predicate
    out = {"schema": RESULT_SCHEMA, "operation": OPERATION, "disposition": disposition, "failure_code": code,
           "failed_predicate": predicate, "required_evidence_or_repair": repair, "retry_entrypoint": ENTRYPOINT,
           "owning_existing_goal": GOAL, "next_attempt": next_attempt, "consequence_committed": False,
           "lowest_supported_mode": PREDICATES[predicate]["lowest_supported_mode"]}
    out.update(extra)
    return out


def _refuse(*a: Any, **k: Any) -> None:
    raise Refused(refusal(*a, **k))


def resolution() -> dict[str, Any]:
    return json.loads(RESOLUTIONS_FILE.read_text(encoding="utf-8"))["resolutions"][QUESTION]


def resolution_sha256(r: Mapping[str, Any]) -> str:
    return sha({k: v for k, v in r.items() if k != "c_review"})


def _boundary(receipt: Any) -> Mapping[str, Any] | None:
    if not mt.sealed(receipt):
        return None
    b = mt._boundary(receipt)
    return b if b.get("operation") == OPERATION else None


def declared(organization: Any = None) -> list[tuple[dict[str, Any], Mapping[str, Any]]]:
    organization = organization if organization is not None else mt.org_store()
    return [(r, b) for _, r in mt.org_chain(organization) if (b := _boundary(r)) is not None]


def declared_generation(repository: str, registry_file: str, blob_sha: str, organization: Any = None) -> tuple[int, str] | None:
    """(generation, organization_receipt_sha256) of the ledgered genesis for exactly this registry blob, else None."""
    for r, b in declared(organization):
        reg = b.get("registry") or {}
        if (reg.get("repository"), reg.get("file"), reg.get("blob_sha")) == (repository, registry_file, blob_sha) \
                and isinstance(b.get("registry_generation"), int):
            return b["registry_generation"], r["receipt_sha256"]
    return None


def undeclared_registry_blob(receipt: Any, repository: str, registry_file: str) -> tuple[str, str] | None:
    """(blob_sha, result_sha256) when the receipt is a sealed, well-shaped readback for this repository that is
    FAIL_CLOSED REGISTRY_GENERATION_NOT_DECLARED and names the registry blob; else None."""
    if not (isinstance(receipt, Mapping) and receipt.get("schema") == ap.BASE_STATE_SCHEMA and receipt.get("component_id") == ap.BASE_STATE_COMPONENT
            and ap.seal_verifies(receipt) and ap.readback_shape_violation(receipt) is None):
        return None
    if (receipt.get("disposition"), receipt.get("failure_code"), receipt.get("repository")) != (FAIL_CLOSED, "REGISTRY_GENERATION_NOT_DECLARED", repository):
        return None
    files = {x.get("file"): x.get("blob_sha") for x in receipt.get("sources") or [] if isinstance(x, Mapping)}
    blob = files.get(registry_file)
    return (blob, receipt[ap.SEAL_FIELD]) if isinstance(blob, str) and GIT_SHA.match(blob) else None


def check_resolution(r: Any, mode: Any, repository: str) -> dict[str, Any]:
    p = "REGISTRY_GENERATION_RESOLUTION_IS_RECORDED"
    if mode not in MODES:
        _refuse("REGISTRY_GENERATION_MODE_UNDECLARED", p, "a mode in E0..E3", "re-run with --mode; nothing was written")
    cr = r.get("c_review") if isinstance(r, Mapping) else None
    reg = r.get("registry") if isinstance(r, Mapping) else None
    if not (isinstance(r, Mapping) and r.get("class") == "C" and isinstance(r.get("genesis_generation"), int) and r["genesis_generation"] >= 0
            and isinstance(reg, Mapping) and reg.get("repository") == repository and isinstance(reg.get("file"), str)
            and isinstance(cr, Mapping) and (cr.get("receipt_sha256") == "PENDING" or SHA256_REF.match(str(cr.get("receipt_sha256"))))):
        _refuse("REGISTRY_GENERATION_RESOLUTION_NOT_RECORDED", p, "the " + QUESTION + " resolution for " + repository + " with a C-review record ("
                + str(RESOLUTIONS_FILE.relative_to(ROOT)) + ")", "record the resolution; nothing was written")
    if mode == "E0" and cr["receipt_sha256"] == "PENDING":
        _refuse("PROVISIONAL_RESOLUTION_NOT_ADMITTED_AT_E0", p,
                "at E0, a filled Claude or ChatGPT review receipt for " + QUESTION + " (receipt_sha256); the C-review is PENDING",
                "run at E1 (the E0 checks plus the PENDING C-review record are enough), or at E0 after the review receipt lands; nothing was written")
    return {"question": QUESTION, "mode": mode, "resolution_sha256": resolution_sha256(r),
            "c_review": {"status": cr.get("status"), "reviewers": cr.get("reviewers"), "receipt_sha256": cr["receipt_sha256"]}}


def plan(base_state: Any, mode: Any, *, repository: str | None = None, organization: Any = None, r: Any = None) -> dict[str, Any]:
    repository = repository or mt.repository()
    organization = organization if organization is not None else mt.org_store()
    try:
        r = r if r is not None else resolution()
        res = check_resolution(r, mode, repository)
        registry_file = r["registry"]["file"]
        observed = undeclared_registry_blob(base_state, repository, registry_file)
        if observed is None:
            _refuse("REGISTRY_UNDECLARED_STATE_NOT_OBSERVED", "READBACK_OBSERVES_THE_UNDECLARED_REGISTRY",
                    "a sealed, well-shaped #3266 readback for " + repository + " that is FAIL_CLOSED REGISTRY_GENERATION_NOT_DECLARED and names the "
                    + registry_file + " blob (an ALLOW readback means the generation is already declared and this genesis is not needed)",
                    "re-run the readback at the current main commit; nothing was written")
        blob, readback_sha = observed
        prior = declared(organization)
        for rc, b in prior:
            reg = b.get("registry") or {}
            if (reg.get("repository"), reg.get("file")) == (repository, registry_file):
                if reg.get("blob_sha") == blob:
                    return {"schema": RESULT_SCHEMA, "operation": OPERATION, "disposition": ALLOW, "replayed": True, "appended": False,
                            "registry_generation": b.get("registry_generation"), "organization_receipt_sha256": rc["receipt_sha256"]}
                _refuse("REGISTRY_GENERATION_GENESIS_ALREADY_DECLARED", "REGISTRY_GENERATION_NOT_ALREADY_DECLARED",
                        "none: the registry's genesis generation is declared once (for blob " + str(reg.get("blob_sha")) + "); later generations come from appends",
                        "read the declared generation from the ledger; nothing was written", disposition=DENY, declared_receipt_sha256=rc["receipt_sha256"])
        epoch, failed = mt.head_epoch(organization)
        if failed is not None:
            _refuse("HB_EPOCH_SOURCE_UNOBSERVED", "HB_EPOCH_IS_THE_LEDGER_HEAD_EPOCH", failed["required_evidence_or_repair"],
                    "re-run once the ledger head carries a supplied epoch; nothing was written", detail=failed.get("detail"))
    except Refused as x:
        return x.out
    boundary = {"append_mode": "FROM_HEAD", "ledger_ref": "refs/stegverse/organization-ledger",
                "registry": {"repository": repository, "file": registry_file, "blob_sha": blob},
                "registry_generation": r["genesis_generation"], "base_state_readback_sha256": readback_sha, "resolution": res}
    return {"schema": RESULT_SCHEMA, "operation": OPERATION, "disposition": ALLOW, "planned": True, "hb_epoch": epoch, "boundary_evidence": boundary}


def append(*args: Any, **kwargs: Any) -> dict[str, Any]:
    out = plan(*args, **kwargs)
    if out["disposition"] != ALLOW or out.get("replayed"):
        return out
    b = out["boundary_evidence"]
    pid = sha({"registry": b["registry"]}).split(":", 1)[1]
    evidence = {"schema": EVIDENCE_SCHEMA, "payload_sha256": b["base_state_readback_sha256"], "disposition": ALLOW,
                "communication_id": f"{OPERATION}:{b['registry']['repository']}:{b['registry']['file']}@{b['registry']['blob_sha']}", "genesis": b}
    try:
        appended, replayed = ingress._append(TRANSITION_CLASS, pid, evidence, out["hb_epoch"], operation=OPERATION, profile_id=PROFILE_ID, boundary_extra=b)
    except (ValueError, SystemExit) as exc:
        return refusal("LEDGER_WRITER_REFUSED", "REGISTRY_GENERATION_GENESIS_APPEND_COMPLETES_AT_BOTH_LEVELS", "repair what the ledger writer refused: " + str(exc),
                       "re-run once repaired; nothing was written", detail=str(exc))
    return {"schema": RESULT_SCHEMA, "operation": OPERATION, "disposition": ALLOW, "appended": not replayed, "replayed": replayed,
            "hb_epoch": out["hb_epoch"], "registry_generation": b["registry_generation"], "registry": b["registry"],
            "repository_receipt_sha256": appended["repository_receipt"]["receipt_sha256"],
            "organization_receipt_sha256": appended["organization_receipt"]["receipt_sha256"]}


def verify(repository: str, registry_file: str, blob_sha: str, organization: Any = None) -> dict[str, Any]:
    found = declared_generation(repository, registry_file, blob_sha, organization)
    if found:
        return {"schema": RESULT_SCHEMA, "operation": OPERATION, "disposition": ALLOW, "registry_generation": found[0],
                "organization_receipt_sha256": found[1], "readback_writes": False}
    return refusal("REGISTRY_GENERATION_GENESIS_NOT_LEDGERED", "REGISTRY_GENERATION_GENESIS_IS_LEDGERED",
                   "a sealed " + OPERATION + " organization receipt for " + repository + ":" + registry_file + "@" + blob_sha, "append it, then verify again")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "append"):
        s = sub.add_parser(name); s.add_argument("--base-state-receipt"); s.add_argument("--mode", default="E0"); s.add_argument("--out")
    v = sub.add_parser("verify")
    for flag in ("--repository", "--registry-file", "--blob-sha"):
        v.add_argument(flag, required=True)
    v.add_argument("--out")
    args = parser.parse_args(argv)
    if args.command == "verify":
        out = verify(args.repository, args.registry_file, args.blob_sha)
    else:
        try:
            rb = json.loads(Path(args.base_state_receipt).read_bytes()) if args.base_state_receipt else None
        except (OSError, ValueError):
            rb = None
        out = (plan if args.command == "plan" else append)(rb, args.mode)
    text = json.dumps(out, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if out.get("disposition") == ALLOW else 1


if __name__ == "__main__":
    raise SystemExit(main())
