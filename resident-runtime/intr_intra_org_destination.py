#!/usr/bin/env python3
"""InTr mesh destination inside this organization: StegVerse-org/.github to a
repository of the same organization whose chain is a subtree of this
organization's ledger ref (refs/stegverse/organization-ledger:
repository-ledger/<repository>).

One crossing, three receipted transitions, all appended by the existing org
writer (.github/workflows/intr-path-transfer.yml, after the push's main-merge
transfer is ledgered; no dispatch, no clock, no credential):

  1. registration: the destination repository's chain is opened with its
     genesis receipt (REPOSITORY_LEDGER_INITIALIZATION, previous null) in its
     own subtree, consumed by an organization receipt (operation
     INTR_INTRA_ORG_DESTINATION_REGISTRATION). A registered destination is
     answered from the ledger.
  2. source half: this repository's own INTR_MESH_PATH_TRANSFER receipt pair,
     linking the push's main-merge transfer receipt and the destination's
     registration genesis by seal.
  3. destination half: the destination repository's own INTR_MESH_PATH_INGRESS
     receipt on its chain, after its genesis, carrying both source seals;
     consumed by an organization receipt (ORGANIZATION_INTR_DESTINATION_INGRESS)
     that carries only digests.

Both sides record the crossing on their own chain. Both chains are read back
through the same git-ref store (resident-runtime/ledger_store.py) the
organization already reads its own chain with, so no cross-organization read
credential is involved. ``verify`` is ALLOW (layer 1, VERIFIED) only when all
three transitions read back sealed and linked; absent is FAIL_CLOSED,
contradicted is DENY, six fields each.

Destinations are defined here in code (INTRA_ORG_DESTINATIONS); a transfer row
in .stegverse/intr-path-transfer/intra-org-transfers.json lands on main to run
the crossing. Each destination is added by its own admitted change.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]


def _module(name: str, relative: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mt = _module("merge_transfer_for_intra_org_destination", "resident-runtime/merge_transfer.py")
intr = _module("intr_protocol_for_intra_org_destination", "org-runtime/intr_protocol.py")
ingress = mt.ingress
org_ledger = ingress.organization_ledger
sha = ingress.sha
sealed = mt.sealed

LEDGER_REF = "refs/stegverse/organization-ledger"
CAPABILITY = "intr-destination"
#: Repositories of this organization registered as InTr mesh destinations. Code-defined (LC-KV-20 item 7):
#: each entry is added by its own admitted change. The chain lives at repository-ledger/<repository> of LEDGER_REF.
INTRA_ORG_DESTINATIONS = ("StegVerse-org/LLM-adapter",)
DECLARATION = ROOT / ".stegverse" / "intr-path-transfer" / "intra-org-transfers.json"
DECLARATION_SCHEMA = "stegverse.intr-intra-org-transfer-declaration/v1"
RESULT_SCHEMA = "stegverse.intr-intra-org-destination-result/v1"
REGISTRATION_SCHEMA = "stegverse.intr-intra-org-destination-registration/v1"
SOURCE_EVIDENCE_SCHEMA = "stegverse.intr-path-transfer-evidence/v1"
INGRESS_EVIDENCE_SCHEMA = "stegverse.intr-path-ingress-evidence/v1"
GENESIS_CLASS = "REPOSITORY_LEDGER_INITIALIZATION"
REGISTRATION_OPERATION = "INTR_INTRA_ORG_DESTINATION_REGISTRATION"
SOURCE_OPERATION = "INTR_MESH_PATH_TRANSFER"
INGRESS_CLASS = "INTR_MESH_PATH_INGRESS"
INGRESS_OPERATION = "ORGANIZATION_INTR_DESTINATION_INGRESS"
PROFILE_ID = "intr-intra-org-destination"
GOAL = "StegVerse-org/.github#162"
ENTRYPOINT = (".github/workflows/intr-path-transfer.yml (after Organization Ledger Main Merge Transfer completes "
              "on a push to main), resident-runtime/intr_intra_org_destination.py")
SIX_FIELDS = mt.SIX_FIELDS
ALLOW, DENY, FAIL_CLOSED = "ALLOW", "DENY", "FAIL_CLOSED"

UNDECLARED = "INTR_INTRA_ORG_DESTINATION_UNDECLARED"
NOT_REGISTERED = "INTR_INTRA_ORG_DESTINATION_NOT_REGISTERED"
REGISTRATION_CONTRADICTED = "INTR_INTRA_ORG_DESTINATION_REGISTRATION_CONTRADICTED"
SOURCE_NOT_LEDGERED = "INTR_PATH_RECEIPT_NOT_LEDGERED"
SOURCE_CONTRADICTED = "INTR_PATH_RECEIPT_LINK_UNVERIFIED"
DESTINATION_NOT_LEDGERED = "INTR_PATH_DESTINATION_RECEIPT_NOT_LEDGERED"
DESTINATION_CONTRADICTED = "INTR_PATH_DESTINATION_RECEIPT_LINK_UNVERIFIED"
TRANSFER_NOT_LEDGERED = "INTR_PATH_TRANSFER_COMMIT_NOT_LEDGERED"
WRITER_REFUSED = mt.WRITER_REFUSED


def repository() -> str:
    return mt.repository()


def organization() -> str:
    return repository().split("/")[0]


def refusal(disposition: str, code: str, predicate: str, repair: str, next_attempt: str,
            **extra: Any) -> dict[str, Any]:
    out = {"schema": RESULT_SCHEMA, "disposition": disposition, "failure_code": code, "failed_predicate": predicate,
           "required_evidence_or_repair": repair, "retry_entrypoint": ENTRYPOINT, "owning_existing_goal": GOAL,
           "next_attempt": next_attempt}
    out.update(extra)
    return out


def path_id(destination: str) -> str:
    return repository() + "->" + destination + ":" + CAPABILITY


def namespace(destination: str) -> str:
    return "repository-ledger/" + destination


def location(destination: str) -> str:
    return LEDGER_REF + ":" + namespace(destination)


def declared_paths() -> list[dict[str, Any]]:
    return [{"path_id": path_id(d), "source": repository(), "destination": d, "capability": CAPABILITY,
             "destination_organization": organization(), "destination_location": location(d),
             "destination_address": intr.destination_address(organization(), intr.load_contract())}
            for d in INTRA_ORG_DESTINATIONS if d.startswith(organization() + "/") and d != repository()]


def load_declaration(path: Path | str = DECLARATION) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != DECLARATION_SCHEMA or document.get("source_repository") != repository():
        raise SystemExit("FAIL_CLOSED: INTR_INTRA_ORG_DECLARATION_INVALID " + str(path))
    return list(document["transfers"])


# -- stores ------------------------------------------------------------------

def org_store() -> Any:
    return mt.org_store()


def repo_store() -> Any:
    return mt.repo_store()


def destination_store(destination: str) -> Any:
    """The destination repository's subtree of the organization ledger ref, opened as the org reads its own."""
    store_module = mt.store_module()
    root = os.environ.get("STEGVERSE_ORG_LEDGER_ROOT")
    if not root:
        raise ValueError("ledger_location_required_from_materializer: STEGVERSE_ORG_LEDGER_ROOT")
    if root.startswith(store_module.GIT_SCHEME):
        if ":" in root.rpartition("#")[2]:
            raise ValueError("organization ledger root names a namespace: " + root)
        return store_module.open_store(store_module.parse_locator(root + ":" + namespace(destination)))
    return store_module.open_store(Path(root) / namespace(destination))


def destination_emitter(destination: str) -> Any:
    """emit.py (the repository chain writer), bound to the destination repository's contract subtree."""
    name = "repo_transition_emit_for_" + destination.replace("/", "__").replace(".", "_").replace("-", "_")
    module = _module(name, ".stegverse/transition-ledger/emit.py")
    contract = copy.deepcopy(module.C)
    contract["repository"] = destination
    contract["repository_ledger_location"] = {"repository": repository(), "ref": LEDGER_REF,
                                              "namespace": namespace(destination)}
    module.C = contract
    return module


def _chain(emitter: Any, store: Any) -> list[dict[str, Any]]:
    """The destination chain newest first, every node verified (emit.chain); [] when absent."""
    head = store.get(mt.store_module().HEAD_KEY)
    return list(emitter.chain(store, head)) if head is not None else []


def _org_chain(store: Any) -> list[tuple[str, Any]]:
    return list(mt.org_chain(store))


def _consumer(chain: list[tuple[str, Any]], repo_digest: str, operation: str) -> tuple[str | None, Any]:
    for digest, receipt in chain:
        if isinstance(receipt, Mapping) and receipt.get("repo_receipt_sha256") == repo_digest \
                and mt._boundary(receipt).get("operation") == operation:
            return digest, receipt
    return None, None


# -- evidence ----------------------------------------------------------------

def _sealed_core(core: Mapping[str, Any], **outer: Any) -> dict[str, Any]:
    return {**core, "payload_sha256": sha(core), **outer}


def _payload_ok(evidence: Mapping[str, Any], outer: tuple[str, ...]) -> bool:
    return evidence.get("payload_sha256") == sha({k: v for k, v in evidence.items()
                                                  if k not in ("payload_sha256",) + outer})


def registration_evidence(path: Mapping[str, Any], transfer_commit: str, merge_receipt: str) -> dict[str, Any]:
    core = {"schema": REGISTRATION_SCHEMA, "repository": path["destination"], "organization": organization(),
            "registered_by": repository(), "capability": CAPABILITY, "ledger_location": path["destination_location"],
            "destination_address": path["destination_address"], "endpoint_kind": "ORG",
            "transfer_commit": transfer_commit, "merge_transfer_organization_receipt_sha256": merge_receipt}
    return _sealed_core(core, disposition=ALLOW)


def message(path: Mapping[str, Any], communication_id: str, transfer_commit: str) -> dict[str, Any]:
    payload_schema = next(p["equals"] for p in intr.load_contract()["destination_capability"]["binding_predicates"]
                          if p["id"] == "BINDING_PAYLOAD_SCHEMA")
    return {"message_class": "ecosystem.communication", "communication_id": communication_id,
            "body": {"schema": payload_schema, "path_id": path["path_id"], "transfer_commit": transfer_commit}}


def source_evidence(path: Mapping[str, Any], communication_id: str, transfer_commit: str, merge_receipt: str,
                    registration: str) -> dict[str, Any]:
    msg = message(path, communication_id, transfer_commit)
    core = {"schema": SOURCE_EVIDENCE_SCHEMA, "repository": repository(), "path_id": path["path_id"],
            "source_organization": organization(), "destination_organization": organization(),
            "destination_repository": path["destination"], "destination_location": path["destination_location"],
            "capability": CAPABILITY, "destination_address": path["destination_address"], "message": msg,
            "message_sha256": sha(msg), "transfer_commit": transfer_commit,
            "merge_transfer_organization_receipt_sha256": merge_receipt,
            "destination_registration_receipt_sha256": registration}
    return _sealed_core(core, disposition=ALLOW, communication_id=communication_id)


def ingress_evidence(path: Mapping[str, Any], communication_id: str, source: Mapping[str, Any],
                     registration: str) -> dict[str, Any]:
    core = {"schema": INGRESS_EVIDENCE_SCHEMA, "repository": path["destination"], "path_id": path["path_id"],
            "source_repository": repository(), "destination_location": path["destination_location"],
            "message_sha256": source["message_sha256"],
            "source_organization_receipt_sha256": source["organization_receipt_sha256"],
            "source_repository_receipt_sha256": source["repository_receipt_sha256"],
            "destination_registration_receipt_sha256": registration}
    return _sealed_core(core, disposition=ALLOW, communication_id=communication_id)


def _ids(path: Mapping[str, Any], communication_id: str) -> dict[str, str]:
    return {"registration": GENESIS_CLASS + ":" + path["destination"],
            "source": SOURCE_OPERATION + ":" + path["path_id"] + "@" + communication_id,
            "ingress": INGRESS_CLASS + ":" + path["path_id"] + "@" + communication_id}


# -- verification (read-only) ------------------------------------------------

def verify_registration(path: Mapping[str, Any], organization_store: Any = None,
                        store: Any = None) -> dict[str, Any]:
    organization_store = organization_store if organization_store is not None else org_store()
    store = store if store is not None else destination_store(path["destination"])
    emitter = destination_emitter(path["destination"])
    base = {"path_id": path["path_id"], "half": "registration", "destination": path["destination"]}
    try:
        chain = _chain(emitter, store)
    except ValueError as exc:
        return refusal(DENY, REGISTRATION_CONTRADICTED, "DESTINATION_CHAIN_READS_BACK_INTACT", str(exc),
                       "restore the addressed receipt byte for byte; nothing was verified", **base)
    if not chain:
        return refusal(FAIL_CLOSED, NOT_REGISTERED, "DESTINATION_REPOSITORY_CHAIN_HAS_A_RECEIPTED_GENESIS",
                       "a sealed " + GENESIS_CLASS + " receipt at " + path["destination_location"]
                       + ", consumed by an organization receipt with operation " + REGISTRATION_OPERATION,
                       "it is appended when a row of " + str(DECLARATION.relative_to(ROOT)) + " lands on main and "
                       + ENTRYPOINT + " runs", **base)
    genesis = chain[-1]
    ev = genesis.get("evidence") if isinstance(genesis.get("evidence"), Mapping) else {}
    problems = []
    if genesis.get("previous_receipt_sha256") is not None or genesis.get("transition_class") != GENESIS_CLASS \
            or genesis.get("transition_id") != _ids(path, "")["registration"]:
        problems.append("first receipt is not the " + GENESIS_CLASS + " genesis for " + path["destination"])
    if genesis.get("repository") != path["destination"] or any(r.get("repository") != path["destination"]
                                                                for r in chain):
        problems.append("the chain carries a receipt of another repository")
    for field, want in (("schema", REGISTRATION_SCHEMA), ("repository", path["destination"]),
                        ("ledger_location", path["destination_location"]), ("capability", CAPABILITY),
                        ("registered_by", repository())):
        if ev.get(field) != want:
            problems.append("registration evidence " + field + " is " + repr(ev.get(field)))
    if not _payload_ok(ev, ("disposition",)):
        problems.append("registration evidence does not carry the digest it claims")
    if problems:
        return refusal(DENY, REGISTRATION_CONTRADICTED, "DESTINATION_GENESIS_IS_ITS_REGISTRATION", "; ".join(problems),
                       "inspect " + path["destination_location"] + "; nothing was verified", **base,
                       detail="; ".join(problems))
    org_digest, org_receipt = _consumer(_org_chain(organization_store), genesis["receipt_sha256"],
                                        REGISTRATION_OPERATION)
    if org_receipt is None or not sealed(org_receipt) or org_receipt.get("source_repository") != path["destination"]:
        return refusal(FAIL_CLOSED, NOT_REGISTERED, "DESTINATION_GENESIS_IS_CONSUMED_BY_THE_ORGANIZATION",
                       "a sealed organization receipt (operation " + REGISTRATION_OPERATION + ") consuming genesis "
                       + genesis["receipt_sha256"], "re-run the writer; a registered destination is answered from "
                       "the ledger", **base)
    return {"schema": RESULT_SCHEMA, "disposition": ALLOW, **base,
            "repository_receipt_sha256": genesis["receipt_sha256"], "organization_receipt_sha256": org_digest}


def verify_source(path: Mapping[str, Any], communication_id: str, registration: str | None,
                  organization_store: Any = None, repository_store: Any = None) -> dict[str, Any]:
    organization_store = organization_store if organization_store is not None else org_store()
    repository_store = repository_store if repository_store is not None else repo_store()
    base = {"path_id": path["path_id"], "communication_id": communication_id, "half": "source"}
    chain = _org_chain(organization_store)
    by_digest = dict(chain)
    for digest, receipt in chain:
        b = mt._boundary(receipt) if isinstance(receipt, Mapping) else {}
        if b.get("operation") != SOURCE_OPERATION or b.get("path_id") != path["path_id"] \
                or b.get("communication_id") != communication_id:
            continue
        linked = receipt.get("repo_receipt_sha256")
        rep = mt._receipt(repository_store, linked)
        if not sealed(receipt) or receipt["receipt_sha256"] != digest or not sealed(rep):
            return refusal(FAIL_CLOSED, SOURCE_NOT_LEDGERED, "PATH_HAS_A_SOURCE_LEDGER_RECEIPT",
                           "sealed organization and repository path receipts", "re-run the writer", **base)
        ev = rep.get("evidence") if isinstance(rep.get("evidence"), Mapping) else {}
        problems = []
        if rep["receipt_sha256"] != linked or rep.get("repository") != repository():
            problems.append("repository receipt " + str(linked) + " is not this repository's")
        for field, want in (("schema", SOURCE_EVIDENCE_SCHEMA), ("path_id", path["path_id"]),
                            ("destination_repository", path["destination"]),
                            ("destination_location", path["destination_location"]),
                            ("destination_address", path["destination_address"]),
                            ("communication_id", communication_id),
                            ("destination_registration_receipt_sha256", registration)):
            if ev.get(field) != want:
                problems.append("evidence " + field + " is " + repr(ev.get(field)))
        if not _payload_ok(ev, ("disposition", "communication_id")):
            problems.append("evidence does not carry the digest it claims")
        msg = ev.get("message")
        if sha(msg) != ev.get("message_sha256") or intr.conform_message(msg, organization())["disposition"] != ALLOW:
            problems.append("message does not match its digest or does not conform to the InTr protocol")
        transfer = by_digest.get(ev.get("merge_transfer_organization_receipt_sha256"))
        tb = mt._boundary(transfer) if isinstance(transfer, Mapping) else {}
        if not sealed(transfer) or tb.get("operation") != mt.OPERATION or tb.get("merge_commit") != ev.get(
                "transfer_commit") or tb.get("repository") != repository():
            problems.append("merge-transfer link is not a sealed main-merge transfer receipt for "
                            + str(ev.get("transfer_commit")))
        if problems:
            return refusal(DENY, SOURCE_CONTRADICTED, "PATH_RECEIPT_LINKS_TO_THE_TRANSFER_AND_THE_REGISTRATION",
                           "; ".join(problems), "inspect organization receipt " + digest + "; nothing was verified",
                           **base, detail="; ".join(problems))
        return {"schema": RESULT_SCHEMA, "disposition": ALLOW, **base, "organization_receipt_sha256": digest,
                "repository_receipt_sha256": linked, "message_sha256": ev["message_sha256"],
                "transfer_commit": ev["transfer_commit"],
                "merge_transfer_organization_receipt_sha256": ev["merge_transfer_organization_receipt_sha256"]}
    return refusal(FAIL_CLOSED, SOURCE_NOT_LEDGERED, "PATH_HAS_A_SOURCE_LEDGER_RECEIPT",
                   "a sealed " + SOURCE_OPERATION + " receipt pair for " + path["path_id"] + " / " + communication_id,
                   "it is appended when the transfer row lands on main and " + ENTRYPOINT + " runs", **base)


def verify_destination(path: Mapping[str, Any], communication_id: str, source: Mapping[str, Any],
                       registration: str, organization_store: Any = None, store: Any = None) -> dict[str, Any]:
    organization_store = organization_store if organization_store is not None else org_store()
    store = store if store is not None else destination_store(path["destination"])
    emitter = destination_emitter(path["destination"])
    base = {"path_id": path["path_id"], "communication_id": communication_id, "half": "destination"}
    want_id = _ids(path, communication_id)["ingress"]
    try:
        chain = _chain(emitter, store)
    except ValueError as exc:
        return refusal(DENY, DESTINATION_CONTRADICTED, "DESTINATION_CHAIN_READS_BACK_INTACT", str(exc),
                       "restore the addressed receipt byte for byte; nothing was verified", **base)
    found = [r for r in chain if r.get("transition_id") == want_id and r.get("transition_class") == INGRESS_CLASS]
    if not found:
        return refusal(FAIL_CLOSED, DESTINATION_NOT_LEDGERED, "PATH_HAS_A_DESTINATION_LEDGER_RECEIPT",
                       "a sealed " + INGRESS_CLASS + " receipt on " + path["destination_location"] + " for this path",
                       "it is appended by the same writer run right after the source half", **base)
    rep = found[0]
    ev = rep.get("evidence") if isinstance(rep.get("evidence"), Mapping) else {}
    problems = []
    if chain[-1].get("receipt_sha256") != registration:
        problems.append("the ingress receipt's chain does not start at the registration genesis " + str(registration))
    for field, want in (("schema", INGRESS_EVIDENCE_SCHEMA), ("repository", path["destination"]),
                        ("path_id", path["path_id"]), ("communication_id", communication_id),
                        ("source_repository", repository()),
                        ("source_organization_receipt_sha256", source["organization_receipt_sha256"]),
                        ("source_repository_receipt_sha256", source["repository_receipt_sha256"]),
                        ("message_sha256", source["message_sha256"]),
                        ("destination_registration_receipt_sha256", registration)):
        if ev.get(field) != want:
            problems.append("ingress evidence " + field + " is " + repr(ev.get(field)))
    if not _payload_ok(ev, ("disposition", "communication_id")):
        problems.append("ingress evidence does not carry the digest it claims")
    org_chain = _org_chain(organization_store)
    org_digest, org_receipt = _consumer(org_chain, rep["receipt_sha256"], INGRESS_OPERATION)
    if org_receipt is None:
        return refusal(FAIL_CLOSED, DESTINATION_NOT_LEDGERED, "DESTINATION_RECEIPT_IS_CONSUMED_BY_THE_ORGANIZATION",
                       "a sealed organization receipt (operation " + INGRESS_OPERATION + ") consuming "
                       + rep["receipt_sha256"], "re-run the writer; a ledgered crossing is answered from the ledger",
                       **base)
    b = mt._boundary(org_receipt)
    if not sealed(org_receipt) or b.get("source_organization_receipt_sha256") != source["organization_receipt_sha256"] \
            or b.get("source_repository_receipt_sha256") != source["repository_receipt_sha256"] \
            or org_receipt.get("source_repository") != path["destination"]:
        problems.append("organization ingress receipt " + str(org_digest) + " does not carry the source seals")
    order = [d for d, _ in org_chain]
    if source["organization_receipt_sha256"] in order and order.index(org_digest) > order.index(
            source["organization_receipt_sha256"]):
        problems.append("organization ingress receipt precedes the source receipt on the chain")
    if problems:
        return refusal(DENY, DESTINATION_CONTRADICTED, "DESTINATION_RECEIPT_LINKS_THE_SOURCE_SEALS",
                       "; ".join(problems), "inspect " + path["destination_location"] + "; nothing was verified",
                       **base, detail="; ".join(problems))
    return {"schema": RESULT_SCHEMA, "disposition": ALLOW, **base, "repository_receipt_sha256": rep["receipt_sha256"],
            "organization_receipt_sha256": org_digest}


def verify_path(path: Mapping[str, Any], communication_id: str | None) -> dict[str, Any]:
    """Layer-1 ALLOW only when registration, source and destination all read back sealed and linked."""
    if communication_id is None:
        return {**refusal(FAIL_CLOSED, UNDECLARED, "PATH_HAS_A_DECLARED_TRANSFER",
                          "a row for " + path["path_id"] + " in " + str(DECLARATION.relative_to(ROOT)),
                          "land the row on main", path_id=path["path_id"]),
                "halves": {"registration": FAIL_CLOSED, "source": FAIL_CLOSED, "destination": FAIL_CLOSED}}
    reg = verify_registration(path)
    registration = reg.get("repository_receipt_sha256") if reg["disposition"] == ALLOW else None
    src = verify_source(path, communication_id, registration)
    dst = (verify_destination(path, communication_id, src, registration) if ALLOW == reg["disposition"]
           == src["disposition"] else refusal(FAIL_CLOSED, DESTINATION_NOT_LEDGERED,
                                              "PATH_HAS_A_DESTINATION_LEDGER_RECEIPT",
                                              "registration and source halves first", "re-run after they verify",
                                              path_id=path["path_id"], half="destination"))
    halves = {"registration": reg["disposition"], "source": src["disposition"], "destination": dst["disposition"]}
    if set(halves.values()) == {ALLOW}:
        core = {"schema": RESULT_SCHEMA, "disposition": ALLOW, "layer": 1, "path": "VERIFIED",
                "path_id": path["path_id"], "communication_id": communication_id, "ledger_ref": LEDGER_REF,
                "destination_location": path["destination_location"], "halves": halves,
                "registration": reg, "source": src, "destination": dst}
        return {**core, "result_sha256": sha(core)}
    first = next(h for h in (reg, src, dst) if h["disposition"] != ALLOW)
    return {**first, "path": "UNVERIFIED", "halves": halves, "path_id": path["path_id"]}


def real_state() -> dict[str, Any]:
    rows = {r.get("path_id"): r.get("communication_id") for r in load_declaration()}
    results = [verify_path(p, rows.get(p["path_id"])) for p in declared_paths()]
    return {"schema": "stegverse.intr-intra-org-destination-real-state/v1", "repository": repository(),
            "counts": {d: sum(r["disposition"] == d for r in results) for d in (ALLOW, DENY, FAIL_CLOSED)},
            "paths": results}


# -- append (the writer) -----------------------------------------------------

def _append_repo(emitter: Any, store: Any, transition_id: str, transition_class: str, evidence: Mapping[str, Any],
                 epoch: int) -> dict[str, Any]:
    predecessor = evidence["payload_sha256"]
    successor = sha({"transition_id": transition_id, "payload_sha256": evidence["payload_sha256"],
                     "disposition": evidence["disposition"]})
    return emitter.append(transition_id, transition_class, predecessor, successor, dict(evidence), "NONE",
                          hb_epoch=epoch, store=store, idempotent_on=("payload_sha256", "disposition"))


def _append_org(repo_receipt: Mapping[str, Any], boundary: Mapping[str, Any], epoch: int) -> dict[str, Any]:
    ev = repo_receipt["evidence"]
    return org_ledger.append(dict(repo_receipt), "REPO_STATE_PROPAGATION", ev["payload_sha256"],
                             repo_receipt["successor_state_sha256"], dict(boundary), "NONE", hb_epoch=epoch,
                             idempotent=True)


def append_row(row: Mapping[str, Any], transfer_commit: str, verified: Mapping[str, Any],
               epoch: int) -> dict[str, Any]:
    pid, cid = row.get("path_id"), row.get("communication_id")
    paths = {p["path_id"]: p for p in declared_paths()}
    path = paths.get(pid)
    if path is None or not isinstance(cid, str) or not cid:
        return refusal(FAIL_CLOSED, UNDECLARED, "TRANSFER_NAMES_A_DECLARED_INTRA_ORG_DESTINATION",
                       "declare the destination in INTRA_ORG_DESTINATIONS by its own admitted change; declared: "
                       + ", ".join(sorted(paths)), "correct the row; nothing was written", path_id=pid,
                       communication_id=cid)
    existing = verify_path(path, cid)
    if existing["disposition"] == ALLOW:
        return {**existing, "replayed": True}
    if existing["disposition"] == DENY:
        return existing
    merge_receipt = verified["organization_receipt_sha256"]
    store = destination_store(path["destination"])
    emitter = destination_emitter(path["destination"])
    ids = _ids(path, cid)
    try:
        reg = verify_registration(path)
        if reg["disposition"] == DENY:
            return reg
        if reg["disposition"] != ALLOW:
            chain = _chain(emitter, store)
            genesis = chain[-1] if chain else _append_repo(emitter, store, ids["registration"], GENESIS_CLASS,
                                                           registration_evidence(path, transfer_commit, merge_receipt),
                                                           epoch)
            _append_org(genesis, {"operation": REGISTRATION_OPERATION, "profile_id": PROFILE_ID, "disposition": ALLOW,
                                  "communication_id": None, "repository": path["destination"],
                                  "destination_location": path["destination_location"]}, epoch)
            reg = verify_registration(path)
            if reg["disposition"] != ALLOW:
                return reg
        registration = reg["repository_receipt_sha256"]
        src = verify_source(path, cid, registration)
        if src["disposition"] == DENY:
            return src
        if src["disposition"] != ALLOW:
            evidence = source_evidence(path, cid, transfer_commit, merge_receipt, registration)
            ingress._append(SOURCE_OPERATION, pid + "@" + cid, evidence, epoch, operation=SOURCE_OPERATION,
                            profile_id=PROFILE_ID,
                            boundary_extra={"path_id": pid, "repository": repository(),
                                            "destination_repository": path["destination"],
                                            "destination_registration_receipt_sha256": registration,
                                            "transfer_commit": transfer_commit})
            src = verify_source(path, cid, registration)
            if src["disposition"] != ALLOW:
                return src
        dst = verify_destination(path, cid, src, registration)
        if dst["disposition"] == DENY:
            return dst
        if dst["disposition"] != ALLOW:
            chain = _chain(emitter, store)
            found = [r for r in chain if r.get("transition_id") == ids["ingress"]]
            receipt = found[0] if found else _append_repo(emitter, store, ids["ingress"], INGRESS_CLASS,
                                                          ingress_evidence(path, cid, src, registration), epoch)
            _append_org(receipt, {"operation": INGRESS_OPERATION, "profile_id": PROFILE_ID, "disposition": ALLOW,
                                  "communication_id": cid, "path_id": pid, "repository": path["destination"],
                                  "source_organization_receipt_sha256": src["organization_receipt_sha256"],
                                  "source_repository_receipt_sha256": src["repository_receipt_sha256"]}, epoch)
    except (ValueError, SystemExit) as exc:
        return refusal(FAIL_CLOSED, WRITER_REFUSED, "LEDGER_WRITER_ADMITS_THE_APPEND",
                       "repair what the ledger writer refused: " + str(exc), "re-run once repaired", path_id=pid,
                       communication_id=cid)
    result = verify_path(path, cid)
    return {**result, "replayed": False, "hb_epoch": epoch, "transfer_commit": transfer_commit}


def append_transfers(transfer_commit: str) -> list[dict[str, Any]]:
    rows = load_declaration()
    if not rows:
        return []
    verified = mt.verify_merge_transfer(repository(), transfer_commit)
    if verified["disposition"] != ALLOW:
        return [refusal(FAIL_CLOSED, TRANSFER_NOT_LEDGERED, "PATH_TRANSFER_RIDES_A_LEDGERED_MAIN_MERGE",
                        "the transfer commit " + transfer_commit + " must have a VERIFIED main-merge transfer receipt ("
                        + str(verified.get("failure_code")) + ")", "re-run after the push's main-merge transfer is "
                        "ledgered; nothing was written", transfer_commit=transfer_commit)]
    epoch, failed = mt.head_epoch(org_store())
    if failed is not None:
        return [{**failed, "schema": RESULT_SCHEMA, "transfer_commit": transfer_commit}]
    return [append_row(row, transfer_commit, verified, epoch) for row in rows]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("paths")
    a = sub.add_parser("append")
    a.add_argument("--transfer-commit", required=True)
    a.add_argument("--out")
    v = sub.add_parser("verify")
    v.add_argument("--out")
    args = parser.parse_args(argv)
    if args.command == "paths":
        print(json.dumps(declared_paths(), indent=2))
        return 0
    result: Any = append_transfers(args.transfer_commit) if args.command == "append" else real_state()
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    rows = result if args.command == "append" else result["paths"]
    return 0 if all(r["disposition"] == ALLOW for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
