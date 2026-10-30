#!/usr/bin/env python3
"""``sv_check_receipt`` -- append one NWI-S1 check receipt to the organization ledger.

Port of the StegVerse-Labs/.github operation of the same name to this organization's own writer
(StegVerse-org/.github#163/#167): a receipt belongs on the ledger of the organization that owns the checked repository, and
each organization keeps its own ledger, so native SV_ISSUEs can be derived from it here (sv_change_admit_append.py).

The NWI-S1 verifier (SV-LLM/.github#46) emits a ``stegverse.sv_check_receipt.v1``
receipt at an exact head. It becomes a ledger receipt only when this writer
operation appends it to refs/stegverse/organization-ledger
(REQUIRED_CHECK_RECEIPTS_ARE_S1_VERIFIER_OUTPUTS_APPENDED_BY_ORG_WRITER).

Layout. These are the existing receipts, unchanged:
  * repository receipt (``stegverse.repo-transition-receipt/v1``, emit.py): ``$.evidence`` IS the check
    receipt, a complete and valid sv-check-receipt.v1 object, self-identified by ``$.evidence.schema``.
    No other marker or field is added.
  * organization receipt (``stegverse.organization-transition-receipt/v1``, aggregate_repo_transition.py):
    ``boundary_evidence.operation == "sv_check_receipt"``. Its ``repo_receipt_sha256`` names the repository
    receipt, which the organization ledger keeps beside it at ``source-receipts/<hex>.json``
    (ledger_store.source_key). The organization receipt itself is at ``receipts/<hex>.json``.
  * Time: ``hb_reference`` is built from the supplied int epoch (>= 32), so derived_from_clock is False. The append epoch and
    the check receipt's own ``hb_epoch`` must both pass this writer's shared rule
    resident-runtime/aggregate_repo_transition.py::supplied_epoch_failure (SHARED_RULE_SHA256 7f36f0e6...) and must be equal. Unobserved -> FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED,
    absent/null/""/"null"/UNKNOWN_NOT_AUTHENTICALLY_OBSERVED -> FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED; any other malformed or
    different value -> DENY HB_EPOCH_MISMATCH; in both cases before anything is written. A clock-derived epoch (only
    possible on a stored hb_reference) is FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED. A clock epoch is never written.
  * Command: P1's own rule, sv_work_items.command_declared (row checks plus the stage manifests' exit_gate_check
    built-ins). An undeclared command is FAIL_CLOSED CHECK_COMMAND_UNDECLARED before any append; the one exception is
    the verifier's own FAIL_CLOSED CHECK_COMMAND_UNDECLARED receipt (P1 validate_check_receipt).
  * Stage-gate receipts (a check id a P1 stage manifest declares as exit_gate_check, e.g. nwi-s0-exit-gate, or any
    receipt supplied with a stage-evaluation subject) bind to the subject, not a change: change_digest =
    sv_work_items.stage_evaluation_digest(subject), head_sha = subject.evaluated_commit. They are validated with P1's
    validate_gate_receipt(receipt, subject, readback, fixture_mode=False) and appended only into the subject
    repository's own ledger (subject.repository == the writer's repository), at receipts/<org hex>.json plus
    source-receipts/<repo hex>.json. Any failure is a six-field FAIL_CLOSED before any write.
  * P1 readers: loaded from tests/vendor/p1_f28c3a76/ (P1 #3264 head f28c3a76, P1's layout mirrored; the pinned kernel.py,
    node_store.py and worker-claim script are vendored beside it, this checkout's own kernel.py is not the pinned one), verified
    file-by-file against P1's manifest data/sv-work-items/contract-pins.json (pinned by its sha256) before use; any
    mismatch refuses every append (FAIL_CLOSED P1_CONTRACT_PINS_UNVERIFIED).

The append path is the same two-level writer the push-receipt operation uses (ingress._ledger_write over
repository_ledger.append and then organization_ledger.append, see _append_two_level), under the writer workflow's
ORGANIZATION_LEDGER_LOCK concurrency group. intr_destination_ingress.py itself is not edited. Validation happens before any write. Every refusal is a
six-field FAIL_CLOSED with consequence_committed false, and nothing is written
for it. Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]

OPERATION_ID = "sv_check_receipt"
TRANSITION_CLASS = "SV_CHECK_RECEIPT_APPEND"
PROFILE_ID = "org-ledger-writer"
CHECK_RECEIPT_SCHEMA_ID = "stegverse.sv_check_receipt.v1"
P1_HEAD = "f28c3a76a8b495d7a815a7ecd513c4d4dc90c9c7"
P1_VENDOR = ROOT / "tests" / "vendor" / "p1_f28c3a76"
P1_MANIFEST = "data/sv-work-items/contract-pins.json"
P1_MANIFEST_SHA256 = "5c0c98d4349274b547a7c4ba8154e77e930e55e0a8dc1827344229661957a4cb"  # blob ef2ff1e8
# the P1 files this operation uses (paths as in P1's tree and in the manifest)
P1_USED_FILES = ("resident-runtime/sv_work_items.py", "resident-runtime/sv_push_receipt.py",
                 "data/sv-work-items/required-checks.json",
                 "data/sv-work-items/lifecycle-transitions.json", "schemas/sv-check-receipt.v1.schema.json",
                 "data/sv-work-items/stages/NWI-S0.json", "data/sv-work-items/stages/NWI-S1.json",
                 "data/sv-work-items/stages/NWI-S2.json", "data/sv-work-items/stages/NWI-S3.json",
                 "data/sv-work-items/stages/NWI-S4.json",
                 "org-kernel/kernel.py", "org-kernel/node_store.py", "scripts/project_worker_claim_into_canonical_task.py")
CHECK_RECEIPT_SCHEMA_PATH = P1_VENDOR / "schemas" / "sv-check-receipt.v1.schema.json"
CHECK_RECEIPT_SCHEMA_BLOB = "a4934cc1afb5f9c65d12f4ab5ae29f462b76b3f3"
RESULT_SCHEMA = "stegverse.org-sv-check-receipt-append-result/v1"
EPOCH_MISMATCH = "HB_EPOCH_MISMATCH"
READBACK_SCHEMA = "stegverse.org-sv-check-receipt-readback/v1"
OWNING_GOAL = "StegVerse-org/.github#163 (REQUIRED_CHECK_RECEIPTS_ARE_S1_VERIFIER_OUTPUTS_APPENDED_BY_ORG_WRITER)"
RETRY = "resident-runtime/sv_check_receipt_append.py::append_check_receipt"
HB_ANCHOR_EPOCH = 32  # org-kernel/kernel.py HB_ANCHOR_EPOCH
P1_REQUIRED_CHECKS_PATH = "data/sv-work-items/required-checks.json"
GATE_LEDGER_PREDICATE = "STAGE_GATE_RECEIPT_APPENDS_TO_THE_SUBJECT_REPOSITORY_LEDGER"
CHECK_COMMAND_PREDICATE = "CHECK_HAS_OFFLINE_COMMAND"
EPOCH_SOURCE_PREDICATE = "ADMISSION_HB_EPOCH_IS_THE_BOUND_LEDGER_HEAD_EPOCH"
EPOCH_TIE_PREDICATE = "CHECK_RECEIPT_HB_EPOCH_EQUALS_APPEND_HB_EPOCH"
# The shared supplied-epoch rule: this writer's copy (resident-runtime/aggregate_repo_transition.py), pinned by the sha256 of its
# source, the digest sv_push_receipt_append.py and intr_hop.py pin.
SHARED_RULE_SHA256 = "7f36f0e697cadc91acd27af121eee3fc460b887ec67cfa258727bfccec0ca5f8"
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
IDEMPOTENT_ON = ("schema", "check_id", "disposition", "change_digest", "head_sha", "hb_epoch", "verifier_ref")
_ANNOTATIONS = {"$id", "$schema", "title", "description"}
_KEYWORDS = {"type", "required", "properties", "additionalProperties", "const", "enum", "pattern",
             "minLength", "allOf", "if", "then"}


def _module(name: str, relative: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ingress = _module("intr_destination_ingress_sv_check", "resident-runtime/intr_destination_ingress.py")
sha = ingress.sha
epoch_rule = ingress.organization_ledger.supplied_epoch_failure


def p1_pin_failure() -> str | None:
    """None when the manifest has its pinned sha256 and every used vendored file has its manifest sha256."""
    try:
        raw = (P1_VENDOR / P1_MANIFEST).read_bytes()
    except OSError as exc:
        return "manifest unreadable: %s" % exc
    if hashlib.sha256(raw).hexdigest() != P1_MANIFEST_SHA256:
        return "manifest sha256 is not the pinned " + P1_MANIFEST_SHA256
    files = json.loads(raw)["files"]
    for rel in P1_USED_FILES:
        pin = (files.get(rel) or {}).get("sha256")
        try:
            have = "sha256:" + hashlib.sha256((P1_VENDOR / rel).read_bytes()).hexdigest()
        except OSError:
            return rel + " is not vendored"
        if pin is None or have != pin:
            return rel + " does not match its manifest digest"
    return None


P1_PIN_FAILURE = p1_pin_failure()
_P1: dict[str, Any] = {}


def p1_readers():
    """P1's sv_work_items at P1_HEAD, run over a temporary root holding the vendored files in P1's layout (this checkout's own
    org-kernel/kernel.py is not the pinned one, so the vendored kernel.py, node_store.py and worker-claim script are used).
    Refuses (RuntimeError) unless the manifest pins verify."""
    if "wi" in _P1:
        return _P1["wi"]
    if P1_PIN_FAILURE is not None:
        raise RuntimeError(P1_PIN_FAILURE)
    import shutil
    import tempfile
    import atexit
    root = Path(tempfile.mkdtemp(prefix="p1_f28c3a76_"))
    atexit.register(shutil.rmtree, root, True)
    for rel in P1_USED_FILES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(P1_VENDOR / rel, root / rel)
    name = "sv_work_items_p1_f28c3a76"
    spec = importlib.util.spec_from_file_location(name, root / "resident-runtime" / "sv_work_items.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _P1["wi"] = module
    return module


REQUIRED_CHECKS = json.loads((P1_VENDOR / P1_REQUIRED_CHECKS_PATH).read_text(encoding="utf-8"))


def supplied_epoch_rule_sha256(source: str) -> str | None:
    if "def supplied_epoch_failure" not in source:
        return None
    a = source.index("def supplied_epoch_failure")
    b = source.find("\ndef ", a + 5)
    return hashlib.sha256(source[a:b if b >= 0 else len(source)].rstrip().encode("utf-8")).hexdigest()


KERNEL_RULE_SHA256 = hashlib.sha256(inspect.getsource(epoch_rule).encode("utf-8")).hexdigest()
CHECK_RECEIPT_SCHEMA = json.loads(CHECK_RECEIPT_SCHEMA_PATH.read_text(encoding="utf-8"))
if CHECK_RECEIPT_SCHEMA.get("$id") != CHECK_RECEIPT_SCHEMA_ID:
    raise SystemExit("pinned sv-check-receipt schema id mismatch")


class SchemaUnsupported(Exception):
    pass


def schema_errors(instance: Any, schema: Mapping[str, Any], pointer: str = "") -> list[str]:
    """Validate against the pinned sv-check-receipt.v1 schema (the JSON Schema subset it uses). An unknown keyword
    raises instead of being skipped silently, so a schema change cannot loosen this check unnoticed."""
    unknown = set(schema) - _KEYWORDS - _ANNOTATIONS
    if unknown:
        raise SchemaUnsupported(", ".join(sorted(unknown)))
    out: list[str] = []
    t = schema.get("type")
    if t == "object" and not isinstance(instance, dict):
        return [pointer + ": type object"]
    if t == "string" and not isinstance(instance, str):
        return [pointer + ": type string"]
    if t not in (None, "object", "string"):
        raise SchemaUnsupported("type " + str(t))
    if "const" in schema and instance != schema["const"]:
        out.append(pointer + ": const")
    if "enum" in schema and instance not in schema["enum"]:
        out.append(pointer + ": enum")
    if isinstance(instance, str):
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            out.append(pointer + ": pattern")
        if "minLength" in schema and len(instance) < schema["minLength"]:
            out.append(pointer + ": minLength")
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                out.append(pointer + "/" + key + ": required")
        props = schema.get("properties", {})
        for key, value in instance.items():
            if key in props:
                out += schema_errors(value, props[key], pointer + "/" + key)
            elif schema.get("additionalProperties") is False:
                out.append(pointer + "/" + key + ": additionalProperties")
    for sub in schema.get("allOf", []):
        out += schema_errors(instance, sub, pointer)
    if "if" in schema:
        if not schema_errors(instance, schema["if"], pointer):
            out += schema_errors(instance, schema.get("then", {}), pointer)
    return out


def refusal(code: str, predicate: str, repair: str, next_attempt: str, **detail: Any) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "operation": OPERATION_ID, "disposition": "FAIL_CLOSED",
            "failure_code": code, "failed_predicate": predicate, "required_evidence_or_repair": repair,
            "retry_entrypoint": RETRY, "owning_existing_goal": OWNING_GOAL, "next_attempt": next_attempt,
            "consequence_committed": False, "authority_effect": "NONE_REFUSAL_ONLY", **detail}


def check_payload(receipt: Any) -> dict[str, Any] | None:
    """None when `receipt` is a complete, valid, self-identified sv-check-receipt.v1; otherwise the refusal."""
    if not isinstance(receipt, dict) or receipt.get("schema") != CHECK_RECEIPT_SCHEMA_ID:
        return refusal("LEDGER_EVIDENCE_NOT_A_CHECK_RECEIPT", "ORGANIZATION_LEDGER_EVIDENCE_IS_A_SELF_IDENTIFYING_CHECK_RECEIPT",
                       "supply the NWI-S1 verifier's receipt object whose $.schema is " + CHECK_RECEIPT_SCHEMA_ID,
                       "after the verifier's receipt is supplied as emitted; nothing was written")
    try:
        errors = schema_errors(receipt, CHECK_RECEIPT_SCHEMA)
    except SchemaUnsupported as exc:
        return refusal("SV_CHECK_RECEIPT_SCHEMA_UNSUPPORTED", "CHECK_RECEIPT_VALIDATES_AGAINST_PINNED_SCHEMA",
                       "the pinned schema uses a keyword this validator does not implement: " + str(exc),
                       "after the validator covers the pinned schema; nothing was written")
    if errors:
        return refusal("LEDGER_EVIDENCE_NOT_A_CHECK_RECEIPT", "CHECK_RECEIPT_VALIDATES_AGAINST_PINNED_SCHEMA",
                       "supply a complete, valid " + CHECK_RECEIPT_SCHEMA_ID + " receipt (P1 schemas/sv-check-receipt.v1.schema.json, vendored blob a4934cc1)",
                       "after the verifier re-emits a valid receipt; nothing was written", schema_errors=errors)
    return None


def command_declared(check_id: str) -> bool:
    """P1's rule itself (sv_work_items.command_declared @f28c3a76): an argv in the row, or a verifier built-in naming
    the check id, the row's checks merged with the stage manifests' exit_gate_check declarations (GATE_CHECKS)."""
    return bool(p1_readers().command_declared(check_id))


def _command_refusal(receipt: Mapping[str, Any]) -> dict[str, Any] | None:
    if command_declared(receipt["check_id"]):
        return None
    if receipt["disposition"] == "FAIL_CLOSED" and receipt.get("failure_code") == "CHECK_COMMAND_UNDECLARED":
        return None  # the verifier's own six-field refusal for an undeclared command is the receipt to ledger
    return refusal("CHECK_COMMAND_UNDECLARED", CHECK_COMMAND_PREDICATE,
                   "neither the row " + P1_REQUIRED_CHECKS_PATH + " nor a stage manifest's exit_gate_check declares a command for "
                   + receipt["check_id"] + "; the only receipt that can be appended for it is the verifier's FAIL_CLOSED CHECK_COMMAND_UNDECLARED",
                   "after the row declares the command, or the verifier emits CHECK_COMMAND_UNDECLARED; nothing was written",
                   check_id=receipt["check_id"], receipt_disposition=receipt["disposition"])


def _unobserved(detail: str, **extra: Any) -> dict[str, Any]:
    return refusal("HB_EPOCH_SOURCE_UNOBSERVED", EPOCH_SOURCE_PREDICATE,
                   "supply the append epoch as an integer and carry the same supplied epoch in the check receipt; both must "
                   "pass resident-runtime/aggregate_repo_transition.py::supplied_epoch_failure (SHARED_RULE_SHA256 " + SHARED_RULE_SHA256 + ")",
                   "after a supplied epoch is observed on both; nothing was written",
                   detail=detail, shared_rule_sha256=SHARED_RULE_SHA256, epoch_storage="hb_reference.epoch of the stored receipt",
                   **extra)


UNKNOWN_SENTINEL = "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"
# P1 sv_work_items.SUPPLIED_EPOCH_UNOBSERVED_VALUES @ae8b105d (unchanged at f28c3a76): an epoch-source field holding one of these is not observed.
UNOBSERVED_EPOCH_VALUES = (None, "", "null", UNKNOWN_SENTINEL)


def _unobserved_value(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value in UNOBSERVED_EPOCH_VALUES[1:])


def _mismatch(detail: str, **extra: Any) -> dict[str, Any]:
    out = refusal(EPOCH_MISMATCH, EPOCH_TIE_PREDICATE,
                  "append the receipt at the epoch it carries: hb_epoch input (an int) = $.evidence.hb_epoch (ASCII digits), "
                  "both passing resident-runtime/aggregate_repo_transition.py::supplied_epoch_failure (SHARED_RULE_SHA256 " + SHARED_RULE_SHA256 + ")",
                  "commit the ingest request again with the receipt's own supplied epoch; nothing was written",
                  detail=detail, shared_rule_sha256=SHARED_RULE_SHA256, **extra)
    out["disposition"] = "DENY"
    return out


def _epoch_refusal(receipt: Mapping[str, Any], hb_epoch: Any) -> dict[str, Any] | None:
    """The epoch tie (orchestrator ruling, refined 15:59Z):
      FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED: the append epoch or the receipt's hb_epoch (both are epoch-source fields, so
        no optional cross-check / HB_EPOCH_NOT_CROSS_CHECKED applies) is absent, JSON null, "", "null" or the sentinel
        UNKNOWN_NOT_AUTHENTICALLY_OBSERVED, checked before the shared rule as in P1 verify_admission_hb_epoch (@ae8b105d, unchanged at f28c3a76);
        or the loaded kernel rule is not the pinned shared rule.
      DENY HB_EPOCH_MISMATCH: any other value failing the shared rule (bool, float, coerced text, < 32), an append epoch
        that is not an int, a receipt epoch that is not ASCII text (as P1 verify_admission_hb_epoch), or unequal values.
    A clock-derived epoch can only appear on a stored hb_reference (the sealed source); see _stored_epoch_refusal."""
    if KERNEL_RULE_SHA256 != SHARED_RULE_SHA256:
        return _unobserved("resident-runtime/aggregate_repo_transition.py::supplied_epoch_failure is not the pinned shared rule",
                           kernel_rule_sha256=KERNEL_RULE_SHA256)
    mine = receipt.get("hb_epoch")
    for side, value in (("append epoch", hb_epoch), ("check receipt hb_epoch", mine)):
        if _unobserved_value(value):
            return _unobserved(side + " is absent, null, '', 'null' or " + UNKNOWN_SENTINEL, side=side, value=repr(value))
    bad = epoch_rule(hb_epoch)
    if bad is not None or type(hb_epoch) is not int:
        return _mismatch("append epoch " + repr(hb_epoch) + ": " + (bad[0] + ": " + bad[1] if bad else "not an int"),
                         hb_epoch=repr(hb_epoch), receipt_hb_epoch=repr(mine))
    bad = epoch_rule(mine)
    if bad is not None or not isinstance(mine, str):
        return _mismatch("check receipt hb_epoch " + repr(mine) + ": " + (bad[0] + ": " + bad[1] if bad else "not ASCII text"),
                         hb_epoch=hb_epoch, receipt_hb_epoch=repr(mine))
    if int(mine) != hb_epoch:
        return _mismatch("the receipt's epoch differs from the append epoch", hb_epoch=hb_epoch, receipt_hb_epoch=mine)
    return None


def _stored_epoch_refusal(row: Any, hb_epoch: int) -> dict[str, Any] | None:
    """A stored receipt: sealed, and hb_reference.epoch (kernel.py:68-74) an int that passes the shared rule with its
    reference (derived_from_clock exactly false) and equals the append epoch. This is the sealed source side: unsealed,
    clock-derived or non-int -> FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED (as P1 base_ledger_head_epoch -> None and the
    readback-slot refusals of verify_admission_hb_epoch); a different int -> DENY HB_EPOCH_MISMATCH."""
    if not _self_verifies(row):
        return _unobserved("a stored receipt does not verify against its body")
    hb = row.get("hb_reference")
    ep = hb.get("epoch") if isinstance(hb, dict) else None
    if type(ep) is not int or epoch_rule(ep, hb) is not None or hb.get("derived_from_clock") is not False:
        return _unobserved("a stored hb_reference.epoch is not a supplied int epoch", receipt_sha256=row.get("receipt_sha256"))
    if ep != hb_epoch:
        out = refusal(EPOCH_MISMATCH, EPOCH_TIE_PREDICATE, "the stored receipt carries another epoch than this append",
                      "none; the recorded receipt stands", receipt_sha256=row.get("receipt_sha256"), stored_epoch=ep, hb_epoch=hb_epoch)
        out["disposition"] = "DENY"
        return out
    return None


def _p1_refusal(record: Mapping[str, Any]) -> dict[str, Any]:
    out = {"schema": RESULT_SCHEMA, "operation": OPERATION_ID, **record}
    out.update({"consequence_committed": False, "authority_effect": "NONE_REFUSAL_ONLY"})
    return out


def _gate_refusal(receipt: Mapping[str, Any], subject: Any, readback: Any, ledger_repository: Any) -> dict[str, Any] | None:
    """A stage-gate receipt: P1 validate_gate_receipt (shape, subject digest and evaluated_commit binding, the Labs#3266
    readback epoch of the subject's own repository), then the subject repository is the ledger being written."""
    wi = p1_readers()
    try:
        wi.validate_gate_receipt(receipt, subject, readback, fixture_mode=False)
    except wi.Refusal as exc:
        return _p1_refusal(exc.record)
    except (KeyError, TypeError, AttributeError) as exc:
        return refusal("STAGE_EVALUATION_SUBJECT_UNOBSERVED", "STAGE_GATE_DECLARATION_IS_COMPLETE",
                       "supply the stage-evaluation subject {repository, stage_id, manifest_blob, evaluated_commit, base_ref}",
                       "after the subject is supplied; nothing was written", detail=f"{type(exc).__name__}: {exc}")
    if not isinstance(ledger_repository, str) or subject.get("repository") != ledger_repository:
        return refusal("STAGE_EVALUATION_LEDGER_NOT_SUBJECT_REPOSITORY", GATE_LEDGER_PREDICATE,
                       "append a stage-evaluation receipt only into the subject repository's own refs/stegverse/organization-ledger "
                       "(subject.repository == the writer's repository)", "commit the ingest request in the subject repository; nothing was written",
                       subject_repository=subject.get("repository"), ledger_repository=ledger_repository)
    return None


def _append_two_level(packet_id: str, evidence: Mapping[str, Any], hb_epoch: int | None,
                      predecessor: str, successor: str, boundary: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    """Both levels for this operation's own digests and boundary evidence. A replay of the same receipt returns the recorded
    pair (the repository ledger's idempotent_on fields); the organization receipt takes the repository receipt's epoch."""
    repository, organization = ingress.repository_ledger, ingress.organization_ledger
    transition_id = TRANSITION_CLASS + ":" + packet_id
    store = repository.ledger_store.open_store(repository.lr())
    prior = ingress._ledger_write(repository.recorded, store, store.get(repository.ledger_store.HEAD_KEY), transition_id,
                                  TRANSITION_CLASS)
    repository_receipt = ingress._ledger_write(repository.append, transition_id, TRANSITION_CLASS, predecessor, successor,
                                               dict(evidence), "NONE", hb_epoch=hb_epoch, idempotent_on=tuple(IDEMPOTENT_ON))
    organization_receipt = ingress._ledger_write(
        organization.append, repository_receipt, "REPO_STATE_PROPAGATION", predecessor, successor, dict(boundary), "NONE",
        hb_epoch=repository_receipt["hb_reference"]["epoch"], idempotent=True)
    return ({"repository_receipt": repository_receipt, "organization_receipt": organization_receipt},
            prior is not None)


def admit_check_receipt(receipt: Any, *, hb_epoch: Any, subject: Any = None, readback: Any = None,
                        ledger_repository: Any = None) -> dict[str, Any]:
    """The admission checks alone (pins, schema, supplied epoch and its tie, declared command, stage-gate binding). Reads no
    ledger and writes nothing, so the PR-facing check can run it on a committed request without appending."""
    if P1_PIN_FAILURE is not None:
        return refusal("P1_CONTRACT_PINS_UNVERIFIED", "VENDORED_P1_FILES_MATCH_THE_PINNED_CONTRACT_MANIFEST",
                       "re-vendor P1's files against data/sv-work-items/contract-pins.json (sha256 " + P1_MANIFEST_SHA256 + ")",
                       "after the vendored files match the pinned manifest; nothing was written", detail=P1_PIN_FAILURE)
    if not isinstance(receipt, dict) or receipt.get("schema") != CHECK_RECEIPT_SCHEMA_ID:
        return check_payload(receipt)
    bad = _epoch_refusal(receipt, hb_epoch) or check_payload(receipt) or _command_refusal(receipt)
    if bad is None and (receipt["check_id"] in p1_readers().GATE_CHECKS or subject is not None):
        bad = _gate_refusal(receipt, subject, readback, ledger_repository)
    if bad is not None:
        return bad
    return {"schema": RESULT_SCHEMA, "operation": OPERATION_ID, "disposition": "ALLOW", "admitted": True, "writes": False,
            "check_id": receipt["check_id"], "check_disposition": receipt["disposition"], "hb_epoch": hb_epoch,
            "check_receipt_sha256": sha(receipt), "authority_effect": "NONE_ADMISSION_ONLY"}


def append_check_receipt(receipt: Any, *, hb_epoch: Any, subject: Any = None, readback: Any = None,
                         ledger_repository: Any = None) -> dict[str, Any]:
    """Append `receipt` as the repository receipt's $.evidence and aggregate it into the organization ledger.
    A stage-gate receipt also needs the stage-evaluation `subject`, the Labs#3266 `readback` and the writer's
    `ledger_repository`."""
    if P1_PIN_FAILURE is not None:
        return refusal("P1_CONTRACT_PINS_UNVERIFIED", "VENDORED_P1_FILES_MATCH_THE_PINNED_CONTRACT_MANIFEST",
                       "re-vendor P1's files against data/sv-work-items/contract-pins.json (sha256 " + P1_MANIFEST_SHA256 + ")",
                       "after the vendored files match the pinned manifest; nothing was written", detail=P1_PIN_FAILURE)
    if not isinstance(receipt, dict) or receipt.get("schema") != CHECK_RECEIPT_SCHEMA_ID:
        return check_payload(receipt)
    bad = _epoch_refusal(receipt, hb_epoch) or check_payload(receipt) or _command_refusal(receipt)
    if bad is None and (receipt["check_id"] in p1_readers().GATE_CHECKS or subject is not None):
        bad = _gate_refusal(receipt, subject, readback, ledger_repository)
    if bad is not None:
        return bad
    payload_sha256 = sha(receipt)
    packet_id = payload_sha256.split(":", 1)[1]
    successor = sha({"operation": OPERATION_ID, "check_receipt_sha256": payload_sha256,
                     "check_id": receipt["check_id"], "disposition": receipt["disposition"],
                     "change_digest": receipt["change_digest"], "head_sha": receipt["head_sha"]})
    boundary = {"operation": OPERATION_ID, "profile_id": PROFILE_ID, "disposition": receipt["disposition"],
                "check_id": receipt["check_id"], "check_receipt_sha256": payload_sha256,
                "change_digest": receipt["change_digest"], "head_sha": receipt["head_sha"]}
    try:
        # Resolve both stores before the first write, so a missing ledger location refuses with nothing written.
        ingress.repository_ledger.lr()
        ingress.organization_ledger.ledger_root()
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - every resolver refusal is reported, none is retried
        return refusal("ORGANIZATION_LEDGER_LOCATION_UNRESOLVED", "WRITER_LEDGER_LOCATIONS_ARE_SUPPLIED",
                       "supply the repository and organization ledger locations the writer workflow declares",
                       "after the ledger locations resolve; nothing was written", detail=f"{type(exc).__name__}: {exc}")
    try:
        appended, replayed = _append_two_level(packet_id, dict(receipt), hb_epoch, payload_sha256,
                                               successor, boundary)
    except (ValueError, SystemExit) as exc:
        if str(exc) == "ledger_receipt_collision":
            return refusal("CHECK_RECEIPT_PACKET_COLLISION", "ONE_PACKET_ID_BINDS_ONE_CHECK_RECEIPT",
                           "the recorded transition for this receipt digest stands; nothing new is minted",
                           "none; the recorded receipt is the evidence", detail=str(exc))
        return refusal("ORGANIZATION_LEDGER_APPEND_REFUSED", "CHECK_RECEIPT_APPEND_COMPLETES_AT_BOTH_LEVELS",
                       "repair the refusal the ledger reported; the writer publishes only when both receipts exist",
                       "after the ledger refusal is repaired", detail=f"{type(exc).__name__}: {getattr(exc, 'code', None) or exc}")
    repository = appended["repository_receipt"]
    organization = appended["organization_receipt"]
    for row in (repository, organization):
        bad = _stored_epoch_refusal(row, hb_epoch)
        if bad is not None:
            bad["consequence_committed"] = "LOCAL_ONLY_NOT_PUBLISHED"  # the writer workflow pushes nothing after a refusal
            return bad
    return {
        "schema": RESULT_SCHEMA,
        "operation": OPERATION_ID,
        "disposition": "ALLOW",
        "transition_class": TRANSITION_CLASS,
        "transition_replayed": replayed,
        "check_receipt_sha256": payload_sha256,
        "check_id": receipt["check_id"],
        "check_disposition": receipt["disposition"],
        "repository_receipt_sha256": repository["receipt_sha256"],
        "organization_receipt_sha256": organization["receipt_sha256"],
        "organization_receipt_key": ingress.repository_ledger.ledger_store.receipt_key(organization["receipt_sha256"]),
        "repository_receipt_source_key": ingress.repository_ledger.ledger_store.source_key(repository["receipt_sha256"]),
        "hb_epoch": repository["hb_reference"]["epoch"],
        "organization_receipt_preserves_repository_receipt": organization.get("repo_receipt_sha256") == repository["receipt_sha256"],
        "consequence_committed": True,
        "authority_effect": "NONE",
    }


def _self_verifies(doc: Any) -> bool:
    return isinstance(doc, dict) and doc.get("receipt_sha256") == sha({k: v for k, v in doc.items() if k != "receipt_sha256"})


def bind_check_receipt(location: str, result: Mapping[str, Any]) -> dict[str, Any]:
    """Read the appended pair back from `location` (a fresh fetch of the ref): sealed, in place, linked, self-identified."""
    store_mod = ingress.repository_ledger.ledger_store
    store = store_mod.open_store(store_mod.parse_locator(location))
    org_sha = result.get("organization_receipt_sha256")
    repo_sha = result.get("repository_receipt_sha256")
    org = store.get(store_mod.receipt_key(org_sha)) if isinstance(org_sha, str) else None
    repo = store.get(store_mod.source_key(repo_sha)) if isinstance(repo_sha, str) else None
    checks = {
        "organization_receipt_sealed": _self_verifies(org) and org.get("receipt_sha256") == org_sha,
        "repository_receipt_sealed_beside_it": _self_verifies(repo) and repo.get("receipt_sha256") == repo_sha,
        "organization_receipt_names_repository_receipt": isinstance(org, dict) and org.get("repo_receipt_sha256") == repo_sha,
        "operation_is_sv_check_receipt": isinstance(org, dict) and (org.get("boundary_evidence") or {}).get("operation") == OPERATION_ID,
        "evidence_is_a_valid_check_receipt": isinstance(repo, dict) and check_payload(repo.get("evidence")) is None,
        "evidence_is_the_appended_receipt": isinstance(repo, dict) and sha(repo.get("evidence")) == result.get("check_receipt_sha256"),
        "epoch_supplied_not_clock": all(isinstance(r, dict) and (r.get("hb_reference") or {}).get("derived_from_clock") is False
                                        for r in (org, repo)),
    }
    if not all(checks.values()):
        failed = sorted(k for k, v in checks.items() if not v)
        return {"schema": READBACK_SCHEMA, "disposition": "FAIL_CLOSED", "failure_code": "SV_CHECK_RECEIPT_READBACK_FAILED",
                "failed_predicate": failed[0].upper(), "required_evidence_or_repair": "the fresh fetch must hold the sealed pair: "
                + ", ".join(failed), "retry_entrypoint": "resident-runtime/sv_check_receipt_append.py::bind_check_receipt",
                "owning_existing_goal": OWNING_GOAL, "next_attempt": "after a fresh fetch of the published ref",
                "checks": checks, "readback_writes": False, "authority_effect": "NONE_READBACK_ONLY"}
    return {"schema": READBACK_SCHEMA, "disposition": "ALLOW", "location": location, "checks": checks,
            "organization_receipt_sha256": org_sha, "repository_receipt_sha256": repo_sha,
            "readback_writes": False, "authority_effect": "NONE_READBACK_ONLY"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("append")
    a.add_argument("--check-receipt", type=Path, required=True, help="the verifier's sv-check-receipt.v1 JSON file")
    a.add_argument("--hb-epoch", required=True, help="supplied epoch, ASCII digits >= 32; never from a clock")
    a.add_argument("--subject", type=Path, default=None, help="stage-evaluation subject JSON (stage-gate receipts)")
    a.add_argument("--readback", type=Path, default=None, help="Labs#3266 base-state readback JSON (stage-gate receipts)")
    a.add_argument("--ledger-repository", default=None, help="the repository whose ledger is written (GITHUB_REPOSITORY)")
    a.add_argument("--out", type=Path, default=None)
    m = sub.add_parser("admit", help="the admission checks alone; reads no ledger and writes nothing")
    m.add_argument("--check-receipt", type=Path, required=True)
    m.add_argument("--hb-epoch", required=True)
    m.add_argument("--subject", type=Path, default=None)
    m.add_argument("--readback", type=Path, default=None)
    m.add_argument("--ledger-repository", default=None)
    m.add_argument("--out", type=Path, default=None)
    r = sub.add_parser("readback")
    r.add_argument("--location", required=True)
    r.add_argument("--result", type=Path, required=True)
    r.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    if args.cmd in ("append", "admit"):
        epoch = int(args.hb_epoch) if re.fullmatch(r"[0-9]+", args.hb_epoch or "") else args.hb_epoch
        try:
            receipt = json.loads(args.check_receipt.read_text(encoding="utf-8"))
            subject = json.loads(args.subject.read_text(encoding="utf-8")) if args.subject else None
            readback = json.loads(args.readback.read_text(encoding="utf-8")) if args.readback else None
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            out = refusal("LEDGER_EVIDENCE_NOT_A_CHECK_RECEIPT", "ORGANIZATION_LEDGER_EVIDENCE_IS_A_SELF_IDENTIFYING_CHECK_RECEIPT",
                          "supply the verifier's receipt as one JSON object", "after a readable receipt is supplied; nothing was written",
                          detail=f"{type(exc).__name__}: {exc}")
        else:
            out = (append_check_receipt if args.cmd == "append" else admit_check_receipt)(
                receipt, hb_epoch=epoch, subject=subject, readback=readback, ledger_repository=args.ledger_repository)
    else:
        out = bind_check_receipt(args.location, json.loads(args.result.read_text(encoding="utf-8")))
    text = json.dumps(out, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(json.dumps(out, sort_keys=True))
    return 0 if out.get("disposition") == "ALLOW" else 1


if __name__ == "__main__":
    sys.exit(main())
