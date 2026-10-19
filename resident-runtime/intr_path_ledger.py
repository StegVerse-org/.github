#!/usr/bin/env python3
"""The one ledger binding the InTr path transfer and path ingress use.

resident-runtime/intr_path_transfer.py and resident-runtime/intr_path_ingress.py
need, from this organization's two-level ledger: the bound readers, the chain
walk, the supplied head epoch, the main-merge transfer verdict for a commit, and
an append that names its own operation. Which code provides them is chosen per
organization by data/intr-protocol/v1/protocol.json main_merge_transfer:

  * listed in ``verifiers_by_organization`` (StegVerse-Labs, GCAT-BCAT-Engine):
    the git-store backend: Lane D's resident-runtime/ledger_gitstore.py
    (``pin.ledger_module``) over resident-runtime/merge_transfer_gitstore.py
    (``pin.path``), each loaded only at its pinned sha256: its injected readers
    (org_store / repo_store), verify_merge_transfer in ``pin.mode``, head_epoch,
    org_chain and its operation-parametric append. A checkout without the ledger
    module reads through the verifier and refuses every append FAIL_CLOSED
    INTR_PATH_GITSTORE_WRITER_UNBOUND, writing nothing;
  * every other organization: resident-runtime/merge_transfer.py and
    intr_destination_ingress.py::_append, exactly as before.

No clock, network or credential is read here. Nothing is pushed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "data" / "intr-protocol" / "v1" / "protocol.json"
GOAL = "StegVerse-org/.github#162"
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
WRITER_REFUSED = "LEDGER_WRITER_REFUSED"
MERGE_OPERATION = "ORGANIZATION_MAIN_MERGE_TRANSFER"
DIGEST_UNPINNED = "INTR_PATH_LEDGER_VERIFIER_DIGEST_UNPINNED"
WRITER_UNBOUND = "INTR_PATH_GITSTORE_WRITER_UNBOUND"
READERS_UNBOUND = "INTR_PATH_LEDGER_READERS_UNBOUND"
WRITER_ENTRYPOINT = ("resident-runtime/ledger_gitstore.py append (Lane D, operation-parametric git-store writer; "
                     "StegVerse-org/.github#213, StegVerse-Labs/.github#3293, GCAT-BCAT-Engine/.github#17)")


class Refused(ValueError):
    """A six-field refusal from the binding; the caller reports ``result`` and writes nothing."""

    def __init__(self, result: Mapping[str, Any]):
        super().__init__(str(result.get("failure_code")) + ": " + str(result.get("detail", "")))
        self.result = dict(result)


def refusal(code: str, predicate: str, repair: str, entrypoint: str, next_attempt: str, **extra: Any) -> dict:
    out = {"disposition": "FAIL_CLOSED", "failure_code": code, "failed_predicate": predicate,
           "required_evidence_or_repair": repair, "retry_entrypoint": entrypoint,
           "owning_existing_goal": GOAL, "next_attempt": next_attempt}
    out.update(extra)
    return out


def _load(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_contract(path: Path | str = CONTRACT) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def pin_for(organization: str, contract: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    contract = contract if contract is not None else load_contract()
    pinned = contract["main_merge_transfer"].get("verifiers_by_organization", {}).get(organization)
    return dict(pinned) if isinstance(pinned, Mapping) else None


def _repository_from_contract(root: Path) -> str:
    return json.loads((root / ".stegverse/transition-ledger/contract.json").read_text(encoding="utf-8"))["repository"]


class MergeTransferBinding:
    """resident-runtime/merge_transfer.py + intr_destination_ingress.py::_append (the default; unchanged)."""

    kind = "MERGE_TRANSFER_PY"

    def __init__(self, root: Path | str = ROOT):
        self.root = Path(root)
        self.mt = _load("merge_transfer_for_intr_path_ledger", self.root / "resident-runtime/merge_transfer.py")
        self.ingress = self.mt.ingress
        self.sha = self.ingress.sha
        self.sealed = self.mt.sealed
        self.boundary = self.mt._boundary
        self.verifier = "resident-runtime/merge_transfer.py verify"
        self.mode = "single"

    def repository(self) -> str:
        return self.mt.repository()

    def readers(self) -> tuple[Any, Any]:
        return self.mt.org_store(), self.mt.repo_store()

    def chain(self, organization_reader: Any) -> Iterable[tuple[str, Any]]:
        return self.mt.org_chain(organization_reader)

    def receipt(self, reader: Any, digest: Any) -> Any:
        return self.mt._receipt(reader, digest)

    def receipt_key(self, digest: str) -> str:
        return self.mt.store_module().receipt_key(digest)

    @property
    def head_key(self) -> str:
        return self.mt.store_module().HEAD_KEY

    def head_epoch(self) -> tuple[int | None, dict | None]:
        return self.mt.head_epoch(self.mt.org_store())

    def verify_transfer(self, commit: str) -> dict[str, Any]:
        return self.mt.verify_merge_transfer(self.repository(), commit)

    def append(self, transition_class: str, packet_id: str, evidence: Mapping[str, Any], epoch: int, *,
               operation: str, profile_id: str, boundary_extra: Mapping[str, Any]) -> tuple[dict, bool]:
        return self.ingress._append(transition_class, packet_id, evidence, epoch, operation=operation,
                                    profile_id=profile_id, boundary_extra=boundary_extra)

    def append_merge_transfer(self, commit: str) -> dict[str, Any]:
        return self.mt.append_merge_transfer(self.mt.commit_facts(commit, self.root))


def _digest(path: Path) -> str | None:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


class GitstoreBinding:
    """Lane D's git-store ledger module at its pinned digests.

    ``resident-runtime/ledger_gitstore.py`` (pin.ledger_module) is the public surface: org_store / repo_store
    readers, verify_merge_transfer (in pin.mode), head_epoch, org_chain and the operation-parametric append.
    It loads ``resident-runtime/merge_transfer_gitstore.py`` (pin.path) from the same checkout; both must be the
    pinned bytes. A checkout that carries the verifier but not yet the ledger module reads and verifies through
    the verifier's own readers, and every append is FAIL_CLOSED INTR_PATH_GITSTORE_WRITER_UNBOUND.
    ``module_root`` is the checkout holding resident-runtime/ (default: this checkout)."""

    kind = "MERGE_TRANSFER_GITSTORE"

    def __init__(self, pin: Mapping[str, Any], root: Path | str = ROOT, *, module_root: Path | str | None = None):
        self.root = Path(root)
        self.pin = dict(pin)
        modules = Path(module_root) if module_root is not None else self.root
        verifier_path = modules / self.pin["path"]
        self._require(verifier_path, self.pin["sha256"], self.pin["path"])
        module = self.pin.get("ledger_module") or {}
        ledger_path = modules / module["path"] if module.get("path") else None
        if ledger_path is not None and ledger_path.is_file():
            self._require(ledger_path, module["sha256"], module["path"])
            self.lg = _load("ledger_gitstore_for_intr_path_ledger_" + module["sha256"][7:19], ledger_path)
            self.gs = self.lg.gitstore
            self.writer_module = module["path"]
        else:
            self.lg = None
            self.gs = _load("merge_transfer_gitstore_for_intr_path_ledger_" + self.pin["sha256"][7:19], verifier_path)
            self.writer_module = None
        self.ingress = _load("intr_destination_ingress_for_intr_path_ledger",
                             self.root / "resident-runtime/intr_destination_ingress.py")
        self.sha = self.gs.sha
        self.sealed = self.gs.sealed
        self.boundary = self.gs._boundary
        self.verifier = self.pin["checked_by"]
        self.mode = self.pin["mode"]

    def _require(self, path: Path, want: str, name: str) -> None:
        got = _digest(path)
        if got != want:
            raise Refused(refusal(
                DIGEST_UNPINNED, "PATH_LEDGER_VERIFIER_IS_THE_PINNED_BYTES",
                name + " must exist with sha256 " + want + " (main_merge_transfer.verifiers_by_organization); it is "
                + str(got), "re-pin data/intr-protocol/v1/protocol.json to the landed module, or carry the pinned file",
                "re-run once the file and the pin agree; nothing was read or written", detail=name + " " + str(got)))

    def repository(self) -> str:
        return self.gs.repository(self.root)

    def readers(self) -> tuple[Any, Any]:
        """Constructed on every call: the ref tip resolves once per reader, and moves after an append."""
        if self.lg is not None:
            try:
                return self.lg.org_store(self.root), self.lg.repo_store(self.root)
            except self.lg.LedgerLocationUnbound as exc:
                raise Refused({**exc.refusal, "failure_code": READERS_UNBOUND,
                               "detail": exc.refusal.get("failure_code")}) from None
        bound = self.gs.bind_readers(self.root)
        if isinstance(bound, dict):
            raise Refused({**bound, "failure_code": READERS_UNBOUND, "detail": bound.get("failure_code")})
        return bound

    def chain(self, organization_reader: Any) -> Iterable[tuple[str, Any]]:
        return self.gs.org_chain(organization_reader)

    def receipt(self, reader: Any, digest: Any) -> Any:
        return self.gs._receipt(reader, digest)

    def receipt_key(self, digest: str) -> str:
        return self.gs.receipt_key(digest)

    def source_key(self, digest: str) -> str:
        return self.gs.source_key(digest)

    @property
    def head_key(self) -> str:
        return self.gs.HEAD_KEY

    def head_epoch(self) -> tuple[int | None, dict | None]:
        return self.gs.head_epoch(self.readers()[0])

    def verify_transfer(self, commit: str) -> dict[str, Any]:
        organization, repository = self.readers()
        return self.gs.verify_merge_transfer(self.repository(), commit, organization, repository, mode=self.mode)

    def append(self, transition_class: str, packet_id: str, evidence: Mapping[str, Any], epoch: int, *,
               operation: str, profile_id: str, boundary_extra: Mapping[str, Any]) -> tuple[dict, bool]:
        """ledger_gitstore.append: raises ValueError / SystemExit as intr_destination_ingress._append does."""
        if self.lg is None:
            raise Refused(refusal(
                WRITER_UNBOUND, "THE_GITSTORE_BACKEND_CARRIES_AN_OPERATION_APPEND",
                "this checkout must carry resident-runtime/ledger_gitstore.py at the pinned digest "
                + str((self.pin.get("ledger_module") or {}).get("sha256")) + ": append(transition_class, packet_id, "
                "evidence, hb_epoch, *, operation, profile_id, boundary_extra, root)",
                WRITER_ENTRYPOINT, "re-run once the writer lands in this organization; nothing was written",
                detail=self.pin["path"] + " is carried without resident-runtime/ledger_gitstore.py"))
        appended, replayed = self.lg.append(transition_class, packet_id, dict(evidence), epoch, operation=operation,
                                            profile_id=profile_id, boundary_extra=dict(boundary_extra), root=self.root)
        return appended, bool(replayed)

    def append_merge_transfer(self, commit: str) -> dict[str, Any]:
        return self.gs.append_merge_transfer(self.gs.commit_facts(commit, self.root), root=self.root)


class UnboundBinding:
    """No usable backend (for example a pinned digest that is not the carried file): every ledger call refuses."""

    kind = "UNBOUND"

    def __init__(self, result: Mapping[str, Any], root: Path | str = ROOT):
        self.root = Path(root)
        self.result = dict(result)
        self.ingress = _load("intr_destination_ingress_for_intr_path_ledger",
                             self.root / "resident-runtime/intr_destination_ingress.py")
        self.verifier, self.mode = None, None

    def sha(self, value: Any) -> str:
        return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                                     ensure_ascii=False).encode("utf-8")).hexdigest()

    def sealed(self, receipt: Any) -> bool:
        return (isinstance(receipt, Mapping) and isinstance(receipt.get("receipt_sha256"), str)
                and self.sha({k: v for k, v in receipt.items() if k != "receipt_sha256"}) == receipt["receipt_sha256"])

    def boundary(self, receipt: Mapping[str, Any]) -> Mapping[str, Any]:
        value = receipt.get("boundary_evidence", receipt.get("evidence"))
        return value if isinstance(value, Mapping) else {}

    def repository(self) -> str:
        return _repository_from_contract(self.root)

    def _refuse(self, *args: Any, **kwargs: Any):
        raise Refused(self.result)

    readers = head_epoch = verify_transfer = append = append_merge_transfer = _refuse

    def chain(self, organization_reader: Any):
        raise Refused(self.result)

    def receipt(self, reader: Any, digest: Any):
        raise Refused(self.result)


def bound(root: Path | str = ROOT, **kwargs: Any):
    """binding(), or an UnboundBinding carrying the six-field refusal that prevented it."""
    try:
        return binding(root, **kwargs)
    except Refused as exc:
        return UnboundBinding(exc.result, root)


def binding(root: Path | str = ROOT, *, contract: Mapping[str, Any] | None = None,
            organization: str | None = None, module_root: Path | str | None = None):
    """The binding for this checkout's organization (or ``organization``), selected by its protocol.json pin."""
    root = Path(root)
    contract = contract if contract is not None else load_contract(root / "data/intr-protocol/v1/protocol.json")
    organization = organization or _repository_from_contract(root).split("/")[0]
    pin = pin_for(organization, contract)
    if pin is None:
        return MergeTransferBinding(root)
    return GitstoreBinding(pin, root, module_root=module_root)


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="the InTr path ledger binding of this checkout")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("which", help="the binding protocol.json selects for this organization")
    a = sub.add_parser("append-merge-transfer", help="append one main-merge transfer through the bound backend")
    a.add_argument("--commit", required=True)
    args = parser.parse_args(argv)
    chosen = bound(ROOT)
    if args.command == "which":
        result = {"kind": chosen.kind, "verifier": chosen.verifier, "mode": chosen.mode,
                  **({"refusal": chosen.result} if chosen.kind == "UNBOUND" else {})}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if chosen.kind != "UNBOUND" else 1
    try:
        result = chosen.append_merge_transfer(args.commit)
    except Refused as exc:
        result = exc.result
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("disposition") == "ALLOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
