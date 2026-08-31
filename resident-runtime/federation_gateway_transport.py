#!/usr/bin/env python3
"""Outbound-only Service Gateway transport for organization federation."""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("org_kernel", ROOT / "org-kernel" / "kernel.py")
K = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(K)

GATEWAY_ENV = "STEGVERSE_ORG_FEDERATION_GATEWAY_URL"
TIMEOUT_ENV = "STEGVERSE_ORG_FEDERATION_GATEWAY_TIMEOUT_SECONDS"


class FederationGatewayTransportError(RuntimeError):
    pass


def gateway_base_url() -> str:
    raw = os.getenv(GATEWAY_ENV, "").strip().rstrip("/")
    if not raw:
        raise FederationGatewayTransportError("organization federation gateway URL not configured")
    if not raw.startswith("https://"):
        raise FederationGatewayTransportError("organization federation gateway must use HTTPS")
    return raw


def timeout_seconds() -> float:
    raw = os.getenv(TIMEOUT_ENV, "10").strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise FederationGatewayTransportError("invalid federation gateway timeout") from exc
    if value <= 0 or value > 60:
        raise FederationGatewayTransportError("federation gateway timeout outside bounds")
    return value


def _json_request(method: str, path: str, *, body: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    url = gateway_base_url() + path
    raw = None if body is None else json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    hdrs = {"Accept": "application/json", **(headers or {})}
    if raw is not None:
        hdrs["Content-Type"] = "application/json"
    req = Request(url, data=raw, headers=hdrs, method=method)
    try:
        with urlopen(req, timeout=timeout_seconds()) as resp:
            payload = resp.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise FederationGatewayTransportError(f"gateway request failed: {exc}") from exc
    try:
        return json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise FederationGatewayTransportError("gateway response is not JSON") from exc


def submit_frame(frame: dict[str, Any]) -> dict[str, Any]:
    validated = K.recover_packet(frame)
    origin_org = validated["origin"]["org"]
    return _json_request(
        "POST",
        "/api/org-federation/v1/frames",
        body=frame,
        headers={"X-StegVerse-Origin-Organization": origin_org},
    )


def fetch_frame(organization: str) -> dict[str, Any]:
    query = urlencode({"organization": organization})
    return _json_request(
        "GET",
        "/api/org-federation/v1/frames?" + query,
        headers={"X-StegVerse-Organization": organization},
    )


def acknowledge_frame(organization: str, frame: dict[str, Any], state: str) -> dict[str, Any]:
    ack = {
        "schema": "stegverse.org-federation-rendezvous.ack/v1",
        "organization": organization,
        "packet_id": frame["packet_id"],
        "frame_sha256": frame["frame_sha256"],
        "state": state,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "gateway_execution_authority": "NONE",
        "authority_effect": "NONE_OBSERVATION_ONLY",
    }
    return _json_request(
        "POST",
        "/api/org-federation/v1/acknowledgements",
        body=ack,
        headers={"X-StegVerse-Organization": organization},
    )


def publish_ecosystem_via_gateway(
    *,
    repo_root: Path,
    message_class: str,
    subject: str,
    body: dict[str, Any],
    requested_action: str | None = None,
    communication_id: str | None = None,
) -> dict[str, Any]:
    registry = K.load_registry(repo_root)
    directory = K.load_federation_directory(repo_root)
    orgs = [row["organization"] for row in directory["organizations"]]
    built = K.build_ecosystem_packets(
        origin_org=registry["organization"],
        origin_service=K.organization_slug(registry["organization"]) + ".org-control",
        organizations=orgs,
        message_class=message_class,
        subject=subject,
        body=body,
        requested_action=requested_action,
        communication_id=communication_id,
    )
    results = []
    for packet in built["packets"]:
        frame = K.carrier_frame(packet)
        stored = submit_frame(frame)
        results.append({
            "organization": packet["destination"]["org"],
            "packet_id": packet["packet_id"],
            "frame_sha256": frame["frame_sha256"],
            "gateway_state": stored.get("state"),
        })
    return {
        "communication_id": built["communication_id"],
        "organization_count": len(results),
        "published_count": sum(1 for row in results if row["gateway_state"] == "PENDING"),
        "gateway_execution_authority": "NONE",
        "organizations": results,
    }


def _persist_response(repo_root: Path, packet: dict[str, Any], execution_result: dict[str, Any]) -> Path:
    payload = packet.get("payload") or {}
    communication_id = str(payload.get("communication_id") or "unknown")
    out = repo_root / "resident-runtime" / "control" / "responses.d"
    out.mkdir(parents=True, exist_ok=True)
    name = K.sha({
        "communication_id": communication_id,
        "packet_id": packet["packet_id"],
        "origin_org": packet["origin"]["org"],
    }).split(":", 1)[1] + ".json"
    record = {
        "schema_version": "stegverse.ecosystem-response-observation.v1",
        "communication_id": communication_id,
        "packet_id": packet["packet_id"],
        "origin_org": packet["origin"]["org"],
        "message_class": payload.get("message_class"),
        "application_result": execution_result.get("application_result"),
        "reconstruction": execution_result.get("reconstruction"),
        "authority_effect": execution_result.get("authority_effect"),
    }
    path = out / name
    if path.exists():
        if json.loads(path.read_text()) != record:
            raise FederationGatewayTransportError("response observation write-once collision")
    else:
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return path


def resident_gateway_cycle(repo_root: Path) -> dict[str, Any]:
    registry = K.load_registry(repo_root)
    organization = registry["organization"]
    fetched = fetch_frame(organization)
    if fetched.get("state") == "NO_FRAME":
        return {
            "schema_version": "stegverse.org-federation-gateway-cycle.v1",
            "organization": organization,
            "state": "NO_FRAME",
            "frames_consumed": 0,
            "responses_emitted": 0,
            "gateway_execution_authority": "NONE",
        }
    if fetched.get("state") != "FRAME_AVAILABLE":
        raise FederationGatewayTransportError("unexpected gateway fetch state")
    frame = fetched["frame"]
    packet = K.recover_packet(frame)
    result = K.ingest_frame(repo_root, frame)
    response_emitted = 0
    response_ref = None
    if result.get("status") == "CONSUMED":
        execution = result["execution_result"]
        message_class = (packet.get("payload") or {}).get("message_class")
        if message_class in {"ecosystem.monitor.request", "ecosystem.work.request", "ecosystem.communication"}:
            response = K.build_control_response(packet, execution)
            response_frame = K.carrier_frame(response)
            submit_frame(response_frame)
            response_emitted = 1
            response_ref = response_frame["frame_sha256"]
        elif message_class in {"ecosystem.monitor.response", "ecosystem.work.ack", "ecosystem.communication.ack"}:
            _persist_response(repo_root, packet, execution)
        ack_state = "CONSUMED"
    else:
        ack_state = "BLOCKED"
    ack = acknowledge_frame(organization, frame, ack_state)
    return {
        "schema_version": "stegverse.org-federation-gateway-cycle.v1",
        "organization": organization,
        "state": ack_state,
        "packet_id": frame["packet_id"],
        "frame_sha256": frame["frame_sha256"],
        "frames_consumed": 1 if ack_state == "CONSUMED" else 0,
        "responses_emitted": response_emitted,
        "response_frame_sha256": response_ref,
        "ack_state": ack.get("state"),
        "gateway_execution_authority": "NONE",
    }


def collect_local_responses(repo_root: Path, communication_id: str) -> dict[str, Any]:
    directory = repo_root / "resident-runtime" / "control" / "responses.d"
    rows = []
    if directory.exists():
        for path in sorted(directory.glob("*.json")):
            try:
                value = json.loads(path.read_text())
            except Exception:
                continue
            if value.get("communication_id") == communication_id:
                rows.append(value)
    orgs = sorted({row.get("origin_org") for row in rows if row.get("origin_org")})
    return {
        "communication_id": communication_id,
        "response_count": len(orgs),
        "organizations": orgs,
        "complete": len(orgs) == 14,
    }
