#!/usr/bin/env python3
"""``MERGE_ADMISSION_RECORD`` -- an ALLOW merge-admission record, sealed, on the organization ledger.

TVC#519 v2 (StegVerse-Labs/TVC#531, record fields in TVC#534) emits, on ALLOW,
a sealed ``stegverse.merge-admission-record/v2.1`` (record_sha256). It carries
the admitted head, change_digest, the manifest digest, hb_epoch from the
organization ledger head, and every predicate's disposition. The B2 checkpoint
(resident-runtime/merge_transfer_admission.py, StegVerse-org/.github#220)
finds a record on this organization's chain as a sealed organization receipt
whose boundary_evidence.operation is MERGE_ADMISSION_RECORD and whose
boundary_evidence.admission_record is the record. This module is that writer
operation. It appends through the existing two-level append
(intr_destination_ingress._append, as merge_transfer.py and sv_push_receipt use it):

  * repository receipt: ``$.evidence`` is ``stegverse.org-merge-admission-record-evidence/v1``,
    ``{admission_record, payload_sha256 = record_sha256, disposition, communication_id}``;
  * organization receipt: ``boundary_evidence.operation == "MERGE_ADMISSION_RECORD"``, with
    ``admission_record`` (the record, byte-equal), repository, pull_number, head_sha,
    record_sha256 and manifest_sha256.

The writer admits a record only when all of these hold (refusals carry the six fields and write nothing):
  * the seal verifies and the schema is the contracted one (DENY ADMISSION_RECORD_SEAL_INVALID);
  * the fields equal the contract (FAIL_CLOSED ADMISSION_RECORD_INVALID);
  * every predicate is ALLOW and the record names this op (DENY ADMISSION_RECORD_NOT_ALLOW);
  * the repository is this one (DENY ADMISSION_RECORD_REPOSITORY_MISMATCH);
  * the manifest digest is the pinned one in data/merge-admission/record-contract.json
    (FAIL_CLOSED ADMISSION_MANIFEST_NOT_PINNED);
  * hb_epoch equals the current organization ledger head epoch (FAIL_CLOSED
    ADMISSION_RECORD_EPOCH_NOT_LEDGER_HEAD; re-evaluate, never re-stamp).
The ledger head commit in the record is provenance: every append moves the commit,
while the epoch is what binds.

A record already ledgered is answered from the ledger (verify-first).

Delivery (A2). TVC is private and holds the record. It reaches this public
writer as a ``stegverse.merge-admission-record-delivery/v1`` envelope:
``{schema, record, signed_payload, signer_key_id, signature}``. The signature is
ed25519 over the canonical bytes of signed_payload =
``{schema, record_sha256, repository, pull_number, head_sha, manifest_sha256}``.
It is verified with the system ``openssl pkeyutl -verify -rawin`` against the
public key pinned in data/merge-admission/record-contract.json ``delivery``:
  * no key pinned -> FAIL_CLOSED ADMISSION_RECORD_SIGNER_KEY_NOT_PINNED. The event
    that pins it is a TVC resident issuance receipt that publishes the
    merge-admission signer public key; the private key stays in TV/TVC custody;
  * a malformed envelope -> FAIL_CLOSED ADMISSION_RECORD_DELIVERY_ENVELOPE_INVALID;
  * the payload does not match the record, or the signature fails -> DENY
    ADMISSION_RECORD_DELIVERY_SIGNATURE_INVALID.
Only a public key is ever pinned here. No private key or credential is
embedded, read or minted, and no workflow writes until the key is pinned and the
delivery event exists. ``append`` with nothing delivered is FAIL_CLOSED
ADMISSION_RECORD_NOT_DELIVERED. Stdlib plus the system openssl binary; no
environment read beyond the ledger location variables the writers already use;
no clock.
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
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


mt = _module("merge_transfer_for_admission_record", ROOT / "resident-runtime" / "merge_transfer.py")
ingress = mt.ingress
sha = ingress.sha

OPERATION = "MERGE_ADMISSION_RECORD"
TRANSITION_CLASS = "MERGE_ADMISSION_RECORD_APPEND"
PROFILE_ID = "org-ledger-writer"
EVIDENCE_SCHEMA = "stegverse.org-merge-admission-record-evidence/v1"
RESULT_SCHEMA = "stegverse.org-merge-admission-record-append-result/v1"
READBACK_SCHEMA = "stegverse.org-merge-admission-record-readback/v1"
CONTRACT_FILE = ROOT / "data" / "merge-admission" / "record-contract.json"
LEDGER_REF = "refs/stegverse/organization-ledger"
GOAL = "StegVerse-org/.github#164 (TVC#519 v2 MERGE_ADMISSION record on the organization ledger; B2 consumer #220)"
ENTRYPOINT = ("resident-runtime/merge_admission_record_append.py append --delivery <the TVC-signed delivery envelope>, run by "
              "the record-delivery event (signer public key pinned from a TVC resident issuance receipt)")
DELIVERY_SCHEMA = "stegverse.merge-admission-record-delivery/v1"
SIGNED_PAYLOAD_SCHEMA = "stegverse.merge-admission-record-delivery-payload/v1"
KEY_PIN_EVENT = ("a TVC resident issuance receipt that publishes the merge-admission signer public key (ed25519, PEM) and "
                 "its key id; a PR re-pins data/merge-admission/record-contract.json delivery.signer_public_key_pem from it")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
ALLOW, DENY, FAIL_CLOSED = "ALLOW", "DENY", "FAIL_CLOSED"
SIX_FIELDS = mt.SIX_FIELDS

_E0_ONLY = "E0 is the only rung: a mechanical check over the record bytes and ledger receipts"
PREDICATES = {
    "ADMISSION_RECORD_IS_DELIVERED": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "the record bytes are present to this writer as a JSON object (delivery is the TV/TVC transition)",
        "llm_inputs": "none at any rung"},
    "ADMISSION_RECORD_DELIVERY_IS_SIGNED_BY_THE_PINNED_TVC_KEY": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": ("the envelope is " + DELIVERY_SCHEMA + ", its signed_payload equals the record's identity, and the ed25519 "
               "signature verifies (openssl pkeyutl -verify -rawin) against the contract's pinned signer public key"),
        "llm_inputs": "none at any rung"},
    "ADMISSION_RECORD_SEAL_VERIFIES": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "schema equals the contract's record_schema and record_sha256 == sha(record without record_sha256)",
        "llm_inputs": "none at any rung"},
    "ADMISSION_RECORD_FIELDS_ARE_THE_CONTRACT": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "the record's keys equal data/merge-admission/record-contract.json record_fields; head and base are 40-hex",
        "llm_inputs": "none at any rung"},
    "ADMISSION_RECORD_IS_ALLOW": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "predicates is non-empty, every row is ALLOW with a lowest mode, and ledger_operation is MERGE_ADMISSION_RECORD",
        "llm_inputs": "none at any rung"},
    "ADMISSION_RECORD_NAMES_THIS_REPOSITORY": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "repository equals this repository's ledger contract repository",
        "llm_inputs": "none at any rung"},
    "ADMISSION_MANIFEST_IS_THE_PINNED_MANIFEST": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "manifest_sha256 equals the contract's admitted_manifest_sha256",
        "llm_inputs": "none at any rung"},
    "ADMISSION_RECORD_EPOCH_IS_THE_LEDGER_HEAD_EPOCH": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "hb_epoch == ledger_head.hb_epoch == str(current organization ledger head hb_reference.epoch); never a clock",
        "llm_inputs": "none at any rung"},
    "ONE_RECORD_BINDS_ONE_RECEIPT": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "verify-first: a record_sha256 already ledgered is answered from the ledger",
        "llm_inputs": "none at any rung"},
    "ADMISSION_RECORD_APPEND_COMPLETES_AT_BOTH_LEVELS": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "the repository receipt and the organization receipt both exist and are sealed",
        "llm_inputs": "none at any rung"},
    "ADMISSION_RECORD_HAS_A_SEALED_ORGANIZATION_LEDGER_RECEIPT": {
        "lowest_supported_mode": "E0", "E3": _E0_ONLY, "E2": _E0_ONLY, "E1": _E0_ONLY,
        "E0": "the organization chain holds the sealed pair carrying this record, byte-equal",
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


def contract() -> dict[str, Any]:
    return json.loads(CONTRACT_FILE.read_text(encoding="utf-8"))


def sealed_record(record: Any) -> bool:
    return isinstance(record, Mapping) and isinstance(record.get("record_sha256"), str) \
        and record["record_sha256"] == sha({k: v for k, v in record.items() if k != "record_sha256"})


def packet_id(record: Mapping[str, Any]) -> str:
    return sha({"repository": record["repository"], "pull_number": record["pull_number"], "head_sha": record["head_sha"],
                "record_sha256": record["record_sha256"]}).split(":", 1)[1]


def recorded(record_sha256: str, organization: Any = None,
             repository_store: Any = None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(organization receipt, repository receipt) already carrying this record, or (None, None)."""
    organization = organization if organization is not None else mt.org_store()
    repository_store = repository_store if repository_store is not None else mt.repo_store()
    for _, receipt in mt.org_chain(organization):
        if not mt.sealed(receipt):
            continue
        b = mt._boundary(receipt)
        if b.get("operation") == OPERATION and b.get("record_sha256") == record_sha256:
            return receipt, mt._receipt(repository_store, receipt.get("repo_receipt_sha256"))
    return None, None


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def signed_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema": SIGNED_PAYLOAD_SCHEMA, "record_sha256": record.get("record_sha256"), "repository": record.get("repository"),
            "pull_number": record.get("pull_number"), "head_sha": record.get("head_sha"), "manifest_sha256": record.get("manifest_sha256")}


def _ed25519_verifies(public_key_pem: str, message: bytes, signature: bytes) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "k.pem").write_text(public_key_pem, encoding="utf-8")
        (t / "m").write_bytes(message)
        (t / "s").write_bytes(signature)
        try:
            run = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(t / "k.pem"), "-rawin",
                                  "-in", str(t / "m"), "-sigfile", str(t / "s")], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return False
        return run.returncode == 0


def check_delivery(envelope: Any, delivery: Mapping[str, Any] | None = None) -> tuple[Any, dict[str, Any] | None]:
    """(record, None) when the envelope is signed by the pinned TVC key; (None, refusal) otherwise. Writes nothing."""
    pid = "ADMISSION_RECORD_DELIVERY_IS_SIGNED_BY_THE_PINNED_TVC_KEY"
    if envelope is None:
        return None, refusal("ADMISSION_RECORD_NOT_DELIVERED", "ADMISSION_RECORD_IS_DELIVERED",
                             "a " + DELIVERY_SCHEMA + " envelope carrying the sealed record TVC emitted on ALLOW",
                             "after the record-delivery event exists; nothing was written")
    d = delivery if delivery is not None else (contract().get("delivery") or {})
    pem, kid = d.get("signer_public_key_pem"), d.get("signer_key_id")
    if not (isinstance(pem, str) and pem.startswith("-----BEGIN PUBLIC KEY-----") and isinstance(kid, str) and kid):
        return None, refusal("ADMISSION_RECORD_SIGNER_KEY_NOT_PINNED", pid,
                             "the merge-admission signer public key and key id pinned in data/merge-admission/record-contract.json "
                             "delivery, taken from " + KEY_PIN_EVENT,
                             "after that issuance receipt exists and a PR pins the key (class A once TVC issues it; the "
                             "issuance is the TV/TVC custody transition); nothing was written")
    if not (isinstance(envelope, Mapping) and envelope.get("schema") == DELIVERY_SCHEMA and isinstance(envelope.get("record"), Mapping)
            and isinstance(envelope.get("signed_payload"), Mapping) and isinstance(envelope.get("signature"), str)
            and isinstance(envelope.get("signer_key_id"), str)):
        return None, refusal("ADMISSION_RECORD_DELIVERY_ENVELOPE_INVALID", pid,
                             "a " + DELIVERY_SCHEMA + " envelope {schema, record, signed_payload, signer_key_id, signature}",
                             "re-deliver a well-formed envelope; nothing was written")
    record = envelope["record"]
    try:
        sig = base64.b64decode(envelope["signature"], validate=True)
    except ValueError:
        sig = b""
    if envelope["signer_key_id"] != kid or dict(envelope["signed_payload"]) != signed_payload(record) \
            or not sig or not _ed25519_verifies(pem, canonical(envelope["signed_payload"]), sig):
        return None, refusal("ADMISSION_RECORD_DELIVERY_SIGNATURE_INVALID", pid,
                             "an envelope whose signed_payload is this record's identity, signed by pinned key " + kid,
                             "re-deliver the envelope as TVC signed it; nothing was written", disposition=DENY,
                             envelope_signer_key_id=envelope.get("signer_key_id"))
    return record, None


def deliver(envelope: Any, *, repository: str | None = None, delivery: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The delivery entrypoint: verify the TVC signature, then the record path (verify-first, check, append)."""
    record, bad = check_delivery(envelope, delivery)
    if bad is not None:
        return bad
    return append_admission_record(record, repository=repository)


def check(record: Any, repository: str, epoch: Any) -> dict[str, Any] | None:
    """The record predicates in order; None when every one holds."""
    c = contract()
    if not isinstance(record, Mapping):
        return refusal("ADMISSION_RECORD_NOT_DELIVERED", "ADMISSION_RECORD_IS_DELIVERED",
                       "the sealed record TVC emitted on ALLOW, delivered to this writer by the TV/TVC transition",
                       "after delivery exists (class B); nothing was written")
    if record.get("schema") != c["record_schema"] or not sealed_record(record):
        return refusal("ADMISSION_RECORD_SEAL_INVALID", "ADMISSION_RECORD_SEAL_VERIFIES",
                       "the record byte-for-byte as TVC sealed it (" + c["record_schema"] + ", record_sha256)",
                       "re-deliver the unmodified record; nothing was written", disposition=DENY)
    keys = sorted(record)
    if keys != sorted(c["record_fields"]) or not all(isinstance(record.get(k), str) and SHA40.match(record[k])
                                                      for k in ("head_sha", "base_head_sha")) \
            or not isinstance(record.get("pull_number"), int):
        return refusal("ADMISSION_RECORD_INVALID", "ADMISSION_RECORD_FIELDS_ARE_THE_CONTRACT",
                       "a record with exactly the contracted fields (data/merge-admission/record-contract.json)",
                       "re-pin the contract with the producer's schema, or re-evaluate; nothing was written",
                       missing=sorted(set(c["record_fields"]) - set(keys)), extra=sorted(set(keys) - set(c["record_fields"])))
    rows = record["predicates"]
    if record.get("ledger_operation") != OPERATION or not isinstance(rows, list) or not rows \
            or any(not isinstance(r, Mapping) or r.get("disposition") != ALLOW or not r.get("lowest_supported_mode") for r in rows):
        return refusal("ADMISSION_RECORD_NOT_ALLOW", "ADMISSION_RECORD_IS_ALLOW",
                       "an admission record exists only on ALLOW: every predicate ALLOW",
                       "none for this record; a fresh evaluation that is ALLOW", disposition=DENY)
    if record["repository"] != repository:
        return refusal("ADMISSION_RECORD_REPOSITORY_MISMATCH", "ADMISSION_RECORD_NAMES_THIS_REPOSITORY",
                       "a record for " + repository + " (each repository's writer ledgers its own admissions)",
                       "deliver it to the named repository's writer; nothing was written", disposition=DENY,
                       record_repository=record["repository"])
    if record["manifest_sha256"] != c["admitted_manifest_sha256"]:
        return refusal("ADMISSION_MANIFEST_NOT_PINNED", "ADMISSION_MANIFEST_IS_THE_PINNED_MANIFEST",
                       "a record under the pinned manifest " + c["admitted_manifest_sha256"] + " (re-pin through a PR when it changes)",
                       "after the contract pins this manifest, or re-evaluate under the pinned one; nothing was written",
                       record_manifest_sha256=record["manifest_sha256"])
    lh = record.get("ledger_head") if isinstance(record.get("ledger_head"), Mapping) else {}
    if epoch is None or record["hb_epoch"] != str(epoch) or lh.get("hb_epoch") != record["hb_epoch"] or lh.get("ledger_ref") != LEDGER_REF:
        return refusal("ADMISSION_RECORD_EPOCH_NOT_LEDGER_HEAD", "ADMISSION_RECORD_EPOCH_IS_THE_LEDGER_HEAD_EPOCH",
                       "a record whose hb_epoch is the organization ledger head's epoch now (" + str(epoch) + ")",
                       "re-evaluate against the current ledger head (never re-stamp the record); nothing was written",
                       record_hb_epoch=record.get("hb_epoch"), ledger_head_epoch=epoch)
    return None


def _evidence(record: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema": EVIDENCE_SCHEMA, "admission_record": dict(record), "payload_sha256": record["record_sha256"],
            "disposition": ALLOW,
            "communication_id": f"{OPERATION}:{record['repository']}#{record['pull_number']}@{record['head_sha']}:{record['record_sha256']}"}


def append_admission_record(record: Any, *, repository: str | None = None) -> dict[str, Any]:
    """Verify first, check the record, append the pair. Never a partial write."""
    repository = repository or mt.repository()
    if sealed_record(record):
        org_prior, repo_prior = recorded(record["record_sha256"])
        if org_prior is not None and isinstance(repo_prior, Mapping) and mt.sealed(repo_prior):
            return {"schema": RESULT_SCHEMA, "operation": OPERATION, "disposition": ALLOW, "replayed": True, "appended": False,
                    "repository": repository, "pull_number": record.get("pull_number"), "head_sha": record.get("head_sha"),
                    "record_sha256": record["record_sha256"], "organization_receipt_sha256": org_prior["receipt_sha256"],
                    "repository_receipt_sha256": repo_prior["receipt_sha256"]}
    epoch, failed = mt.head_epoch(mt.org_store())
    if failed is not None and isinstance(record, Mapping):
        return refusal("HB_EPOCH_SOURCE_UNOBSERVED", "ADMISSION_RECORD_EPOCH_IS_THE_LEDGER_HEAD_EPOCH",
                       failed["required_evidence_or_repair"], "re-run once the ledger head carries a supplied epoch; nothing was written",
                       detail=failed.get("detail"))
    bad = check(record, repository, epoch)
    if bad is not None:
        return bad
    try:
        appended, replayed = ingress._append(
            TRANSITION_CLASS, packet_id(record), _evidence(record), epoch, operation=OPERATION, profile_id=PROFILE_ID,
            boundary_extra={"admission_record": dict(record), "repository": repository, "pull_number": record["pull_number"],
                            "head_sha": record["head_sha"], "record_sha256": record["record_sha256"],
                            "manifest_sha256": record["manifest_sha256"]})
    except ValueError as exc:
        code = "ADMISSION_RECORD_COLLISION" if str(exc) == "ledger_receipt_collision" else "LEDGER_WRITER_REFUSED"
        return refusal(code, "ONE_RECORD_BINDS_ONE_RECEIPT" if code == "ADMISSION_RECORD_COLLISION"
                       else "ADMISSION_RECORD_APPEND_COMPLETES_AT_BOTH_LEVELS",
                       "the ledger binds this record's packet to other evidence, or the writer refused: " + str(exc),
                       "inspect the recorded receipt; nothing was written", detail=str(exc))
    except SystemExit as exc:
        return refusal("LEDGER_WRITER_REFUSED", "ADMISSION_RECORD_APPEND_COMPLETES_AT_BOTH_LEVELS",
                       "repair what the ledger writer refused (" + str(exc.code) + ")",
                       "re-run once repaired; nothing was written", detail=str(exc.code))
    return {"schema": RESULT_SCHEMA, "operation": OPERATION, "disposition": ALLOW, "replayed": replayed,
            "appended": not replayed, "repository": repository, "pull_number": record["pull_number"],
            "head_sha": record["head_sha"], "record_sha256": record["record_sha256"], "hb_epoch": epoch,
            "repository_receipt_sha256": appended["repository_receipt"]["receipt_sha256"],
            "organization_receipt_sha256": appended["organization_receipt"]["receipt_sha256"]}


def verify_admission_record(record_sha256: str, organization: Any = None, repository_store: Any = None) -> dict[str, Any]:
    """ALLOW only when a sealed organization receipt carries this record byte-equal, linked to its sealed repository receipt."""
    org, rep = recorded(record_sha256, organization, repository_store)
    if org is None:
        return {**refusal("ADMISSION_RECORD_NOT_LEDGERED", "ADMISSION_RECORD_HAS_A_SEALED_ORGANIZATION_LEDGER_RECEIPT",
                          "a sealed organization receipt with operation MERGE_ADMISSION_RECORD for " + record_sha256,
                          "append it (record delivery), then verify again"), "schema": READBACK_SCHEMA, "record_sha256": record_sha256}
    b = mt._boundary(org)
    ev = rep.get("evidence") if isinstance(rep, Mapping) and mt.sealed(rep) else None
    if not (isinstance(ev, Mapping) and ev.get("schema") == EVIDENCE_SCHEMA and sealed_record(b.get("admission_record"))
            and b["admission_record"] == ev.get("admission_record") and ev.get("payload_sha256") == record_sha256
            and b["admission_record"]["record_sha256"] == record_sha256):
        return {**refusal("ADMISSION_RECORD_LINK_UNVERIFIED", "ADMISSION_RECORD_HAS_A_SEALED_ORGANIZATION_LEDGER_RECEIPT",
                          "the organization receipt and its sealed repository receipt must carry this record byte-equal",
                          "inspect organization receipt " + org["receipt_sha256"] + "; nothing was verified", disposition=DENY),
                "schema": READBACK_SCHEMA, "record_sha256": record_sha256}
    return {"schema": READBACK_SCHEMA, "disposition": ALLOW, "record_sha256": record_sha256,
            "repository": b.get("repository"), "pull_number": b.get("pull_number"), "head_sha": b.get("head_sha"),
            "organization_receipt_sha256": org["receipt_sha256"], "repository_receipt_sha256": rep["receipt_sha256"],
            "readback_writes": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("append", help="append one delivered admission record")
    a.add_argument("--delivery", help="path of the TVC-signed delivery envelope; absent -> FAIL_CLOSED ADMISSION_RECORD_NOT_DELIVERED")
    a.add_argument("--out")
    v = sub.add_parser("verify", help="read one record back from the ledger")
    v.add_argument("--record-sha256", required=True)
    v.add_argument("--out")
    args = parser.parse_args(argv)
    if args.command == "append":
        try:
            envelope = json.loads(Path(args.delivery).read_text(encoding="utf-8")) if args.delivery else None
        except (OSError, ValueError):
            envelope = None
        out = deliver(envelope)
    else:
        out = verify_admission_record(args.record_sha256)
    text = json.dumps(out, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if out.get("disposition") == ALLOW else 1


if __name__ == "__main__":
    raise SystemExit(main())
