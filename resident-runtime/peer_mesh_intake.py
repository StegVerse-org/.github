#!/usr/bin/env python3
"""Take in the frames a peer organization published for this one onto this organization's mesh.

A run holds credentials for its own repository only (resident-runtime/
mesh_locator_binding.py), so a deciding organization answers on a mesh ref it
can publish -- its own -- and this organization reads that ref. Nothing is
pushed to the peer and no credential for it is used or inferred: the peer's
ref is fetched anonymously, and every frame on it addressed to this
organization is placed on this organization's designated mesh with the same
write-once put the kernel uses, under the key its content addresses.

A frame is taken only if its key addresses its content and the kernel
recovers its packet; anything else is refused, and the run with it, before
anything is placed. A key this mesh already holds with the same frame is
already present; with a different frame it is a collision, never an
overwrite. A peer that has published nothing is an observation, not a
transition: absence is not an arrival.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "stegverse.peer-mesh-intake/v1"
OWNING_EXISTING_GOAL = "SDK-MR-A-VALIDATION-CUSTODY-001"
RETRY_ENTRYPOINT = ".github/workflows/organization-governance-return.yml (workflow_dispatch: peer_mesh)"


def _module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kernel = _module("peer_mesh_intake_kernel", "org-kernel/kernel.py")
binding = _module("peer_mesh_intake_binding", "resident-runtime/mesh_locator_binding.py")
node_store = kernel.node_store_module


def _refused(failure_code, failed_predicate, repair, next_attempt, **detail):
    return {"schema": SCHEMA, "disposition": "FAIL_CLOSED", "failure_code": failure_code,
            "failed_predicate": failed_predicate, "required_evidence_or_repair": repair,
            "retry_entrypoint": RETRY_ENTRYPOINT, "owning_existing_goal": OWNING_EXISTING_GOAL,
            "next_attempt": next_attempt, "taken": [], "authority_effect": "NONE_REFUSAL_ONLY", **detail}


def _fetch_url(repository):
    """Where the peer's ref is read from: a GitHub slug over anonymous HTTPS, or a path as given."""
    if repository.startswith(("https://", "/", ".")):
        return repository
    return "https://github.com/" + repository


def intake(peer_locator, *, own_mesh_root, organization=None):
    """Place every verified frame the peer published for this organization on its own mesh."""
    organization = organization or kernel.load_registry(ROOT)["organization"]
    try:
        repository, ref = binding.parse_locator(peer_locator)
    except ValueError as exc:
        return _refused("PEER_MESH_LOCATOR_INVALID", "PEER_MESH_LOCATOR_IS_A_QUALIFIED_GIT_REF_OF_A_NAMED_REPOSITORY",
                        "supply peer_mesh as git+<repository>#refs/<name>",
                        "rerun the dispatch with a well-formed peer locator", detail=str(exc), peer=peer_locator)
    with tempfile.TemporaryDirectory() as tmp:
        peer_git = Path(tmp) / "peer.git"
        subprocess.run(["git", "init", "-q", "--bare", str(peer_git)], check=True)
        # Run outside any checkout, so no repository-local credential applies.
        anonymous = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        listed = subprocess.run(["git", "ls-remote", _fetch_url(repository), ref], capture_output=True, text=True,
                                cwd=tmp, env=anonymous)
        if listed.returncode != 0:
            return _refused("PEER_MESH_NOT_READABLE", "PEER_MESH_REF_IS_ANONYMOUSLY_READABLE",
                            "the peer's mesh ref must be readable without a credential; none is inferred here",
                            "rerun once the peer publishes its mesh on a readable ref",
                            peer=peer_locator, detail=listed.stderr.strip()[-300:])
        if not listed.stdout.strip():
            return {"schema": SCHEMA, "disposition": "NOTHING_PUBLISHED", "peer": peer_locator,
                    "observation_only": True, "absence_is_not_a_transition": True, "taken": [],
                    "authority_effect": "NONE_OBSERVATION_ONLY"}
        subprocess.run(["git", "--git-dir", str(peer_git), "fetch", "-q", "--no-tags", _fetch_url(repository),
                        "+" + ref + ":" + ref], check=True, capture_output=True, cwd=tmp, env=anonymous)
        peer_tip = subprocess.run(["git", "--git-dir", str(peer_git), "rev-parse", ref],
                                  capture_output=True, text=True, check=True).stdout.strip()
        peer = kernel.mesh_store("git+" + str(peer_git) + "#" + ref)
        own = kernel.mesh_store(own_mesh_root)
        addressed, findings = [], []
        for key in sorted(peer.list_prefix(node_store.MESH_FRAME_PREFIX)):
            frame = peer.get(key)
            if not isinstance(frame, dict) or frame.get("destination_org") != organization:
                continue
            if node_store.frame_key(frame) != key:
                findings.append({"key": key, "finding": "PEER_FRAME_KEY_DOES_NOT_ADDRESS_ITS_CONTENT"})
                continue
            try:
                packet = kernel.recover_packet(frame)
            except Exception as exc:  # the kernel's own recovery decides what a frame is
                findings.append({"key": key, "finding": "PEER_FRAME_DOES_NOT_RECOVER", "detail": str(exc)[:200]})
                continue
            held = own.get(key)
            if held is not None and held != frame:
                findings.append({"key": key, "finding": "PEER_FRAME_COLLIDES_WITH_A_HELD_FRAME"})
                continue
            addressed.append((key, frame, packet, held is not None))
        if findings:
            return _refused("PEER_MESH_FRAME_REFUSED", "EVERY_PEER_FRAME_FOR_THIS_ORGANIZATION_VERIFIES",
                            "the peer must publish frames whose key addresses their content and whose packet recovers; "
                            "nothing was placed", "rerun once the peer's published frames verify",
                            peer=peer_locator, peer_tip=peer_tip, findings=findings)
        taken, present = [], []
        for key, frame, packet, held in addressed:
            row = {"key": key, "packet_id": frame.get("packet_id"), "frame_sha256": frame.get("frame_sha256"),
                   "origin_org": frame.get("origin_org"), "message_class": (packet.get("payload") or {}).get("message_class")}
            if held:
                present.append(row)
                continue
            own.put_once(key, frame)
            taken.append(row)
        return {"schema": SCHEMA, "disposition": "ALLOW", "organization": organization, "peer": peer_locator,
                "peer_tip": peer_tip, "own_mesh_root": str(own_mesh_root), "taken": taken,
                "already_present": present, "authority_effect": "NONE_CARRIER_ONLY"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--peer-mesh", required=True, help="git+<repository>#refs/<name> the peer publishes")
    parser.add_argument("--own-mesh-root", required=True, help="this organization's bound mesh locator")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    result = intake(args.peer_mesh, own_mesh_root=args.own_mesh_root)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(text)
    return 1 if result["disposition"] == "FAIL_CLOSED" else 0


if __name__ == "__main__":
    sys.exit(main())
