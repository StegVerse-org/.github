#!/usr/bin/env python3
"""Canonical InTr protocol v1 conformance validator.

Reads data/intr-protocol/v1/protocol.json, the single versioned contract for
the InTr message envelope, the route (destination address derivation), and the
destination capability every organization's .github boundary must declare.

Pure and offline: no clock, no network, no environment, no ledger. It returns
conformance evidence only. ALLOW here is not admission, routing or execution
authority, and it is not proof that a live peer installed the capability.

Every non-ALLOW result carries the six fields named in the contract.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "data" / "intr-protocol" / "v1" / "protocol.json"
RESULT_SCHEMA = "stegverse.intr-protocol-conformance-result/v1"
ALLOW, DENY, FAIL_CLOSED = "ALLOW", "DENY", "FAIL_CLOSED"
_MISSING = object()


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canon(value)).hexdigest()


def load_contract(path: Path | str | None = None) -> dict[str, Any]:
    with open(path or CONTRACT_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _kernel():
    spec = importlib.util.spec_from_file_location(
        "org_kernel_intr_protocol", ROOT / "org-kernel" / "kernel.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def organization_slug(organization: str) -> str:
    """The kernel's derivation; the contract names it as the only one."""
    return _kernel().organization_slug(organization)


def destination_address(organization: str, contract: Mapping[str, Any]) -> str:
    profile = contract["destination_capability"]["profile_id"]
    return organization_slug(organization) + "." + profile


def _get(document: Any, path: str) -> Any:
    node = document
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return _MISSING
        node = node[part]
    return node


def _expected(value: Any, context: Mapping[str, str]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return context[value[1:]]
    return value


def _refusal(contract: Mapping[str, Any], disposition: str, code: str,
             predicate: str, repair: str, subject: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "schema": RESULT_SCHEMA,
        "protocol": contract["protocol"],
        "contract_digest": digest(contract),
        "subject": dict(subject),
        "disposition": disposition,
        "failure_code": code,
        "failed_predicate": predicate,
        "required_evidence_or_repair": repair,
        "retry_entrypoint": contract["retry_entrypoint"],
        "owning_existing_goal": contract["owning_existing_goal"],
        "next_attempt": "after the repair lands on the subject organization's .github default branch, re-run retry_entrypoint against the repaired documents",
        "authority_effect": contract["authority_effect"],
    }
    result["result_digest"] = digest(result)
    return result


def _allow(contract: Mapping[str, Any], subject: Mapping[str, Any],
           checked: list[str]) -> dict[str, Any]:
    result = {
        "schema": RESULT_SCHEMA,
        "protocol": contract["protocol"],
        "contract_digest": digest(contract),
        "subject": dict(subject),
        "disposition": ALLOW,
        "predicates_checked": checked,
        "authority_effect": contract["authority_effect"],
    }
    result["result_digest"] = digest(result)
    return result


def _check(contract, subject, predicate, observed, context):
    """Return a refusal for one predicate, or None when it holds."""
    pid = predicate["id"]
    if observed is _MISSING:
        return _refusal(contract, FAIL_CLOSED, "INTR_PROTOCOL_FIELD_UNOBSERVED", pid,
                        f"declare {predicate.get('path') or predicate.get('row_path')}", subject)
    if "contains" in predicate:
        want = _expected(predicate["contains"], context)
        if not isinstance(observed, list) or want not in observed:
            return _refusal(contract, DENY, "INTR_PROTOCOL_VALUE_MISMATCH", pid,
                            f"{predicate['row_path']} must contain {want!r}; observed {observed!r}", subject)
        return None
    want = _expected(predicate["equals"], context)
    if observed != want or type(observed) is not type(want):
        disposition = predicate.get("unknown", DENY)
        code = ("INTR_PROTOCOL_VERSION_UNKNOWN" if disposition == FAIL_CLOSED
                else "INTR_PROTOCOL_VALUE_MISMATCH")
        path = predicate.get("path") or predicate.get("row_path")
        return _refusal(contract, disposition, code, pid,
                        f"{path} must be {want!r}; observed {observed!r}", subject)
    return None


def conform_destination(organization: Any, interlock: Any, services: Any,
                        contract: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Check one organization's destination documents against the contract."""
    contract = contract or load_contract()
    spec = contract["destination_capability"]
    subject = {"organization": organization,
               "interlock_digest": digest(interlock) if interlock is not None else None,
               "services_digest": digest(services) if services is not None else None}
    if not isinstance(organization, str) or not organization.strip():
        return _refusal(contract, FAIL_CLOSED, "INTR_PROTOCOL_SUBJECT_UNOBSERVED",
                        "SUBJECT_NAMES_AN_ORGANIZATION", "name the organization under test", subject)
    for name, document, path in (("interlock", interlock, spec["interlock_document"]),
                                 ("services", services, spec["service_registry_document"])):
        if not isinstance(document, Mapping):
            return _refusal(contract, FAIL_CLOSED, "INTR_PROTOCOL_DOCUMENT_UNOBSERVED",
                            f"{name.upper()}_DOCUMENT_IS_AN_OBJECT",
                            f"supply {organization}/.github {path} as a JSON object", subject)
    address = destination_address(organization, contract)
    context = {"ORG": organization, "REPO": organization + "/.github", "ADDRESS": address}
    checked: list[str] = []
    for predicate in spec["interlock_predicates"]:
        refusal = _check(contract, subject, predicate, _get(interlock, predicate["path"]), context)
        if refusal:
            return refusal
        checked.append(predicate["id"])
    bindings = _get(interlock, "ingress.capability_endpoint_bindings")
    rows = [b for b in bindings if isinstance(b, Mapping) and b.get("profile_id") == spec["profile_id"]] \
        if isinstance(bindings, list) else []
    if len(rows) != 1:
        disposition = FAIL_CLOSED if not rows else DENY
        return _refusal(contract, disposition,
                        "INTR_PROTOCOL_DESTINATION_BINDING_UNOBSERVED" if not rows
                        else "INTR_PROTOCOL_DESTINATION_BINDING_AMBIGUOUS",
                        "EXACTLY_ONE_INTR_DESTINATION_BINDING",
                        f"declare exactly one ingress binding with profile_id {spec['profile_id']!r}; found {len(rows)}",
                        subject)
    checked.append("EXACTLY_ONE_INTR_DESTINATION_BINDING")
    for predicate in spec["binding_predicates"]:
        refusal = _check(contract, subject, predicate, _get(rows[0], predicate["path"]), context)
        if refusal:
            return refusal
        checked.append(predicate["id"])
    service_rows = services.get("services")
    served = [r for r in service_rows if isinstance(r, Mapping) and r.get("service_id") == address] \
        if isinstance(service_rows, list) else []
    for predicate in spec["service_predicates"]:
        if "path" in predicate:
            refusal = _check(contract, subject, predicate, _get(services, predicate["path"]), context)
            if refusal:
                return refusal
            checked.append(predicate["id"])
    if len(served) != 1:
        return _refusal(contract, FAIL_CLOSED if not served else DENY,
                        "INTR_PROTOCOL_DESTINATION_NOT_SERVED" if not served
                        else "INTR_PROTOCOL_DESTINATION_SERVED_AMBIGUOUSLY",
                        "REGISTRY_SERVES_THE_DERIVED_ADDRESS_ONCE",
                        f"serve exactly one services.json row with service_id {address!r}; found {len(served)}",
                        subject)
    checked.append("REGISTRY_SERVES_THE_DERIVED_ADDRESS_ONCE")
    for predicate in spec["service_predicates"]:
        if "row_path" in predicate:
            refusal = _check(contract, subject, predicate, _get(served[0], predicate["row_path"]), context)
            if refusal:
                return refusal
            checked.append(predicate["id"])
    return _allow(contract, subject, checked)


def conform_message(payload: Any, destination_organization: Any,
                    contract: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Check one InTr message envelope and its route to a destination."""
    contract = contract or load_contract()
    spec = contract["destination_capability"]
    subject = {"destination_organization": destination_organization,
               "message_digest": digest(payload)}
    if not isinstance(destination_organization, str) or not destination_organization.strip():
        return _refusal(contract, FAIL_CLOSED, "INTR_PROTOCOL_ROUTE_UNOBSERVED",
                        "ROUTE_NAMES_A_DESTINATION_ORGANIZATION",
                        "name the destination organization", subject)
    subject["destination_address"] = destination_address(destination_organization, contract)
    if not isinstance(payload, Mapping):
        return _refusal(contract, FAIL_CLOSED, "INTR_PROTOCOL_MESSAGE_UNOBSERVED",
                        "MESSAGE_IS_AN_OBJECT", "send the message as a JSON object", subject)
    checked = []
    expected_class = contract["message"]["message_class"]
    if "message_class" not in payload:
        return _refusal(contract, FAIL_CLOSED, "INTR_PROTOCOL_FIELD_UNOBSERVED",
                        "MESSAGE_DECLARES_ITS_CLASS", "declare message_class", subject)
    if payload["message_class"] != expected_class:
        return _refusal(contract, DENY, "INTR_PROTOCOL_VALUE_MISMATCH", "MESSAGE_DECLARES_ITS_CLASS",
                        f"message_class must be {expected_class!r}", subject)
    checked.append("MESSAGE_DECLARES_ITS_CLASS")
    identifier = payload.get("communication_id", _MISSING)
    if identifier is _MISSING or identifier is None:
        return _refusal(contract, FAIL_CLOSED, "INTR_PROTOCOL_FIELD_UNOBSERVED",
                        "MESSAGE_CARRIES_A_COMMUNICATION_ID", "declare communication_id", subject)
    if (not isinstance(identifier, str) or not identifier
            or any(ord(c) <= 32 or ord(c) > 126 for c in identifier)):
        return _refusal(contract, DENY, "INTR_PROTOCOL_VALUE_MISMATCH",
                        "MESSAGE_CARRIES_A_COMMUNICATION_ID",
                        "communication_id must be one printable token with no spaces", subject)
    checked.append("MESSAGE_CARRIES_A_COMMUNICATION_ID")
    body = payload.get("body", _MISSING)
    if not isinstance(body, Mapping) or "schema" not in body:
        return _refusal(contract, FAIL_CLOSED, "INTR_PROTOCOL_FIELD_UNOBSERVED",
                        "MESSAGE_BODY_DECLARES_ITS_SCHEMA", "send body as an object with schema", subject)
    payload_schema = next(p["equals"] for p in spec["binding_predicates"] if p["id"] == "BINDING_PAYLOAD_SCHEMA")
    if body["schema"] != payload_schema:
        return _refusal(contract, DENY, "INTR_PROTOCOL_VALUE_MISMATCH",
                        "MESSAGE_BODY_DECLARES_ITS_SCHEMA",
                        f"body.schema must be {payload_schema!r}", subject)
    checked.append("MESSAGE_BODY_DECLARES_ITS_SCHEMA")
    for key in ("host", "url", "environment_url", "github_token", "token"):
        if key in payload:
            return _refusal(contract, DENY, "INTR_PROTOCOL_ROUTE_CARRIES_HOST_OR_CREDENTIAL",
                            "ROUTE_IS_ADDRESS_NOT_HOST_OR_CREDENTIAL",
                            f"remove {key!r}; routes are {contract['route']['address_form']} over INTERLOCK_INTR with TV/TVC credentials",
                            subject)
    checked.append("ROUTE_IS_ADDRESS_NOT_HOST_OR_CREDENTIAL")
    return _allow(contract, subject, checked)


def conform_mesh(manifest_path: Path | str, contract: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Check every destination named by a snapshot manifest; offline."""
    contract = contract or load_contract()
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base = manifest_path.parent
    results = []
    for row in manifest["destinations"]:
        documents = {}
        for key in ("interlock", "services"):
            entry = row[key]
            path = base / entry["file"]
            if not path.is_file():
                documents[key] = None
                continue
            raw = path.read_bytes()
            if "sha256:" + hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                documents[key] = None
                continue
            documents[key] = json.loads(raw)
        results.append(conform_destination(row["organization"], documents["interlock"],
                                           documents["services"], contract))
    counts = {d: sum(r["disposition"] == d for r in results) for d in (ALLOW, DENY, FAIL_CLOSED)}
    report = {"schema": "stegverse.intr-protocol-mesh-conformance/v1",
              "protocol": contract["protocol"], "contract_digest": digest(contract),
              "manifest_digest": digest(manifest), "counts": counts,
              "results": results}
    report["report_digest"] = digest(report)
    return report


def _read(path: str | None) -> Any:
    if path is None or not Path(path).is_file():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("conform")
    one.add_argument("--org", required=True)
    one.add_argument("--interlock", default=str(ROOT / "org-runtime" / "interlock-intr.json"))
    one.add_argument("--services", default=str(ROOT / "org-boundary" / "registry" / "services.json"))
    mesh = sub.add_parser("mesh")
    mesh.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)
    if args.command == "conform":
        result = conform_destination(args.org, _read(args.interlock), _read(args.services))
    else:
        result = conform_mesh(args.manifest)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
