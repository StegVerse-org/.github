#!/usr/bin/env python3
"""Consume TVC's org conformance test receipt from the organization ledger chain.

Ported from StegVerse-Labs/.github#3332 scripts/tvc_conformance_receipt.py
(head acc4adf6). The logic is unchanged; only the identities differ.

StegVerse-org/.github's tests/test_origin_attestation_tvc_conformance.py
exercises TVC's signer and verifier. This repository cannot read the private
TVC repository (github_token_runtime_authority is NONE), so the test runs in
StegVerse-Labs/TVC's own CI. That CI is the run block `tvc-conformance-receipt`
in TVC's tools/tasks/task_catalog.json, hosted by the existing
merge-admitted-pull-request-validation.yml workflow (StegVerse-Labs/TVC#539).
It fetches this repository anonymously at an exact commit, runs the set with
STEGVERSE_TVC_ROOT naming the TVC checkout, and seals a
stegverse.test-suite-skip-receipt/v1 test receipt of kind
TVC_ORG_CONFORMANCE_TEST_RECEIPT. This organization's ledger writer appends it
to refs/stegverse/organization-ledger as a retained source receipt. This
consumer never reads TVC source and holds no TVC credential: it reads that
ledger chain.

The spec input `tvc` (.stegverse/test-set-spec.json, kind receipt_consumer)
runs ``consume`` at the exact head. The steps are:

1. walk and verify the ledger chain from HEAD
   (resident-runtime/organization_ledger_readback.readback);
2. take the newest retained source receipt that is TVC's org conformance
   receipt (schema, kind, suite, repository), with ALLOW, 0 skipped, every
   test file observed, and offered as a ledger candidate;
3. bind it only if every surface path it consumed, and every path that
   .stegverse/verification-inputs/tvc-conformance-receipt.json declares, has
   the same sha256 at this head.

Anything else is a six-field FAIL_CLOSED REQUIRED_VERIFICATION_INPUT_UNAVAILABLE.
The epoch is the ledger head receipt, never a clock. The consumer only reads;
it never appends, dispatches or polls. It uses the standard library and git
only and is non-authorizing (authority_effect NONE).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "resident-runtime"))
from ledger_store import open_store, parse_locator, receipt_key, source_key  # noqa: E402
import organization_ledger_readback as readback_module  # noqa: E402

SCHEMA = "stegverse.tvc-conformance-receipt-consumption/v1"
CONTRACT_DEFAULT = ROOT / ".stegverse" / "verification-inputs" / "tvc-conformance-receipt.json"
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair",
       "retry_entrypoint", "owning_existing_goal", "next_attempt")
CODE = "REQUIRED_VERIFICATION_INPUT_UNAVAILABLE"
RETRY = ("tools/tasks group required-verification.full-suite, test-set selection input tvc "
         "(resident-runtime/tvc_conformance_receipt.py consume)")
GOAL = ("StegVerse-org/.github#164 (GITHUB-UNIVERSAL-GOVERNANCE-PRODUCT-001); receipt producer "
        "StegVerse-Labs/TVC#539 (run block tvc-conformance-receipt); append: the organization ledger writer")
NEXT = ("the next push to this pull request head reruns the full-suite job, which re-reads the ledger ref "
        "once; nothing is polled or dispatched")
PREDICATES = [
    {"predicate": "ORGANIZATION_LEDGER_CHAIN_READABLE", "lowest_mode": "E0",
     "degraded_form": "E0: one anonymous fetch of the public ledger ref, then a local chain walk; "
                      "unreadable is FAIL_CLOSED for the [tvc] set only"},
    {"predicate": "TVC_CONFORMANCE_RECEIPT_ON_ORGANIZATION_LEDGER", "lowest_mode": "E0",
     "degraded_form": "E0: a retained source receipt that self-verifies and carries ALLOW, 0 skipped; "
                      "none is FAIL_CLOSED, never ALLOW"},
    {"predicate": "TVC_CONFORMANCE_RECEIPT_MATCHES_HEAD_SURFACE", "lowest_mode": "E0",
     "degraded_form": "E0: per-file sha256 of the consumed surface at this head; any difference is "
                      "FAIL_CLOSED (the receipt does not cover these bytes)"},
]


def refusal(predicate: str, repair: str) -> dict:
    return dict(zip(SIX, (CODE, predicate, repair, RETRY, GOAL, NEXT)))


def file_sha256(path: Path) -> str | None:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def module_of(path: str) -> str:
    return ".".join(Path(path).with_suffix("").parts)


def tvc_sets(selection: dict | None) -> list[str]:
    if selection is None:
        return []
    return sorted(s["id"] for s in selection.get("selected", [])
                  if any(i.get("id") == "tvc" for i in s.get("inputs", [])))


def is_conformance_receipt(doc: dict, contract: dict) -> bool:
    want = contract["receipt"]
    return (isinstance(doc, dict) and doc.get("schema") == want["schema"]
            and doc.get("receipt_kind") == want["receipt_kind"] and doc.get("suite") == want["suite"]
            and doc.get("repository") == want["repository"])


def usable(doc: dict, contract: dict) -> list[str]:
    """Why a conformance receipt cannot stand as evidence (empty when it can)."""
    why = []
    if doc.get("disposition") != "ALLOW" or doc.get("refusals"):
        why.append("disposition is not ALLOW")
    if (doc.get("counts") or {}).get("skipped") != 0:
        why.append("skipped is not 0")
    if not (doc.get("ledger_candidate") or {}).get("candidate"):
        why.append("not offered as a ledger candidate (only an ALLOW push to TVC main is)")
    ids = doc.get("test_ids") or []
    for t in contract["tests"]:
        mod = module_of(t)
        if not any(i == mod or i.startswith(mod + ".") or i.startswith(mod + "::") for i in ids):
            why.append(f"{t} has no test id in the receipt")
    return why


def surface_diff(doc: dict, contract: dict, head_root: Path) -> list[str]:
    observed = (doc.get("consumed_source") or {}).get("observed_surface") or {}
    out = []
    for path in sorted(set(observed) | set(contract["surface_paths"])):
        if path not in observed:
            out.append(f"{path} (declared surface not covered by the receipt)")
        elif file_sha256(head_root / path) != observed[path]:
            out.append(path)
    return out


def consume(contract: dict, ledger: str, head_root: Path, selection: dict | None) -> dict:
    sets = tvc_sets(selection)
    record = {"schema": SCHEMA, "authority_effect": "NONE", "derived_from_clock": False,
              "lowest_supported_mode": "E0", "predicates": PREDICATES, "ledger": str(ledger),
              "tvc_sets_selected": sets, "writes": False}
    if selection is not None and not sets:
        return record | {"disposition": "NOT_SELECTED", "refusals": [],
                         "note": "this change selects no [tvc] set; no TVC receipt is required"}
    try:
        chain = readback_module.readback(ledger)
        store = open_store(parse_locator(ledger))
    except Exception as exc:  # any unreadable or unverifiable chain is the same fail-closed answer
        return record | {"disposition": "FAIL_CLOSED", "refusals": [refusal(
            "ORGANIZATION_LEDGER_CHAIN_READABLE",
            f"a readable, self-verifying refs/stegverse/organization-ledger chain in this job "
            f"({exc.__class__.__name__}: {exc}); the full-suite job fetches it anonymously before selection")]}
    record["epoch_from_ledger_head"] = chain["head_receipt_sha256"]
    record["chain_length"] = chain["chain_length"]
    candidates, rejected = [], []
    for row in reversed(chain["chain"]):
        org = store.get(receipt_key(row["receipt_sha256"])) or {}
        digest = org.get("source_transition_sha256")
        doc = store.get(source_key(digest)) if digest else None
        if not is_conformance_receipt(doc, contract):
            continue
        why = usable(doc, contract)
        if why:
            rejected.append({"receipt_sha256": doc.get("receipt_sha256"), "why": why})
            continue
        candidates.append((row["receipt_sha256"], doc))
    if not candidates:
        detail = (f"no {contract['receipt']['receipt_kind']} is retained on the chain" if not rejected else
                  f"{len(rejected)} TVC conformance receipt(s) on the chain, none usable")
        return record | {"disposition": "FAIL_CLOSED", "rejected_receipts": rejected, "refusals": [refusal(
            "TVC_CONFORMANCE_RECEIPT_ON_ORGANIZATION_LEDGER",
            f"{detail}; TVC's run block tvc-conformance-receipt seals one on every qualifying push to TVC main "
            "(StegVerse-Labs/TVC#539) and the organization ledger writer appends it - never this job")]}
    stale = []
    for org_digest, doc in candidates:
        diff = surface_diff(doc, contract, head_root)
        if not diff:
            return record | {"disposition": "ALLOW", "refusals": [],
                             "bound_receipt_sha256": doc["receipt_sha256"],
                             "bound_by_organization_receipt_sha256": org_digest,
                             "bound_tvc_head_sha": doc.get("head_sha"),
                             # key name fixed by the pinned selector; the value is the org commit TVC fetched
                             "bound_labs_commit": (doc.get("consumed_source") or {}).get("commit"),
                             "surface_files_matched": len(set(contract["surface_paths"])
                                                          | set(doc["consumed_source"]["observed_surface"]))}
        stale.append({"receipt_sha256": doc["receipt_sha256"], "differs": diff})
    newest = stale[0]
    return record | {"disposition": "FAIL_CLOSED", "stale_receipts": stale, "refusals": [refusal(
        "TVC_CONFORMANCE_RECEIPT_MATCHES_HEAD_SURFACE",
        f"the newest TVC conformance receipt ({newest['receipt_sha256']}) was observed against different "
        f"bytes for {len(newest['differs'])} surface path(s) ({', '.join(newest['differs'][:5])}); re-pin "
        "TVC's config/org_conformance_source.json to an org commit holding this surface, let TVC CI seal "
        "a receipt on TVC main, and have the organization ledger writer append it")]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("consume")
    c.add_argument("--contract", type=Path, default=CONTRACT_DEFAULT)
    c.add_argument("--ledger", required=True)
    c.add_argument("--head-root", type=Path, default=ROOT)
    c.add_argument("--selection", type=Path)
    c.add_argument("--out", type=Path)
    a = p.parse_args(argv)
    contract = json.loads(a.contract.read_text(encoding="utf-8"))
    selection = None
    if a.selection is not None:
        try:
            selection = json.loads(a.selection.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            selection = None  # unreadable selection: evaluate as if selected, never NOT_SELECTED
    record = consume(contract, a.ledger, a.head_root, selection)
    if a.out is not None:
        a.out.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"TVC_CONFORMANCE_RECEIPT disposition={record['disposition']} "
          f"tvc_sets={len(record['tvc_sets_selected'])} "
          f"bound={record.get('bound_receipt_sha256', 'NONE')} "
          f"epoch={record.get('epoch_from_ledger_head', 'UNKNOWN_NOT_AUTHENTICALLY_OBSERVED')}")
    for row in record["refusals"]:
        print("FAIL_CLOSED " + " ".join(f"{k}={row[k]!r}" for k in SIX))
    return 0 if record["disposition"] in ("ALLOW", "NOT_SELECTED") else 1


if __name__ == "__main__":
    sys.exit(main())
