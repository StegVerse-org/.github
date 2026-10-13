#!/usr/bin/env python3
"""Verify each governance decision return against the deciding organization's published ledger.

SDK-MR-A is complete end to end only when a returned decision is verified by
the SDK's `verify_governance_decision_return` (StegVerse-SDK#465): the return
readback names one admitted return for the packet, its closure is on this
organization's ledger, the decision is ALLOW or DENY, and the deciding
organization's own receipt is on an independent fresh-fetch readback of the
deciding organization's ledger.

This runs after the return workflow's own readback. The deciding
organization's ledger is named by the committed return request as `git+<repository>#<ref>`
and fetched anonymously into a fresh repository (no credential is used or
inferred), then read back with `organization_ledger_readback.py`. The
verifier is imported from the SDK checkout the caller names and the module's
location is recorded, so the acceptance names exactly which SDK judged it.

Nothing here appends, admits or promotes anything: it records what the
verifier says for each returned packet. ALLOW means the verification ran;
whether a packet is accepted end to end is that packet's own verifier result. An absent deciding ledger is not
completion; the verifier refuses it with its own six fields.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "stegverse.organization-governance-return-acceptance-run/v1"
OWNING_EXISTING_GOAL = "SDK-MR-A-VALIDATION-CUSTODY-001"
RETRY_ENTRYPOINT = ".github/workflows/organization-governance-return.yml (push: .stegverse/governance-return-requests/*.json)"


def _module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


intake = _module("governance_return_acceptance_intake", "resident-runtime/peer_mesh_intake.py")
readback_module = _module("governance_return_acceptance_readback", "resident-runtime/organization_ledger_readback.py")


def _refused(failure_code, failed_predicate, repair, next_attempt, **detail):
    return {"schema": SCHEMA, "disposition": "FAIL_CLOSED", "failure_code": failure_code,
            "failed_predicate": failed_predicate, "required_evidence_or_repair": repair,
            "retry_entrypoint": RETRY_ENTRYPOINT, "owning_existing_goal": OWNING_EXISTING_GOAL,
            "next_attempt": next_attempt, "acceptances": [], "authority_effect": "NONE_REFUSAL_ONLY", **detail}


def verifier(sdk_path=None):
    """The SDK's acceptance verifier, from `sdk_path` when given, and where it was loaded from."""
    if sdk_path is not None:
        sys.path.insert(0, str(Path(sdk_path).resolve()))
        for name in [n for n in sys.modules if n == "stegverse" or n.startswith("stegverse.")]:
            del sys.modules[name]
    module = importlib.import_module("stegverse.governance_return_evidence")
    source = Path(module.__file__).resolve()
    if sdk_path is not None and Path(sdk_path).resolve() not in source.parents:
        raise ImportError("verifier not loaded from " + str(sdk_path) + ": " + str(source))
    return module.verify_governance_decision_return, str(source)


def deciding_readback(deciding_ledger, work):
    """The deciding organization's ledger, read back from a fresh anonymous fetch; None when unpublished."""
    repository, ref = intake.binding.parse_locator(deciding_ledger)
    url = intake._fetch_url(repository)
    anonymous = intake._anonymous_env()
    listed = subprocess.run(["git", "ls-remote", url, ref], capture_output=True, text=True, cwd=work, env=anonymous)
    if listed.returncode != 0:
        raise OSError("deciding ledger not anonymously readable: " + listed.stderr.strip()[-300:])
    if not listed.stdout.strip():
        return None, None
    fresh = Path(work) / "deciding-ledger.git"
    subprocess.run(["git", "init", "-q", "--bare", str(fresh)], check=True, cwd=work, env=anonymous)
    fetched = subprocess.run(["git", "--git-dir", str(fresh), "fetch", "-q", "--no-tags", url, "+" + ref + ":" + ref],
                             capture_output=True, text=True, cwd=work, env=anonymous)
    if fetched.returncode != 0:
        raise OSError("deciding ledger not fetched: " + fetched.stderr.strip()[-300:])
    tip = subprocess.run(["git", "--git-dir", str(fresh), "rev-parse", ref], capture_output=True, text=True,
                         check=True).stdout.strip()
    try:
        return readback_module.readback("git+" + str(fresh) + "#" + ref), tip
    except readback_module.ReadbackRefused as exc:
        # A ledger that does not read back is no evidence; the verifier refuses it.
        return {"disposition": "FAIL_CLOSED", "detail": str(exc)[:300]}, tip


def accept(deciding_ledger, *, return_readback, sender_readback, sdk_path=None, work=None):
    """What the SDK verifier says for every packet the return readback names."""
    try:
        intake.binding.parse_locator(deciding_ledger)
    except ValueError as exc:
        return _refused("DECIDING_LEDGER_LOCATOR_INVALID", "DECIDING_LEDGER_IS_A_QUALIFIED_GIT_REF_OF_A_NAMED_REPOSITORY",
                        "supply deciding_ledger as git+<repository>#refs/<name>",
                        "commit a successor return request declaring a well-formed deciding_ledger", detail=str(exc))
    try:
        verify, source = verifier(sdk_path)
    except ImportError as exc:
        return _refused("SDK_ACCEPTANCE_VERIFIER_UNAVAILABLE", "SDK_ACCEPTANCE_VERIFIER_IMPORTS",
                        "check out the pinned SDK that carries stegverse/governance_return_evidence.py",
                        "commit a successor return request once the pinned SDK is available", detail=str(exc)[:300])
    with tempfile.TemporaryDirectory(dir=work) as scratch:
        try:
            deciding, tip = deciding_readback(deciding_ledger, scratch)
        except OSError as exc:
            return _refused("DECIDING_LEDGER_NOT_READABLE", "DECIDING_LEDGER_IS_ANONYMOUSLY_READABLE",
                            "the deciding organization must publish its ledger on a readable ref; none is inferred here",
                            "commit a successor return request once the deciding ledger is published", detail=str(exc))
    packets = sorted({str(row.get("governance_request_packet_id")) for row in (return_readback or {}).get("returns") or []
                      if isinstance(row, dict) and row.get("governance_request_packet_id")})
    acceptances = []
    for packet in packets:
        result = verify(return_readback, sender_readback=sender_readback, deciding_readback=deciding,
                        request_packet_id=packet)
        acceptances.append({"request_packet_id": packet, **result})
    return {"schema": SCHEMA, "disposition": "ALLOW", "deciding_ledger": deciding_ledger, "deciding_tip": tip,
            "deciding_readback_disposition": (deciding or {}).get("disposition"),
            "deciding_chain_length": (deciding or {}).get("chain_length"),
            "verifier_source": source, "acceptances": acceptances,
            "end_to_end_acceptance": sorted(a["request_packet_id"] for a in acceptances
                                            if a.get("end_to_end_acceptance") is True),
            "authority_effect": "NONE_VERIFICATION_ONLY"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deciding-ledger", required=True, help="git+<repository>#<ref> the deciding organization publishes")
    parser.add_argument("--return-readback", type=Path, required=True)
    parser.add_argument("--sender-readback", type=Path, required=True)
    parser.add_argument("--sdk-path", type=Path, default=None, help="the SDK checkout whose verifier judges")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    result = accept(args.deciding_ledger, return_readback=json.loads(args.return_readback.read_text()),
                    sender_readback=json.loads(args.sender_readback.read_text()), sdk_path=args.sdk_path)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(text)
    return 1 if result["disposition"] == "FAIL_CLOSED" else 0


if __name__ == "__main__":
    sys.exit(main())
