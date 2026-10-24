#!/usr/bin/env python3
"""The committed ingest request the organization ledger writer processes on push to main.

The same ingest route StegVerse-Labs/.github runs (its
resident-runtime/organization_ledger_ingest.py): a request committed at
REQUEST_PATH, read on push to main by the writer's ledger-ingest job
(.github/workflows/organization-ledger-writer.yml, selected by
control/workflow-surface-registry.json writer_jobs[]). Nothing here or in the
workflow hand-writes the ledger ref; the append is the existing writer
(aggregate_repo_transition.append over ledger_store) and the ref moves only by
the job's fast-forward publish.

  {"schema": "stegverse.organization-ledger-ingest-request/v1",
   "operation": "sealed_test_receipt",
   "receipt": {<a test receipt sealed by its producer's CI, byte-for-value as the run printed it>},
   "provenance": {"repository": "<producer>", "run_id": <int>, "head_sha": "<producer commit>", ...}}

The sealed receipt is retained unchanged as source-receipts/<receipt_sha256>.json,
consumed by one organization transition receipt (aggregate_repo_transition
.verify_sealed_test_receipt), at the supplied epoch the ledger head carries
(merge_transfer.head_epoch; no clock). Before any write it must: carry a seal
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
SEALED_CLASS = "ORGANIZATION_SEALED_TEST_RECEIPT_INGEST"
FIELDS = {
    SEALED: ({"schema", "operation", "receipt", "provenance"}, set()),
}
FILES = {"receipt": "sealed-receipt.json", "provenance": "provenance.json"}
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
    for name in required - {"schema", "operation"}:
        if not isinstance(request[name], dict):
            return refusal("INGEST_REQUEST_SCHEMA_MISMATCH", name.upper() + "_IS_ONE_JSON_OBJECT", name + " as one JSON object")
    result = {"disposition": "ALLOW", "operation": operation}
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
    org = _module("aggregate_repo_transition", "resident-runtime/aggregate_repo_transition.py")
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
    if args.command == "read":
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
