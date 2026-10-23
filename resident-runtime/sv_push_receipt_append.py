#!/usr/bin/env python3
"""``sv_push_receipt`` -- every push to a PR branch is ledgered as one sv-push-receipt.v1.

TVC#519 v2 (StegVerse-Labs/TVC#531) derives BRANCH_WRITER_IS_BRANCH_OWNER from a
contiguous chain of sealed ``stegverse.sv_push_receipt.v1`` receipts for one
repository and one ``refs/heads/<branch>``, read from this organization's
published ledger ref (refs/stegverse/organization-ledger). This writer operation
produces that chain. It is a new operation on the existing two-level append
(resident-runtime/intr_destination_ingress.py::_append, as
resident-runtime/merge_transfer.py uses it), in the same layout as the
``sv_check_receipt`` operation (StegVerse-Labs/.github#3255/#3270):

  * repository receipt: ``$.evidence`` is ``stegverse.org-sv-push-receipt-evidence/v1``,
    ``{push_receipt, payload_sha256, disposition, communication_id}``; ``push_receipt`` IS the
    complete, sealed sv-push-receipt.v1 object.
  * organization receipt: ``boundary_evidence.operation == "sv_push_receipt"``, with
    repository, ref, old_sha, new_sha and push_receipt_sha256.

Trigger: .github/workflows/organization-ledger-push-receipt.yml on ``push`` to
any branch but main (a pull_request run holds no write token; a push is the
event that moves a PR head). The producer is Labs#3267's
``resident-runtime/sv_push_receipt.py`` at bb780200, vendored by blob under
resident-runtime/vendor/labs_bb780200/ and pinned in
data/sv-push-receipt/vendor-pins.json; a pin mismatch refuses every append.

Inputs, all observed by GitHub for this push (none declared by a lane):
  * new_sha = the push event's ``after``; old_sha = its ``before``, or, for a new branch
    (before is the zero sha), the merge-base of after with main (the fork base the schema names);
  * pushed_commits = git rev-list --reverse --topo-order old_sha..new_sha (the producer);
  * pusher_session = ``github-push-sender:<login>#<id>``, the account GitHub observed pushing.
    That is the E0 observable. GitHub does not observe which session on that account pushed, so
    a finer session identity is UNKNOWN_NOT_AUTHENTICALLY_OBSERVED here and is never declared;
  * hb_epoch = the supplied epoch on the organization ledger head receipt (hb_reference.epoch,
    int >= 32, derived_from_clock false), as merge_transfer.head_epoch reads it. No clock is read.

Refused, six fields, nothing written: a push to main (that is
ORGANIZATION_MAIN_MERGE_TRANSFER's), a non-fast-forward (force) push, a push
that moved nothing, an unobserved epoch, a receipt that does not verify, and a
second receipt for a (ref, old_sha, new_sha) already ledgered with other bytes.
A replay of the same push answers from the ledger (verify-first).

Every predicate declares its lowest mode and its degraded form to E0 in
PREDICATES. LLM review takes no input at any rung. Stdlib only; no environment
read beyond the ledger location variables the writers already use.
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


mt = _module("merge_transfer_for_sv_push_receipt", ROOT / "resident-runtime" / "merge_transfer.py")
ingress = mt.ingress
sha = ingress.sha

OPERATION = "sv_push_receipt"
TRANSITION_CLASS = "SV_PUSH_RECEIPT_APPEND"
PROFILE_ID = "org-ledger-writer"
EVIDENCE_SCHEMA = "stegverse.org-sv-push-receipt-evidence/v1"
RESULT_SCHEMA = "stegverse.org-sv-push-receipt-append-result/v1"
READBACK_SCHEMA = "stegverse.org-sv-push-receipt-readback/v1"
RECEIPT_SCHEMA = "stegverse.sv_push_receipt.v1"
MAIN_REF = "refs/heads/main"
SESSION_PREFIX = "github-push-sender:"
GOAL = "StegVerse-org/.github#164 (TVC#519 v2 BRANCH_WRITER_IS_BRANCH_OWNER push-receipt chain)"
ENTRYPOINT = ".github/workflows/organization-ledger-push-receipt.yml (re-run the push's run)"
PINS_FILE = ROOT / "data" / "sv-push-receipt" / "vendor-pins.json"
ZERO = "0" * 40
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
ALLOW, DENY, FAIL_CLOSED = "ALLOW", "DENY", "FAIL_CLOSED"
SIX_FIELDS = mt.SIX_FIELDS

_E0_ONLY = "E0 is the only rung: a mechanical check over git objects and ledger receipts"
PREDICATES = {
    "VENDORED_PUSH_RECEIPT_PRODUCER_MATCHES_ITS_PINS": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "git blob and sha256 of each vendored file equal data/sv-push-receipt/vendor-pins.json",
        "llm_inputs": "none at any rung"},
    "PUSH_IS_TO_A_PR_BRANCH_NOT_MAIN": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "ref is refs/heads/<branch> and not refs/heads/main (main is ORGANIZATION_MAIN_MERGE_TRANSFER)",
        "llm_inputs": "none at any rung"},
    "PUSH_INPUTS_ARE_GITHUB_OBSERVED": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "before/after are 40-hex from the push event; the sender login and id are present; a new branch's "
              "old_sha is the merge-base with main",
        "llm_inputs": "none at any rung"},
    "PUSH_RECEIPT_EPOCH_IS_THE_LEDGER_HEAD_EPOCH": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "hb_epoch = str(organization ledger head hb_reference.epoch); unobserved -> FAIL_CLOSED, other -> DENY",
        "llm_inputs": "none at any rung"},
    "PUSH_RECEIPT_IS_A_SEALED_SV_PUSH_RECEIPT_V1": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "the vendored producer's receipt_problem(receipt) is None and repository is this repository",
        "llm_inputs": "none at any rung"},
    "PUSH_IS_A_FAST_FORWARD_THAT_MOVED_THE_REF": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "the producer's emit(): old_sha is an ancestor of new_sha and differs from it (a force-push is never receipted)",
        "llm_inputs": "none at any rung"},
    "ONE_PUSH_BINDS_ONE_PUSH_RECEIPT": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "verify-first: a (repository, ref, old_sha, new_sha) already ledgered is answered from the ledger",
        "llm_inputs": "none at any rung"},
    "PUSH_RECEIPT_APPEND_COMPLETES_AT_BOTH_LEVELS": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "the repository receipt and the organization receipt both exist and are sealed",
        "llm_inputs": "none at any rung"},
    "PUSH_HAS_A_SEALED_ORGANIZATION_LEDGER_RECEIPT": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "a fresh fetch of the published ref holds the sealed pair linking this push",
        "llm_inputs": "none at any rung"},
}


def refusal(code: str, predicate: str, repair: str, next_attempt: str, *, disposition: str = FAIL_CLOSED,
            **extra: Any) -> dict[str, Any]:
    assert predicate in PREDICATES, predicate
    out = {"schema": RESULT_SCHEMA, "operation": OPERATION, "disposition": disposition, "failure_code": code,
           "failed_predicate": predicate, "required_evidence_or_repair": repair, "retry_entrypoint": ENTRYPOINT,
           "owning_existing_goal": GOAL, "next_attempt": next_attempt, "consequence_committed": False,
           "lowest_supported_mode": PREDICATES[predicate]["lowest_supported_mode"]}
    out.update(extra)
    return out


# -- the vendored producer ---------------------------------------------------

def _git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def pin_failure(pins_file: Path = PINS_FILE) -> str | None:
    try:
        pins = json.loads(pins_file.read_text(encoding="utf-8"))
        root = ROOT / pins["vendor_root"]
        for rel, pin in pins["files"].items():
            data = (root / rel).read_bytes()
            if _git_blob(data) != pin["git_blob"]:
                return rel + " git blob is not " + pin["git_blob"]
            if "sha256:" + hashlib.sha256(data).hexdigest() != pin["sha256"]:
                return rel + " sha256 is not " + pin["sha256"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def producer():
    """The vendored Labs producer, loaded only after its pins verify (else RuntimeError)."""
    bad = pin_failure()
    if bad is not None:
        raise RuntimeError(bad)
    pins = json.loads(PINS_FILE.read_text(encoding="utf-8"))
    return _module("sv_push_receipt_labs_bb780200", ROOT / pins["vendor_root"] / "resident-runtime" / "sv_push_receipt.py")


def _pin_refusal(detail: str) -> dict[str, Any]:
    return refusal("SV_PUSH_RECEIPT_PRODUCER_PIN_MISMATCH", "VENDORED_PUSH_RECEIPT_PRODUCER_MATCHES_ITS_PINS",
                   "re-vendor resident-runtime/sv_push_receipt.py and schemas/sv-push-receipt.v1.schema.json from "
                   "StegVerse-Labs/.github at the pinned commit, or re-pin both in data/sv-push-receipt/vendor-pins.json",
                   "after the vendored files match their pins; nothing was written", detail=detail)


# -- identities --------------------------------------------------------------

def packet_id(repository: str, ref: str, old_sha: str, new_sha: str) -> str:
    return sha({"repository": repository, "ref": ref, "old_sha": old_sha, "new_sha": new_sha}).split(":", 1)[1]


def pusher_session(login: Any, account_id: Any) -> str | None:
    if not isinstance(login, str) or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?", login):
        return None
    if not isinstance(account_id, str) or not re.fullmatch(r"[1-9][0-9]*", account_id):
        return None
    return SESSION_PREFIX + login + "#" + account_id


def old_sha_for(before: Any, after: str, git_dir: Path | str, base_ref: str) -> str | None:
    """before, or for a new branch (zero/absent before) the merge-base of after with base_ref."""
    if isinstance(before, str) and SHA40.match(before) and before != ZERO:
        return before
    p = subprocess.run(["git", "-C", str(git_dir), "merge-base", after, base_ref], capture_output=True, text=True)
    value = p.stdout.strip()
    return value if p.returncode == 0 and SHA40.match(value) else None


# -- ledger reads ------------------------------------------------------------

def recorded(repository: str, ref: str, old_sha: str, new_sha: str, organization: Any = None,
             repository_store: Any = None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(organization receipt, repository receipt) already binding this push, or (None, None)."""
    organization = organization if organization is not None else mt.org_store()
    repository_store = repository_store if repository_store is not None else mt.repo_store()
    for digest, receipt in mt.org_chain(organization):
        if not mt.sealed(receipt):
            continue
        b = mt._boundary(receipt)
        if b.get("operation") != OPERATION or b.get("repository") != repository or b.get("ref") != ref \
                or b.get("old_sha") != old_sha or b.get("new_sha") != new_sha:
            continue
        return receipt, mt._receipt(repository_store, receipt.get("repo_receipt_sha256"))
    return None, None


def _evidence(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema": EVIDENCE_SCHEMA, "push_receipt": dict(receipt), "payload_sha256": receipt["result_sha256"],
            "disposition": ALLOW,
            "communication_id": OPERATION + ":" + receipt["repository"] + ":" + receipt["ref"] + "@" + receipt["new_sha"]}


# -- append ------------------------------------------------------------------

def append_push_receipt(receipt: Any, *, repository: str | None = None) -> dict[str, Any]:
    """Append one sealed sv-push-receipt.v1 at both levels, or refuse with six fields; never a partial write."""
    repository = repository or mt.repository()
    try:
        pr = producer()
    except RuntimeError as exc:
        return _pin_refusal(str(exc))
    problem = pr.receipt_problem(receipt)
    if problem is not None or receipt.get("repository") != repository:
        return refusal("PUSH_RECEIPT_INVALID", "PUSH_RECEIPT_IS_A_SEALED_SV_PUSH_RECEIPT_V1",
                       "a sealed sv-push-receipt.v1 from the vendored producer, for this repository",
                       "re-emit from the push; nothing was written", problem=problem or "repository",
                       repository=repository)
    if receipt["ref"] == MAIN_REF:
        return refusal("PUSH_RECEIPT_REF_IS_MAIN", "PUSH_IS_TO_A_PR_BRANCH_NOT_MAIN",
                       "a push to main is recorded by ORGANIZATION_MAIN_MERGE_TRANSFER, not as a push receipt",
                       "none; main's push is ledgered by organization-ledger-merge-transfer.yml", disposition=DENY,
                       ref=receipt["ref"])
    epoch, failed = mt.head_epoch(mt.org_store())
    if failed is not None:
        return refusal("HB_EPOCH_SOURCE_UNOBSERVED", "PUSH_RECEIPT_EPOCH_IS_THE_LEDGER_HEAD_EPOCH",
                       failed["required_evidence_or_repair"], "re-run once the ledger head carries a supplied epoch; nothing was written",
                       detail=failed.get("detail"))
    if receipt["hb_epoch"] != str(epoch):
        return refusal("HB_EPOCH_MISMATCH", "PUSH_RECEIPT_EPOCH_IS_THE_LEDGER_HEAD_EPOCH",
                       "emit the receipt at the ledger head's supplied epoch (" + str(epoch) + ")",
                       "re-emit at the head epoch; nothing was written", disposition=DENY,
                       receipt_hb_epoch=receipt["hb_epoch"], ledger_head_epoch=epoch)
    key = (repository, receipt["ref"], receipt["old_sha"], receipt["new_sha"])
    org_prior, repo_prior = recorded(*key)
    if org_prior is not None:
        prior = (repo_prior or {}).get("evidence", {}).get("push_receipt") if isinstance(repo_prior, Mapping) else None
        if not mt.sealed(repo_prior) or pr.receipt_problem(prior) is not None:
            return refusal("PUSH_RECEIPT_RECORD_UNSEALED", "ONE_PUSH_BINDS_ONE_PUSH_RECEIPT",
                           "the recorded receipt for this push must be sealed at both levels",
                           "inspect organization receipt " + org_prior["receipt_sha256"] + "; nothing was written")
        return {"schema": RESULT_SCHEMA, "operation": OPERATION, "disposition": ALLOW, "replayed": True,
                "appended": False, "repository": repository, "ref": key[1], "old_sha": key[2], "new_sha": key[3],
                "push_receipt_sha256": prior["result_sha256"], "same_bytes_as_offered": prior == receipt,
                "organization_receipt_sha256": org_prior["receipt_sha256"],
                "repository_receipt_sha256": repo_prior["receipt_sha256"],
                "hb_epoch": (org_prior.get("hb_reference") or {}).get("epoch")}
    evidence = _evidence(receipt)
    try:
        appended, replayed = ingress._append(
            TRANSITION_CLASS, packet_id(*key), evidence, epoch, operation=OPERATION, profile_id=PROFILE_ID,
            boundary_extra={"repository": repository, "ref": key[1], "old_sha": key[2], "new_sha": key[3],
                            "push_receipt_sha256": receipt["result_sha256"],
                            "pusher_session": receipt["pusher_session"]})
    except ValueError as exc:
        code = "PUSH_RECEIPT_COLLISION" if str(exc) == "ledger_receipt_collision" else "LEDGER_WRITER_REFUSED"
        return refusal(code, "ONE_PUSH_BINDS_ONE_PUSH_RECEIPT" if code == "PUSH_RECEIPT_COLLISION"
                       else "PUSH_RECEIPT_APPEND_COMPLETES_AT_BOTH_LEVELS",
                       "the ledger binds this push to other evidence, or the writer refused: " + str(exc),
                       "inspect the recorded receipt; nothing was written", detail=str(exc))
    except SystemExit as exc:
        return refusal("LEDGER_WRITER_REFUSED", "PUSH_RECEIPT_APPEND_COMPLETES_AT_BOTH_LEVELS",
                       "repair what the ledger writer refused (" + str(exc.code) + ")",
                       "re-run once repaired; nothing was written", detail=str(exc.code))
    return {"schema": RESULT_SCHEMA, "operation": OPERATION, "disposition": ALLOW, "replayed": replayed,
            "appended": not replayed, "repository": repository, "ref": key[1], "old_sha": key[2], "new_sha": key[3],
            "push_receipt_sha256": receipt["result_sha256"], "pusher_session": receipt["pusher_session"],
            "pushed_commits": len(receipt["pushed_commits"]), "hb_epoch": epoch,
            "repository_receipt_sha256": appended["repository_receipt"]["receipt_sha256"],
            "organization_receipt_sha256": appended["organization_receipt"]["receipt_sha256"]}


def emit_and_append(git_dir: Path | str, *, repository: str, ref: str, before: Any, after: Any, base_ref: str,
                    sender_login: Any, sender_id: Any) -> dict[str, Any]:
    """The writer's whole step for one push event: observe, emit with the vendored producer, append."""
    try:
        pr = producer()
    except RuntimeError as exc:
        return _pin_refusal(str(exc))
    if not isinstance(ref, str) or not ref.startswith("refs/heads/"):
        return refusal("PUSH_RECEIPT_REF_NOT_A_BRANCH", "PUSH_IS_TO_A_PR_BRANCH_NOT_MAIN", "a push to refs/heads/<branch>",
                       "none; only branch pushes are receipted", disposition=DENY, ref=ref)
    if ref == MAIN_REF:
        return refusal("PUSH_RECEIPT_REF_IS_MAIN", "PUSH_IS_TO_A_PR_BRANCH_NOT_MAIN",
                       "a push to main is recorded by ORGANIZATION_MAIN_MERGE_TRANSFER, not as a push receipt",
                       "none; main's push is ledgered by organization-ledger-merge-transfer.yml", disposition=DENY, ref=ref)
    session = pusher_session(sender_login, sender_id)
    if not (isinstance(after, str) and SHA40.match(after) and after != ZERO) or session is None:
        return refusal("PUSH_NOT_OBSERVED", "PUSH_INPUTS_ARE_GITHUB_OBSERVED",
                       "the push event's after sha and the sender login and id GitHub observed",
                       "none for a branch deletion; otherwise re-run the push's run", after=after,
                       sender_observed=session is not None)
    old = old_sha_for(before, after, git_dir, base_ref)
    if old is None:
        return refusal("PUSH_NOT_OBSERVED", "PUSH_INPUTS_ARE_GITHUB_OBSERVED",
                       "the push's before sha, or for a new branch a merge-base with " + base_ref,
                       "re-run with full history fetched; nothing was written", before=before, after=after)
    epoch, failed = mt.head_epoch(mt.org_store())
    if failed is not None:
        return refusal("HB_EPOCH_SOURCE_UNOBSERVED", "PUSH_RECEIPT_EPOCH_IS_THE_LEDGER_HEAD_EPOCH",
                       failed["required_evidence_or_repair"], "re-run once the ledger head carries a supplied epoch; nothing was written",
                       detail=failed.get("detail"))
    receipt = pr.emit(git_dir, repository_name=repository, ref=ref, old_sha=old, pusher_session=session,
                      hb_epoch=str(epoch), after_ref=after)
    if receipt.get("schema") != RECEIPT_SCHEMA:
        predicate = ("PUSH_IS_A_FAST_FORWARD_THAT_MOVED_THE_REF"
                     if receipt.get("failure_code") in ("PUSH_NOT_FAST_FORWARD", "PUSH_NOT_OBSERVED")
                     else "PUSH_INPUTS_ARE_GITHUB_OBSERVED")
        return refusal(receipt.get("failure_code", "PUSH_RECEIPT_NOT_EMITTED"), predicate,
                       receipt.get("required_evidence_or_repair", "a receipt from the vendored producer"),
                       "none for a force-push or a push that moved nothing (the range stays UNKNOWN); nothing was written",
                       producer_refusal=receipt, old_sha=old, new_sha=after)
    return append_push_receipt(receipt, repository=repository)


# -- readback ----------------------------------------------------------------

def verify_push_receipt(repository: str, ref: str, old_sha: str, new_sha: str, organization: Any = None,
                        repository_store: Any = None) -> dict[str, Any]:
    """ALLOW only when a sealed organization receipt names this push and its sealed repository receipt carries
    the sealed sv-push-receipt.v1 for exactly this push; absent is FAIL_CLOSED, contradicted is DENY."""
    try:
        pr = producer()
    except RuntimeError as exc:
        return _pin_refusal(str(exc))
    org, rep = recorded(repository, ref, old_sha, new_sha, organization, repository_store)
    base = {"repository": repository, "ref": ref, "old_sha": old_sha, "new_sha": new_sha}
    if org is None:
        return {**refusal("PUSH_RECEIPT_NOT_LEDGERED", "PUSH_HAS_A_SEALED_ORGANIZATION_LEDGER_RECEIPT",
                          "a sealed organization receipt with operation sv_push_receipt for this push",
                          "the push's run appends it; verify again after it publishes"), **base, "schema": READBACK_SCHEMA}
    ev = rep.get("evidence") if mt.sealed(rep) else None
    r = ev.get("push_receipt") if isinstance(ev, Mapping) else None
    wrong = []
    if not isinstance(ev, Mapping) or ev.get("schema") != EVIDENCE_SCHEMA:
        wrong.append("evidence schema")
    if pr.receipt_problem(r) is not None:
        wrong.append("push_receipt " + str(pr.receipt_problem(r)))
    elif (r["repository"], r["ref"], r["old_sha"], r["new_sha"]) != (repository, ref, old_sha, new_sha):
        wrong.append("push_receipt names another push")
    elif mt._boundary(org).get("push_receipt_sha256") != r["result_sha256"] or ev.get("payload_sha256") != r["result_sha256"]:
        wrong.append("digests do not link")
    if wrong:
        return {**refusal("PUSH_RECEIPT_LINK_UNVERIFIED", "PUSH_HAS_A_SEALED_ORGANIZATION_LEDGER_RECEIPT",
                          "the organization receipt's sealed repository receipt must carry this push's sealed receipt",
                          "inspect organization receipt " + org["receipt_sha256"] + "; nothing was verified",
                          disposition=DENY, detail="; ".join(wrong)), **base, "schema": READBACK_SCHEMA}
    return {"schema": READBACK_SCHEMA, "disposition": ALLOW, **base, "push_receipt_sha256": r["result_sha256"],
            "pusher_session": r["pusher_session"], "organization_receipt_sha256": org["receipt_sha256"],
            "repository_receipt_sha256": rep["receipt_sha256"], "hb_epoch": (org.get("hb_reference") or {}).get("epoch"),
            "readback_writes": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    e = sub.add_parser("emit-append", help="observe one push, emit its sv-push-receipt.v1, append it")
    e.add_argument("--git-dir", default=".")
    e.add_argument("--repository", required=True)
    e.add_argument("--ref", required=True)
    e.add_argument("--before", default="")
    e.add_argument("--after", required=True)
    e.add_argument("--base-ref", default="refs/remotes/origin/main")
    e.add_argument("--sender-login", required=True)
    e.add_argument("--sender-id", required=True)
    e.add_argument("--out")
    v = sub.add_parser("verify", help="read one push's receipts back")
    v.add_argument("--result", required=True, help="the emit-append result JSON")
    v.add_argument("--out")
    args = parser.parse_args(argv)
    if args.command == "emit-append":
        out = emit_and_append(args.git_dir, repository=args.repository, ref=args.ref, before=args.before,
                              after=args.after, base_ref=args.base_ref, sender_login=args.sender_login,
                              sender_id=args.sender_id)
    else:
        res = json.loads(Path(args.result).read_text(encoding="utf-8"))
        if res.get("disposition") != ALLOW:
            out = refusal("PUSH_RECEIPT_NOT_LEDGERED", "PUSH_HAS_A_SEALED_ORGANIZATION_LEDGER_RECEIPT",
                          "an ALLOW emit-append result to verify", "none; the append refused", appended_result=res)
        else:
            out = verify_push_receipt(res["repository"], res["ref"], res["old_sha"], res["new_sha"])
    text = json.dumps(out, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if out.get("disposition") == ALLOW else 1


if __name__ == "__main__":
    raise SystemExit(main())
