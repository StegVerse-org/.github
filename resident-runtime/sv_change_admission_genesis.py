#!/usr/bin/env python3
"""``SV_CHANGE_ADMISSION_GENESIS`` -- the merge-admission genesis, appended FROM_HEAD at registry generation + 1.

TVC's MERGE_ADMISSION (StegVerse-Labs/TVC#534, manifest v2.2) is FAIL_CLOSED
SV_CHANGE_ADMISSION_GENESIS_NOT_DECLARED until a sealed organization receipt on
refs/stegverse/organization-ledger declares its manifest digest. The first admission
is a registry and ledger genesis, not a GitHub merge (KV INDEX, Q-SV-NATIVE-BOOTSTRAP).
This module is that writer op. It never merges and never reads the private manifest:
TVC recomputes the digest from its own manifest on every evaluation.

The manifest event is a same-repository genesis-request PR in this repository that
adds only control/sv-merge-admission/genesis-request.json (a copy of TVC's request).
``plan`` runs the E0 checks; ``append`` runs them and appends the pair through the
existing two-level append (intr_destination_ingress._append, as merge_transfer.py does);
``verify`` reads it back. E0 checks, in order (each refusal carries the six fields and
``lowest_supported_mode`` E0, and writes nothing):

  1. GENESIS_REQUEST_IS_THE_CONTRACT: schema, operation, FROM_HEAD, ledger_ref, a sha256 digest.
  2. GENESIS_REQUEST_PR_IS_SAME_REPOSITORY_SINGLE_FILE: the PR is open, same-repository, and changes
     only the request path, whose blob at the head is these request bytes.
  3. GENESIS_NOT_ALREADY_DECLARED: verify-first (same digest -> replay ALLOW); a different prior genesis
     is DENY GENESIS_ALREADY_DECLARED unless this request supersedes exactly it.
  4. REGISTRY_GENERATION_FROM_SEALED_BASE_STATE: from_registry_generation from an ALLOW #3266 base-state
     readback for this repository (verified as admission_predicate.base_state_from_readback does), + 1;
     its sealed hb_epoch must be the ledger head epoch now. Never declared by the request.
  5. SELECTED_TESTS_RECEIPTED_ZERO_SKIPPED_AT_REQUEST_HEAD: Lane B's receipt at the request head
     (ALLOW, 0 skipped, selection declared, no refusal), its producer files byte-pinned on the base.
  6. MODE_AND_CROSS_LLM_FORM_DECLARED: E0..E3; at E1+ a cross-LLM form (degrades, never stops).
  7. GENESIS_APPEND_COMPLETES_AT_BOTH_LEVELS.

No workflow runs this op yet: which event runs it on the request PR's exact head is the
undecided authorization form (Q-SV-NATIVE-BOOTSTRAP, class C). Stdlib only; no clock;
no credential; no environment read beyond the ledger location variables the writers use.
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

OPERATION = "SV_CHANGE_ADMISSION_GENESIS"
TRANSITION_CLASS = "SV_CHANGE_ADMISSION_GENESIS_APPEND"
PROFILE_ID = "org-ledger-writer"
EVIDENCE_SCHEMA = "stegverse.org-sv-change-admission-genesis-evidence/v1"
RESULT_SCHEMA = "stegverse.org-sv-change-admission-genesis-result/v1"
CONTRACT_FILE = ROOT / "data" / "sv-merge-admission" / "genesis-contract.json"
GOAL = "StegVerse-org/.github#164 (Lane C: SV_CHANGE_ADMISSION_GENESIS for TVC MERGE_ADMISSION; P1 #163)"
ENTRYPOINT = ("resident-runtime/sv_change_admission_genesis.py append over the same-repository genesis-request PR's exact head "
              "(--request --pull --files --base-state-receipt --test-receipt --mode); its triggering event is undecided (Q-SV-NATIVE-BOOTSTRAP, C)")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA256_REF = re.compile(r"sha256:[0-9a-f]{64}\Z")
ALLOW, DENY, FAIL_CLOSED = "ALLOW", "DENY", "FAIL_CLOSED"
SIX_FIELDS = mt.SIX_FIELDS

_E0 = "E0 is the only rung: mechanical over the request, the PR observation, sealed receipts and byte pins"
PREDICATES = {p: {"lowest_supported_mode": "E0", "E3": _E0, "E2": _E0, "E1": _E0, "E0": e0, "llm_inputs": "none at any rung"} for p, e0 in (
    ("GENESIS_REQUEST_IS_THE_CONTRACT", "request schema, operation SV_CHANGE_ADMISSION_GENESIS, FROM_HEAD, ledger_ref, admission_manifest_sha256 a sha256 ref"),
    ("GENESIS_REQUEST_PR_IS_SAME_REPOSITORY_SINGLE_FILE", "the PR is open, head repository == base repository == this one, and its only changed file is the request path, whose head blob is the request bytes"),
    ("GENESIS_NOT_ALREADY_DECLARED", "verify-first over the organization chain; a different prior genesis must be the one this request supersedes"),
    ("REGISTRY_GENERATION_FROM_SEALED_BASE_STATE", "an ALLOW #3266 base-state readback for this repository supplies from_registry_generation; registry_generation = from + 1; its sealed hb_epoch is the ledger head epoch"),
    ("SELECTED_TESTS_RECEIPTED_ZERO_SKIPPED_AT_REQUEST_HEAD", "Lane B's stegverse.test-suite-skip-receipt/v1 at the request head: ALLOW, counts.skipped 0, selection declared, no refusal; producer files byte-pinned on the base"),
    ("MODE_AND_CROSS_LLM_FORM_DECLARED", "mode E0..E3; at E1+ a declared cross_llm_confirmation form (a PENDING later review suffices; degrades, never stops)"),
    ("GENESIS_APPEND_COMPLETES_AT_BOTH_LEVELS", "the repository receipt and the organization receipt both exist and are sealed"),
    ("GENESIS_HAS_A_SEALED_ORGANIZATION_LEDGER_RECEIPT", "the organization chain holds a sealed SV_CHANGE_ADMISSION_GENESIS receipt for the digest"))}


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


def contract() -> dict[str, Any]:
    return json.loads(CONTRACT_FILE.read_text(encoding="utf-8"))


def _boundary_genesis(receipt: Any) -> Mapping[str, Any] | None:
    if not mt.sealed(receipt):
        return None
    b = mt._boundary(receipt)
    return b if b.get("operation") == OPERATION else None


def declared(organization: Any = None) -> list[tuple[dict[str, Any], Mapping[str, Any]]]:
    """Every sealed genesis receipt on the organization chain, newest first."""
    organization = organization if organization is not None else mt.org_store()
    return [(r, b) for _, r in mt.org_chain(organization) if (b := _boundary_genesis(r)) is not None]


def _supersedes_chain(request: Mapping[str, Any]) -> list[str]:
    out, s = [], request.get("supersedes")
    while isinstance(s, Mapping):
        if isinstance(s.get("admission_manifest_sha256"), str):
            out.append(s["admission_manifest_sha256"])
        s = s.get("supersedes")
    return out


def check_request(request: Any, c: Mapping[str, Any]) -> None:
    p = "GENESIS_REQUEST_IS_THE_CONTRACT"
    if not (isinstance(request, Mapping) and request.get("schema") == c["request_schema"] and request.get("operation") == c["operation"]
            and request.get("append_mode") == c["append_mode"] and request.get("ledger_ref") == c["ledger_ref"]
            and isinstance(request.get("admission_manifest_sha256"), str) and SHA256_REF.match(request["admission_manifest_sha256"])):
        _refuse("GENESIS_REQUEST_INVALID", p, "a " + c["request_schema"] + " request (" + c["request_origin"] + ")",
                "correct the request on the genesis-request PR; nothing was written")


def check_pull(pull: Any, files: Any, request_bytes: bytes, repository: str, c: Mapping[str, Any]) -> dict[str, Any]:
    p = "GENESIS_REQUEST_PR_IS_SAME_REPOSITORY_SINGLE_FILE"
    if not isinstance(pull, Mapping) or not isinstance(files, list):
        _refuse("GENESIS_REQUEST_PR_UNOBSERVED", p, "the GitHub REST pull and its files list for the genesis-request PR", "re-observe; nothing was written")
    head, base = pull.get("head") or {}, pull.get("base") or {}
    hr, br = (head.get("repo") or {}).get("full_name"), (base.get("repo") or {}).get("full_name")
    if pull.get("state") != "open" or pull.get("merged") is True:
        _refuse("GENESIS_REQUEST_PR_NOT_OPEN", p, "an open genesis-request PR (no merge is part of the genesis)", "open a successor request PR; nothing was written", disposition=DENY)
    if not (hr == br == repository) or not isinstance(head.get("sha"), str) or not SHA40.match(head["sha"]):
        _refuse("GENESIS_REQUEST_PR_NOT_SAME_REPOSITORY", p, "head repository == base repository == " + repository, "open the request from a branch of this repository; nothing was written",
                disposition=DENY, head_repository=hr, base_repository=br)
    names = sorted(f.get("filename") for f in files if isinstance(f, Mapping))
    if names != [c["request_path"]] or len(files) != 1:
        _refuse("GENESIS_REQUEST_PR_CHANGES_MORE_THAN_THE_REQUEST", p, "a PR whose only change is " + c["request_path"],
                "split the other changes into their own admissions; nothing was written", disposition=DENY, changed=names[:20])
    if files[0].get("sha") != ap.git_blob_sha(request_bytes) or files[0].get("status") not in ("added", "modified"):
        _refuse("GENESIS_REQUEST_BYTES_NOT_AT_HEAD", p, "the request bytes given to the op are the blob at the PR head", "re-read the request at the head; nothing was written",
                head_blob=files[0].get("sha"), given_blob=ap.git_blob_sha(request_bytes))
    return {"repository": repository, "pull_number": pull.get("number"), "head_sha": head["sha"]}


def check_prior(request: Mapping[str, Any], organization: Any) -> Mapping[str, Any] | None:
    """The prior genesis receipt for this digest (replay), or None. DENY when another genesis stands unsuperseded."""
    want, sup = request["admission_manifest_sha256"], _supersedes_chain(request)
    prior = declared(organization)
    same = [r for r, b in prior if b.get("admission_manifest_sha256") == want]
    if same:
        return same[0]
    if prior and prior[0][1].get("admission_manifest_sha256") not in sup:
        _refuse("GENESIS_ALREADY_DECLARED", "GENESIS_NOT_ALREADY_DECLARED",
                "a request that supersedes the declared genesis " + str(prior[0][1].get("admission_manifest_sha256")),
                "regenerate the request with that digest under supersedes (an admitted manifest change); nothing was written", disposition=DENY,
                declared_receipt_sha256=prior[0][0].get("receipt_sha256"))
    return None


def check_base_state(receipt: Any, repository: str, epoch: int) -> tuple[int, int, str]:
    p = "REGISTRY_GENERATION_FROM_SEALED_BASE_STATE"
    state, code, why = ap.base_state_from_readback(receipt)
    if state is None:
        inner = receipt.get("failure_code") if isinstance(receipt, Mapping) else None
        _refuse("GENESIS_REGISTRY_GENERATION_NOT_OBSERVED", p,
                "an ALLOW #3266 base-state readback for " + repository + " whose base_ref.registry_generation is an integer (" + str(code) + ": " + str(why) + ")",
                "after the readback binds (for the organization registry: joint item Q-ORG-REGISTRY-GENERATION decides how "
                "orchestration/task-registry.json declares its generation); nothing was written",
                readback_failure_code=code, readback_inner_failure_code=inner)
    if state.get("repository") != repository:
        _refuse("GENESIS_REGISTRY_GENERATION_NOT_OBSERVED", p, "a base-state readback for " + repository, "re-run the readback for this repository; nothing was written",
                readback_repository=state.get("repository"))
    if state["hb_epoch"] is not None and str(state["hb_epoch"]) != str(epoch):
        _refuse("GENESIS_BASE_STATE_NOT_CURRENT", p, "a readback sealed at the organization ledger head epoch now (" + str(epoch) + ")",
                "re-run the readback against the current ledger head; nothing was written", readback_hb_epoch=state["hb_epoch"])
    return state["registry_generation"], state["registry_generation"] + 1, state["result_sha256"]


def check_test_receipt(rc: Any, rc_bytes: bytes, head_sha: str, c: Mapping[str, Any], root: Path = ROOT) -> dict[str, Any]:
    p, spec = "SELECTED_TESTS_RECEIPTED_ZERO_SKIPPED_AT_REQUEST_HEAD", c["test_suite_receipt"]
    off = {}
    for path, pin in sorted(spec["files"].items()):
        f = root / path
        data = f.read_bytes() if f.is_file() else None
        if data is None or (ap.git_blob_sha(data), hashlib.sha256(data).hexdigest()) != (pin["git_blob_sha"], pin["sha256"]):
            off[path] = None if data is None else ap.git_blob_sha(data)
    if off:
        _refuse("TEST_SUITE_RECEIPT_PRODUCER_NOT_PINNED", p, "Lane B's receipt producer on the base at the pinned bytes (" + spec["status"] + ")",
                "Lane B's producer lands (StegVerse-org/.github#" + str(spec["producer_pull_request"]) + "), then re-pin; nothing was written", observed=off)
    if not (isinstance(rc, Mapping) and rc.get("schema") == spec["schema"] and rc.get("head_sha") == head_sha
            and rc.get("tested_commit", head_sha) == head_sha and isinstance(rc.get("selected_tests"), list)
            and rc.get("not_selected_are_not_run_for_this_verdict_and_not_reported_as_passing") is True
            and rc.get("skips_are_never_converted_or_deselected") is True and isinstance(rc.get("counts"), Mapping)
            and isinstance(rc["counts"].get("tests"), int)):
        _refuse("TEST_SUITE_NOT_OBSERVED_ON_HEAD", p, "Lane B's selected-tests receipt for exactly the request head " + head_sha,
                "the producer's pull_request run at the request head; nothing was written")
    if rc["counts"].get("skipped") != 0 or rc.get("skipped"):
        _refuse("TEST_SUITE_SKIPPED_ON_HEAD", p, "0 skipped among the selected tests (a skip-items row names an owner, it never excuses the skip)",
                "a successor request head whose receipt shows 0 skipped; nothing was written", skipped_count=rc["counts"].get("skipped"))
    if rc.get("new_failures_on_head"):
        _refuse("TEST_SUITE_NEW_FAILURE_ON_HEAD", p, "no selected test newly failing at the request head", "fix them on a successor head; nothing was written")
    if rc.get("disposition") != ALLOW or rc.get("refusals"):
        _refuse("TEST_SUITE_NOT_OBSERVED_ON_HEAD", p, "a receipt whose disposition is ALLOW with no refusal", "re-run the producer at the request head; nothing was written",
                receipt_disposition=rc.get("disposition"))
    return {"head_sha": head_sha, "receipt_sha256": "sha256:" + hashlib.sha256(rc_bytes).hexdigest(), "disposition": ALLOW,
            "skipped": 0, "tests": rc["counts"]["tests"], "selected_files": len(rc["selected_tests"])}


def check_mode(mode: Any, request: Mapping[str, Any], c: Mapping[str, Any]) -> dict[str, Any]:
    p = "MODE_AND_CROSS_LLM_FORM_DECLARED"
    if mode not in c["modes"]:
        _refuse("GENESIS_MODE_UNDECLARED", p, "a mode in E0..E3", "re-run with --mode; nothing was written")
    if mode == "E0":
        return {"mode": "E0"}
    form = request.get("cross_llm_confirmation_at_e1")
    lr = form.get("later_review") if isinstance(form, Mapping) else None
    if not (isinstance(form, Mapping) and form.get("form") == "E0_CHECKS_PLUS_LATER_RECEIPTED_REVIEW" and isinstance(lr, Mapping)
            and lr.get("lane") and lr.get("reviewer") and (lr.get("receipt_sha256") == "PENDING" or SHA256_REF.match(str(lr.get("receipt_sha256"))))):
        _refuse("GENESIS_CROSS_LLM_FORM_UNDECLARED", p, "at " + str(mode) + ", the request's cross_llm_confirmation_at_e1 (form E0_CHECKS_PLUS_LATER_RECEIPTED_REVIEW, review PENDING is enough)",
                "regenerate the request with the form, or run at E0; nothing was written")
    return {"mode": mode, "cross_llm_confirmation": {"form": form["form"], "later_review": {k: lr[k] for k in ("lane", "reviewer", "receipt_sha256")}}}


def plan(request_bytes: bytes, pull: Any, files: Any, base_state: Any, test_receipt_bytes: bytes | None, mode: Any, *,
         repository: str | None = None, organization: Any = None, root: Path = ROOT) -> dict[str, Any]:
    """The E0 checks in order; the boundary evidence the append would write. Writes nothing."""
    repository = repository or mt.repository()
    organization = organization if organization is not None else mt.org_store()
    c = contract()
    try:
        try:
            request = json.loads(request_bytes)
        except ValueError:
            request = None
        check_request(request, c)
        gr = check_pull(pull, files, request_bytes, repository, c)
        prior = check_prior(request, organization)
        if prior is not None:
            return {"schema": RESULT_SCHEMA, "operation": OPERATION, "disposition": ALLOW, "replayed": True, "appended": False,
                    "organization_receipt_sha256": prior["receipt_sha256"], "admission_manifest_sha256": request["admission_manifest_sha256"]}
        epoch, failed = mt.head_epoch(organization)
        if failed is not None:
            _refuse("HB_EPOCH_SOURCE_UNOBSERVED", "REGISTRY_GENERATION_FROM_SEALED_BASE_STATE", failed["required_evidence_or_repair"],
                    "re-run once the ledger head carries a supplied epoch; nothing was written", detail=failed.get("detail"))
        frm, gen, readback = check_base_state(base_state, repository, epoch)
        try:
            rc = json.loads(test_receipt_bytes) if test_receipt_bytes is not None else None
        except ValueError:
            rc = None
        tests = check_test_receipt(rc, test_receipt_bytes or b"", gr["head_sha"], c, root)
        m = check_mode(mode, request, c)
    except Refused as r:
        return r.out
    boundary = {"append_mode": c["append_mode"], "ledger_ref": c["ledger_ref"], "from_registry_generation": frm, "registry_generation": gen,
                "base_state_readback_sha256": readback, "admission_manifest_sha256": request["admission_manifest_sha256"],
                "genesis_request": gr, "genesis_request_sha256": "sha256:" + hashlib.sha256(request_bytes).hexdigest(),
                "selected_tests_receipt": tests, **m}
    return {"schema": RESULT_SCHEMA, "operation": OPERATION, "disposition": ALLOW, "planned": True, "hb_epoch": epoch, "boundary_evidence": boundary}


def append(*args: Any, **kwargs: Any) -> dict[str, Any]:
    out = plan(*args, **kwargs)
    if out["disposition"] != ALLOW or out.get("replayed"):
        return out
    b = out["boundary_evidence"]
    pid = sha({"admission_manifest_sha256": b["admission_manifest_sha256"], "genesis_request": b["genesis_request"]}).split(":", 1)[1]
    evidence = {"schema": EVIDENCE_SCHEMA, "payload_sha256": b["genesis_request_sha256"], "disposition": ALLOW,
                "communication_id": f"{OPERATION}:{b['admission_manifest_sha256']}@{b['genesis_request']['head_sha']}", "genesis": b}
    try:
        appended, replayed = ingress._append(TRANSITION_CLASS, pid, evidence, out["hb_epoch"], operation=OPERATION, profile_id=PROFILE_ID, boundary_extra=b)
    except (ValueError, SystemExit) as exc:
        return refusal("LEDGER_WRITER_REFUSED", "GENESIS_APPEND_COMPLETES_AT_BOTH_LEVELS", "repair what the ledger writer refused: " + str(exc),
                       "re-run once repaired; nothing was written", detail=str(exc))
    return {"schema": RESULT_SCHEMA, "operation": OPERATION, "disposition": ALLOW, "appended": not replayed, "replayed": replayed,
            "hb_epoch": out["hb_epoch"], "admission_manifest_sha256": b["admission_manifest_sha256"],
            "registry_generation": b["registry_generation"],
            "repository_receipt_sha256": appended["repository_receipt"]["receipt_sha256"],
            "organization_receipt_sha256": appended["organization_receipt"]["receipt_sha256"]}


def verify(admission_manifest_sha256: str, organization: Any = None) -> dict[str, Any]:
    for r, b in declared(organization):
        if b.get("admission_manifest_sha256") == admission_manifest_sha256:
            return {"schema": RESULT_SCHEMA, "operation": OPERATION, "disposition": ALLOW, "organization_receipt_sha256": r["receipt_sha256"],
                    "registry_generation": b.get("registry_generation"), "readback_writes": False}
    return refusal("GENESIS_NOT_LEDGERED", "GENESIS_HAS_A_SEALED_ORGANIZATION_LEDGER_RECEIPT",
                   "a sealed SV_CHANGE_ADMISSION_GENESIS organization receipt for " + admission_manifest_sha256, "append it, then verify again")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "append"):
        s = sub.add_parser(name)
        for flag in ("--request", "--pull", "--files", "--base-state-receipt", "--test-receipt"):
            s.add_argument(flag)
        s.add_argument("--mode", default="E0")
        s.add_argument("--out")
    v = sub.add_parser("verify"); v.add_argument("--admission-manifest-sha256", required=True); v.add_argument("--out")
    args = parser.parse_args(argv)

    def read(path: str | None, raw: bool = False) -> Any:
        if not path:
            return None
        try:
            data = Path(path).read_bytes()
            return data if raw else json.loads(data)
        except (OSError, ValueError):
            return None
    if args.command == "verify":
        out = verify(args.admission_manifest_sha256)
    else:
        fn = plan if args.command == "plan" else append
        out = fn(read(args.request, True) or b"", read(args.pull), read(args.files), read(args.base_state_receipt), read(args.test_receipt, True), args.mode)
    text = json.dumps(out, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if out.get("disposition") == ALLOW else 1


if __name__ == "__main__":
    raise SystemExit(main())
