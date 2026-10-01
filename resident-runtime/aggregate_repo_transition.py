#!/usr/bin/env python3
"""Append organization receipts with serialized, durable HEAD publication.

The organization ledger is local sovereign state. This emitter neither performs
InTr transport nor grants transition authority.

Admission is governed by the `consumes` list in the organization ledger
contract, not by a single hard-coded schema. Every state transition occurring
within the organization emits an organization receipt, so a canonical governed
state transition manifested through Interlock/InTr is admitted on its own
terms and bound by its own canonical digest.
"""
import argparse
import base64
import fcntl
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
C = json.loads((ROOT / ".stegverse/transition-ledger/org-contract.json").read_text())


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(value):
    return "sha256:" + hashlib.sha256(canon(value)).hexdigest()


def ledger_root():
    override = os.getenv("STEGVERSE_ORG_LEDGER_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return (Path(os.getenv("XDG_STATE_HOME", str(Path.home() / ".local/state")))
            / "stegverse/org-ledgers" / C["organization"]).resolve()


def load(path):
    return json.loads(Path(path).read_text())


def verify_required_evidence(receipt):
    """Require exact inline canonical evidence bytes for organization-local replay.

    Organization replay must terminate on this chain alone, so a canonical state
    transition carries its own evidence bytes rather than a reachability promise.
    """
    manifest = receipt.get("required_evidence_manifest")
    if not isinstance(manifest, list):
        raise SystemExit("canonical required evidence manifest missing")
    seen = set()
    for item in manifest:
        if not isinstance(item, dict):
            raise SystemExit("canonical evidence entry invalid")
        for key in ("evidence_id", "evidence_type", "origin_transition_id",
                    "encoding", "sha256", "content"):
            if key not in item:
                raise SystemExit("canonical evidence field missing: " + key)
        identity = item["evidence_id"]
        if not isinstance(identity, str) or not identity or identity in seen:
            raise SystemExit("canonical evidence identity invalid")
        seen.add(identity)
        if (not isinstance(item["evidence_type"], str) or not item["evidence_type"]
                or item["origin_transition_id"] != receipt.get("transition_id")):
            raise SystemExit("canonical evidence transition binding invalid")
        encoding = item["encoding"]
        content = item["content"]
        if encoding == "canonical-json":
            raw = canon(content)
        elif encoding == "utf-8" and isinstance(content, str):
            raw = content.encode("utf-8")
        elif encoding == "base64" and isinstance(content, str):
            try:
                raw = base64.b64decode(content.encode("ascii"), validate=True)
            except (ValueError, UnicodeError) as exc:
                raise SystemExit("canonical evidence base64 invalid") from exc
        else:
            raise SystemExit("canonical evidence encoding invalid")
        digest = item["sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or hashlib.sha256(raw).hexdigest() != digest:
            raise SystemExit("canonical required evidence digest mismatch")


def verify_source(receipt):
    """Verify a source transition receipt this organization's contract consumes.

    The contract's `consumes` list is the admission gate. Every state transition
    occurring within the organization emits an organization receipt, so a
    canonical governed transition is admitted on its own terms: it is bound by
    its own canonical digest and keeps its own schema and transition id, rather
    than being relabelled as a repository transition it is not.
    """
    schema = receipt.get("schema")
    allowed = C.get("consumes")
    if isinstance(allowed, str):
        allowed = [allowed]
    if schema not in (allowed or []):
        raise SystemExit("organization source receipt schema mismatch")
    transition_id = receipt.get("transition_id")
    if not isinstance(transition_id, str) or not transition_id:
        raise SystemExit("organization source transition id invalid")
    if schema == "stegverse.repo-transition-receipt/v1":
        repository = str(receipt.get("repository", ""))
        if not repository.startswith(C["organization"] + "/"):
            raise SystemExit("repo outside organization")
        claimed = receipt.get("receipt_sha256")
        body = dict(receipt)
        body.pop("receipt_sha256", None)
        if claimed != sha(body):
            raise SystemExit("repo receipt hash mismatch")
        return {
            "source_receipt_schema": schema,
            "source_transition_sha256": claimed,
            "source_transition_id": transition_id,
            "source_repository": repository,
            "repo_receipt_sha256": claimed,
            "repo_transition_id": transition_id,
            "canonical_state_transition_receipt_sha256": None,
            "subject_or_correlation_id": None,
        }
    verify_required_evidence(receipt)
    digest = sha(receipt)
    return {
        "source_receipt_schema": schema,
        "source_transition_sha256": digest,
        "source_transition_id": transition_id,
        "source_repository": None,
        "repo_receipt_sha256": None,
        "repo_transition_id": None,
        "canonical_state_transition_receipt_sha256": digest,
        "subject_or_correlation_id": receipt.get("subject_or_correlation_id"),
    }


def _sync_directory(directory):
    fd = os.open(str(directory), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_json(path, value):
    """Publish complete JSON by same-directory atomic replacement."""
    fd, temp = tempfile.mkstemp(prefix=".org-append-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True).encode() + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _validate_existing_head(head, receipt_dir):
    if not head.exists():
        # A missing HEAD with existing receipts requires explicit recovery;
        # never silently fork or reset the organization chain.
        if any(receipt_dir.glob("*.json")):
            raise SystemExit("ORG_LEDGER_HEAD_MISSING_WITH_EXISTING_RECEIPTS")
        return None
    state = load(head)
    previous = state.get("receipt_sha256")
    if not isinstance(previous, str) or not previous.startswith("sha256:"):
        raise SystemExit("ORG_LEDGER_HEAD_INVALID")
    path = receipt_dir / (previous.split(":", 1)[1] + ".json")
    if not path.is_file():
        raise SystemExit("ORG_LEDGER_HEAD_RECEIPT_MISSING")
    receipt = load(path)
    body = dict(receipt)
    body.pop("receipt_sha256", None)
    if receipt.get("receipt_sha256") != previous or sha(body) != previous:
        raise SystemExit("ORG_LEDGER_HEAD_RECEIPT_HASH_MISMATCH")
    # A receipt written before a crash but not published as HEAD must not be
    # silently bypassed. Detect all unreachable receipts before appending.
    reachable = set()
    cursor = previous
    while cursor:
        if cursor in reachable:
            raise SystemExit("ORG_LEDGER_PREDECESSOR_CYCLE")
        reachable.add(cursor)
        predecessor_path = receipt_dir / (cursor.split(":", 1)[1] + ".json")
        if not predecessor_path.is_file():
            raise SystemExit("ORG_LEDGER_PREDECESSOR_MISSING")
        record = load(predecessor_path)
        record_body = dict(record)
        record_body.pop("receipt_sha256", None)
        if record.get("receipt_sha256") != cursor or sha(record_body) != cursor:
            raise SystemExit("ORG_LEDGER_PREDECESSOR_HASH_MISMATCH")
        cursor = record.get("previous_receipt_sha256")
    stored = {"sha256:" + item.stem for item in receipt_dir.glob("*.json")}
    if stored != reachable:
        raise SystemExit("ORG_LEDGER_UNPUBLISHED_OR_ORPHAN_RECEIPTS_RECOVERY_REQUIRED")
    return previous


def append(source_receipt, org_transition_class, predecessor_state, successor_state,
           boundary_evidence, authority_effect):
    # Admission is decided before the append lock is taken; an inadmissible
    # source receipt never contends for the organization ledger.
    source = verify_source(source_receipt)
    root = ledger_root()
    receipt_dir = root / "receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    head = root / "HEAD.json"
    lock_path = root / ".append.lock"
    # All writers using this emitter serialize the HEAD read, receipt creation,
    # and HEAD publication. No second resident process is required.
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        previous = _validate_existing_head(head, receipt_dir)
        body = {
            "schema": "stegverse.organization-transition-receipt/v1",
            "organization": C["organization"],
            **source,
            "org_transition_class": org_transition_class,
            "predecessor_org_state_sha256": predecessor_state,
            "successor_org_state_sha256": successor_state,
            "boundary_evidence": boundary_evidence,
            "authority_effect": authority_effect,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "previous_receipt_sha256": previous,
        }
        digest = sha(body)
        receipt = {**body, "receipt_sha256": digest}
        receipt_path = receipt_dir / (digest.split(":", 1)[1] + ".json")
        if receipt_path.exists():
            if load(receipt_path) != receipt:
                raise SystemExit("org receipt collision")
            raise SystemExit("ORG_LEDGER_DUPLICATE_RECEIPT_RECOVERY_REQUIRED")
        _atomic_json(receipt_path, receipt)
        _atomic_json(head, {
            "organization": C["organization"],
            "receipt_sha256": digest,
            "receipt_path": str(receipt_path),
        })
        return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-receipt")
    parser.add_argument("--transition-receipt")
    parser.add_argument("--org-transition-class", default=None)
    parser.add_argument("--predecessor-org-state-sha256", required=True)
    parser.add_argument("--successor-org-state-sha256", required=True)
    parser.add_argument("--boundary-evidence-json", default="{}")
    parser.add_argument("--authority-effect", default="NONE")
    args = parser.parse_args()
    source_path = args.transition_receipt or args.repo_receipt
    if not source_path:
        raise SystemExit("transition receipt required")
    receipt = load(source_path)
    default_class = ("REPO_STATE_PROPAGATION"
                     if receipt.get("schema") == "stegverse.repo-transition-receipt/v1"
                     else "ORGANIZATION_STATE_TRANSITION")
    result = append(receipt, args.org_transition_class or default_class,
                    args.predecessor_org_state_sha256, args.successor_org_state_sha256,
                    json.loads(args.boundary_evidence_json), args.authority_effect)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
