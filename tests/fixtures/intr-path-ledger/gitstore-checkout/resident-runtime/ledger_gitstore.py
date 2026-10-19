#!/usr/bin/env python3
"""Operation-parametric two-level append and public ledger readers over the git ledger store.

The public surface a caller binds instead of merge_transfer.py internals
(``mt.org_store()``, ``mt.repo_store()``, ``mt.ingress._append``):

  org_store(root=ROOT, *, git_dir=None, ref=None) -> reader
  repo_store(root=ROOT, *, git_dir=None, ref=None, namespace=None) -> reader
      Readers of the organization ledger and of the repository chain, as
      merge_transfer_gitstore binds them (STEGVERSE_ORG_LEDGER_ROOT /
      STEGVERSE_ORG_LEDGER_GIT_DIR / STEGVERSE_REPO_LEDGER_ROOT, or the
      arguments). Each has ``get(key)`` over HEAD.json / receipts/<hex>.json /
      source-receipts/<hex>.json, so merge_transfer_gitstore.verify_merge_transfer,
      org_chain and head_epoch accept them. An unbound location raises
      LedgerLocationUnbound (a ValueError carrying the six-field ``refusal``).

  append(transition_class, packet_id, evidence, hb_epoch, *, operation, profile_id,
         boundary_extra=None, root=ROOT) -> (appended, replayed)
      One repository receipt (transition_id = transition_class + ":" + packet_id,
      evidence as given; idempotent on communication_id, payload_sha256 and
      disposition) and one organization receipt (REPO_STATE_PROPAGATION,
      boundary_evidence {operation, profile_id, disposition, communication_id,
      **boundary_extra}) through this checkout's own writer surface:
      dual_ledger.py (GCAT), aggregate_transition (Labs) or the two-module append.
      ``evidence`` must carry payload_sha256 and disposition. The org receipt takes
      the repository receipt's epoch. Returns
      ({"repository_receipt": <sealed>, "organization_receipt": <sealed>,
        "repository_receipt_sha256": ..., "organization_receipt_sha256": ...,
        "writer_surface": ...}, replayed: bool).
      Raises ValueError("ledger_receipt_collision") for a different body under a
      recorded transition id, ValueError for any other writer refusal (nothing
      half-verified is returned), and SystemExit as the writers do; the same
      contract as StegVerse-org intr_destination_ingress._append.

  head_epoch(reader) / verify_merge_transfer(...) / org_chain(reader) / sealed(receipt)
      re-exported from merge_transfer_gitstore unchanged.

The receipt bodies are those intr_destination_ingress._append writes for the
same arguments; merge_transfer_gitstore's own main-merge append is the case
operation=ORGANIZATION_MAIN_MERGE_TRANSFER.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gitstore = _load("merge_transfer_gitstore_for_ledger_gitstore", ROOT / "resident-runtime/merge_transfer_gitstore.py")

sha = gitstore.sha
sealed = gitstore.sealed
head_epoch = gitstore.head_epoch
org_chain = gitstore.org_chain
verify_merge_transfer = gitstore.verify_merge_transfer
receipt_key, source_key = gitstore.receipt_key, gitstore.source_key
SIX_FIELDS = gitstore.SIX_FIELDS
IDEMPOTENT_ON = ("communication_id", "payload_sha256", "disposition")
ORG_TRANSITION_CLASS = "REPO_STATE_PROPAGATION"


class LedgerLocationUnbound(ValueError):
    def __init__(self, refusal: Mapping[str, Any]):
        super().__init__(refusal["failure_code"] + ": " + refusal["required_evidence_or_repair"])
        self.refusal = dict(refusal)


def readers(root: Path | str = ROOT, *, git_dir: str | None = None, ref: str | None = None,
            namespace: str | None = None) -> tuple[Any, Any]:
    bound = gitstore.bind_readers(root, git_dir=git_dir, ref=ref, namespace=namespace)
    if isinstance(bound, dict):
        raise LedgerLocationUnbound(bound)
    return bound


def org_store(root: Path | str = ROOT, *, git_dir: str | None = None, ref: str | None = None) -> Any:
    return readers(root, git_dir=git_dir, ref=ref)[0]


def repo_store(root: Path | str = ROOT, *, git_dir: str | None = None, ref: str | None = None,
               namespace: str | None = None) -> Any:
    return readers(root, git_dir=git_dir, ref=ref, namespace=namespace)[1]


def writer_surface(root: Path | str = ROOT) -> Any:
    """merge_transfer_gitstore.WriterSurface: which two-level append this checkout carries."""
    return gitstore.WriterSurface(root)


def append(transition_class: str, packet_id: str, evidence: Mapping[str, Any], hb_epoch: int | None, *,
           operation: str, profile_id: str, boundary_extra: Mapping[str, Any] | None = None,
           root: Path | str = ROOT, surface: Any = None) -> tuple[dict[str, Any], bool]:
    if not isinstance(operation, str) or not operation or not isinstance(profile_id, str) or not profile_id:
        raise ValueError("operation and profile_id are required")
    if not isinstance(evidence, Mapping) or not isinstance(evidence.get("payload_sha256"), str) \
            or "disposition" not in evidence:
        raise ValueError("evidence carries payload_sha256 and disposition")
    surface = surface or writer_surface(root)
    predecessor = evidence["payload_sha256"]
    successor = sha({"disposition": evidence["disposition"], "packet_id": packet_id,
                     "communication_id": evidence.get("communication_id"),
                     "payload_sha256": evidence["payload_sha256"]})
    transition_id = transition_class + ":" + packet_id
    if surface.kind == "DUAL_LEDGER":
        prior = surface.dual.find_repository(transition_id)
        repository_receipt = surface.dual.append_repository(
            transition_id, transition_class, predecessor, successor, dict(evidence), "NONE",
            hb_epoch=hb_epoch, idempotent_on=IDEMPOTENT_ON)
    else:
        store = surface._repository_store()
        try:
            head = store.get(surface.emit.ledger_store.HEAD_KEY)
        except FileNotFoundError:
            head = None
        prior = surface.emit.recorded(store, head, transition_id, transition_class)
        repository_receipt = surface.emit.append(
            transition_id, transition_class, predecessor, successor, dict(evidence), "NONE",
            hb_epoch=hb_epoch, idempotent_on=IDEMPOTENT_ON)
    epoch = repository_receipt["hb_reference"]["epoch"]
    boundary = {"operation": operation, "profile_id": profile_id, "disposition": evidence["disposition"],
                "communication_id": evidence.get("communication_id"), **dict(boundary_extra or {})}
    if surface.kind == "DUAL_LEDGER":
        organization_receipt = surface.dual.append_organization(
            repository_receipt, ORG_TRANSITION_CLASS, predecessor, successor, boundary, "NONE",
            hb_epoch=epoch, idempotent=True)
    elif surface.kind == "AGGREGATE_TRANSITION":
        organization_receipt = surface.aggregate.aggregate_transition(
            receipt=repository_receipt, org_transition_class=ORG_TRANSITION_CLASS,
            predecessor_org_state_sha256=predecessor, successor_org_state_sha256=successor,
            boundary_evidence=boundary, authority_effect="NONE", hb_epoch=epoch)
    else:
        organization_receipt = surface.aggregate.append(
            repository_receipt, ORG_TRANSITION_CLASS, predecessor, successor, boundary, "NONE",
            hb_epoch=epoch, idempotent=True)
    if not sealed(repository_receipt) or not sealed(organization_receipt) \
            or organization_receipt.get("repo_receipt_sha256") != repository_receipt.get("receipt_sha256"):
        raise ValueError("ledger_writer_returned_no_sealed_pair")
    return ({"repository_receipt": repository_receipt, "organization_receipt": organization_receipt,
             "repository_receipt_sha256": repository_receipt["receipt_sha256"],
             "organization_receipt_sha256": organization_receipt["receipt_sha256"],
             "writer_surface": surface.kind}, prior is not None)
