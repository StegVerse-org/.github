#!/usr/bin/env python3
"""The committed ingest request the organization ledger writer processes on push to main.

The same ingest route StegVerse-Labs/.github runs (its
resident-runtime/organization_ledger_ingest.py): a request committed at
REQUEST_PATH, read on push to main by the writer's ledger-ingest job
(.github/workflows/organization-ledger-writer.yml, selected by
control/workflow-surface-registry.json writer_jobs[]). Nothing here or in the
workflow hand-writes the ledger ref; the append is the existing writer
(aggregate_repo_transition.append over ledger_store, see writer()) and the ref moves only by
the job's fast-forward publish.

  {"schema": "stegverse.organization-ledger-ingest-request/v1",
   "operation": "sealed_test_receipt",
   "receipt": {<a test receipt sealed by its producer's CI, byte-for-value as the run printed it>},
   "provenance": {"repository": "<producer>", "run_id": <int>, "head_sha": "<producer commit>", ...}}

  {"schema": "stegverse.organization-ledger-ingest-request/v1",
   "operation": "sv_check_receipt",
   "check_receipt": {<one stegverse.sv_check_receipt.v1 object>},
   "hb_epoch": <non-negative integer>,
   "evaluation_subject": {<optional: the stage-evaluation subject of a stage-gate receipt>},
   "base_state_readback": {<optional: its base-state readback>}}

sv_check_receipt is appended by resident-runtime/sv_check_receipt_append.py (the port of the StegVerse-Labs/.github
operation of the same name) at the request's supplied epoch (it must equal the receipt's own hb_epoch). A failing check
receipt appended here is the only source of a native SV_ISSUE on this ledger (sv_change_admit_append.py derives it).

  {"schema": "stegverse.organization-ledger-ingest-request/v1",
   "operation": "sv_push_receipt",
   "push_receipt": {<one stegverse.sv_push_receipt.v1 object, as resident-runtime/sv_push_receipt.py emit wrote it>},
   "hb_epoch": <non-negative integer>}

sv_push_receipt is appended by resident-runtime/sv_push_receipt_append.py (the port of StegVerse-Labs/.github#3424) at
the request's supplied epoch (it must equal the receipt's own hb_epoch), once per push range (repository, ref,
old_sha, new_sha); a second receipt for the same range is refused as a duplicate. The operations are declared in
.stegverse/organization-ledger-ingest/operations.json.

  {"schema": "stegverse.organization-ledger-ingest-request/v1",
   "operation": "sv_change_admit",
   "predecessor": {<the stegverse.sv_change.v1 record being superseded>},
   "successor": {<the NATIVE stegverse.sv_change.v1 record that names it in $.supersedes>},
   "admission": {"predicate_digest", "corpus_head", "actor_session", "change_commits", "push_ranges", "registry_generation"},
   "hb_epoch": <non-negative integer>}

sv_change_admit is evaluated and appended by resident-runtime/sv_change_admit_append.py: the pinned P1
SV_CHANGE_SUPERSEDE -> SV_CHANGE_VERIFY -> SV_CHANGE_ADMIT outcome is the repository receipt's $.evidence, once per
change (a second request for the same change is refused as a duplicate), on the ledger of the organization that owns the
change's target repository (this one: StegVerse-org repositories, the SDK included).

The sealed receipt is retained unchanged as source-receipts/<receipt_sha256>.json,
consumed by one organization transition receipt, at the supplied epoch the
ledger head carries (merge_transfer.head_epoch; no clock). The append is the
writer's own aggregate_repo_transition.append (lineage, head validation,
idempotent replay, one atomic receipt + source + HEAD transaction) on a private
instance whose source binding also accepts this schema (sealed_source). The
shared aggregate_repo_transition.py and org-contract.json are not edited: they
are in the selection of every ledger test, two of which skip without a TV/TVC
checkout or a deferred step, so this route keeps its own binding and its own
admission gate (ACCEPTED_PATH) until the contract names the schema under its
own change. Before any write it must: carry a seal
that verifies over its canonical body; match an entry of ACCEPTED_PATH; be
ALLOW with no refusals and zero skipped, failed and errored tests; name this
organization's ledger as ledger_candidate.target; and agree with the request's
provenance. Readback is from a fresh fetch of the published ref.

Every refusal is six-field FAIL_CLOSED and nothing is appended. An exact retry
answers from the ledger (idempotent append) rather than minting another receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "stegverse.organization-ledger-ingest-request/v1"
REQUEST_PATH = ".stegverse/organization-ledger-ingest/request.json"
ACCEPTED_PATH = ".stegverse/organization-ledger-ingest/accepted-sealed-receipts.json"
ACCEPTED_SCHEMA = "stegverse.organization-ledger-ingest-accepted-sealed-receipts/v1"
LEDGER_REF = "refs/stegverse/organization-ledger"
ENTRYPOINT = ".github/workflows/organization-ledger-writer.yml ledger-ingest (push to main touching " + REQUEST_PATH + ")"
GOAL = "StegVerse-org/.github#162 P0-runtime-and-custody"
SEALED = "sealed_test_receipt"
SV_CHECK = "sv_check_receipt"
SV_PUSH = "sv_push_receipt"
SV_ADMIT = "sv_change_admit"
OPERATIONS_PATH = ".stegverse/organization-ledger-ingest/operations.json"
SEALED_CLASS = "ORGANIZATION_SEALED_TEST_RECEIPT_INGEST"
FIELDS = {
    SEALED: ({"schema", "operation", "receipt", "provenance"}, set()),
    SV_CHECK: ({"schema", "operation", "check_receipt", "hb_epoch"}, {"evaluation_subject", "base_state_readback"}),
    SV_PUSH: ({"schema", "operation", "push_receipt", "hb_epoch"}, set()),
    SV_ADMIT: ({"schema", "operation", "predecessor", "successor", "admission", "hb_epoch"}, set()),
}
FILES = {"check_receipt": "check-receipt.json", "evaluation_subject": "evaluation-subject.json",
         "base_state_readback": "base-state-readback.json", "receipt": "sealed-receipt.json", "provenance": "provenance.json", "push_receipt": "push-receipt.json",
         "predecessor": "predecessor.json", "successor": "successor.json", "admission": "admission.json"}
MATCH_KEYS = ("schema", "receipt_kind", "suite", "repository")


def refusal(code: str, predicate: str, repair: str, next_attempt: str | None = None, **detail: Any) -> dict[str, Any]:
    return {"disposition": "FAIL_CLOSED", "failure_code": code, "failed_predicate": predicate,
            "required_evidence_or_repair": repair, "retry_entrypoint": ENTRYPOINT, "owning_existing_goal": GOAL,
            "next_attempt": next_attempt or ("commit a corrected " + REQUEST_PATH + " to main; nothing was appended"),
            "consequence_committed": False, "authority_effect": "NONE_REFUSAL_ONLY", **detail}


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canon(value)).hexdigest()


def seal_verifies(document: Any) -> bool:
    return (isinstance(document, dict) and isinstance(document.get("receipt_sha256"), str)
            and document["receipt_sha256"] == sha({k: v for k, v in document.items() if k != "receipt_sha256"}))


def read_request(path: Path | str) -> dict[str, Any]:
    """{"disposition": "ALLOW", "operation", and that operation's fields} or a refusal."""
    path = Path(path)
    if not path.is_file():
        return refusal("INGEST_REQUEST_ABSENT", "PUSHED_COMMIT_CARRIES_THE_REQUEST", REQUEST_PATH + " is absent at the pushed commit")
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return refusal("INGEST_REQUEST_UNREADABLE", "REQUEST_IS_UTF8_JSON", REQUEST_PATH + " is not UTF-8 JSON")
    operation = request.get("operation") if isinstance(request, dict) else None
    if not isinstance(request, dict) or request.get("schema") != SCHEMA or operation not in FIELDS:
        return refusal("INGEST_REQUEST_SCHEMA_MISMATCH", "REQUEST_MATCHES_" + SCHEMA,
                       "an object with schema " + SCHEMA + " and operation one of " + ", ".join(sorted(FIELDS)))
    required, optional = FIELDS[operation]
    if required - set(request) or set(request) - required - optional:
        return refusal("INGEST_REQUEST_SCHEMA_MISMATCH", "REQUEST_MATCHES_" + SCHEMA,
                       operation + " takes the fields " + ", ".join(sorted(required))
                       + (" and optionally " + ", ".join(sorted(optional)) if optional else ""))
    for name in (required | optional) - {"schema", "operation", "hb_epoch"}:
        if name in request and not isinstance(request[name], dict):
            code = {"check_receipt": "LEDGER_EVIDENCE_NOT_A_CHECK_RECEIPT",
                    "push_receipt": "LEDGER_EVIDENCE_NOT_A_PUSH_RECEIPT"}.get(name, "INGEST_REQUEST_SCHEMA_MISMATCH")
            return refusal(code, name.upper() + "_IS_ONE_JSON_OBJECT", name + " as one JSON object")
    result = {"disposition": "ALLOW", "operation": operation}
    if operation == SV_CHECK:
        epoch = request["hb_epoch"]
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
            return refusal("SV_CHECK_RECEIPT_HB_EPOCH_INVALID", "HB_EPOCH_IS_A_NON_NEGATIVE_INTEGER",
                           "hb_epoch as a non-negative integer in the request; no clock is read for it")
        return result | {"check_receipt": request["check_receipt"], "hb_epoch": epoch,
                         "evaluation_subject": request.get("evaluation_subject"),
                         "base_state_readback": request.get("base_state_readback")}
    if operation == SV_PUSH:
        epoch = request["hb_epoch"]
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
            return refusal("SV_PUSH_RECEIPT_HB_EPOCH_INVALID", "HB_EPOCH_IS_A_NON_NEGATIVE_INTEGER",
                           "hb_epoch as a non-negative integer in the request; no clock is read for it")
        return result | {"push_receipt": request["push_receipt"], "hb_epoch": epoch}
    if operation == SV_ADMIT:
        epoch = request["hb_epoch"]
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
            return refusal("SV_CHANGE_ADMIT_HB_EPOCH_INVALID", "HB_EPOCH_IS_A_NON_NEGATIVE_INTEGER",
                           "hb_epoch as a non-negative integer in the request; no clock is read for it")
        return result | {"predecessor": request["predecessor"], "successor": request["successor"],
                         "admission": request["admission"], "hb_epoch": epoch}
    return result | {"receipt": request["receipt"], "provenance": request["provenance"]}


def load_accepted(path: Path | str | None = None) -> list[dict[str, Any]] | dict[str, Any]:
    path = Path(path) if path else ROOT / ACCEPTED_PATH
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        doc = None
    if not isinstance(doc, dict) or doc.get("schema") != ACCEPTED_SCHEMA or not isinstance(doc.get("accepted"), list) \
            or not all(isinstance(e, dict) and all(isinstance(e.get(k), str) for k in MATCH_KEYS) for e in doc["accepted"]):
        return refusal("SEALED_RECEIPT_ACCEPTANCE_UNDECLARED", "ACCEPTED_SEALED_RECEIPTS_ARE_DECLARED",
                       ACCEPTED_PATH + " with schema " + ACCEPTED_SCHEMA + " and accepted entries naming "
                       + ", ".join(MATCH_KEYS))
    return doc["accepted"]


SEALED_TEST_RECEIPT_SCHEMA = "stegverse.test-suite-skip-receipt/v1"


def sealed_source(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """The organization source binding of a sealed test receipt (SystemExit when it is not one).

    Bound by its producer's seal: source_transition_sha256 is its receipt_sha256, so
    source-receipts/<receipt_sha256>.json holds the producer's exact bytes and
    organization_ledger_readback.self_verifies accepts it. It is no repository
    transition of this organization: repo_receipt_sha256 and source_repository are None.
    """
    if not isinstance(receipt, Mapping) or receipt.get("schema") != SEALED_TEST_RECEIPT_SCHEMA:
        raise SystemExit("not a sealed test receipt")
    if not seal_verifies(dict(receipt)):
        raise SystemExit("sealed test receipt hash mismatch")
    identity = [receipt.get(k) for k in ("receipt_kind", "repository", "head_sha")]
    if not all(isinstance(v, str) and v for v in identity):
        raise SystemExit("sealed test receipt identity invalid")
    return {"source_receipt_schema": SEALED_TEST_RECEIPT_SCHEMA,
            "source_transition_sha256": receipt["receipt_sha256"],
            "source_transition_id": "@".join(identity),
            "source_repository": None, "repo_receipt_sha256": None, "repo_transition_id": None,
            "canonical_state_transition_receipt_sha256": None, "subject_or_correlation_id": None}


def writer():
    """A private instance of the organization writer whose source binding also takes sealed_source.

    Only this instance's verify_source changes; every other schema still goes to the
    writer's own verify_source, and the shared module other callers import is untouched.
    """
    org = _module("aggregate_repo_transition_sealed_ingest", "resident-runtime/aggregate_repo_transition.py")
    contract_source = org.verify_source

    def verify_source(receipt):
        if isinstance(receipt, Mapping) and receipt.get("schema") == SEALED_TEST_RECEIPT_SCHEMA:
            return sealed_source(receipt)
        return contract_source(receipt)

    org.verify_source = verify_source
    return org


def ledger_target(ledger_repository: str) -> str:
    return "git+https://github.com/" + ledger_repository + "#" + LEDGER_REF


def admit_sealed(receipt: Any, provenance: Any, *, ledger_repository: str,
                 accepted: list[dict[str, Any]] | dict[str, Any] | None = None) -> dict[str, Any] | None:
    """None when the sealed receipt may be appended to `ledger_repository`'s ledger, else a refusal."""
    accepted = load_accepted() if accepted is None else accepted
    if isinstance(accepted, dict):
        return accepted
    if not seal_verifies(receipt):
        return refusal("SEALED_RECEIPT_SEAL_MISMATCH", "RECEIPT_SHA256_IS_THE_SHA256_OF_THE_CANONICAL_BODY",
                       "the receipt exactly as its producer's run printed it; its receipt_sha256 must equal the sha256 "
                       "of its canonical JSON body (sort_keys, separators (',', ':'), ensure_ascii False)")
    digest = receipt["receipt_sha256"]
    if not any(all(receipt.get(k) == entry[k] for k in MATCH_KEYS) for entry in accepted):
        return refusal("SEALED_RECEIPT_NOT_ACCEPTED", "RECEIPT_MATCHES_A_DECLARED_ACCEPTED_KIND",
                       "a receipt whose " + ", ".join(MATCH_KEYS) + " match an entry of " + ACCEPTED_PATH,
                       receipt_sha256=digest, observed={k: receipt.get(k) for k in MATCH_KEYS})
    counts = receipt.get("counts") if isinstance(receipt.get("counts"), dict) else {}
    if receipt.get("disposition") != "ALLOW" or receipt.get("refusals") not in ([], None):
        return refusal("SEALED_RECEIPT_NOT_ALLOW", "RECEIPT_DISPOSITION_IS_ALLOW_WITH_NO_REFUSALS",
                       "an ALLOW receipt from a passing producer run", receipt_sha256=digest)
    if any(counts.get(k) != 0 for k in ("skipped", "failed", "errors")) or not isinstance(counts.get("tests"), int) \
            or counts["tests"] < 1:
        return refusal("SEALED_RECEIPT_TESTS_NOT_ZERO_SKIPPED", "RECEIPT_COUNTS_AT_LEAST_ONE_TEST_ZERO_SKIPPED_FAILED_ERRORED",
                       "a receipt whose counts show tests >= 1 and skipped, failed and errors all 0",
                       receipt_sha256=digest, counts=counts)
    candidate = receipt.get("ledger_candidate") if isinstance(receipt.get("ledger_candidate"), dict) else {}
    if candidate.get("candidate") is not True or candidate.get("target") != ledger_target(ledger_repository):
        return refusal("SEALED_RECEIPT_TARGETS_ANOTHER_LEDGER", "LEDGER_CANDIDATE_TARGET_IS_THIS_ORGANIZATION_LEDGER",
                       "ledger_candidate.candidate true and target " + ledger_target(ledger_repository),
                       receipt_sha256=digest, observed_target=candidate.get("target"))
    if not isinstance(provenance, dict) or provenance.get("repository") != receipt.get("repository") \
            or provenance.get("head_sha") != receipt.get("head_sha") \
            or isinstance(provenance.get("run_id"), bool) or not isinstance(provenance.get("run_id"), int):
        return refusal("SEALED_RECEIPT_PROVENANCE_MISMATCH", "REQUEST_PROVENANCE_NAMES_THE_PRODUCER_RUN",
                       "provenance with the receipt's repository and head_sha and the producer run_id (an integer)",
                       receipt_sha256=digest)
    return None


def _module(name: str, relative: str):
    if name in sys.modules:
        return sys.modules[name]
    runtime = str(ROOT / "resident-runtime")
    if runtime not in sys.path:
        sys.path.insert(0, runtime)
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def boundary(provenance: Mapping[str, Any], receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {"operation": SEALED, "request_path": REQUEST_PATH, "receipt_kind": receipt.get("receipt_kind"),
            "producer_repository": receipt.get("repository"), "producer_head_sha": receipt.get("head_sha"),
            "producer_run_id": provenance.get("run_id")}


def append_sealed(receipt: Any, provenance: Any, *, ledger_repository: str,
                  accepted: list[dict[str, Any]] | dict[str, Any] | None = None) -> dict[str, Any]:
    """Retain the sealed receipt on the declared organization ledger store (STEGVERSE_ORG_LEDGER_GIT_DIR)."""
    refused = admit_sealed(receipt, provenance, ledger_repository=ledger_repository, accepted=accepted)
    if refused:
        return refused
    org = writer()
    ledger_store = _module("ledger_store", "resident-runtime/ledger_store.py")
    transfer = _module("merge_transfer", "resident-runtime/merge_transfer.py")
    try:
        store = org.open_store(org.ledger_root())
        epoch, unobserved = transfer.head_epoch(store)
    except Exception as exc:  # an unsupplied or unreadable ledger is the same refusal: nothing written
        return refusal("ORGANIZATION_LEDGER_UNAVAILABLE", "SUPPLIED_ORGANIZATION_LEDGER_STORE_OPENS",
                       "the organization ledger supplied as STEGVERSE_ORG_LEDGER_ROOT=git+<checkout>#" + LEDGER_REF,
                       "re-run the push once the ledger ref is fetched; nothing was written",
                       detail=exc.__class__.__name__ + ": " + str(exc))
    if unobserved:
        return {"owning_existing_goal": GOAL, "authority_effect": "NONE_REFUSAL_ONLY", **unobserved,
                "disposition": "FAIL_CLOSED", "retry_entrypoint": ENTRYPOINT, "consequence_committed": False}
    digest = receipt["receipt_sha256"]
    recorded = store.get(ledger_store.source_key(digest)) is not None
    try:
        row = org.append(receipt, SEALED_CLASS, org.FROM_HEAD, digest, boundary(provenance, receipt), "NONE",
                         hb_epoch=epoch, store=store, idempotent=True)
    except (Exception, SystemExit) as exc:
        return refusal("SEALED_RECEIPT_APPEND_REFUSED", "GOVERNED_WRITER_APPENDS_THE_SEALED_RECEIPT",
                       "the organization ledger writer's own refusal, below", detail=exc.__class__.__name__ + ": " + str(exc),
                       receipt_sha256=digest)
    return {"disposition": "ALLOW", "operation": SEALED, "receipt_sha256": digest,
            "receipt_kind": receipt.get("receipt_kind"), "hb_epoch": epoch,
            "organization_receipt_sha256": row["receipt_sha256"],
            "organization_receipt_key": ledger_store.receipt_key(row["receipt_sha256"]),
            "source_receipt_key": ledger_store.source_key(digest), "transition_replayed": recorded,
            "authority_effect": "NONE"}


def readback_sealed(location: str, receipt: Mapping[str, Any]) -> dict[str, Any]:
    """From a fresh fetch: a self-verifying chain with one organization receipt consuming this exact receipt."""
    rb = _module("organization_ledger_readback", "resident-runtime/organization_ledger_readback.py")
    ledger_store = _module("ledger_store", "resident-runtime/ledger_store.py")
    digest = receipt.get("receipt_sha256")
    try:
        chain = rb.readback(location)
        store = ledger_store.open_store(ledger_store.parse_locator(location))
    except Exception as exc:
        return refusal("LEDGER_READBACK_UNAVAILABLE", "PUBLISHED_CHAIN_SELF_VERIFIES_ON_A_FRESH_FETCH",
                       "a readable, self-verifying " + LEDGER_REF + " at " + location,
                       "re-run the push; nothing further was written", detail=exc.__class__.__name__ + ": " + str(exc))
    rows = [r for r in chain["chain"]
            if (store.get(ledger_store.receipt_key(r["receipt_sha256"])) or {}).get("source_transition_sha256") == digest]
    if len(rows) != 1 or store.get(ledger_store.source_key(digest)) != dict(receipt):
        return refusal("SEALED_RECEIPT_NOT_READ_BACK", "ONE_ORGANIZATION_RECEIPT_CONSUMES_THE_EXACT_RETAINED_RECEIPT",
                       "exactly one organization receipt on the chain whose source is " + str(digest)
                       + ", retained byte-for-value", "re-run the push; an appended receipt is answered from the ledger",
                       matches=len(rows))
    org = store.get(ledger_store.receipt_key(rows[0]["receipt_sha256"]))
    return {"disposition": "ALLOW", "operation": SEALED, "receipt_sha256": digest,
            "organization_receipt_sha256": rows[0]["receipt_sha256"], "org_transition_class": org.get("org_transition_class"),
            "hb_reference": org.get("hb_reference"), "chain_length": chain["chain_length"],
            "head_receipt_sha256": chain["head_receipt_sha256"], "authority_effect": "NONE"}


def _emit(result: Mapping[str, Any], out: str | None) -> int:
    text = json.dumps(result, sort_keys=True, indent=1)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.get("disposition") == "ALLOW" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    read = sub.add_parser("read", help="check the request's shape; materialize its parts")
    read.add_argument("--request", default=REQUEST_PATH)
    read.add_argument("--materialize", help="write the request's parts here as the operation's input files")
    read.add_argument("--github-env", help="append INGEST_OPERATION (and HB_EPOCH for sv_check_receipt, sv_push_receipt and sv_change_admit) here")
    append = sub.add_parser("append-sealed", help="append a sealed_test_receipt request through the governed writer")
    append.add_argument("--request", default=REQUEST_PATH)
    append.add_argument("--ledger-repository", required=True)
    append.add_argument("--out")
    admit = sub.add_parser("admit-sealed", help="the admission checks alone; reads no ledger and writes nothing")
    admit.add_argument("--request", default=REQUEST_PATH)
    admit.add_argument("--ledger-repository", required=True)
    admit.add_argument("--out")
    back = sub.add_parser("readback-sealed", help="read a sealed_test_receipt back from a fresh fetch")
    back.add_argument("--request", default=REQUEST_PATH)
    back.add_argument("--location", required=True)
    back.add_argument("--out")
    args = parser.parse_args(argv)
    result = read_request(args.request)
    if result["disposition"] != "ALLOW":
        return _emit(result, getattr(args, "out", None))
    if args.command != "read" and result["operation"] != SEALED:
        return _emit(refusal("INGEST_OPERATION_NOT_SEALED_TEST_RECEIPT", "COMMAND_MATCHES_THE_REQUESTS_OPERATION",
                             args.command + " runs the " + SEALED + " operation; the committed request is "
                             + result["operation"] + ", appended by its own step"), getattr(args, "out", None))
    if args.command == "read":
        if args.github_env:
            with open(args.github_env, "a", encoding="utf-8") as env:
                env.write("INGEST_OPERATION=%s\n" % result["operation"])
                if result["operation"] in (SV_CHECK, SV_PUSH, SV_ADMIT):
                    env.write("HB_EPOCH=%d\n" % result["hb_epoch"])
        if result["operation"] == SV_CHECK:
            if args.materialize:
                target = Path(args.materialize)
                target.mkdir(parents=True, exist_ok=True)
                for part in ("check_receipt", "evaluation_subject", "base_state_readback"):
                    if result.get(part) is not None:
                        (target / FILES[part]).write_text(json.dumps(result[part], sort_keys=True), encoding="utf-8")
            return _emit({"disposition": "ALLOW", "request": args.request, "operation": SV_CHECK, "hb_epoch": result["hb_epoch"],
                          "check_id": result["check_receipt"].get("check_id"),
                          "stage_gate_inputs": sorted(n for n in FIELDS[SV_CHECK][1] if result.get(n) is not None)}, None)
        if result["operation"] == SV_ADMIT:
            if args.materialize:
                target = Path(args.materialize)
                target.mkdir(parents=True, exist_ok=True)
                for part in ("predecessor", "successor", "admission"):
                    (target / FILES[part]).write_text(json.dumps(result[part], sort_keys=True), encoding="utf-8")
            successor = result["successor"]
            return _emit({"disposition": "ALLOW", "request": args.request, "operation": SV_ADMIT, "hb_epoch": result["hb_epoch"],
                          "change_id": successor.get("change_id"), "target_repository": successor.get("target_repository"),
                          "supersedes": successor.get("supersedes")}, None)
        if result["operation"] == SV_PUSH:
            if args.materialize:
                target = Path(args.materialize)
                target.mkdir(parents=True, exist_ok=True)
                (target / FILES["push_receipt"]).write_text(json.dumps(result["push_receipt"], sort_keys=True), encoding="utf-8")
            receipt = result["push_receipt"]
            return _emit({"disposition": "ALLOW", "request": args.request, "operation": SV_PUSH,
                          "hb_epoch": result["hb_epoch"], "repository": receipt.get("repository"),
                          "ref": receipt.get("ref"), "old_sha": receipt.get("old_sha"),
                          "new_sha": receipt.get("new_sha")}, None)
        if args.materialize:
            target = Path(args.materialize)
            target.mkdir(parents=True, exist_ok=True)
            for name, filename in FILES.items():
                if result.get(name) is not None:
                    (target / filename).write_text(json.dumps(result[name], sort_keys=True), encoding="utf-8")
        return _emit({"disposition": "ALLOW", "request": args.request, "operation": result["operation"],
                      "receipt_sha256": result["receipt"].get("receipt_sha256"),
                      "receipt_kind": result["receipt"].get("receipt_kind"),
                      "seal_verifies": seal_verifies(result["receipt"])}, None)
    if args.command == "admit-sealed":
        refused = admit_sealed(result["receipt"], result["provenance"], ledger_repository=args.ledger_repository)
        return _emit(refused or {"disposition": "ALLOW", "operation": SEALED, "admitted": True, "writes": False,
                                 "receipt_sha256": result["receipt"]["receipt_sha256"],
                                 "receipt_kind": result["receipt"].get("receipt_kind")}, args.out)
    if args.command == "append-sealed":
        return _emit(append_sealed(result["receipt"], result["provenance"], ledger_repository=args.ledger_repository),
                     args.out)
    return _emit(readback_sealed(args.location, result["receipt"]), args.out)


if __name__ == "__main__":
    sys.exit(main())
