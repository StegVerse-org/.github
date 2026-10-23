#!/usr/bin/env python3
"""InTr post-genesis kit: sealed destination payloads, per-path checks and the replay after admission genesis.

StegVerse-org/.github#162 (Lane B). Next blocker: INTR_PATH_DESTINATION_RECEIPT_NOT_LEDGERED. It clears when the
inbound rows in StegVerse-org/.github#224 and StegVerse-Labs/.github#3312 land on main and each destination's
.github/workflows/intr-path-ingress.yml appends an ORGANIZATION_INTR_DESTINATION_INGRESS receipt (workflow_run after
the main-merge transfer; no dispatch). This kit does everything up to that event and nothing at it:

  seal    for every one of the 56 declared paths, compute the destination ingress evidence the writer will append
          (resident-runtime/intr_path_ingress.py ingress_evidence, field for field) from the source receipts read
          back from anonymously fetched public ledger copies, and write one sealed record per path plus a sha256
          manifest under .stegverse/intr-post-genesis/. A path whose payload cannot be computed at E0 carries the
          six fields instead. Nothing is appended to any ledger; the records are not receipts and not authentic.
  check   re-verify the committed records offline: seals, manifest digests, and every payload recomputed from the
          source receipts embedded in its record.
  replay  after genesis: read back each destination ingress receipt from the local fetched ledger copies, verify
          end to end (resident-runtime/intr_path_ingress.py verify_end_to_end over both readbacks, and
          `end-to-end-via-tvc --public-ledgers` where this organization is an end), compare the ledgered evidence
          with the sealed payload, and emit ALLOW or the six-field non-ALLOW per path.

Deterministic: the verifiers read only local files and local git objects (no clock, no network, no credential, no
new dependency). Copies of private or internal organizations' ledgers are never read: only what an anonymous fetch
produced may be in --public-ledgers (the workflow fetches with credential.helper= and no auth header), so those
paths stay FAIL_CLOSED with retry at StegVerse-Labs/TVC#532 + #535. Every outcome is terminal at E0.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
KIT_DIR = ROOT / ".stegverse" / "intr-post-genesis"
INPUTS = KIT_DIR / "inputs.json"
PAYLOAD_DIR = KIT_DIR / "payloads"
MANIFEST = KIT_DIR / "manifest.json"
SUMS = KIT_DIR / "SHA256SUMS"

INPUTS_SCHEMA = "stegverse.intr-post-genesis-inputs/v1"
RECORD_SCHEMA = "stegverse.intr-post-genesis-path/v1"
MANIFEST_SCHEMA = "stegverse.intr-post-genesis-manifest/v1"
REPLAY_SCHEMA = "stegverse.intr-post-genesis-replay/v1"
SEAL = "record_sha256"
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
       "owning_existing_goal", "next_attempt")
ALLOW, DENY, FAIL_CLOSED = "ALLOW", "DENY", "FAIL_CLOSED"
GOAL = "StegVerse-org/.github#162"

GENESIS_READY = "GENESIS_READY"                    # ALLOW once the genesis PR for its destination is admitted
TVC_SOURCE = "TVC_PRIVATE_SOURCE_READ"             # source ledger not anonymously readable
TVC_DESTINATION = "TVC_PRIVATE_DESTINATION_READ"   # destination ledger not anonymously readable
SOURCE_NOT_LEDGERED = "SOURCE_RECEIPT_NOT_LEDGERED"
INGRESS_NOT_ON_MAIN = "DESTINATION_INGRESS_NOT_ON_MAIN"
INBOUND_ROW_ABSENT = "DESTINATION_INBOUND_ROW_ABSENT"
CLASSES = (GENESIS_READY, TVC_SOURCE, TVC_DESTINATION, SOURCE_NOT_LEDGERED, INGRESS_NOT_ON_MAIN, INBOUND_ROW_ABSENT)


def _module(name: str, relative: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ingress = _module("intr_path_ingress", "resident-runtime/intr_path_ingress.py")
transfer = _module("intr_path_transfer", "resident-runtime/intr_path_transfer.py")


# -- canonical bytes and seals --------------------------------------------------------------------------------

def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def seal(body: Mapping[str, Any]) -> dict:
    clean = {k: v for k, v in body.items() if k != SEAL}
    return {**clean, SEAL: digest(clean)}


def seal_verifies(record: Any) -> bool:
    return isinstance(record, Mapping) and seal(record).get(SEAL) == record.get(SEAL)


def six(code: str, predicate: str, repair: str, retry: str, goal: str, nxt: str, **extra: Any) -> dict:
    return {"failure_code": code, "failed_predicate": predicate, "required_evidence_or_repair": repair,
            "retry_entrypoint": retry, "owning_existing_goal": goal, "next_attempt": nxt, **extra}


def has_six(result: Mapping[str, Any]) -> bool:
    return all(isinstance(result.get(f), str) and result.get(f).strip() for f in SIX)


# -- inputs -----------------------------------------------------------------------------------------------------

def load_inputs(path: Path | str = INPUTS) -> dict:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema") != INPUTS_SCHEMA:
        raise SystemExit("FAIL_CLOSED: INTR_POST_GENESIS_INPUTS_INVALID " + str(path))
    return document


def communication_id(source: str, destination: str) -> str:
    return "intr-path-v1:" + source + "->" + destination


def slug(path_id: str) -> str:
    return path_id.split(":")[0].replace("->", "__")


def paths() -> list[dict]:
    return [{"path_id": p["path_id"], "source": p["source"], "destination": p["destination"],
             "communication_id": communication_id(p["source"], p["destination"])}
            for p in sorted(transfer.declared_paths(), key=lambda p: p["path_id"])]


def tvc_six(inputs: Mapping[str, Any], path: Mapping[str, Any], purpose: str) -> dict:
    tvc = inputs["tvc"]
    other = path["source"] if purpose == "source_inclusion" else path["destination"]
    return six(ingress.CREDENTIAL_NOT_ISSUED,
               "SOURCE_INCLUSION_IS_READ_FROM_THE_SOURCE_LEDGER" if purpose == "source_inclusion"
               else "DESTINATION_READBACK_IS_READ_FROM_THE_DESTINATION_LEDGER",
               other + "/.github's ledger is not anonymously readable, so the " + purpose + " read for "
               + path["path_id"] + " needs a TV/TVC read receipt (scope " + path["path_id"] + "#" + purpose
               + ") landed at .stegverse/intr-path-transfer/tvc-read-receipts/; no bot holds a credential",
               tvc["retry_entrypoint"], tvc["owning_existing_goal"],
               "after TVC#532 and TVC#535 are admitted and the read receipt lands, re-run this replay")


# -- the destination payload (mirrors intr_path_ingress.ingress_evidence) ---------------------------------------

def destination_address(organization: str) -> str:
    return ingress.address(organization)


def evidence_core(checked: Mapping[str, Any], destination: str) -> dict:
    """ingress_evidence's core without source_inclusion, for ``destination`` (not necessarily this repository)."""
    return {"schema": ingress.EVIDENCE_SCHEMA, "repository": destination + "/.github", "path_id": checked["path_id"],
            "source_repository": checked["source_repository"],
            "source_organization_receipt_sha256": checked["source_organization_receipt_sha256"],
            "source_repository_receipt_sha256": checked["source_repository_receipt_sha256"],
            "message": checked["message"], "message_sha256": ingress.sha(checked["message"]),
            "addressed_service": destination_address(destination)}


def evidence_at_tip(core: Mapping[str, Any], communication: str, source_ledger_tip: str) -> dict:
    """The full evidence the writer appends when the source inclusion is read anonymously at ``source_ledger_tip``."""
    full = {**core, "source_inclusion": {"state": ingress.PUBLIC_STATE, "source_ledger_tip": source_ledger_tip,
                                         "tvc_read_receipt": None}}
    return {**full, "payload_sha256": ingress.sha(full), "disposition": ALLOW, "communication_id": communication}


INVARIANT_FIELDS = ("schema", "repository", "path_id", "source_repository", "source_organization_receipt_sha256",
                    "source_repository_receipt_sha256", "message", "message_sha256", "addressed_service")


# -- seal -------------------------------------------------------------------------------------------------------

def readable(public_ledgers: Path | str | None, organization: str) -> bool:
    return ingress.public_ledger_dir(organization + "/.github", public_ledgers) is not None


def classify(inputs: Mapping[str, Any], path: Mapping[str, Any], public_ledgers: Path | str | None) -> dict:
    """One path's sealed record. Order = the order the end-to-end verifier evaluates its predicates."""
    pid, cid, src, dst = path["path_id"], path["communication_id"], path["source"], path["destination"]
    rec: dict[str, Any] = {"schema": RECORD_SCHEMA, "path_id": pid, "communication_id": cid, "source": src,
                           "destination": dst, "operation": ingress.OPERATION, "ledgered": False,
                           "authentic": False, "authority_effect": "NONE", "e0_terminal": True,
                           "source_receipts": None, "payload": None, "blockers": []}
    genesis = inputs["genesis"].get(dst)
    ingress_on_main = inputs["destination_ingress_on_main"].get(dst)
    later: list[dict] = []
    if not readable(public_ledgers, dst):
        later.append(tvc_six(inputs, path, "destination_readback"))
    if ingress_on_main == "PRESENT_WITHOUT_PUBLIC_ROUTE":
        later.append(six("INTR_PATH_DESTINATION_PUBLIC_ROUTE_NOT_ON_MAIN", "DESTINATION_INGRESS_HAS_THE_PUBLIC_LEDGER_ROUTE",
                         "the public-ledger route of resident-runtime/intr_path_ingress.py (as in StegVerse-org/.github#224"
                         " and StegVerse-Labs/.github#3312) on " + dst + "/.github main",
                         "a Lane B public-route port draft to " + dst + "/.github (laneb/ branch)", GOAL,
                         "re-run seal and replay after the port is admitted"))
    elif ingress_on_main is not True:
        later.append(six("INTR_PATH_DESTINATION_INGRESS_NOT_ON_MAIN", "DESTINATION_HAS_INTR_PATH_INGRESS",
                         "resident-runtime/intr_path_ingress.py and .github/workflows/intr-path-ingress.yml on "
                         + dst + "/.github main", "a Lane B port draft to " + dst + "/.github (laneb/ branch)", GOAL,
                         "re-run seal and replay after the port is admitted"))
    if not (genesis and genesis.get("inbound_row") == pid):
        later.append(six(ingress.NOT_LEDGERED, "PATH_HAS_A_DESTINATION_LEDGER_RECEIPT",
                         "an inbound row for " + pid + " on " + dst + "/.github main carrying the source receipt pair",
                         dst + "/.github .github/workflows/intr-path-ingress.yml (workflow_run after the main-merge "
                         "transfer of the push that lands the row)", GOAL, "seal, then replay after the row lands"))
    if not readable(public_ledgers, src):
        rec.update(cls=TVC_SOURCE, expected_at_genesis=FAIL_CLOSED, status=tvc_six(inputs, path, "source_inclusion"))
        rec["blockers"] = [rec["status"]] + later
        return seal(rec)
    rb = ingress.public_readback(pid, cid, src + "/.github", public_ledgers)
    org_r = rb.get("organization_receipt") if rb else None
    if not isinstance(org_r, Mapping):
        rec.update(cls=SOURCE_NOT_LEDGERED, expected_at_genesis=FAIL_CLOSED, status=six(
            ingress.SOURCE_NOT_LEDGERED, "PATH_HAS_A_SOURCE_LEDGER_RECEIPT",
            "an INTR_MESH_PATH_TRANSFER receipt for " + pid + " on " + src + "/.github's ledger (read anonymously at "
            + str(rb.get("ledger_tip") if rb else None) + ": none)",
            src + "/.github .github/workflows/intr-path-transfer.yml (a transfers.json row landing on main)", GOAL,
            "read the source ledger back, then re-run seal"))
        rec["blockers"] = [rec["status"]] + later
        return seal(rec)
    checked = ingress.check_source_pair(org_r, rb.get("repository_receipt"), pid, cid, dst)
    if checked["disposition"] != ALLOW or not ingress._included(rb, org_r):
        status = {k: checked.get(k) for k in SIX} if has_six(checked) else six(
            ingress.SOURCE_LINK_UNVERIFIED, "SOURCE_RECEIPT_IS_INCLUDED_IN_THE_SOURCE_LEDGER",
            "the source receipt must be on the source chain read back anonymously", "seal", GOAL, "inspect")
        rec.update(cls=SOURCE_NOT_LEDGERED, expected_at_genesis=DENY, status=status)
        rec["blockers"] = [status] + later
        return seal(rec)
    core = evidence_core(checked, dst)
    rec["source_receipts"] = {"source_ledger_tip_observed": rb["ledger_tip"],
                              "organization_receipt": org_r, "repository_receipt": rb["repository_receipt"]}
    rec["payload"] = {"evidence_invariant": {k: core[k] for k in INVARIANT_FIELDS},
                      "evidence_invariant_sha256": digest({k: core[k] for k in INVARIANT_FIELDS}),
                      "source_inclusion_rule": {"state": ingress.PUBLIC_STATE, "tvc_read_receipt": None,
                                                "source_ledger_tip": "the source ledger tip read at consume time; "
                                                "its chain must include source_organization_receipt_sha256"},
                      "evidence_at_observed_source_tip": evidence_at_tip(core, cid, rb["ledger_tip"])}
    if later:
        rec.update(cls=(TVC_DESTINATION if not readable(public_ledgers, dst) else
                        INGRESS_NOT_ON_MAIN if ingress_on_main is not True else INBOUND_ROW_ABSENT),
                   expected_at_genesis=FAIL_CLOSED, status=later[0])
        rec["blockers"] = later
        return seal(rec)
    status = six(ingress.NOT_LEDGERED, "PATH_HAS_A_DESTINATION_LEDGER_RECEIPT",
                 "the inbound row in " + genesis["pr"] + " (head " + genesis["head"][:8] + ") admitted to " + dst
                 + "/.github main and consumed by intr-path-ingress.yml",
                 dst + "/.github .github/workflows/intr-path-ingress.yml (workflow_run after the main-merge transfer "
                 "of the admission push)", GOAL,
                 "fetch both ledgers anonymously, then scripts/intr_post_genesis_replay.py replay")
    rec.update(cls=GENESIS_READY, expected_at_genesis=ALLOW, status=status, genesis_pr=genesis["pr"],
               genesis_head=genesis["head"])
    rec["blockers"] = [status]
    return seal(rec)


def seal_all(inputs: Mapping[str, Any], public_ledgers: Path | str) -> tuple[list[dict], dict]:
    records = [classify(inputs, p, public_ledgers) for p in paths()]
    files = {}
    for r in records:
        files["payloads/" + slug(r["path_id"]) + ".json"] = r
    texts = {name: json.dumps(r, indent=1, sort_keys=True) + "\n" for name, r in files.items()}
    inputs_text = INPUTS.read_text(encoding="utf-8") if INPUTS.is_file() else json.dumps(inputs, indent=1) + "\n"
    entries = {name: hashlib.sha256(t.encode("utf-8")).hexdigest() for name, t in sorted(texts.items())}
    entries["inputs.json"] = hashlib.sha256(inputs_text.encode("utf-8")).hexdigest()
    counts: dict[str, int] = {}
    for r in records:
        counts[r["cls"]] = counts.get(r["cls"], 0) + 1
    manifest = seal({"schema": MANIFEST_SCHEMA, "paths_total": len(records), "class_counts": dict(sorted(counts.items())),
                     "genesis_allow": sorted(r["path_id"] for r in records if r["cls"] == GENESIS_READY),
                     "files_sha256": dict(sorted(entries.items())), "ledgered": False, "authentic": False,
                     "authority_effect": "NONE", "owning_existing_goal": GOAL})
    return records, {"texts": texts, "manifest": manifest, "entries": entries}


def write_sealed(out: dict, kit_dir: Path = KIT_DIR) -> str:
    (kit_dir / "payloads").mkdir(parents=True, exist_ok=True)
    for name, text in out["texts"].items():
        (kit_dir / name).write_text(text, encoding="utf-8")
    mtext = json.dumps(out["manifest"], indent=1, sort_keys=True) + "\n"
    (kit_dir / "manifest.json").write_text(mtext, encoding="utf-8")
    sums = dict(out["entries"])
    sums["manifest.json"] = hashlib.sha256(mtext.encode("utf-8")).hexdigest()
    (kit_dir / "SHA256SUMS").write_text("".join(f"{h}  {n}\n" for n, h in sorted(sums.items())), encoding="utf-8")
    return sums["manifest.json"]


# -- check (offline) --------------------------------------------------------------------------------------------

def load_record(path_id: str, kit_dir: Path = KIT_DIR) -> dict:
    return json.loads((kit_dir / "payloads" / (slug(path_id) + ".json")).read_text(encoding="utf-8"))


def check_record(record: Mapping[str, Any], manifest: Mapping[str, Any] | None = None,
                 kit_dir: Path = KIT_DIR) -> list[str]:
    """Problems with one committed record ([] = verified): seal, manifest digest, class rules, payload recompute."""
    problems = []
    if not seal_verifies(record) or record.get("schema") != RECORD_SCHEMA:
        return ["record seal or schema"]
    name = "payloads/" + slug(record["path_id"]) + ".json"
    if manifest is not None:
        text = (kit_dir / name).read_bytes()
        if manifest.get("files_sha256", {}).get(name) != hashlib.sha256(text).hexdigest():
            problems.append("manifest digest for " + name)
    if record.get("cls") not in CLASSES or record.get("e0_terminal") is not True:
        problems.append("class " + repr(record.get("cls")))
    if record.get("ledgered") is not False or record.get("authentic") is not False:
        problems.append("a sealed payload is never ledgered or authentic")
    if not has_six(record.get("status", {})) or not all(has_six(b) for b in record.get("blockers", [])) \
            or not record.get("blockers"):
        problems.append("six fields")
    if record.get("cls") in (TVC_SOURCE, TVC_DESTINATION):
        retry = record["status"]["retry_entrypoint"]
        if "TVC#532" not in retry or "TVC#535" not in retry:
            problems.append("TVC retry must name TVC#532 and TVC#535")
    if record.get("cls") == GENESIS_READY and record.get("expected_at_genesis") != ALLOW:
        problems.append("genesis-ready path must expect ALLOW")
    if record.get("cls") != GENESIS_READY and record.get("expected_at_genesis") == ALLOW:
        problems.append("only genesis-ready paths expect ALLOW")
    src = record.get("source_receipts")
    if record.get("payload") is not None:
        if not isinstance(src, Mapping):
            return problems + ["payload without its source receipts"]
        checked = ingress.check_source_pair(src.get("organization_receipt"), src.get("repository_receipt"),
                                            record["path_id"], record["communication_id"], record["destination"])
        if checked["disposition"] != ALLOW:
            return problems + ["embedded source receipts: " + str(checked.get("detail") or checked.get("failure_code"))]
        core = evidence_core(checked, record["destination"])
        inv = {k: core[k] for k in INVARIANT_FIELDS}
        p = record["payload"]
        if p.get("evidence_invariant") != inv or p.get("evidence_invariant_sha256") != digest(inv):
            problems.append("payload invariant does not recompute")
        if p.get("evidence_at_observed_source_tip") != evidence_at_tip(core, record["communication_id"],
                                                                       src.get("source_ledger_tip_observed")):
            problems.append("payload at the observed source tip does not recompute")
    elif record.get("cls") in (GENESIS_READY, INGRESS_NOT_ON_MAIN, INBOUND_ROW_ABSENT, TVC_DESTINATION):
        problems.append("class " + record["cls"] + " needs a payload")
    return problems


def check_all(kit_dir: Path = KIT_DIR) -> dict:
    manifest = json.loads((kit_dir / "manifest.json").read_text(encoding="utf-8"))
    problems = {} if seal_verifies(manifest) and manifest.get("schema") == MANIFEST_SCHEMA else {"manifest": ["seal"]}
    names = sorted(slug(p["path_id"]) for p in paths())
    on_disk = sorted(f.stem for f in (kit_dir / "payloads").glob("*.json"))
    if names != on_disk:
        problems["payloads"] = ["the payload files are not exactly the declared paths"]
    for p in paths():
        got = check_record(load_record(p["path_id"], kit_dir), manifest, kit_dir)
        if got:
            problems[p["path_id"]] = got
    return {"verified": not problems, "problems": problems, "paths": len(names),
            "genesis_allow": manifest.get("genesis_allow"), "class_counts": manifest.get("class_counts")}


# -- replay (after genesis) -------------------------------------------------------------------------------------

def _here() -> str:
    return ingress.organization()


def _cli_end_to_end(path: Mapping[str, Any], public_ledgers: Path, namespace: str | None) -> dict | None:
    """`end-to-end-via-tvc --public-ledgers` in this checkout, this organization's ledger bound read-only to its
    fetched copy. None when this organization is not an end of the path or its copy was not fetched."""
    here = _here()
    if here not in (path["source"], path["destination"]):
        return None
    own = ingress.public_ledger_dir(here + "/.github", public_ledgers)
    if own is None or not namespace:
        return None
    ref = ingress.LEDGER_REF
    env = {k: v for k, v in os.environ.items() if not k.startswith("STEGVERSE_")}
    env.update({"STEGVERSE_ORG_LEDGER_ROOT": "git+" + str(own) + "#" + ref,
                "STEGVERSE_REPO_LEDGER_ROOT": "git+" + str(own) + "#" + ref + ":" + namespace,
                "STEGVERSE_ORG_LEDGER_GIT_DIR": str(own), "STEGVERSE_ORG_LEDGER_GIT_REF": ref,
                "STEGVERSE_INTR_PUBLIC_LEDGERS": str(public_ledgers)})
    done = subprocess.run([sys.executable, str(ROOT / "resident-runtime" / "intr_path_ingress.py"), "end-to-end-via-tvc",
                           "--path-id", path["path_id"], "--communication-id", path["communication_id"],
                           "--public-ledgers", str(public_ledgers)], cwd=ROOT, env=env, capture_output=True, text=True)
    try:
        return json.loads(done.stdout)
    except ValueError:
        return six("INTR_POST_GENESIS_CLI_OUTPUT_UNREADABLE", "END_TO_END_VIA_TVC_EMITS_A_RESULT",
                   "intr_path_ingress.py end-to-end-via-tvc must print one JSON result: " + done.stderr[-300:],
                   "scripts/intr_post_genesis_replay.py replay", GOAL, "repair and re-run", disposition=FAIL_CLOSED)


def _namespace() -> str | None:
    contract = ROOT / ".stegverse" / "transition-ledger" / "contract.json"
    try:
        return json.loads(contract.read_text(encoding="utf-8"))["repository_ledger_location"]["namespace"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def replay_path(record: Mapping[str, Any], inputs: Mapping[str, Any], public_ledgers: Path,
                namespace: str | None) -> dict:
    path = {k: record[k] for k in ("path_id", "communication_id", "source", "destination")}
    base = {"path_id": path["path_id"], "communication_id": path["communication_id"], "cls": record.get("cls"),
            "expected_at_genesis": record.get("expected_at_genesis")}
    problems = check_record(record)
    if problems:
        return {**base, "disposition": FAIL_CLOSED, **six(
            "INTR_POST_GENESIS_SEALED_RECORD_UNVERIFIED", "SEALED_PAYLOAD_RECORD_VERIFIES",
            "the committed sealed record: " + "; ".join(problems), "scripts/intr_post_genesis_replay.py seal", GOAL,
            "re-seal from the anonymous ledger copies and re-run")}
    if not readable(public_ledgers, path["source"]):
        return {**base, "disposition": FAIL_CLOSED, "half": "source", **tvc_six(inputs, path, "source_inclusion")}
    if not readable(public_ledgers, path["destination"]):
        return {**base, "disposition": FAIL_CLOSED, "half": "destination",
                **tvc_six(inputs, path, "destination_readback")}
    src = ingress.public_readback(path["path_id"], path["communication_id"], path["source"] + "/.github", public_ledgers)
    dst = ingress.public_readback(path["path_id"], path["communication_id"], path["destination"] + "/.github",
                                  public_ledgers)
    result = ingress.verify_end_to_end(path["path_id"], path["communication_id"], src, dst)
    out = {**base, **{k: result.get(k) for k in ("disposition", "path", "half") if k in result},
           "source_ledger_tip": src.get("ledger_tip") if src else None,
           "destination_ledger_tip": dst.get("ledger_tip") if dst else None}
    if result["disposition"] != ALLOW:
        verifier = {k: result.get(k) for k in SIX}
        if not has_six(verifier):
            verifier = dict(record["status"])
        # the verifier's six fields come first; the kit's known repairs ride beside them
        return {**out, **verifier, "kit_blockers": record.get("blockers", [])}
    d_repo = dst.get("repository_receipt") if isinstance(dst.get("repository_receipt"), Mapping) else {}
    evidence = d_repo.get("evidence") if isinstance(d_repo.get("evidence"), Mapping) else {}
    expected = record["payload"]["evidence_invariant"]
    differs = sorted(k for k in INVARIANT_FIELDS if evidence.get(k) != expected.get(k))
    inc = evidence.get("source_inclusion") if isinstance(evidence.get("source_inclusion"), Mapping) else {}
    if inc.get("state") != ingress.PUBLIC_STATE or inc.get("tvc_read_receipt") is not None:
        differs.append("source_inclusion.state")
    if differs:
        return {**out, "disposition": DENY, **six(
            "INTR_POST_GENESIS_LEDGERED_PAYLOAD_DIFFERS_FROM_SEALED", "LEDGERED_INGRESS_EVIDENCE_EQUALS_SEALED_PAYLOAD",
            "the ledgered ORGANIZATION_INTR_DESTINATION_INGRESS evidence differs from the sealed payload in "
            + ", ".join(differs), "scripts/intr_post_genesis_replay.py check (then inspect the ingress writer)", GOAL,
            "inspect; nothing was written")}
    cli = _cli_end_to_end(path, public_ledgers, namespace)
    if cli is not None and cli.get("disposition") != ALLOW:
        return {**out, "disposition": FAIL_CLOSED, "end_to_end_via_tvc": {k: cli.get(k) for k in ("disposition",) + SIX},
                **six("INTR_POST_GENESIS_VERIFIERS_DISAGREE", "END_TO_END_VIA_TVC_AGREES_WITH_VERIFY_END_TO_END",
                      "end-to-end-via-tvc --public-ledgers returned " + str(cli.get("failure_code")),
                      "resident-runtime/intr_path_ingress.py end-to-end-via-tvc", GOAL, "inspect and re-run")}
    return {**out, "disposition": ALLOW, "path": "VERIFIED", "payload_matches_sealed": True,
            "destination_organization_receipt_sha256": result.get("destination_organization_receipt_sha256"),
            "source_organization_receipt_sha256": result.get("source_organization_receipt_sha256"),
            "end_to_end_via_tvc": cli.get("disposition") if cli is not None else "NOT_AN_END_OF_THIS_ORGANIZATION"}


def replay_all(public_ledgers: Path | str, kit_dir: Path = KIT_DIR, inputs_path: Path | str = INPUTS) -> dict:
    inputs = load_inputs(inputs_path)
    pub = Path(public_ledgers)
    ns = _namespace()
    results = [replay_path(load_record(p["path_id"], kit_dir), inputs, pub, ns) for p in paths()]
    counts = {ALLOW: 0, DENY: 0, FAIL_CLOSED: 0}
    for r in results:
        counts[r["disposition"]] = counts.get(r["disposition"], 0) + 1
    terminal = all(r["disposition"] == ALLOW or has_six(r) for r in results)
    tips = {}
    for d in sorted(pub.glob("*.git")) if pub.is_dir() else []:
        tip = ingress._git_tip(d)
        if tip:
            tips[d.name[:-4]] = tip
    return seal({"schema": REPLAY_SCHEMA, "run_in": ingress.repository(), "public_ledger_tips": tips,
                 "counts": counts, "e0_terminal": terminal,
                 "genesis_ready_not_allow": sorted(r["path_id"] for r in results
                                                   if r["cls"] == GENESIS_READY and r["disposition"] != ALLOW),
                 "results": results, "authority_effect": "NONE"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("seal")
    s.add_argument("--public-ledgers", required=True)
    s.add_argument("--inputs", default=str(INPUTS))
    sub.add_parser("check")
    r = sub.add_parser("replay")
    r.add_argument("--public-ledgers", required=True)
    r.add_argument("--out")
    r.add_argument("--require-genesis-allow", action="store_true",
                   help="exit 1 unless every GENESIS_READY path is ALLOW (use after both genesis PRs are admitted)")
    a = parser.parse_args(argv)
    if a.command == "seal":
        records, out = seal_all(load_inputs(a.inputs), a.public_ledgers)
        digest_hex = write_sealed(out)
        print(json.dumps({"manifest_sha256": digest_hex, "class_counts": out["manifest"]["class_counts"],
                          "genesis_allow": out["manifest"]["genesis_allow"]}, indent=1, sort_keys=True))
        return 0
    if a.command == "check":
        result = check_all()
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0 if result["verified"] else 1
    result = replay_all(a.public_ledgers)
    text = json.dumps(result, indent=1, sort_keys=True)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    for x in result["results"]:
        print("INTR_POST_GENESIS", x["path_id"], x["disposition"], x.get("failure_code") or x.get("path"))
    print("INTR_POST_GENESIS_COUNTS", json.dumps(result["counts"], sort_keys=True), "e0_terminal=" + str(result["e0_terminal"]))
    if not result["e0_terminal"]:
        return 1
    if a.require_genesis_allow and result["genesis_ready_not_allow"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
