"""A peer organization materialized for a test: its own kernel, emitters and ledgers.

The kernel records every crossing it consumes on its own organization's
ledgers, through the emitters of the repository it lives in, and refuses a
dispatch root that is not that repository. A peer therefore cannot be a bare
directory handed to this organization's kernel: that would be this
organization's emitter writing a receipt in another organization's name. Each
peer gets a copy of the kernel, the two emitters and the ledger contracts,
rewritten to its own name, and consumes through its own kernel into ledger
roots supplied to it, as a materializer would.

Not a test module; loaded by path from the tests that need a peer.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json"
COPIED = (
    "org-kernel/kernel.py",
    "org-kernel/node_store.py",
    "resident-runtime/ledger_store.py",
    "resident-runtime/aggregate_repo_transition.py",
    ".stegverse/transition-ledger/emit.py",
    "org-boundary/runtime/process_boundary.py",
    "org-boundary/runtime/manifest_selection.py",
    "org-boundary/runtime/node_standing.py",
    CONTRACT,
)


class Peer:
    def __init__(self, root: Path, ledgers: Path, organization: str):
        self.root = root
        self.organization = organization
        self.repo_ledger = ledgers / "repo"
        self.org_ledger = ledgers / "org"
        spec = importlib.util.spec_from_file_location(
            "peer_kernel_" + organization.replace("-", "_").lower() + "_" + root.name,
            root / "org-kernel/kernel.py")
        self.kernel = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.kernel)

    def consume(self, *, mesh_root, node_state_root, **options):
        return self.kernel.consume_and_respond(
            self.root, mesh_root=mesh_root, node_state_root=node_state_root,
            repo_ledger_root=self.repo_ledger, org_ledger_root=self.org_ledger, **options)

    def consume_addressed(self, *, mesh_root, **options):
        return self.kernel.consume_addressed_frames(
            self.root, mesh_root=mesh_root,
            repo_ledger_root=self.repo_ledger, org_ledger_root=self.org_ledger, **options)

    def receipts(self, level="org"):
        root = self.org_ledger if level == "org" else self.repo_ledger
        return [json.loads(p.read_text(encoding="utf-8")) for p in (root / "receipts").glob("*.json")] \
            if (root / "receipts").is_dir() else []


def materialize(case, organization: str, services: list, *, extra=()) -> Peer:
    """A peer node for `organization` serving `services`, cleaned up with `case`."""
    root = Path(tempfile.mkdtemp())
    ledgers = Path(tempfile.mkdtemp())
    if case is not None:  # a workflow step passes None and leaves the runner to clean up
        case.addCleanup(shutil.rmtree, root, True)
        case.addCleanup(shutil.rmtree, ledgers, True)
    for relative in tuple(COPIED) + tuple(extra):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, root / relative)
    repository = json.loads((ROOT / ".stegverse/transition-ledger/contract.json").read_text())
    repository["repository"] = organization + "/.github"
    (root / ".stegverse/transition-ledger/contract.json").write_text(json.dumps(repository))
    org_contract = json.loads((ROOT / ".stegverse/transition-ledger/org-contract.json").read_text())
    org_contract["organization"] = organization
    (root / ".stegverse/transition-ledger/org-contract.json").write_text(json.dumps(org_contract))
    (root / "org-boundary/registry").mkdir(parents=True, exist_ok=True)
    (root / "org-boundary/registry/services.json").write_text(json.dumps({
        "schema_version": "stegverse.org-boundary-registry.v1",
        "organization": organization,
        "boundary_rule": "ALL_ORGANIZATION_INGRESS_EGRESS_GENERATED_AT_ORG_DOT_GITHUB_BOUNDARY",
        "services": services}))
    return Peer(root, ledgers, organization)
