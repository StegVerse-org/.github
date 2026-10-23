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

import argparse
import contextlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator, Mapping

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


class BoundSurface:
    """A writer surface over modules the caller already holds, so the preflight resolves exactly
    the stores that caller's own appends will write (intr_destination_ingress passes its own)."""

    def __init__(self, *, emit: Any, aggregate: Any, dual: Any = None):
        self.emit, self.aggregate, self.dual = emit, aggregate, dual
        if dual is not None:
            self.kind = "DUAL_LEDGER"
        elif hasattr(aggregate, "aggregate_transition"):
            self.kind = "AGGREGATE_TRANSITION"
        else:
            self.kind = "TWO_MODULE_APPEND"

    def _repository_store(self) -> Any:
        if hasattr(self.emit, "repository_store"):
            return self.emit.repository_store()
        return self.emit.ledger_store.open_store(self.emit.lr())


def writer_surface(root: Path | str = ROOT) -> Any:
    """merge_transfer_gitstore.WriterSurface: which two-level append this checkout carries."""
    return gitstore.WriterSurface(root)


class TwoLevelAppendRefused(ValueError):
    """Raised before either half is written, or when a rollback could not restore a ref."""

    def __init__(self, refusal: Mapping[str, Any]):
        super().__init__(refusal["failure_code"] + ": " + refusal["required_evidence_or_repair"])
        self.refusal = dict(refusal)


PREFLIGHT_REFUSED = "LEDGER_TWO_LEVEL_PREFLIGHT_REFUSED"
ROLLBACK_FAILED = "LEDGER_TWO_LEVEL_ROLLBACK_FAILED"
MAX_COMMITS_PER_ATTEMPT = 2


def _refusal(code: str, predicate: str, repair: str, next_attempt: str, **extra: Any) -> dict[str, Any]:
    return gitstore.refusal(code, predicate, repair, next_attempt, retry_entrypoint=
                            "resident-runtime/ledger_gitstore.py::append (or the workflow that called it)", **extra)


def _git_out(*args: str) -> str | None:
    done = subprocess.run(["git", *args], capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else None


class _Location:
    """Where one half of the append lands: a git ref in a git dir, or a POSIX root."""

    def __init__(self, level: str, store: Any):
        self.level, self.store = level, store
        self.ref = getattr(store, "ref", None)
        self.namespace = getattr(store, "namespace", None)
        if self.ref is not None:
            if getattr(store, "git_dir", None) is not None:
                place = store.git_dir
            elif callable(getattr(store, "_git_dir", None)):
                place = store._git_dir()
            else:
                place = getattr(store, "repository", None)
            self.git_dir = _git_out("-C", str(place), "rev-parse", "--absolute-git-dir") if place else None
            self.key = ("git", self.git_dir, self.ref)
        else:
            self.root = Path(getattr(store, "root"))
            self.key = ("posix", str(self.root.resolve()))

    def tip(self) -> Any:
        if self.key[0] == "git":
            return _git_out("--git-dir", self.git_dir, "rev-parse", "--verify", "--quiet", self.ref + "^{commit}")
        if not self.root.is_dir():
            return {}
        return {str(p.relative_to(self.root)): p.read_bytes() for p in sorted(self.root.rglob("*")) if p.is_file()}

    def restore(self, before: Any) -> bool:
        now = self.tip()
        if now == before:
            return True
        if self.key[0] == "git":
            # Only this attempt's own commits are undone: the ref must still descend from its prior tip by at
            # most one commit per half (writers share ORGANIZATION_LEDGER_LOCK). Anything else is left as found.
            if now is None:
                return False
            if before is not None:
                span = _git_out("--git-dir", self.git_dir, "rev-list", "--count", "--ancestry-path", before + ".." + now)
                if _git_out("--git-dir", self.git_dir, "merge-base", "--is-ancestor", before, now) is None \
                        or span is None or int(span) > MAX_COMMITS_PER_ATTEMPT:
                    return False
            args = (["update-ref", self.ref, before, now] if before else ["update-ref", "-d", self.ref, now])
            if subprocess.run(["git", "--git-dir", self.git_dir, *args], capture_output=True).returncode != 0:
                return False
        else:
            for name in set(now) - set(before):
                (self.root / name).unlink()
            for name, data in before.items():
                if now.get(name) != data:
                    (self.root / name).write_bytes(data)
        return self.tip() == before


def _organization_store(surface: Any) -> Any:
    aggregate = surface.aggregate
    if callable(getattr(aggregate, "organization_store", None)):
        return aggregate.organization_store()
    # A checkout without organization_store: the location its append opens, open_store(ledger_root()), which is
    # STEGVERSE_ORG_LEDGER_ROOT as parse_locator reads it (no host path is filled in when it is unset).
    supplied = os.environ.get("STEGVERSE_ORG_LEDGER_ROOT")
    if not supplied:
        raise LookupError("ledger_location_required_from_materializer: STEGVERSE_ORG_LEDGER_ROOT")
    return aggregate.open_store(aggregate.parse_locator(supplied))


def _repository_store(surface: Any) -> Any:
    if surface.kind == "DUAL_LEDGER":
        return surface.dual.ledger_store.open_store(surface.dual.emit.lr())
    return surface._repository_store()


def preflight(root: Path | str = ROOT, *, surface: Any = None) -> tuple[_Location, _Location]:
    """Both halves' locations, resolved as the writers will resolve them, checked before any write."""
    root = Path(root)

    def refuse(predicate: str, repair: str, **extra: Any):
        raise TwoLevelAppendRefused(_refusal(
            PREFLIGHT_REFUSED, predicate, repair,
            "repair the ledger location and re-run; neither the repository nor the organization half was written",
            **extra))

    try:
        surface = surface or writer_surface(root)
    except (LookupError, OSError) as exc:
        refuse("THE_CHECKOUT_CARRIES_A_TWO_LEVEL_APPEND", "carry this organization's two-level writer",
               detail=str(exc))
    located = []
    supplied_ref = os.environ.get("STEGVERSE_ORG_LEDGER_GIT_REF")
    for level, resolve in (("repository", _repository_store), ("organization", _organization_store)):
        try:
            located.append(_Location(level, resolve(surface)))
        except (Exception, SystemExit) as exc:  # the writer's own location refusal, raised before it writes
            declared = None
            if level == "organization" and supplied_ref:
                try:
                    declared = gitstore.org_contract(root).get("organization_ledger_ref")
                except (OSError, ValueError):
                    declared = None
            if supplied_ref and declared and supplied_ref != declared:
                # the writer refused the stray materializer ref itself (a locus check); name that ref, as a
                # writer that reads the ref unchecked is named below
                refuse("STEGVERSE_ORG_LEDGER_GIT_REF_IS_THE_BOUND_REF",
                       "STEGVERSE_ORG_LEDGER_GIT_REF names " + supplied_ref + "; the organization contract declares "
                       + declared, level="organization", supplied_ref=supplied_ref,
                       detail=type(exc).__name__ + ": " + str(exc)[:200])
            refuse(level.upper() + "_LEDGER_LOCATION_RESOLVES",
                   "the " + level + " ledger location this writer binds is refused: " + str(exc)[:300],
                   level=level, detail=type(exc).__name__)
    repository_location, organization_location = located
    # A materializer variable naming the organization ledger is non-authoritative: present, it must agree
    # with what the organization half resolves to, whether or not this checkout's writer reads it.
    if supplied_ref and organization_location.key[0] == "git" and supplied_ref != organization_location.ref:
        refuse("STEGVERSE_ORG_LEDGER_GIT_REF_IS_THE_BOUND_REF",
               "STEGVERSE_ORG_LEDGER_GIT_REF names " + supplied_ref + "; the organization half resolves to "
               + str(organization_location.ref), level="organization", supplied_ref=supplied_ref)
    declared_org = gitstore.org_contract(root).get("organization_ledger_ref")
    declared_repo = gitstore.contract(root).get("repository_ledger_location") or {}
    for location, ref, namespace in ((organization_location, declared_org, None),
                                     (repository_location, declared_repo.get("ref"), declared_repo.get("namespace"))):
        if location.key[0] != "git":
            continue
        if not location.git_dir:
            refuse(location.level.upper() + "_LEDGER_GIT_DIR_EXISTS",
                   "the " + location.level + " ledger git dir does not exist", level=location.level)
        if ref and location.ref != ref:
            refuse(location.level.upper() + "_LEDGER_REF_IS_THE_DECLARED_REF",
                   "the " + location.level + " half would land on " + str(location.ref) + "; the contract declares "
                   + ref, level=location.level, bound_ref=location.ref, declared_ref=ref)
        if namespace and location.level == "repository" and location.namespace != namespace:
            refuse("REPOSITORY_LEDGER_NAMESPACE_IS_THE_DECLARED_NAMESPACE",
                   "the repository half would land under " + str(location.namespace) + "; contract.json declares "
                   + namespace, level=location.level)
        current = _git_out("--git-dir", location.git_dir, "rev-parse", "--verify", "--quiet", location.ref)
        if current is not None and location.tip() is None:
            refuse(location.level.upper() + "_LEDGER_REF_NAMES_A_COMMIT",
                   location.ref + " does not name a commit", level=location.level)
    if repository_location.key[0] == organization_location.key[0] == "git" and declared_org \
            and declared_repo.get("ref") == declared_org and repository_location.git_dir != organization_location.git_dir:
        refuse("BOTH_HALVES_SHARE_THE_DECLARED_LEDGER_REF",
               "contract.json keeps the repository chain on the organization ledger ref itself; the halves resolve "
               "to two git dirs: " + str(repository_location.git_dir) + " and " + str(organization_location.git_dir))
    return repository_location, organization_location


@contextlib.contextmanager
def two_level_atomic(root: Path | str = ROOT, *, surface: Any = None) -> Iterator[tuple[_Location, _Location]]:
    """Preflight both halves, then undo every ref the body moved if the body does not complete."""
    locations = preflight(root, surface=surface)
    distinct = {location.key: location for location in locations}
    before = {key: location.tip() for key, location in distinct.items()}
    try:
        yield locations
    except BaseException as exc:
        failed = [key for key, location in distinct.items() if not location.restore(before[key])]
        if failed:
            raise TwoLevelAppendRefused(_refusal(
                ROLLBACK_FAILED, "A_FAILED_TWO_LEVEL_APPEND_LEAVES_BOTH_REFS_AT_THEIR_PRIOR_TIPS",
                "a ref moved by the failed append could not be compare-and-swapped back (another writer moved it); "
                "inspect " + ", ".join(str(key[-1]) for key in failed),
                "restore the listed refs to their prior tips before any further append",
                detail=str(exc)[:300])) from exc
        raise


class _Undo(Exception):
    def __init__(self, result: Mapping[str, Any]):
        super().__init__(result.get("failure_code"))
        self.result = dict(result)


def append_merge_transfer(facts: Mapping[str, Any], *, root: Path | str = ROOT, readers: Any = None,
                          surface: Any = None) -> dict[str, Any]:
    """merge_transfer_gitstore.append_merge_transfer, all or nothing."""
    try:
        surface = surface or writer_surface(root)
    except (LookupError, OSError):
        return gitstore.append_merge_transfer(facts, root=root, readers=readers)  # its own SURFACE_UNBOUND refusal
    try:
        with two_level_atomic(root, surface=surface):
            result = gitstore.append_merge_transfer(facts, root=root, readers=readers, surface=surface)
            if result.get("disposition") != gitstore.ALLOW:
                raise _Undo(result)  # a refusal after the repository half: roll it back
    except _Undo as undo:
        return undo.result
    except TwoLevelAppendRefused as exc:
        return {**exc.refusal, "repository": gitstore.repository(root),
                "merge_commit": facts.get("merge_commit") if isinstance(facts, Mapping) else None}
    return result


def append(transition_class: str, packet_id: str, evidence: Mapping[str, Any], hb_epoch: int | None, *,
           operation: str, profile_id: str, boundary_extra: Mapping[str, Any] | None = None,
           root: Path | str = ROOT, surface: Any = None) -> tuple[dict[str, Any], bool]:
    if not isinstance(operation, str) or not operation or not isinstance(profile_id, str) or not profile_id:
        raise ValueError("operation and profile_id are required")
    if not isinstance(evidence, Mapping) or not isinstance(evidence.get("payload_sha256"), str) \
            or "disposition" not in evidence:
        raise ValueError("evidence carries payload_sha256 and disposition")
    surface = surface or writer_surface(root)
    with two_level_atomic(root, surface=surface):
        return _append_unguarded(transition_class, packet_id, evidence, hb_epoch, operation=operation,
                                 profile_id=profile_id, boundary_extra=boundary_extra, surface=surface)


def _append_unguarded(transition_class: str, packet_id: str, evidence: Mapping[str, Any], hb_epoch: int | None, *,
                      operation: str, profile_id: str, boundary_extra: Mapping[str, Any] | None,
                      surface: Any) -> tuple[dict[str, Any], bool]:
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


def main(argv: list[str] | None = None) -> int:
    """``merge-transfer-append``: merge_transfer_gitstore.py append, all or nothing (same arguments and output)."""
    parser = argparse.ArgumentParser(description=main.__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("merge-transfer-append")
    p.add_argument("--commit", action="append", default=[])
    p.add_argument("--commits-file")
    p.add_argument("--out")
    p.add_argument("--git-dir")
    p.add_argument("--ref")
    p.add_argument("--repo-namespace")
    args = parser.parse_args(argv)
    commits = list(args.commit)
    if args.commits_file:
        commits += Path(args.commits_file).read_text(encoding="utf-8").split()
    if not commits:
        print(json.dumps(gitstore.refusal(gitstore.FACTS_INVALID, "A_PUSH_NAMES_ITS_COMMITS", "name at least one commit",
                                          "re-run with --commit or --commits-file; nothing was done"), indent=2))
        return 1
    results = []
    for commit in commits:
        readers = gitstore.bind_readers(ROOT, git_dir=args.git_dir, ref=args.ref, namespace=args.repo_namespace)
        if isinstance(readers, dict):
            results.append({**readers, "merge_commit": commit})
            continue
        results.append(append_merge_transfer(gitstore.commit_facts(commit), readers=readers))
    text = json.dumps(results, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if all(r["disposition"] == gitstore.ALLOW for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
