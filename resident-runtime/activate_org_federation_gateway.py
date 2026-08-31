#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REQUEST = ROOT / "resident-runtime" / "activation-requests" / "org-federation-gateway.json"


def _env_path(name: str) -> Path:
    raw = os.getenv(name, "").strip()
    if not raw:
        raise RuntimeError(name + " not configured")
    return Path(raw).expanduser().resolve()


def _optional_path(name: str) -> Path | None:
    raw = os.getenv(name, "").strip()
    return Path(raw).expanduser().resolve() if raw else None


def main() -> int:
    request = json.loads(REQUEST.read_text())
    llm_root = _env_path("STEGVERSE_LLM_ADAPTER_ROOT")
    required = [llm_root / p for p in request["required_source_surfaces"]]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise RuntimeError("required federation gateway source missing: " + ",".join(missing))

    launcher = llm_root / request["source_entrypoint"]
    host = os.getenv("STEGVERSE_SERVICE_GATEWAY_HOST", "127.0.0.1").strip()
    port = int(os.getenv("STEGVERSE_SERVICE_GATEWAY_PORT", "8000").strip())
    durable_root = Path(
        os.getenv(
            "STEGVERSE_SERVICE_GATEWAY_DURABLE_ROOT",
            str(Path.home() / ".local" / "state" / "stegverse" / "service-gateway" / "data"),
        )
    ).expanduser().resolve()

    status = subprocess.run(
        [sys.executable, str(launcher), "status"],
        cwd=llm_root,
        text=True,
        capture_output=True,
        check=True,
    )
    current = json.loads(status.stdout)
    started = False
    receipt = current.get("receipt")
    if current.get("state") != "RUNNING":
        cmd = [
            sys.executable,
            str(launcher),
            "start",
            "--host",
            host,
            "--port",
            str(port),
            "--durable-root",
            str(durable_root),
        ]
        cert = _optional_path("STEGDEPLOY_NATIVE_TLS_CERT_FILE")
        key = _optional_path("STEGDEPLOY_NATIVE_TLS_KEY_FILE")
        if bool(cert) != bool(key):
            raise RuntimeError("TLS cert/key must be provided together")
        if cert and key:
            cmd += ["--tls-cert-file", str(cert), "--tls-key-file", str(key)]
        started_result = subprocess.run(
            cmd,
            cwd=llm_root,
            text=True,
            capture_output=True,
            check=True,
        )
        receipt = json.loads(started_result.stdout)
        started = True

    if not isinstance(receipt, dict):
        raise RuntimeError("native gateway receipt missing")
    if receipt.get("org_federation_rendezvous_enabled") is not True:
        raise RuntimeError("organization federation rendezvous not enabled in gateway receipt")
    if receipt.get("org_federation_gateway_execution_authority") != "NONE":
        raise RuntimeError("gateway execution authority drift")
    rendezvous_root = Path(str(receipt.get("org_federation_rendezvous_root", ""))).expanduser().resolve()
    rendezvous_root.mkdir(parents=True, exist_ok=True)

    result = {
        "schema_version": "stegverse.org-federation-gateway-activation-result.v1",
        "organization": "StegVerse-org",
        "request_id": request["request_id"],
        "state": "LOCAL_NATIVE_GATEWAY_READY",
        "started_this_run": started,
        "host": receipt.get("host"),
        "port": receipt.get("port"),
        "org_federation_rendezvous_enabled": True,
        "org_federation_rendezvous_root": str(rendezvous_root),
        "gateway_execution_authority": "NONE",
        "credential_authority": "TV/TVC",
        "github_token_runtime_authority": "NONE",
        "public_reachability_observed": False,
    }
    out = ROOT / "resident-runtime" / "evidence" / "org-federation-gateway.latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
