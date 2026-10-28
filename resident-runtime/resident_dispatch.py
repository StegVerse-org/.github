#!/usr/bin/env python3
"""Dispatch the resident cycle with a supplied heartbeat epoch, gate first.

The activation manifest's epoch_binding names the epoch-requiring entrypoints
(resident_executor.py, and federation_cycle.py, which the executor runs) and
the in-tree dispatcher that supplies their hb_epoch (this module, invoked
with --hb-epoch; its workflow was removed by G17, see the manifest's open
record RESIDENT_DISPATCH_WORKFLOW_REMOVED_BY_G17). The epoch is checked by the
shared rule before anything is invoked; an absent or invalid one is a six-field
refusal and exit 1. Each invocation carries the supplied epoch; none reads a
clock.

Where the manifest declares github_actions_is_runtime_authority false, the
dispatcher is not the runtime: it records the manifest's OPEN six-field
MANIFEST_DISPATCHER_PROHIBITED_ON_HOSTED (RUNTIME_DISPATCHER_PENDING_SUBSTRATE,
dispatcher status PENDING_SUBSTRATE), which does not fail the dispatch, and
hands the resident substrate the exact invocations instead of executing them.
"""
from __future__ import annotations
import argparse, importlib.util, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "resident-runtime" / "activation-manifest.json"
RETRY_ENTRYPOINT = "resident-runtime/resident_dispatch.py --hb-epoch"


def _rule():
    spec = importlib.util.spec_from_file_location("resident_dispatch_epoch_rule",
                                                  ROOT / "resident-runtime" / "aggregate_repo_transition.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invocations(binding, *, hb_epoch, mesh_root, node_state_root):
    """Each epoch-requiring entrypoint as it is invoked, every one carrying the supplied epoch."""
    common = ["--mesh-root", str(mesh_root), "--node-state-root", str(node_state_root), "--hb-epoch", str(hb_epoch)]
    return [{"entrypoint": entrypoint, "argv": [sys.executable, entrypoint, *common]}
            for entrypoint in binding["entrypoints"]]


def pending_substrate(binding):
    """The non-blocking six-field line the manifest declares: the dispatcher is not the runtime authority."""
    dispatcher = binding["runtime_dispatcher"]
    return {"status": dispatcher["status"], "line": dispatcher["line"], "blocking": dispatcher["blocking"],
            **dispatcher["record"], "consequence_committed": False}


def dispatch(*, hb_epoch, mesh_root, node_state_root, manifest=None, run=subprocess.run):
    rule = _rule()
    refusal = rule.epoch_refusal(hb_epoch if hb_epoch not in (None, "") else None)
    if refusal is not None:
        return {**refusal, "retry_entrypoint": RETRY_ENTRYPOINT, "consequence_committed": False}
    manifest = manifest if manifest is not None else json.loads(MANIFEST.read_text(encoding="utf-8"))
    binding = manifest["epoch_binding"]
    handed = invocations(binding, hb_epoch=hb_epoch, mesh_root=mesh_root, node_state_root=node_state_root)
    if manifest.get("github_actions_is_runtime_authority") is False:
        return {"schema": "stegverse.resident-runtime-dispatch/v1", "disposition": "ALLOW",
                "hb_epoch": str(hb_epoch), "invocations": handed, "executed": False,
                "runtime_dispatcher": pending_substrate(binding), "authority_effect": "NONE_DISPATCH_ONLY"}
    # The executor runs the federation cycle with the same epoch.
    completed = run(handed[0]["argv"], cwd=str(ROOT), check=False)
    return {"schema": "stegverse.resident-runtime-dispatch/v1",
            "disposition": "ALLOW" if completed.returncode == 0 else "FAIL_CLOSED",
            "hb_epoch": str(hb_epoch), "invocations": handed, "executed": True,
            "returncode": completed.returncode, "authority_effect": "NONE_DISPATCH_ONLY"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hb-epoch", default=None)
    parser.add_argument("--mesh-root", required=True)
    parser.add_argument("--node-state-root", required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    result = dispatch(hb_epoch=args.hb_epoch, mesh_root=args.mesh_root, node_state_root=args.node_state_root)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["disposition"] == "ALLOW" else 1


if __name__ == "__main__":
    import importlib.util as _writer_util
    _writer_spec = _writer_util.spec_from_file_location("writer_cli", Path(__file__).resolve().parent / "writer_cli.py")
    _writer = _writer_util.module_from_spec(_writer_spec); _writer_spec.loader.exec_module(_writer)
    sys.exit(_writer.run(main, "resident-runtime/resident_dispatch.py"))
