#!/usr/bin/env python3
"""InTr mesh path transfer: a declared path (source organization to destination
organization, per declared capability) is exercised by a real transfer
transition on main, and leaves its own sealed path receipt on the ledger.

Declared paths: every ordered pair of distinct organizations whose destination
documents conform to data/intr-protocol/v1/protocol.json in the pinned mesh
snapshot (tests/fixtures/intr-protocol/destinations/manifest.json), for the one
declared capability, intr-destination. A path is addressed
``<SOURCE>-><DESTINATION>:intr-destination``.

Transition: a transfer declared in .stegverse/intr-path-transfer/transfers.json
lands on main. After the push's main-merge transfer is ledgered
(.github/workflows/organization-ledger-merge-transfer.yml), the writer
.github/workflows/intr-path-transfer.yml appends, for each declared transfer
whose source is this organization and that is not yet ledgered, one repository
receipt and one organization receipt through the existing two-level append
(resident-runtime/intr_destination_ingress.py::_append), operation
INTR_MESH_PATH_TRANSFER. The repository receipt's evidence
(stegverse.intr-path-transfer-evidence/v1) carries the InTr message (it must
conform to the protocol), the derived destination address, and the link to the
transfer: the pushed merge commit and the seal of its main-merge transfer
organization receipt. No dispatch, schedule, clock or cross-organization call.

Verification, per path, has two halves:
  source half: a sealed organization receipt (operation INTR_MESH_PATH_TRANSFER,
    path_id, communication_id) linked to a sealed repository receipt whose
    evidence names the same path and message, and whose merge-transfer link
    resolves to a sealed ORGANIZATION_MAIN_MERGE_TRANSFER receipt on the same
    chain for the same commit;
  destination half: the destination organization's own ledger holds a sealed
    ORGANIZATION_INTR_DESTINATION_INGRESS receipt for the same communication_id,
    linked to its sealed repository receipt. That readback needs a carrier that
    delivers the message to the destination and a TV/TVC-issued cross-organization
    read credential; neither exists here, so it is FAIL_CLOSED class B unless a
    readback is supplied.
ALLOW only when both halves verify. Absent or unsealed evidence is FAIL_CLOSED;
present, sealed evidence that contradicts the path is DENY. Six fields each.

Typed bodies (INTR-PATH-TRANSFER-TYPED-BODY-001, StegVerse-org/.github#162). A
declaration row that carries ``typed_body`` is a typed transfer: its message
body is that typed body instead of the fixed {schema, path_id, transfer_commit}
body. The body is sealed (the row's ``typed_body_sha256`` must equal its digest,
and the evidence binds both), and its schema must be on TYPED_BODY_SCHEMAS.
Only stegverse.repository-ledger-genesis-observed/v1 (REPOSITORY_LEDGER_GENESIS_OBSERVED,
the trigger StegVerse-org/LLM-adapter#431's pre-pin receiver accepts) is listed;
any other typed schema is refused with six fields. A typed transfer's evidence
also carries ``destination_location`` (a location inside this organization's
ledger ref) and ``endpoint_kind`` (StegVerse-org/LLM-adapter#432
schemas/endpoint-kind.v1.json). An endpoint_kind GATEWAY row never carries an
external ledger ref. Rows without ``typed_body`` and the other typed keys take
the untyped code path, which is unchanged: its output is byte-identical
(tests/fixtures/intr-path-transfer/untyped-golden.json, from main @907f4305).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]


def _module(name: str, relative: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mt = _module("merge_transfer_for_path_transfer", "resident-runtime/merge_transfer.py")
intr = _module("intr_protocol_for_path_transfer", "org-runtime/intr_protocol.py")
ingress = mt.ingress

OPERATION = "INTR_MESH_PATH_TRANSFER"
TRANSITION_CLASS = OPERATION
PROFILE_ID = "intr-mesh-path-transfer"
CAPABILITY = "intr-destination"
EVIDENCE_SCHEMA = "stegverse.intr-path-transfer-evidence/v1"
RESULT_SCHEMA = "stegverse.intr-path-transfer-result/v1"
DECLARATION_SCHEMA = "stegverse.intr-path-transfer-declaration/v1"
DESTINATION_OPERATION = "ORGANIZATION_INTR_DESTINATION_INGRESS"
GOAL = "StegVerse-org/.github#162"
ENTRYPOINT = (".github/workflows/intr-path-transfer.yml (after Organization Ledger Main Merge "
              "Transfer completes on a push to main)")
SNAPSHOT = ROOT / "tests" / "fixtures" / "intr-protocol" / "destinations" / "manifest.json"
DECLARATION = ROOT / ".stegverse" / "intr-path-transfer" / "transfers.json"
SIX_FIELDS = mt.SIX_FIELDS
ALLOW, DENY, FAIL_CLOSED = "ALLOW", "DENY", "FAIL_CLOSED"

NOT_LEDGERED = "INTR_PATH_RECEIPT_NOT_LEDGERED"
LINK_UNVERIFIED = "INTR_PATH_RECEIPT_LINK_UNVERIFIED"
CREDENTIAL_NOT_ISSUED = "INTR_PATH_CROSS_ORG_READ_CREDENTIAL_NOT_ISSUED"
DESTINATION_NOT_LEDGERED = "INTR_PATH_DESTINATION_RECEIPT_NOT_LEDGERED"
DESTINATION_LINK_UNVERIFIED = "INTR_PATH_DESTINATION_RECEIPT_LINK_UNVERIFIED"
TRANSFER_NOT_LEDGERED = "INTR_PATH_TRANSFER_COMMIT_NOT_LEDGERED"
PATH_UNDECLARED = "INTR_PATH_UNDECLARED"
MESSAGE_REFUSED = "INTR_PATH_MESSAGE_NONCONFORMANT"

sha = ingress.sha
sealed = mt.sealed


def repository() -> str:
    return mt.repository()


def organization() -> str:
    return repository().split("/")[0]


def refusal(disposition: str, code: str, predicate: str, repair: str, next_attempt: str,
            *, entrypoint: str = ENTRYPOINT, **extra: Any) -> dict[str, Any]:
    out = {"schema": RESULT_SCHEMA, "disposition": disposition, "failure_code": code,
           "failed_predicate": predicate, "required_evidence_or_repair": repair,
           "retry_entrypoint": entrypoint, "owning_existing_goal": GOAL, "next_attempt": next_attempt}
    out.update(extra)
    return out


# -- declared paths ----------------------------------------------------------

def path_id(source: str, destination: str) -> str:
    return source + "->" + destination + ":" + CAPABILITY


def declared_paths(manifest_path: Path | str = SNAPSHOT) -> list[dict[str, Any]]:
    """Ordered pairs of distinct organizations whose destination documents conform (ALLOW)."""
    report = intr.conform_mesh(manifest_path)
    contract = intr.load_contract()
    conformant = sorted(r["subject"]["organization"] for r in report["results"] if r["disposition"] == ALLOW)
    return [{"path_id": path_id(s, d), "source": s, "destination": d, "capability": CAPABILITY,
             "destination_address": intr.destination_address(d, contract)}
            for s in conformant for d in conformant if s != d]


def load_declaration(path: Path | str = DECLARATION) -> list[dict[str, Any]]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema") != DECLARATION_SCHEMA or document.get("source_repository") != repository():
        raise SystemExit("FAIL_CLOSED: INTR_PATH_DECLARATION_INVALID " + str(path))
    return list(document["transfers"])


def message(path: Mapping[str, Any], communication_id: str, transfer_commit: str) -> dict[str, Any]:
    payload_schema = next(p["equals"] for p in intr.load_contract()["destination_capability"]["binding_predicates"]
                          if p["id"] == "BINDING_PAYLOAD_SCHEMA")
    return {"message_class": "ecosystem.communication", "communication_id": communication_id,
            "body": {"schema": payload_schema, "path_id": path["path_id"], "transfer_commit": transfer_commit}}


def path_evidence(path: Mapping[str, Any], communication_id: str, transfer_commit: str,
                  merge_transfer_receipt: str) -> dict[str, Any]:
    msg = message(path, communication_id, transfer_commit)
    core = {"schema": EVIDENCE_SCHEMA, "repository": repository(), "path_id": path["path_id"],
            "source_organization": path["source"], "destination_organization": path["destination"],
            "capability": path["capability"], "destination_address": path["destination_address"],
            "message": msg, "message_sha256": sha(msg), "transfer_commit": transfer_commit,
            "merge_transfer_organization_receipt_sha256": merge_transfer_receipt}
    return {**core, "payload_sha256": sha(core), "disposition": ALLOW, "communication_id": communication_id}


def _payload_ok(evidence: Mapping[str, Any]) -> bool:
    return evidence.get("payload_sha256") == sha({k: v for k, v in evidence.items()
                                                  if k not in ("payload_sha256", "disposition", "communication_id")})


# -- source half --------------------------------------------------------------

def _chain(store: Any) -> list[tuple[str, Any]]:
    return list(mt.org_chain(store))


def verify_source(path: Mapping[str, Any], communication_id: str, organization_store: Any = None,
                  repository_store: Any = None) -> dict[str, Any]:
    organization_store = organization_store if organization_store is not None else mt.org_store()
    repository_store = repository_store if repository_store is not None else mt.repo_store()
    base = {"path_id": path["path_id"], "communication_id": communication_id, "half": "source"}

    def not_ledgered(detail: str) -> dict[str, Any]:
        return refusal(FAIL_CLOSED, NOT_LEDGERED, "PATH_HAS_A_SOURCE_LEDGER_RECEIPT",
                       "a sealed organization receipt on " + path["source"] + "'s ledger with boundary_evidence.operation "
                       + OPERATION + ", path_id " + path["path_id"] + " and communication_id " + communication_id
                       + ", linked to a sealed repository receipt and to the transfer's main-merge transfer receipt",
                       "receipts appear only after the transfer declaration lands on " + path["source"]
                       + "/.github main and " + ENTRYPOINT + " appends it; verify again after it reads back",
                       **base, detail=detail)

    chain = _chain(organization_store)
    by_digest = {d: r for d, r in chain}
    for digest, receipt in chain:
        if not sealed(receipt) or receipt["receipt_sha256"] != digest:
            return not_ledgered("organization receipt " + digest + " on the chain is absent or unsealed")
        boundary = mt._boundary(receipt)
        if boundary.get("operation") != OPERATION or boundary.get("path_id") != path["path_id"] \
                or boundary.get("communication_id") != communication_id:
            continue
        linked = receipt.get("repo_receipt_sha256")
        repo_receipt = mt._receipt(repository_store, linked)
        if not sealed(repo_receipt):
            return not_ledgered("repository receipt " + str(linked) + " is absent or unsealed")
        evidence = repo_receipt.get("evidence") if isinstance(repo_receipt.get("evidence"), Mapping) else {}
        problems = []
        if repo_receipt["receipt_sha256"] != linked:
            problems.append("repository receipt at " + str(linked) + " is sealed as " + repo_receipt["receipt_sha256"])
        for field, want in (("schema", EVIDENCE_SCHEMA), ("path_id", path["path_id"]),
                            ("source_organization", path["source"]), ("destination_organization", path["destination"]),
                            ("capability", path["capability"]), ("destination_address", path["destination_address"]),
                            ("communication_id", communication_id)):
            if evidence.get(field) != want:
                problems.append("evidence " + field + " is " + repr(evidence.get(field)))
        if not _payload_ok(evidence):
            problems.append("evidence does not carry the digest it claims")
        msg = evidence.get("message")
        if sha(msg) != evidence.get("message_sha256") or not isinstance(msg, Mapping) \
                or msg.get("communication_id") != communication_id:
            problems.append("message does not match its digest or communication_id")
        elif intr.conform_message(msg, path["destination"])["disposition"] != ALLOW:
            problems.append("message does not conform to the InTr protocol")
        transfer = by_digest.get(evidence.get("merge_transfer_organization_receipt_sha256"))
        tb = mt._boundary(transfer) if isinstance(transfer, Mapping) else {}
        if not sealed(transfer) or tb.get("operation") != mt.OPERATION \
                or tb.get("merge_commit") != evidence.get("transfer_commit") or tb.get("repository") != repository():
            problems.append("merge-transfer link " + str(evidence.get("merge_transfer_organization_receipt_sha256"))
                            + " is not a sealed main-merge transfer receipt for " + str(evidence.get("transfer_commit")))
        if problems:
            return refusal(DENY, LINK_UNVERIFIED, "PATH_RECEIPT_LINKS_TO_THE_TRANSFER",
                           "the path receipt's repository receipt must carry this path, message and address and link "
                           "the sealed main-merge transfer receipt of its transfer commit; the ledger contradicts it",
                           "inspect organization receipt " + digest + "; nothing was verified", **base,
                           organization_receipt_sha256=digest, detail="; ".join(problems))
        return {"schema": RESULT_SCHEMA, "disposition": ALLOW, "half": "source", "path_id": path["path_id"],
                "communication_id": communication_id, "organization_receipt_sha256": digest,
                "repository_receipt_sha256": linked, "transfer_commit": evidence["transfer_commit"],
                "merge_transfer_organization_receipt_sha256": evidence["merge_transfer_organization_receipt_sha256"]}
    return not_ledgered("no organization receipt names " + OPERATION + " for " + path["path_id"] + " / " + communication_id)


# -- destination half --------------------------------------------------------

def path_ingress():
    return _module("intr_path_ingress_for_path_transfer", "resident-runtime/intr_path_ingress.py")


def verify_destination(path: Mapping[str, Any], communication_id: str, source: Mapping[str, Any] | None = None,
                       readback: Any = None) -> dict[str, Any]:
    """The destination ledger's ingress receipts for this path, linking the source receipts by seal.

    The destination is another organization's internal repository: without a supplied readback
    (stegverse.intr-path-ledger-readback/v1) it is FAIL_CLOSED INTR_PATH_CROSS_ORG_READ_CREDENTIAL_NOT_ISSUED."""
    pi = path_ingress()
    refused = None
    if readback is None and source is not None and source.get("disposition") == ALLOW:
        # the destination ledger, read through the TV/TVC issuance transition (resident-runtime/intr_path_tvc_read.py)
        readback, refused = pi.tvc_readback(path["path_id"], communication_id, path["destination"] + "/.github")
    if readback is None or source is None or source.get("disposition") != ALLOW:
        base = refused or pi.inclusion_refusal(path["destination"] + "/.github", path["path_id"], communication_id)
        if base.get("failure_code") != pi.CREDENTIAL_NOT_ISSUED:
            return {**base, "half": "destination"}
        return {**base, "half": "destination", "failed_predicate": "PATH_HAS_A_DESTINATION_LEDGER_RECEIPT",
                "required_evidence_or_repair":
                    "the destination's sealed " + DESTINATION_OPERATION + " receipt for this path, read from "
                    + path["destination"] + "/.github refs/stegverse/organization-ledger through the TV/TVC issuance "
                    "transition (" + pi.tvc_read.TVC_TRANSITION + ", scope " + path["path_id"] + "#destination_readback; "
                    "GITHUB_TOKEN reads only this repository; no bot holds a credential). The receipt itself exists "
                    "only after the inbound row lands on the destination's main"}
    link = {"path_id": path["path_id"], "communication_id": communication_id,
            "source_organization_receipt_sha256": source["organization_receipt_sha256"],
            "source_repository_receipt_sha256": source["repository_receipt_sha256"]}
    if not isinstance(readback, Mapping) or not pi._included(readback, readback.get("organization_receipt") or {}):
        return pi.verify_destination_pair(None, None, link, path["destination"] + "/.github")
    return pi.verify_destination_pair(readback.get("organization_receipt"), readback.get("repository_receipt"), link,
                                      path["destination"] + "/.github")


def verify_path(path: Mapping[str, Any], communication_id: str | None, organization_store: Any = None,
                repository_store: Any = None, destination_readback: Any = None) -> dict[str, Any]:
    """ALLOW only when both halves verify; otherwise the first non-ALLOW half, with six fields."""
    if communication_id is None or path["source"] != organization():
        source = refusal(FAIL_CLOSED, NOT_LEDGERED, "PATH_HAS_A_SOURCE_LEDGER_RECEIPT",
                         "class B (missing capability) when the source is another organization: install the path-transfer "
                         "transition in " + path["source"] + "/.github and declare a transfer for " + path["path_id"],
                         "receipts appear only after a transfer for this path lands on " + path["source"]
                         + "/.github main and its writer appends it", path_id=path["path_id"], half="source",
                         communication_id=communication_id,
                         classification="B" if path["source"] != organization() else None,
                         detail="no transfer for this path is declared in this organization")
    else:
        source = verify_source(path, communication_id, organization_store, repository_store)
    destination = verify_destination(path, communication_id or "", source, destination_readback)
    halves = {"source": source["disposition"], "destination": destination["disposition"]}
    if source["disposition"] == ALLOW and destination["disposition"] == ALLOW:
        return {"schema": RESULT_SCHEMA, "disposition": ALLOW, "path_id": path["path_id"], "path": "VERIFIED",
                "communication_id": communication_id, "halves": halves, "source": source, "destination": destination}
    first = source if source["disposition"] != ALLOW else destination
    return {**first, "path": "UNVERIFIED", "halves": halves, "path_id": path["path_id"]}


# -- typed bodies (INTR-PATH-TRANSFER-TYPED-BODY-001) ------------------------------

LEDGER_REF = "refs/stegverse/organization-ledger"
#: StegVerse-org/LLM-adapter schemas/endpoint-kind.v1.json $defs.endpoint_kind (#432), copied, not imported
ENDPOINT_KINDS = ("EPHEMERAL", "PERMANENT", "GATEWAY", "KV", "SKAP_VAULT", "ORG")
GATEWAY = "GATEWAY"
GENESIS_OBSERVED_SCHEMA = "stegverse.repository-ledger-genesis-observed/v1"
#: The typed-body allowlist. A schema is added only by its own admitted change.
TYPED_BODY_SCHEMAS: dict[str, dict[str, Any]] = {
    GENESIS_OBSERVED_SCHEMA: {
        "signal_class": "REPOSITORY_LEDGER_GENESIS_OBSERVED",
        "transition_class": "REPOSITORY_LEDGER_GENESIS_PIN",
        "keys": ("genesis_receipt_sha256", "ledger_location", "node_ref", "repository", "schema", "signal_class",
                 "transition_class"),
        "endpoint_kinds": ("ORG",),
        "receiver": "StegVerse-org/LLM-adapter scripts/llm_adapter_genesis_pin_ingress.py (#431 @1541d465)",
    },
}
TYPED_ROW_KEYS = ("communication_id", "destination_location", "endpoint_kind", "path_id", "typed_body",
                  "typed_body_sha256")
TYPED_MARKERS = ("typed_body", "typed_body_sha256", "destination_location", "endpoint_kind")
#: Keys that name a ledger outside this organization's ledger ref.
EXTERNAL_LEDGER_KEYS = ("ledger_root", "external_ledger_ref", "external_ledger", "external_chain", "imported_chain",
                        "source_ledger_root")
TYPED_ENTRYPOINT = (ENTRYPOINT + "; typed rows: a typed_body row of " + ".stegverse/intr-path-transfer/transfers.json "
                    "(built by resident-runtime/intr_path_transfer.py typed-row)")

TYPED_SCHEMA_NOT_ALLOWLISTED = "INTR_PATH_TYPED_BODY_SCHEMA_NOT_ALLOWLISTED"
TYPED_BODY_UNSEALED = "INTR_PATH_TYPED_BODY_UNSEALED"
TYPED_BODY_NONCONFORMANT = "INTR_PATH_TYPED_BODY_NONCONFORMANT"
ENDPOINT_KIND_UNDECLARED = "INTR_PATH_ENDPOINT_KIND_UNDECLARED"
GATEWAY_EXTERNAL_LEDGER = "INTR_PATH_GATEWAY_CARRIES_EXTERNAL_LEDGER_REF"
#: KV-HEAD-ROLLBACK (Lane D condition 2; Rigel, StegVerse-org/.github#160 comment 6372216673): each InTr exchange with
#: an independent endpoint records that endpoint's ledger head digest, sealed, in the Org-side linked receipt. It is a
#: digest only, never a ledger ref; KV refuses any head older than the newest one recorded here
#: (KV_LEDGER_HEAD_ROLLBACK_DETECTED, StegVerse-org/LLM-adapter llm_adapter/endpoint_ledger_designation.py).
ENDPOINT_HEAD_KEY = "endpoint_head_sha256"
ENDPOINT_HEAD_REQUIRED_KINDS = ("KV", "SKAP_VAULT")
ENDPOINT_HEAD_MISSING = "INTR_PATH_ENDPOINT_HEAD_DIGEST_MISSING"
ENDPOINT_HEAD_NOT_A_DIGEST = "INTR_PATH_ENDPOINT_HEAD_NOT_A_DIGEST"


PATH_NOT_INTRA_ORG = "INTR_PATH_INTRA_ORG_PATH_UNDECLARED"
GENESIS_NOT_READ_BACK = "INTR_PATH_GENESIS_NOT_READ_BACK"
GENESIS_CLASS = "REPOSITORY_LEDGER_INITIALIZATION"


def intra_org_paths() -> list[dict[str, Any]]:
    """The declared intra-organization repository-destination paths: data rows of the existing path schema,
    data/intr-protocol/v1/protocol.json mesh_path_transfer.intra_org_paths (path_id, source, destination,
    capability, plus the endpoint kinds, typed-body schemas and destination-location prefix the path admits)."""
    return [dict(r) for r in intr.load_contract()["mesh_path_transfer"].get("intra_org_paths", [])]


def intra_org_path(path_id: Any) -> dict[str, Any] | None:
    return next((p for p in intra_org_paths() if p.get("path_id") == path_id and p.get("source") == repository()
                 and p.get("destination") == organization() and p.get("capability") == CAPABILITY), None)


def endpoint_paths() -> list[dict[str, Any]]:
    """Declared paths to an independent endpoint (KV, SKAP Vault) that runs its own ledger behind its own InTr
    ingress/egress and is never stored on this organization's ledger ref: data rows of the same path schema,
    mesh_path_transfer.endpoint_paths. None is declared yet; a row is added by its own admitted change."""
    return [dict(r) for r in intr.load_contract()["mesh_path_transfer"].get("endpoint_paths", [])]


def endpoint_path(path_id: Any) -> dict[str, Any] | None:
    return next((p for p in endpoint_paths() if p.get("path_id") == path_id and p.get("source") == repository()
                 and p.get("capability") == CAPABILITY), None)


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 71 and value.startswith("sha256:") \
        and all(c in "0123456789abcdef" for c in value[7:])


def endpoint_head_refusal(row: Mapping[str, Any], base: Mapping[str, Any], fix: str) -> dict[str, Any] | None:
    """Six-field refusal unless the row's optional sealed endpoint_head_sha256 is well formed, and present for KV and
    SKAP_VAULT. Pure."""
    kind, head = row.get("endpoint_kind"), row.get(ENDPOINT_HEAD_KEY)
    if ENDPOINT_HEAD_KEY not in row:
        if kind in ENDPOINT_HEAD_REQUIRED_KINDS:
            return refusal(FAIL_CLOSED, ENDPOINT_HEAD_MISSING, "INDEPENDENT_ENDPOINT_HEAD_DIGEST_RECORDED",
                           "a typed row with endpoint_kind " + kind + " must carry " + ENDPOINT_HEAD_KEY + ", the "
                           "sha256 digest of that endpoint's current ledger head, so the Org-side linked receipt "
                           "records it (the rollback watermark)", fix, entrypoint=TYPED_ENTRYPOINT, **base)
        return None
    if not _is_digest(head):
        return refusal(DENY, ENDPOINT_HEAD_NOT_A_DIGEST, "ENDPOINT_HEAD_IS_A_DIGEST_NEVER_A_LEDGER_REF",
                       ENDPOINT_HEAD_KEY + " must be a sha256:<64 hex> digest and never names an external ledger; "
                       "got " + repr(head), fix, entrypoint=TYPED_ENTRYPOINT, **base)
    return None


def is_typed(row: Mapping[str, Any]) -> bool:
    return isinstance(row, Mapping) and any(k in row for k in TYPED_MARKERS)


def typed_path_id() -> str:
    """The node-ref path the receiver derives: ``<this repository>-><this organization>:intr-destination``."""
    return repository() + "->" + organization() + ":" + CAPABILITY


def org_location(namespace: str) -> str:
    return LEDGER_REF + ":" + namespace


def genesis_observed_body(target_repository: str, genesis_receipt_sha256: str) -> dict[str, Any]:
    """The REPOSITORY_LEDGER_GENESIS_OBSERVED body, exactly as #431's genesis_signal builds it."""
    spec = TYPED_BODY_SCHEMAS[GENESIS_OBSERVED_SCHEMA]
    return {"schema": GENESIS_OBSERVED_SCHEMA, "signal_class": spec["signal_class"], "repository": target_repository,
            "ledger_location": repository() + "#" + org_location("repository-ledger/" + target_repository),
            "genesis_receipt_sha256": genesis_receipt_sha256, "transition_class": spec["transition_class"],
            "node_ref": repository()}


def genesis_observed_row(target_repository: str, genesis_receipt_sha256: str) -> dict[str, Any]:
    """A typed declaration row carrying the receipted genesis-observed record for ``target_repository``."""
    body = genesis_observed_body(target_repository, genesis_receipt_sha256)
    return {"path_id": typed_path_id(),
            "communication_id": "intr-path-v1:" + repository() + "->" + target_repository + ":genesis-observed",
            "destination_location": org_location("repository-ledger/" + target_repository),
            "endpoint_kind": "ORG", "typed_body": body, "typed_body_sha256": sha(body)}


def genesis_observed_row_from_readback(readback: Any) -> dict[str, Any]:
    """The genesis-append trigger, minimal: the typed row for a repository genesis, derived only from the
    organization ledger read-back that organization-ledger-transition.yml writes (organization_ledger_readback.py
    --repository-namespace repository-ledger/<repo> --out readback.json). Landing the row in transfers.json on
    main is the existing path-transfer transition. Pure: reads nothing but the document given."""
    block = readback.get("repository_ledger") if isinstance(readback, Mapping) else None
    chain = block.get("chain") if isinstance(block, Mapping) else None
    namespace = block.get("namespace") if isinstance(block, Mapping) else None
    target = namespace[len("repository-ledger/"):] if isinstance(namespace, str) \
        and namespace.startswith("repository-ledger/") else None
    problems = []
    if not isinstance(readback, Mapping) or readback.get("disposition", ALLOW) != ALLOW:
        problems.append("the read-back is not an ALLOW organization-ledger read-back")
    if not isinstance(chain, list) or not chain or not isinstance(chain[0], Mapping):
        problems.append("no repository_ledger.chain in the read-back")
    elif chain[0].get("transition_class") != GENESIS_CLASS or chain[0].get("previous_receipt_sha256") is not None \
            or chain[0].get("receipt_sha256") != block.get("genesis_receipt_sha256"):
        problems.append("the chain's first receipt is not a " + GENESIS_CLASS + " genesis equal to "
                        "repository_ledger.genesis_receipt_sha256")
    if isinstance(block, Mapping) and (block.get("every_receipt_verifies_against_its_body") is not True
                                       or block.get("every_receipt_retained_in_organization_ledger") is not True):
        problems.append("the read-back does not verify and retain every repository receipt")
    if target is None:
        problems.append("repository_ledger.namespace " + repr(namespace) + " is not repository-ledger/<repository>")
    if problems:
        return refusal(FAIL_CLOSED, GENESIS_NOT_READ_BACK, "GENESIS_OBSERVED_ON_THE_PUBLISHED_LEDGER_READ_BACK",
                       "; ".join(problems) + ". The row is derived only from organization-ledger-transition.yml's "
                       "read-back of the published " + LEDGER_REF, "re-run typed-row --from-readback on the "
                       "read-back of the genesis-append transition; nothing was emitted",
                       entrypoint=TYPED_ENTRYPOINT, half="source", typed=True)
    return genesis_observed_row(target, block["genesis_receipt_sha256"])


def _external_ledger_refs(row: Mapping[str, Any]) -> list[str]:
    found: list[str] = []

    def walk(value: Any, where: str) -> None:
        if isinstance(value, Mapping):
            for k, v in value.items():
                if k in EXTERNAL_LEDGER_KEYS:
                    found.append(where + k)
                walk(v, where + str(k) + ".")
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, where + str(i) + ".")
    walk(row, "")
    location = row.get("destination_location")
    if not isinstance(location, str) or not location.startswith(LEDGER_REF + ":") or "#" in location \
            or "://" in location or ".." in location.split(":", 1)[-1].split("/"):
        found.append("destination_location " + repr(location) + " is not a location inside " + LEDGER_REF)
    return found


def typed_refusal(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Six-field refusal for a typed row, or None when it is an allowlisted, sealed, conformant typed transfer."""
    pid, cid = row.get("path_id"), row.get("communication_id")
    base = {"path_id": pid, "communication_id": cid, "half": "source", "typed": True}
    fix = "correct the typed row in " + str(DECLARATION.relative_to(ROOT)) + "; nothing was written for this row"
    kind = row.get("endpoint_kind")
    if kind not in ENDPOINT_KINDS:
        return refusal(FAIL_CLOSED, ENDPOINT_KIND_UNDECLARED, "TYPED_TRANSFER_DECLARES_AN_ENDPOINT_KIND",
                       "endpoint_kind must be one of " + ", ".join(ENDPOINT_KINDS) + " (StegVerse-org/LLM-adapter "
                       "schemas/endpoint-kind.v1.json); got " + repr(kind), fix, entrypoint=TYPED_ENTRYPOINT, **base)
    if kind == GATEWAY:
        external = _external_ledger_refs(row)
        if external:
            return refusal(DENY, GATEWAY_EXTERNAL_LEDGER, "GATEWAY_ENDPOINT_CARRIES_NO_EXTERNAL_LEDGER_REF",
                           "a GATEWAY endpoint is carried inside " + LEDGER_REF + " and never imports or names an "
                           "external chain; remove " + "; ".join(external), fix, entrypoint=TYPED_ENTRYPOINT,
                           detail="; ".join(external), **base)
    refused = endpoint_head_refusal(row, base, fix)
    if refused is not None:
        return refused
    extra = sorted(set(row) - set(TYPED_ROW_KEYS) - {ENDPOINT_HEAD_KEY})
    missing = sorted(set(TYPED_ROW_KEYS) - set(row))
    if extra or missing:
        return refusal(FAIL_CLOSED, TYPED_BODY_NONCONFORMANT, "TYPED_ROW_HAS_EXACTLY_THE_TYPED_KEYS",
                       "a typed row has exactly " + ", ".join(TYPED_ROW_KEYS) + "; extra " + repr(extra)
                       + ", missing " + repr(missing), fix, entrypoint=TYPED_ENTRYPOINT, **base)
    body = row["typed_body"]
    schema = body.get("schema") if isinstance(body, Mapping) else None
    spec = TYPED_BODY_SCHEMAS.get(schema) if isinstance(schema, str) else None
    if spec is None:
        return refusal(FAIL_CLOSED, TYPED_SCHEMA_NOT_ALLOWLISTED, "TYPED_BODY_SCHEMA_IS_ALLOWLISTED",
                       "typed_body.schema must be one of " + ", ".join(sorted(TYPED_BODY_SCHEMAS)) + "; got "
                       + repr(schema) + ". Another typed schema needs its own admitted change to TYPED_BODY_SCHEMAS",
                       "re-run after the schema is admitted to the allowlist, or carry an untyped transfer; nothing "
                       "was written for this row", entrypoint=TYPED_ENTRYPOINT, **base)
    if row["typed_body_sha256"] != sha(body):
        return refusal(DENY, TYPED_BODY_UNSEALED, "TYPED_BODY_MATCHES_ITS_DIGEST",
                       "typed_body_sha256 must be the digest of typed_body (" + sha(body) + "); the row names "
                       + repr(row["typed_body_sha256"]), fix, entrypoint=TYPED_ENTRYPOINT, **base)
    problems = []
    if tuple(sorted(body)) != spec["keys"]:
        problems.append("typed_body keys " + repr(sorted(body)) + " are not " + repr(list(spec["keys"])))
    target = body.get("repository")
    if not isinstance(target, str) or target.count("/") != 1 or not target.startswith(organization() + "/") \
            or target == repository():
        problems.append("typed_body.repository " + repr(target) + " is not another repository of " + organization())
    elif body != genesis_observed_body(target, body.get("genesis_receipt_sha256")):
        problems.append("typed_body differs from the " + spec["signal_class"] + " record for " + target)
    else:
        if row["destination_location"] != org_location("repository-ledger/" + target):
            problems.append("destination_location " + repr(row["destination_location"]) + " is not "
                            + org_location("repository-ledger/" + target))
    g = body.get("genesis_receipt_sha256")
    if not (isinstance(g, str) and g.startswith("sha256:") and len(g) == 71
            and all(c in "0123456789abcdef" for c in g[7:])):
        problems.append("genesis_receipt_sha256 " + repr(g) + " is not a sha256: digest")
    if kind not in spec["endpoint_kinds"]:
        problems.append("endpoint_kind " + kind + " is not one of " + repr(list(spec["endpoint_kinds"]))
                        + " for " + schema)
    if pid != typed_path_id():
        problems.append("path_id " + repr(pid) + " is not " + typed_path_id())
    if problems:
        return refusal(FAIL_CLOSED, TYPED_BODY_NONCONFORMANT, "TYPED_BODY_CONFORMS_TO_ITS_SCHEMA",
                       "; ".join(problems), fix, entrypoint=TYPED_ENTRYPOINT, detail="; ".join(problems), **base)
    declared = intra_org_path(pid) or endpoint_path(pid)
    if declared is None or kind not in declared.get("endpoint_kinds", ()) \
            or schema not in declared.get("typed_body_schemas", ()) \
            or not row["destination_location"].startswith(declared.get("destination_location_prefix") or "\0"):
        problems.append("path " + repr(pid) + " with endpoint_kind " + kind + ", schema " + schema + " and "
                        "destination_location " + row["destination_location"] + " is not a declared intra-org path "
                        "(data/intr-protocol/v1/protocol.json mesh_path_transfer.intra_org_paths)")
        return refusal(FAIL_CLOSED, PATH_NOT_INTRA_ORG, "TYPED_TRANSFER_NAMES_A_DECLARED_INTRA_ORG_PATH",
                       "; ".join(problems), "declare the path as a row of mesh_path_transfer.intra_org_paths by its "
                       "own admitted change, or correct the typed row; nothing was written for this row",
                       entrypoint=TYPED_ENTRYPOINT, detail="; ".join(problems), **base)
    if problems:
        return refusal(FAIL_CLOSED, TYPED_BODY_NONCONFORMANT, "TYPED_BODY_CONFORMS_TO_ITS_SCHEMA",
                       "; ".join(problems), fix, entrypoint=TYPED_ENTRYPOINT, detail="; ".join(problems), **base)
    # the envelope keeps every protocol predicate; only the body-schema predicate is replaced by the allowlist
    payload_schema = next(p["equals"] for p in intr.load_contract()["destination_capability"]["binding_predicates"]
                          if p["id"] == "BINDING_PAYLOAD_SCHEMA")
    envelope = {**typed_message(row), "body": {"schema": payload_schema}}
    conform = intr.conform_message(envelope, organization())
    if conform["disposition"] != ALLOW:
        return refusal(FAIL_CLOSED, MESSAGE_REFUSED, "PATH_MESSAGE_CONFORMS_TO_THE_PROTOCOL",
                       conform["required_evidence_or_repair"], fix, entrypoint=TYPED_ENTRYPOINT, **base)
    return None


def typed_message(row: Mapping[str, Any]) -> dict[str, Any]:
    return {"message_class": "ecosystem.communication", "communication_id": row["communication_id"],
            "body": dict(row["typed_body"])}


def typed_path_evidence(row: Mapping[str, Any], transfer_commit: str, merge_transfer_receipt: str) -> dict[str, Any]:
    """The typed source half's evidence: the intr_transport_carrier source shape (#431/#432/#433), on the org writer.

    ``payload_sha256`` covers everything but payload_sha256, disposition, communication_id and boundary_evidence."""
    msg = typed_message(row)
    pid, cid = row["path_id"], row["communication_id"]
    core = {"schema": EVIDENCE_SCHEMA, "repository": repository(), "path_id": pid,
            "source_organization": organization(), "destination_organization": organization(),
            "capability": CAPABILITY, "destination_location": row["destination_location"],
            "endpoint_kind": row["endpoint_kind"], "typed_body_schema": msg["body"]["schema"],
            "typed_body_sha256": row["typed_body_sha256"], "message": msg, "message_sha256": sha(msg),
            "transfer_commit": transfer_commit, "merge_transfer_organization_receipt_sha256": merge_transfer_receipt}
    if ENDPOINT_HEAD_KEY in row:     # optional; sealed by payload_sha256; absent rows are byte-identical to before
        core[ENDPOINT_HEAD_KEY] = row[ENDPOINT_HEAD_KEY]
    return {**core, "payload_sha256": sha(core), "disposition": ALLOW, "communication_id": cid,
            "boundary_evidence": {"operation": OPERATION, "path_id": pid, "communication_id": cid}}


def verify_typed_source(row: Mapping[str, Any], organization_store: Any = None,
                        repository_store: Any = None) -> dict[str, Any]:
    """The typed source half on this ledger: the sealed pair whose evidence is exactly typed_path_evidence."""
    refused = typed_refusal(row)
    if refused is not None:
        return refused
    organization_store = organization_store if organization_store is not None else mt.org_store()
    repository_store = repository_store if repository_store is not None else mt.repo_store()
    pid, cid = row["path_id"], row["communication_id"]
    base = {"path_id": pid, "communication_id": cid, "half": "source", "typed": True}
    chain = _chain(organization_store)
    by_digest = {d: r for d, r in chain}
    for digest, receipt in chain:
        if not sealed(receipt) or receipt["receipt_sha256"] != digest:
            break
        boundary = mt._boundary(receipt)
        if boundary.get("operation") != OPERATION or boundary.get("path_id") != pid \
                or boundary.get("communication_id") != cid:
            continue
        linked = receipt.get("repo_receipt_sha256")
        repo_receipt = mt._receipt(repository_store, linked)
        evidence = repo_receipt.get("evidence") if sealed(repo_receipt) and isinstance(
            repo_receipt.get("evidence"), Mapping) else {}
        want = typed_path_evidence(row, evidence.get("transfer_commit"),
                                   evidence.get("merge_transfer_organization_receipt_sha256"))
        transfer = by_digest.get(evidence.get("merge_transfer_organization_receipt_sha256"))
        tb = mt._boundary(transfer) if isinstance(transfer, Mapping) else {}
        if not sealed(repo_receipt) or repo_receipt["receipt_sha256"] != linked or evidence != want \
                or not sealed(transfer) or tb.get("operation") != mt.OPERATION \
                or tb.get("merge_commit") != evidence.get("transfer_commit") or tb.get("repository") != repository():
            return refusal(DENY, LINK_UNVERIFIED, "PATH_RECEIPT_LINKS_TO_THE_TRANSFER",
                           "the typed path receipt's repository receipt must carry exactly this typed row's evidence "
                           "and link the sealed main-merge transfer receipt of its transfer commit; the ledger "
                           "contradicts it", "inspect organization receipt " + digest + "; nothing was verified",
                           entrypoint=TYPED_ENTRYPOINT, organization_receipt_sha256=digest, **base)
        return {"schema": RESULT_SCHEMA, "disposition": ALLOW, "half": "source", "typed": True, "path_id": pid,
                "communication_id": cid, "typed_body_schema": row["typed_body"]["schema"],
                "organization_receipt_sha256": digest, "repository_receipt_sha256": linked,
                "transfer_commit": evidence["transfer_commit"],
                "merge_transfer_organization_receipt_sha256": evidence["merge_transfer_organization_receipt_sha256"]}
    return refusal(FAIL_CLOSED, NOT_LEDGERED, "PATH_HAS_A_SOURCE_LEDGER_RECEIPT",
                   "a sealed organization receipt with boundary_evidence.operation " + OPERATION + ", path_id " + str(pid)
                   + " and communication_id " + str(cid) + ", linked to a sealed repository receipt carrying the typed "
                   "evidence", "receipts appear only after the typed row lands on main and " + ENTRYPOINT
                   + " appends it", entrypoint=TYPED_ENTRYPOINT, **base)


def _append_typed(row: Mapping[str, Any], transfer_commit: str, merge_transfer_receipt: str,
                  epoch: Any) -> dict[str, Any]:
    refused = typed_refusal(row)
    if refused is not None:
        return refused
    existing = verify_typed_source(row)
    if existing["disposition"] == ALLOW:
        return {**existing, "replayed": True}
    if existing["disposition"] == DENY:
        return existing
    pid, cid = row["path_id"], row["communication_id"]
    evidence = typed_path_evidence(row, transfer_commit, merge_transfer_receipt)
    try:
        appended, replayed = ingress._append(TRANSITION_CLASS, pid + "@" + cid, evidence, epoch,
                                             operation=OPERATION, profile_id=PROFILE_ID,
                                             boundary_extra={"path_id": pid, "repository": repository(),
                                                             "destination_organization": organization(),
                                                             "transfer_commit": transfer_commit,
                                                             "destination_location": row["destination_location"],
                                                             "endpoint_kind": row["endpoint_kind"],
                                                             "typed_body_schema": row["typed_body"]["schema"]})
    except (ValueError, SystemExit) as exc:
        return refusal(FAIL_CLOSED, mt.WRITER_REFUSED, "LEDGER_WRITER_ADMITS_THE_APPEND",
                       "repair what the ledger writer refused: " + str(exc),
                       "re-run once repaired; nothing was written for this row", entrypoint=TYPED_ENTRYPOINT,
                       path_id=pid, communication_id=cid, typed=True)
    return {"schema": RESULT_SCHEMA, "disposition": ALLOW, "half": "source", "typed": True, "path_id": pid,
            "communication_id": cid, "typed_body_schema": row["typed_body"]["schema"],
            "transfer_commit": transfer_commit, "hb_epoch": epoch, "replayed": replayed,
            "organization_receipt_sha256": appended["organization_receipt"]["receipt_sha256"],
            "repository_receipt_sha256": appended["repository_receipt"]["receipt_sha256"]}


# -- append -------------------------------------------------------------------

def append_transfers(transfer_commit: str, declaration: Path | str = DECLARATION,
                     manifest: Path | str = SNAPSHOT) -> list[dict[str, Any]]:
    paths = {p["path_id"]: p for p in declared_paths(manifest)}
    repo = repository()
    verified = mt.verify_merge_transfer(repo, transfer_commit)
    if verified["disposition"] != ALLOW:
        return [refusal(FAIL_CLOSED, TRANSFER_NOT_LEDGERED, "PATH_TRANSFER_RIDES_A_LEDGERED_MAIN_MERGE",
                        "the transfer commit " + transfer_commit + " must have a VERIFIED main-merge transfer receipt "
                        "before a path receipt links it (" + str(verified.get("failure_code")) + ")",
                        "re-run after the push's main-merge transfer is ledgered; nothing was written",
                        transfer_commit=transfer_commit)]
    epoch, failed = mt.head_epoch(mt.org_store())
    if failed is not None:
        return [{**failed, "schema": RESULT_SCHEMA, "transfer_commit": transfer_commit}]
    results = []
    for row in load_declaration(declaration):
        if is_typed(row):
            results.append(_append_typed(row, transfer_commit, verified["organization_receipt_sha256"], epoch))
            continue
        pid, cid = row.get("path_id"), row.get("communication_id")
        path = paths.get(pid)
        if path is None or path["source"] != organization():
            results.append(refusal(FAIL_CLOSED, PATH_UNDECLARED, "TRANSFER_NAMES_A_DECLARED_PATH_FROM_THIS_ORGANIZATION",
                                   "declare transfers only for conformant paths whose source is " + organization(),
                                   "correct " + str(DECLARATION.relative_to(ROOT)) + "; nothing was written for this row",
                                   path_id=pid, communication_id=cid))
            continue
        existing = verify_source(path, cid)
        if existing["disposition"] == ALLOW:
            results.append({**existing, "replayed": True})
            continue
        if existing["disposition"] == DENY:
            results.append(existing)
            continue
        evidence = path_evidence(path, cid, transfer_commit, verified["organization_receipt_sha256"])
        conform = intr.conform_message(evidence["message"], path["destination"])
        if conform["disposition"] != ALLOW:
            results.append(refusal(FAIL_CLOSED, MESSAGE_REFUSED, "PATH_MESSAGE_CONFORMS_TO_THE_PROTOCOL",
                                   conform["required_evidence_or_repair"], "correct the message; nothing was written",
                                   path_id=pid, communication_id=cid))
            continue
        try:
            appended, replayed = ingress._append(TRANSITION_CLASS, pid + "@" + cid, evidence, epoch,
                                                 operation=OPERATION, profile_id=PROFILE_ID,
                                                 boundary_extra={"path_id": pid, "repository": repo,
                                                                 "destination_organization": path["destination"],
                                                                 "transfer_commit": transfer_commit})
        except (ValueError, SystemExit) as exc:
            results.append(refusal(FAIL_CLOSED, mt.WRITER_REFUSED, "LEDGER_WRITER_ADMITS_THE_APPEND",
                                   "repair what the ledger writer refused: " + str(exc),
                                   "re-run once repaired; nothing was written for this row", path_id=pid,
                                   communication_id=cid))
            continue
        results.append({"schema": RESULT_SCHEMA, "disposition": ALLOW, "half": "source", "path_id": pid,
                        "communication_id": cid, "transfer_commit": transfer_commit, "hb_epoch": epoch,
                        "replayed": replayed,
                        "organization_receipt_sha256": appended["organization_receipt"]["receipt_sha256"],
                        "repository_receipt_sha256": appended["repository_receipt"]["receipt_sha256"]})
    return results


# -- real state ----------------------------------------------------------------

def real_state(declaration: Path | str = DECLARATION, manifest: Path | str = SNAPSHOT,
               organization_store: Any = None, repository_store: Any = None) -> dict[str, Any]:
    declared = load_declaration(declaration)
    transfers = {row["path_id"]: row["communication_id"] for row in declared if not is_typed(row)}
    rows = []
    for path in declared_paths(manifest):
        result = verify_path(path, transfers.get(path["path_id"]), organization_store, repository_store)
        rows.append({"path_id": path["path_id"], "capability": path["capability"],
                     "disposition": result["disposition"], "failure_code": result.get("failure_code"),
                     "failed_predicate": result.get("failed_predicate"), "halves": result["halves"],
                     "classification": result.get("classification")})
    counts = {d: sum(r["disposition"] == d for r in rows) for d in (ALLOW, DENY, FAIL_CLOSED)}
    state = {"schema": "stegverse.intr-path-transfer-real-state/v1", "repository": repository(),
             "counts": counts, "paths": rows}
    typed_rows = [row for row in declared if is_typed(row)]
    if typed_rows:   # absent when no typed row is declared, so the untyped real state is unchanged
        state["typed_transfers"] = []
        for row in typed_rows:
            r = verify_typed_source(row, organization_store, repository_store)
            state["typed_transfers"].append({k: r.get(k) for k in ("path_id", "communication_id", "disposition",
                                                                   "failure_code", "failed_predicate")})
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("paths")
    a = sub.add_parser("append")
    a.add_argument("--transfer-commit", required=True)
    a.add_argument("--out")
    v = sub.add_parser("verify")
    v.add_argument("--out")
    v.add_argument("--expect-source", choices=(ALLOW, FAIL_CLOSED))
    t = sub.add_parser("typed-row", help="print a typed REPOSITORY_LEDGER_GENESIS_OBSERVED declaration row")
    t.add_argument("--repository")
    t.add_argument("--genesis-receipt")
    t.add_argument("--from-readback", help="an organization_ledger_readback.py --repository-namespace output")
    args = parser.parse_args(argv)
    if args.command == "paths":
        print(json.dumps(declared_paths(), indent=2))
        return 0
    if args.command == "typed-row":
        if args.from_readback:
            row = genesis_observed_row_from_readback(json.loads(Path(args.from_readback).read_text()))
        elif args.repository and args.genesis_receipt:
            row = genesis_observed_row(args.repository, args.genesis_receipt)
        else:
            parser.error("typed-row needs --from-readback, or --repository and --genesis-receipt")
        refused = row if row.get("disposition") in (FAIL_CLOSED, DENY) else typed_refusal(row)
        print(json.dumps(refused or row, indent=2, sort_keys=True))
        return 0 if refused is None else 1
    if args.command == "append":
        result: Any = append_transfers(args.transfer_commit)
    else:
        result = real_state()
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.command == "append":
        return 0 if all(r["disposition"] == ALLOW for r in result) else 1
    if args.expect_source:
        mine = [p for p in result["paths"] if p["path_id"].startswith(organization() + "->")]
        return 0 if mine and all(p["halves"]["source"] == args.expect_source for p in mine) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
