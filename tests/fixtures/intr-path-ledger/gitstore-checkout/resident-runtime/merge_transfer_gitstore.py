#!/usr/bin/env python3
"""Main-merge transfer over the git store: one verifier and writer for every ledger surface.

resident-runtime/merge_transfer.py (sha256 032ed727..., pinned in
data/intr-protocol/v1/protocol.json) reaches the ledger through the
destination ingress module: ``ingress.repository_ledger`` /
``ingress.organization_ledger``, their ``lr()`` / ``ledger_root()`` roots and
``ledger_store.open_store``, and appends through ``ingress._append(...,
operation=, profile_id=, boundary_extra=)``. Two organizations hold the same
ledger layout behind other writer surfaces, so that file fails there before it
reads a receipt (MERGE_TRANSFER_VERIFIER_STORE_INCOMPATIBLE):

  * StegVerse-Labs declares its organization ledger as {store: git}
    (org-contract.json organization_ledger) behind ``organization_store()`` and
    ``aggregate_transition``; ``ledger_root()`` refuses a git locus
    (LedgerStoreKindMismatch: declared git).
  * GCAT-BCAT-Engine appends through resident-runtime/dual_ledger.py; its
    ingress exposes ``ledger`` only, with no ``repository_ledger``.

Both keep the layout every organization ledger ref carries:
``HEAD.json``, ``receipts/<hex>.json`` and ``source-receipts/<hex>.json`` at
the ref root, and the repository chain under ``repository-ledger/<repo>/``.

This module reads that layout from the git object store at one resolved
commit of the ledger ref (``git cat-file``; no working tree, no store module,
no writer import), so the verdict does not depend on how a writer surface is
loaded. The verdict and its codes are merge_transfer.py's:

  ALLOW / VERIFIED: a sealed organization receipt whose boundary_evidence names
    ORGANIZATION_MAIN_MERGE_TRANSFER, the repository and the merge commit, and
    whose repo_receipt_sha256 is the seal of a sealed repository receipt whose
    evidence carries the same merge, repository, ref and payload digest.
  FAIL_CLOSED MERGE_TRANSFER_RECEIPT_NOT_LEDGERED: absent or unsealed evidence.
  DENY MERGE_TRANSFER_RECEIPT_LINK_UNVERIFIED: present, sealed, contradicting.

Dual mode (the default) reads both ledgers the two-level append writes: the
repository receipt in the repository chain and the copy the organization
receipt retained under ``source-receipts/``. They must be the same receipt;
otherwise FAIL_CLOSED MERGE_TRANSFER_DUAL_LEDGER_DIVERGENCE, since neither copy
can be preferred. ``--mode single`` is merge_transfer.py's verdict exactly
(the parity tests hold both modes to it on the same receipts).

The append binds the writer surface the checkout carries (dual_ledger.py,
``aggregate_transition`` or the two-module ``append``) and writes the same
receipt bodies merge_transfer.py writes. The epoch is the supplied epoch on the
organization ledger head (hb_reference.epoch, an int >= 32 with
derived_from_clock exactly false), read from the same git snapshot; no clock is
read and an unobserved epoch is FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED before
anything is written.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]

OPERATION = "ORGANIZATION_MAIN_MERGE_TRANSFER"
TRANSITION_CLASS = OPERATION
PROFILE_ID = "main-merge-transfer"
EVIDENCE_SCHEMA = "stegverse.main-merge-transfer-evidence/v1"
RESULT_SCHEMA = "stegverse.main-merge-transfer-result/v1"
PENDING_SCHEMA = "stegverse.main-merge-transfer-pending/v1"
MAIN_REF = "refs/heads/main"
DEFAULT_LEDGER_REF = "refs/stegverse/organization-ledger"
GOAL = "StegVerse-org/.github#162 (INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001)"
ENTRYPOINT = ".github/workflows/organization-ledger-merge-transfer.yml (push to main)"
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")

ALLOW, DENY, FAIL_CLOSED = "ALLOW", "DENY", "FAIL_CLOSED"
NOT_LEDGERED = "MERGE_TRANSFER_RECEIPT_NOT_LEDGERED"
LINK_UNVERIFIED = "MERGE_TRANSFER_RECEIPT_LINK_UNVERIFIED"
EPOCH_UNOBSERVED = "HB_EPOCH_SOURCE_UNOBSERVED"
FACTS_INVALID = "MERGE_COMMIT_FACTS_INVALID"
COLLISION = "MERGE_TRANSFER_RECEIPT_COLLISION"
WRITER_REFUSED = "LEDGER_WRITER_REFUSED"
DUAL_DIVERGENCE = "MERGE_TRANSFER_DUAL_LEDGER_DIVERGENCE"
LOCATION_UNBOUND = "MERGE_TRANSFER_LEDGER_LOCATION_UNBOUND"
SURFACE_UNBOUND = "MERGE_TRANSFER_WRITER_SURFACE_UNBOUND"
MODES = ("dual", "single")

HEAD_KEY = "HEAD.json"
RECEIPT_PREFIX = "receipts/"
SOURCE_PREFIX = "source-receipts/"
GIT_SCHEME = "git+"

SHA40 = re.compile(r"[0-9a-f]{40}")
PR_SUBJECT = re.compile(r"Merge pull request #([0-9]+) from \S+")


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canon(value)).hexdigest()


def receipt_key(digest: str) -> str:
    return RECEIPT_PREFIX + digest.split(":", 1)[1] + ".json"


def source_key(digest: str) -> str:
    return SOURCE_PREFIX + digest.split(":", 1)[1] + ".json"


def contract(root: Path | str = ROOT) -> dict[str, Any]:
    return json.loads((Path(root) / ".stegverse/transition-ledger/contract.json").read_text(encoding="utf-8"))


def org_contract(root: Path | str = ROOT) -> dict[str, Any]:
    return json.loads((Path(root) / ".stegverse/transition-ledger/org-contract.json").read_text(encoding="utf-8"))


def repository(root: Path | str = ROOT) -> str:
    return contract(root)["repository"]


def refusal(code: str, predicate: str, repair: str, next_attempt: str, *, disposition: str = FAIL_CLOSED,
            **extra: Any) -> dict[str, Any]:
    out = {"schema": RESULT_SCHEMA, "disposition": disposition, "failure_code": code,
           "failed_predicate": predicate, "required_evidence_or_repair": repair,
           "retry_entrypoint": ENTRYPOINT, "owning_existing_goal": GOAL, "next_attempt": next_attempt}
    out.update(extra)
    return out


# -- readers: the ledger layout, from git objects or a directory -------------

class _Reader:
    def get(self, key: str) -> Any:  # pragma: no cover - interface
        raise NotImplementedError


def _decode(data: bytes | None) -> Any:
    if data is None:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None  # present but not a document: it cannot be sealed


class GitTreeReader(_Reader):
    """Documents under ``namespace`` of one commit of ``ref`` in ``git_dir``, read with git cat-file.

    The ref is resolved once, so every read of one verification is from the
    same snapshot. An absent ref has no documents.
    """

    def __init__(self, git_dir: Path | str, ref: str, namespace: str = "", *, tip: str | None = None):
        self.git_dir, self.ref = str(git_dir), ref
        self.namespace = namespace.strip("/")
        if tip is None:
            done = subprocess.run(["git", "-C", self.git_dir, "rev-parse", "--verify", "-q", ref + "^{commit}"],
                                  capture_output=True, text=True)
            tip = done.stdout.strip() if done.returncode == 0 else None
        self.tip = tip

    def at(self, namespace: str) -> "GitTreeReader":
        return GitTreeReader(self.git_dir, self.ref, namespace, tip=self.tip or "")

    def get(self, key: str) -> Any:
        if not self.tip:
            return None
        path = (self.namespace + "/" + key) if self.namespace else key
        done = subprocess.run(["git", "-C", self.git_dir, "cat-file", "blob", self.tip + ":" + path],
                              capture_output=True)
        return _decode(done.stdout) if done.returncode == 0 else None

    def __repr__(self) -> str:
        return "git+%s#%s@%s:%s" % (self.git_dir, self.ref, self.tip, self.namespace)


class DirReader(_Reader):
    """The same layout under a POSIX ledger root (the temp ledgers of the parity tests)."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def at(self, namespace: str) -> "DirReader":
        return DirReader(self.root / namespace)

    def get(self, key: str) -> Any:
        path = self.root / key
        return _decode(path.read_bytes()) if path.is_file() else None


def parse_locator(value: str) -> tuple[str, str, str]:
    """``git+<dir>#<ref>[:<namespace>]`` as the ledger writers read it."""
    body = value[len(GIT_SCHEME):]
    git_dir, _, rest = body.partition("#")
    ref, _, namespace = rest.partition(":")
    if not git_dir or not ref.startswith("refs/"):
        raise ValueError("invalid git ledger locator " + value)
    return git_dir, ref, namespace


def bind_readers(root: Path | str = ROOT, *, git_dir: str | None = None, ref: str | None = None,
                 namespace: str | None = None, env: Mapping[str, str] | None = None) -> tuple[Any, Any] | dict:
    """(organization reader, repository reader) for this execution, or a six-field refusal.

    Arguments win; then STEGVERSE_ORG_LEDGER_ROOT / STEGVERSE_REPO_LEDGER_ROOT
    (a ``git+`` locator or a POSIX root), then STEGVERSE_ORG_LEDGER_GIT_DIR with
    the declared ref. Nothing is derived from the host.
    """
    env = os.environ if env is None else env
    declared = org_contract(root)
    locus = declared.get("organization_ledger") if isinstance(declared.get("organization_ledger"), Mapping) else {}
    declared_ref = locus.get("ref") or declared.get("organization_ledger_ref") or DEFAULT_LEDGER_REF
    location = contract(root).get("repository_ledger_location") or {}
    repo_namespace = namespace if namespace is not None else location.get("namespace")
    org_root, repo_root = env.get("STEGVERSE_ORG_LEDGER_ROOT"), env.get("STEGVERSE_REPO_LEDGER_ROOT")
    if git_dir is None and org_root and not org_root.startswith(GIT_SCHEME):
        organization = DirReader(Path(org_root).expanduser())
        if repo_root and not repo_root.startswith(GIT_SCHEME):
            return organization, DirReader(Path(repo_root).expanduser())
        return organization, organization.at(repo_namespace or "")
    if git_dir is None and org_root:
        git_dir, ref_from_env, _ = parse_locator(org_root)
        ref = ref or ref_from_env
    if git_dir is None and env.get("STEGVERSE_ORG_LEDGER_GIT_DIR"):
        git_dir = env["STEGVERSE_ORG_LEDGER_GIT_DIR"]
    if git_dir is None:
        return refusal(LOCATION_UNBOUND, "MERGE_TRANSFER_READS_THE_SUPPLIED_LEDGER",
                       "supply the organization ledger as --git-dir/--ref, STEGVERSE_ORG_LEDGER_ROOT "
                       "(git+<dir>#<ref> or a root) or STEGVERSE_ORG_LEDGER_GIT_DIR; no host path is derived",
                       "re-run with the ledger location bound; nothing was read or written")
    ref = ref or declared_ref
    if repo_namespace is None and repo_root and repo_root.startswith(GIT_SCHEME):
        repo_namespace = parse_locator(repo_root)[2]
    organization = GitTreeReader(git_dir, ref)
    if repo_root and repo_root.startswith(GIT_SCHEME) and namespace is None:
        repo_dir, repo_ref, repo_ns = parse_locator(repo_root)
        if (os.path.realpath(repo_dir), repo_ref) != (os.path.realpath(git_dir), ref):
            return organization, GitTreeReader(repo_dir, repo_ref, repo_ns)
        repo_namespace = repo_ns
    return organization, organization.at(repo_namespace or "")


# -- receipts ---------------------------------------------------------------

def sealed(receipt: Any) -> bool:
    return (isinstance(receipt, Mapping) and isinstance(receipt.get("receipt_sha256"), str)
            and sha({k: v for k, v in receipt.items() if k != "receipt_sha256"}) == receipt["receipt_sha256"])


def _receipt(reader: Any, digest: Any) -> Any:
    if not isinstance(digest, str) or ":" not in digest:
        return None
    return reader.get(receipt_key(digest))


def _boundary(receipt: Mapping[str, Any]) -> Mapping[str, Any]:
    value = receipt.get("boundary_evidence", receipt.get("evidence"))
    return value if isinstance(value, Mapping) else {}


def org_chain(reader: Any) -> Iterable[tuple[str, Any]]:
    head = reader.get(HEAD_KEY)
    digest = head.get("receipt_sha256") if isinstance(head, Mapping) else None
    seen = set()
    while isinstance(digest, str) and digest not in seen:
        seen.add(digest)
        receipt = _receipt(reader, digest)
        yield digest, receipt
        if not isinstance(receipt, Mapping):
            return
        digest = receipt.get("previous_receipt_sha256")


def head_epoch(reader: Any) -> tuple[int | None, dict[str, Any] | None]:
    def unobserved(detail: str) -> tuple[None, dict[str, Any]]:
        return None, refusal(EPOCH_UNOBSERVED, "MERGE_TRANSFER_EPOCH_IS_THE_LEDGER_HEAD_SUPPLIED_EPOCH",
                             "the organization ledger head receipt must be sealed and carry hb_reference.epoch, "
                             "an int >= 32 with derived_from_clock exactly false; no clock is read",
                             "re-run the push's merge-transfer workflow once the head carries a supplied epoch; "
                             "nothing was written", detail=detail)
    head = reader.get(HEAD_KEY)
    if not isinstance(head, Mapping):
        return unobserved("the organization ledger has no HEAD")
    receipt = _receipt(reader, head.get("receipt_sha256"))
    if not sealed(receipt):
        return unobserved("the organization ledger head receipt is absent or unsealed")
    reference = receipt.get("hb_reference")
    epoch = reference.get("epoch") if isinstance(reference, Mapping) else None
    if type(epoch) is not int or epoch < 32 or reference.get("derived_from_clock") is not False:
        return unobserved("head hb_reference " + repr(reference) + " is not a supplied epoch")
    return epoch, None


def verify_merge_transfer(repo: str, merge_commit: str, organization: Any, repository_reader: Any, *,
                          mode: str = "dual") -> dict[str, Any]:
    """merge_transfer.verify_merge_transfer over readers; in dual mode both ledgers must hold one receipt."""
    if mode not in MODES:
        raise ValueError("mode must be one of " + ", ".join(MODES))
    base = {"repository": repo, "merge_commit": merge_commit, "operation": OPERATION}

    def not_ledgered(detail: str, **extra: Any) -> dict[str, Any]:
        return refusal(NOT_LEDGERED, "MAIN_MERGE_HAS_AN_ORGANIZATION_LEDGER_RECEIPT",
                       "a sealed organization receipt on this organization's ledger with boundary_evidence.operation "
                       + OPERATION + ", repository " + repo + " and merge_commit " + merge_commit
                       + ", linked to a sealed repository receipt carrying the same merge",
                       "the next push to main runs " + ENTRYPOINT + ", which appends every listed pending merge "
                       "(.stegverse/merge-transfer/pending.json) and the pushed range; verify again after it reads back",
                       **base, transfer="UNVERIFIED", detail=detail, **extra)

    for digest, receipt in org_chain(organization):
        if not sealed(receipt) or receipt["receipt_sha256"] != digest:
            return not_ledgered("organization receipt " + digest + " on the chain is absent or its seal does not verify",
                                organization_receipt_sha256=digest)
        boundary = _boundary(receipt)
        if boundary.get("operation") != OPERATION or boundary.get("merge_commit") != merge_commit \
                or boundary.get("repository") != repo:
            continue
        linked = receipt.get("repo_receipt_sha256")
        repo_receipt = _receipt(repository_reader, linked)
        if not sealed(repo_receipt):
            return not_ledgered("repository receipt " + str(linked) + " is absent or unsealed",
                                organization_receipt_sha256=digest)
        if mode == "dual":
            retained = organization.get(source_key(linked)) if isinstance(linked, str) and ":" in linked else None
            if retained != repo_receipt:
                return refusal(DUAL_DIVERGENCE, "REPOSITORY_AND_ORGANIZATION_LEDGERS_HOLD_ONE_RECEIPT",
                               "the repository chain's receipt " + str(linked) + " and the copy the organization "
                               "ledger retained under " + SOURCE_PREFIX + " must be the same receipt",
                               "inspect both copies of " + str(linked) + "; neither is preferred, nothing was "
                               "verified and nothing is appended over a divergence",
                               **base, transfer="UNVERIFIED", organization_receipt_sha256=digest,
                               repository_receipt_sha256=linked,
                               detail="retained copy is absent" if retained is None
                               else "retained copy differs from the repository chain's receipt")
        evidence = repo_receipt.get("evidence")
        evidence = evidence if isinstance(evidence, Mapping) else {}
        contradictions = []
        named = receipt.get("repository", receipt.get("source_repository"))
        if named != repo:
            contradictions.append("organization receipt names repository " + repr(named))
        if repo_receipt["receipt_sha256"] != linked:
            contradictions.append("repository receipt at " + str(linked) + " is sealed as " + repo_receipt["receipt_sha256"])
        for field, want in (("schema", EVIDENCE_SCHEMA), ("merge_commit", merge_commit), ("repository", repo),
                            ("ref", MAIN_REF)):
            if evidence.get(field) != want:
                contradictions.append("repository receipt evidence " + field + " is " + repr(evidence.get(field)))
        if evidence.get("payload_sha256") != sha({k: v for k, v in evidence.items()
                                                  if k not in ("payload_sha256", "disposition", "communication_id")}):
            contradictions.append("repository receipt evidence does not carry the digest it claims")
        if contradictions:
            return refusal(LINK_UNVERIFIED, "ORGANIZATION_RECEIPT_LINKS_TO_THE_MERGE_COMMIT",
                           "the organization receipt's repository receipt must carry merge_commit, repository and ref "
                           "equal to the merge being verified; this ledger records evidence that contradicts it",
                           "inspect organization receipt " + digest + " and repository receipt " + str(linked)
                           + "; nothing was verified and nothing is appended over a contradiction",
                           disposition=DENY, **base, transfer="UNVERIFIED", organization_receipt_sha256=digest,
                           repository_receipt_sha256=linked, detail="; ".join(contradictions))
        return {"schema": RESULT_SCHEMA, "disposition": ALLOW, "transfer": "VERIFIED", **base,
                "organization_receipt_sha256": digest,
                "repository_receipt_sha256": repo_receipt["receipt_sha256"],
                "pull_request": evidence.get("pull_request"),
                "hb_epoch": (receipt.get("hb_reference") or {}).get("epoch")}
    return not_ledgered("no organization receipt names " + OPERATION + " for " + repo + "@" + merge_commit)


# -- commit facts -----------------------------------------------------------

def commit_facts(commit: str, git_dir: Path | str = ROOT) -> dict[str, Any]:
    raw = subprocess.run(["git", "-C", str(git_dir), "cat-file", "commit", commit],
                         check=True, capture_output=True, text=True).stdout
    header, _, message = raw.partition("\n\n")
    tree, parents = None, []
    for line in header.splitlines():
        key, _, value = line.partition(" ")
        if key == "tree":
            tree = value
        elif key == "parent":
            parents.append(value)
    full = subprocess.run(["git", "-C", str(git_dir), "rev-parse", "--verify", commit + "^{commit}"],
                          check=True, capture_output=True, text=True).stdout.strip()
    return {"merge_commit": full, "tree": tree, "parents": parents,
            "subject": message.splitlines()[0] if message else ""}


def facts_failure(facts: Any) -> str | None:
    if not isinstance(facts, Mapping):
        return "commit facts are not an object"
    if not isinstance(facts.get("merge_commit"), str) or not SHA40.fullmatch(facts["merge_commit"]):
        return "merge_commit is not 40 lowercase hex"
    if not isinstance(facts.get("tree"), str) or not SHA40.fullmatch(facts["tree"]):
        return "tree is not 40 lowercase hex"
    parents = facts.get("parents")
    if not isinstance(parents, list) or not parents or not all(isinstance(p, str) and SHA40.fullmatch(p) for p in parents):
        return "parents is not a non-empty list of 40 lowercase hex"
    if not isinstance(facts.get("subject"), str):
        return "subject is not text"
    return None


def merge_evidence(repo: str, facts: Mapping[str, Any]) -> dict[str, Any]:
    match = PR_SUBJECT.fullmatch(facts["subject"]) if len(facts["parents"]) == 2 else None
    core = {"schema": EVIDENCE_SCHEMA, "repository": repo, "ref": MAIN_REF,
            "merge_commit": facts["merge_commit"], "tree": facts["tree"],
            "parents": list(facts["parents"]),
            "merge_kind": "MERGE_COMMIT" if len(facts["parents"]) == 2 else "FIRST_PARENT_COMMIT",
            "pull_request": int(match.group(1)) if match else None,
            "pull_request_source": "MERGE_COMMIT_SUBJECT" if match else None}
    return {**core, "payload_sha256": sha(core), "disposition": ALLOW,
            "communication_id": PROFILE_ID + ":" + repo + "@" + facts["merge_commit"]}


# -- writer surfaces --------------------------------------------------------

def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class WriterSurface:
    """The two-level append this checkout carries, bound by what it exposes, never by organization name.

    DUAL_LEDGER: resident-runtime/dual_ledger.py (find_repository, append_repository, append_organization).
    AGGREGATE_TRANSITION: emit.py repository_store() + aggregate_repo_transition.aggregate_transition(...).
    TWO_MODULE_APPEND: emit.py lr()/open_store + aggregate_repo_transition.append(...).
    """

    def __init__(self, root: Path | str = ROOT):
        root = Path(root)
        dual = root / "resident-runtime/dual_ledger.py"
        if dual.is_file():
            self.kind = "DUAL_LEDGER"
            self.dual = _load("dual_ledger_for_merge_transfer_gitstore", dual)
            self.emit, self.aggregate = self.dual.emit, self.dual.aggregate
            return
        self.emit = _load("repo_transition_emit_for_merge_transfer_gitstore",
                          root / ".stegverse/transition-ledger/emit.py")
        self.aggregate = _load("aggregate_repo_transition_for_merge_transfer_gitstore",
                               root / "resident-runtime/aggregate_repo_transition.py")
        if hasattr(self.aggregate, "aggregate_transition"):
            self.kind = "AGGREGATE_TRANSITION"
        elif hasattr(self.aggregate, "append"):
            self.kind = "TWO_MODULE_APPEND"
        else:
            raise LookupError("no two-level append in " + str(root))

    def _repository_store(self):
        if hasattr(self.emit, "repository_store"):
            return self.emit.repository_store()
        return self.emit.ledger_store.open_store(self.emit.lr())

    def prior(self, transition_id: str) -> Any:
        if self.kind == "DUAL_LEDGER":
            return self.dual.find_repository(transition_id)
        store = self._repository_store()
        try:
            head = store.get(self.emit.ledger_store.HEAD_KEY)
        except FileNotFoundError:
            head = None
        return self.emit.recorded(store, head, transition_id, TRANSITION_CLASS)

    def append(self, transition_id: str, predecessor: str, successor: str, evidence: Mapping[str, Any],
               epoch: int, boundary: Mapping[str, Any]) -> dict[str, Any]:
        idempotent_on = ("communication_id", "payload_sha256", "disposition")
        if self.kind == "DUAL_LEDGER":
            repository_receipt = self.dual.append_repository(
                transition_id, TRANSITION_CLASS, predecessor, successor, dict(evidence), "NONE",
                hb_epoch=epoch, idempotent_on=idempotent_on)
        else:
            repository_receipt = self.emit.append(
                transition_id, TRANSITION_CLASS, predecessor, successor, dict(evidence), "NONE",
                hb_epoch=epoch, idempotent_on=idempotent_on)
        org_epoch = repository_receipt["hb_reference"]["epoch"]
        if self.kind == "DUAL_LEDGER":
            organization_receipt = self.dual.append_organization(
                repository_receipt, "REPO_STATE_PROPAGATION", predecessor, successor, dict(boundary), "NONE",
                hb_epoch=org_epoch, idempotent=True)
        elif self.kind == "AGGREGATE_TRANSITION":
            organization_receipt = self.aggregate.aggregate_transition(
                receipt=repository_receipt, org_transition_class="REPO_STATE_PROPAGATION",
                predecessor_org_state_sha256=predecessor, successor_org_state_sha256=successor,
                boundary_evidence=dict(boundary), authority_effect="NONE", hb_epoch=org_epoch)
        else:
            organization_receipt = self.aggregate.append(
                repository_receipt, "REPO_STATE_PROPAGATION", predecessor, successor, dict(boundary), "NONE",
                hb_epoch=org_epoch, idempotent=True)
        if not sealed(organization_receipt) or organization_receipt.get("repo_receipt_sha256") \
                != repository_receipt.get("receipt_sha256"):
            raise ValueError("organization writer returned no sealed receipt preserving the repository receipt: "
                             + json.dumps(organization_receipt, sort_keys=True, default=str)[:400])
        return {"repository_receipt": repository_receipt, "organization_receipt": organization_receipt}


def append_merge_transfer(facts: Mapping[str, Any], *, root: Path | str = ROOT, readers: Any = None,
                          surface: WriterSurface | None = None) -> dict[str, Any]:
    """Append the merge's repository and organization receipts, or refuse with six fields."""
    repo = repository(root)
    bad = facts_failure(facts)
    if bad is not None:
        return refusal(FACTS_INVALID, "MERGE_COMMIT_FACTS_ARE_READ_FROM_THE_COMMIT_OBJECT",
                       "pass the commit's tree, parents and subject as git cat-file reads them",
                       "re-run on the pushed commit; nothing was written", repository=repo, detail=bad)
    readers = readers if readers is not None else bind_readers(root)
    if isinstance(readers, dict):
        return {**readers, "repository": repo, "merge_commit": facts["merge_commit"]}
    epoch, failed = head_epoch(readers[0])
    if failed is not None:
        return {**failed, "repository": repo, "merge_commit": facts["merge_commit"]}
    try:
        surface = surface or WriterSurface(root)
    except (LookupError, OSError) as exc:
        return refusal(SURFACE_UNBOUND, "THE_CHECKOUT_CARRIES_A_TWO_LEVEL_APPEND",
                       "carry dual_ledger.py, or emit.py with aggregate_repo_transition.py", "re-run once carried; "
                       "nothing was written", repository=repo, merge_commit=facts["merge_commit"], detail=str(exc))
    evidence = merge_evidence(repo, facts)
    packet_id = facts["merge_commit"]
    predecessor = evidence["payload_sha256"]
    successor = sha({"disposition": evidence["disposition"], "packet_id": packet_id,
                     "communication_id": evidence["communication_id"], "payload_sha256": evidence["payload_sha256"]})
    transition_id = TRANSITION_CLASS + ":" + packet_id
    boundary = {"operation": OPERATION, "profile_id": PROFILE_ID, "disposition": evidence["disposition"],
                "communication_id": evidence["communication_id"], "repository": repo,
                "merge_commit": facts["merge_commit"]}
    try:
        replayed = surface.prior(transition_id) is not None
        appended = surface.append(transition_id, predecessor, successor, evidence, epoch, boundary)
    except ValueError as exc:
        code = COLLISION if str(exc) == "ledger_receipt_collision" else WRITER_REFUSED
        return refusal(code, "ONE_MERGE_COMMIT_BINDS_ONE_TRANSFER_RECEIPT",
                       "the ledger already binds this merge commit to different evidence, or the writer refused: " + str(exc),
                       "inspect the recorded receipt; a replay of the same merge is answered from the ledger",
                       repository=repo, merge_commit=facts["merge_commit"], detail=str(exc), writer_surface=surface.kind)
    except SystemExit as exc:
        return refusal(WRITER_REFUSED, "LEDGER_WRITER_ADMITS_THE_APPEND",
                       "repair what the ledger writer refused (" + str(exc.code) + ")",
                       "re-run once repaired; a replay of the same merge is answered from the ledger",
                       repository=repo, merge_commit=facts["merge_commit"], writer_surface=surface.kind)
    return {"schema": RESULT_SCHEMA, "disposition": ALLOW, "operation": OPERATION, "repository": repo,
            "merge_commit": facts["merge_commit"], "pull_request": evidence["pull_request"], "hb_epoch": epoch,
            "replayed": replayed, "writer_surface": surface.kind,
            "repository_receipt_sha256": appended["repository_receipt"]["receipt_sha256"],
            "organization_receipt_sha256": appended["organization_receipt"]["receipt_sha256"]}


# -- which commits a push carries ------------------------------------------

def pending(path: Path | str, root: Path | str = ROOT) -> list[str]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema") != PENDING_SCHEMA or document.get("repository") != repository(root):
        raise SystemExit("FAIL_CLOSED: PENDING_MANIFEST_INVALID " + str(path))
    commits = [row["merge_commit"] for row in document["merges"]]
    if not all(isinstance(c, str) and SHA40.fullmatch(c) for c in commits):
        raise SystemExit("FAIL_CLOSED: PENDING_MANIFEST_INVALID " + str(path))
    return commits


def _git(*args: str, git_dir: Path | str = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(git_dir), *args], capture_output=True, text=True)


def pushed_commits(before: str | None, after: str, pending_path: Path | str | None,
                   git_dir: Path | str = ROOT) -> list[str]:
    """Pending merges reachable from ``after`` (oldest first), then the pushed first-parent range."""
    out: list[str] = []
    for commit in pending(pending_path, git_dir) if pending_path else []:
        if _git("merge-base", "--is-ancestor", commit, after, git_dir=git_dir).returncode != 0:
            raise SystemExit("FAIL_CLOSED: PENDING_MERGE_NOT_ON_MAIN " + commit)
        out.append(commit)
    zero = before is None or not SHA40.fullmatch(before or "") or set(before) == {"0"}
    if zero or _git("merge-base", "--is-ancestor", before, after, git_dir=git_dir).returncode != 0:
        pushed = [after]
    else:
        listed = _git("rev-list", "--first-parent", "--reverse", before + ".." + after, git_dir=git_dir)
        if listed.returncode != 0:
            raise SystemExit("FAIL_CLOSED: PUSHED_RANGE_UNREADABLE " + listed.stderr.strip())
        pushed = listed.stdout.split()
    for commit in pushed:
        if commit not in out:
            out.append(commit)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("commits", help="the commits a push to main carries")
    c.add_argument("--before", default="")
    c.add_argument("--after", required=True)
    c.add_argument("--pending")
    for name in ("append", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--commit", action="append", default=[])
        p.add_argument("--commits-file")
        p.add_argument("--out")
        p.add_argument("--git-dir", help="git dir holding the organization ledger ref (else the bound location)")
        p.add_argument("--ref", help="the organization ledger ref (else the declared ref)")
        p.add_argument("--repo-namespace", help="the repository chain's subtree (else contract.json)")
        if name == "verify":
            p.add_argument("--expect", choices=(ALLOW, FAIL_CLOSED), default=ALLOW)
            p.add_argument("--mode", choices=MODES, default="dual")
    args = parser.parse_args(argv)
    if args.command == "commits":
        print("\n".join(pushed_commits(args.before, args.after, args.pending)))
        return 0
    commits = list(args.commit)
    if args.commits_file:
        commits += Path(args.commits_file).read_text(encoding="utf-8").split()
    expected = args.expect if args.command == "verify" else ALLOW
    if not commits:
        print(json.dumps(refusal(FACTS_INVALID, "A_PUSH_NAMES_ITS_COMMITS", "name at least one commit",
                                 "re-run with --commit or --commits-file; nothing was done"), indent=2))
        return 1
    readers = bind_readers(ROOT, git_dir=args.git_dir, ref=args.ref, namespace=args.repo_namespace)
    results = []
    for commit in commits:
        if isinstance(readers, dict):
            results.append({**readers, "merge_commit": commit})
        elif args.command == "append":
            results.append(append_merge_transfer(commit_facts(commit), readers=bind_readers(
                ROOT, git_dir=args.git_dir, ref=args.ref, namespace=args.repo_namespace)))
        else:
            results.append(verify_merge_transfer(repository(), commit_facts(commit)["merge_commit"],
                                                 readers[0], readers[1], mode=args.mode))
    text = json.dumps(results, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    for result in results:
        if result["disposition"] != expected:
            return 1
        if expected == FAIL_CLOSED and not all(result.get(f) for f in SIX_FIELDS):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
