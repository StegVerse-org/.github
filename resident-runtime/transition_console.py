#!/usr/bin/env python3
"""A console view of state transitions, which says what reality it is watching.

Two questions this answers together, because answering either alone would
mislead.

**What a console shows.** State transitions, in heartbeat order, as they are
appended. Not a log of what a process did -- the receipted dispositions, which
is the only thing in this ecosystem that is evidence rather than narration.

**What "live" can mean here.** Not what it usually means. Ordering is
`OSCILLATOR_HEARTBEAT_EPOCH_ONLY` and `wall_clock_ordering_permitted` is false,
so there is no wall-clock stream to tail, and there is no host to push from. A
transition becomes visible at the epoch a reader samples, so "live" means *at
the resolution the reader sampled*, and the console reports that resolution
rather than implying continuity. A console that scrolled would be claiming a
stream nobody implemented.

**What reality it is watching**, which is the part that was never established.
The SDK can be fetched and run with no network at all, and it can in principle
be run against a medium other nodes also reach. Those produce very different
evidence, and until now nothing made a run say which one it was in. The mesh
store already knows -- `node_store` records how a store came to know where it
is, and only a supplied root is considered portable:

    SUPPLIED                      a root this run was told
    DERIVED_FROM_ENVIRONMENT      a root taken from the environment
    DERIVED_FROM_HOME_DIRECTORY   the fallback the kernel itself calls
                                  "a node pretending to be a host"

    PORTABLE_PROVENANCE = {SUPPLIED}

so the console derives the run mode from that rather than declaring a second
vocabulary for it.

**This is the mesh axis, and only the mesh axis.** This organization's mesh
store kind is `POSIX_FILESYSTEM`, so the medium is a filesystem and two
parties who share no filesystem cannot share a mesh. The roadmap item that
would change it -- appenders on separate substrates producing one chain -- is
recorded as blocked, pending an owner decision about what a lost
compare-and-swap should leave behind.

An earlier revision of this module turned that into
`reaches_a_production_ecosystem_over_a_network: false` and offered the store
kind as the reason, which generalised a fact about one organization's frame
medium into a claim about the ecosystem. It is not one. The SDK publishes a
`CANONICAL_PRODUCTION` routing surface whose runtime binding is installed;
what is unproven there is an *authenticated* crossing, and a path that is not
proven authentic is not the same as a path that does not exist. The correction
matters because the two readings lead a reviewer to opposite conclusions.

**Local versus production for an SDK caller is decided on the route axis, not
here.** A manifest declares a route, the route declares a `routing_surface`,
and `stegverse/route_resolution.py` refuses substitution and grants no
authority by selection. This console cites that surface rather than answering
for it; a second vocabulary over an axis that already has one would be the
defect this ecosystem keeps correcting.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]

CONSOLE_SCHEMA = "stegverse.transition-console.v1"
AUTHORITY_EFFECT = "NONE_CONSOLE_ONLY"


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kernel = _module("org_kernel", "org-kernel/kernel.py")
node_store = _module("node_store", "org-kernel/node_store.py")
lineage = _module("receipt_lineage_projection",
                  "resident-runtime/receipt_lineage_projection.py")

#: StegOS no longer derives a mesh location from host state. The only valid
#: mode is a mesh location explicitly supplied by the node materializer.
MATERIALIZER_SUPPLIED = "MATERIALIZER_SUPPLIED"

_MODE_MEANS = {
    MATERIALIZER_SUPPLIED:
        "This run was explicitly supplied its mesh location by the materializer; "
        "no environment variable, home directory, checkout, or host clock selected it.",
}


def live_means() -> dict[str, Any]:
    """What "live" can honestly mean for a state transition here."""
    return {
        "ordering": "OSCILLATOR_HEARTBEAT_EPOCH_ONLY",
        "wall_clock_ordering_permitted": False,
        "is_a_pushed_stream": False,
        "becomes_visible": "AT_THE_EPOCH_THE_READER_SAMPLES",
        "live_means_at_the_resolution_the_reader_sampled": True,
        # Said rather than implied, because a console is the surface a reader
        # is most likely to mistake for a tail of something continuous.
        "a_gap_between_samples_is_not_an_absence_of_transitions": True,
    }


def run_mode(root: Path | None = None, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Which reality this run observes from a materializer-supplied mesh."""
    if env is not None:
        raise ValueError("host_environment_mesh_binding_forbidden")
    provenance = kernel.node_state_provenance(root)
    mode = MATERIALIZER_SUPPLIED
    return {
        "run_mode": mode,
        "run_mode_means": _MODE_MEANS[mode],
        "mesh_locator": provenance["mesh_locator"],
        "mesh_provenance": provenance["mesh_provenance"],
        "mesh_portable": provenance["mesh_portable"],
        "store_kind": provenance["store_kind"],
        # This is the mesh axis. It is not the route axis, and an earlier
        # revision of this module conflated them -- it reported
        # `reaches_a_production_ecosystem_over_a_network: false` and gave the
        # mesh store kind as the reason, which generalised a fact about this
        # organization's frame medium into a claim about the ecosystem. The
        # SDK publishes a `CANONICAL_PRODUCTION` routing surface with its
        # runtime installed; what is unproven there is an authenticated
        # crossing, which is a different statement from a path not existing.
        "axis": "MESH_MEDIUM",
        "mesh_medium_is_a_shared_filesystem_or_nothing": True,
        "two_parties_sharing_no_filesystem_cannot_share_this_mesh": True,
        "why": ("this organization's mesh store kind is " + provenance["store_kind"]
                + ", so the medium is a filesystem and reach over it is reach "
                  "to that filesystem"),
        "changing_this_is_recorded_as": "SVORG-LEDGER-APPEND-SUBSTRATE-001",
        # The other axis, cited to the surface that owns it rather than
        # restated or answered here. A manifest declares a route, the route
        # declares a routing surface, and that is where local-versus-production
        # is decided for an SDK caller.
        "route_axis_owner": "StegVerse-org/StegVerse-SDK:stegverse/route_resolution.py",
        "route_axis_field": "routing_surface",
        "route_axis_is_not_resolved_here": True,
        "authority_effect": AUTHORITY_EFFECT,
    }


def lines(records: Sequence[Mapping[str, Any]]) -> list[str]:
    """One console line per transition, in the chain's own order."""
    rendered = []
    for record in records:
        rendered.append(
            "HB {epoch:<8} {event:<11} seq={seq:<4} {cls:<34} {rid}".format(
                epoch=record["hb_epoch"], event=record["event_type"],
                seq=record["sequence"], cls=record["transition_class"],
                rid=record["receipt_id"][:28]))
    return rendered


def transitions(chain: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The chain as console records: the lineage projection plus what it ran under."""
    projected = lineage.project(list(chain))
    rows = []
    for receipt, record in zip(chain, projected):
        reference = receipt.get("hb_reference") or {}
        rows.append({
            **record,
            "transition_class": receipt.get("transition_class") or "UNDECLARED",
            "hb_epoch": reference.get("epoch"),
            "hb_derived_from_clock": reference.get("derived_from_clock"),
            "authority_effect": receipt.get("authority_effect"),
        })
    return rows


def view(chain: Sequence[Mapping[str, Any]] | None = None, *,
         root: Path | None = None, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The console's whole output: what is transitioning, and under what reality."""
    resolved = lineage.repository_chain() if chain is None else list(chain)
    rows = transitions(resolved)
    return {
        "schema": CONSOLE_SCHEMA,
        "run": run_mode(root, env),
        "live": live_means(),
        "transitions": rows,
        "transition_count": len(rows),
        "lines": lines(rows),
        "ledger_unchanged_by_this_view": True,
        "authority_effect": AUTHORITY_EFFECT,
    }


def _main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        prog="transition_console.py",
        description="State transitions in heartbeat order, and the reality this run observes.")
    parser.add_argument("--mesh-root", required=True,
                        help="mesh location supplied by the node materializer")
    parser.add_argument("--json", action="store_true", help="emit the whole view as JSON")
    args = parser.parse_args(argv)

    rendered = view(root=Path(args.mesh_root))
    if args.json:
        print(json.dumps(rendered, indent=2, sort_keys=True))
        return 0

    run = rendered["run"]
    print("run mode : " + run["run_mode"])
    print("           " + run["run_mode_means"])
    print("mesh     : " + run["mesh_locator"])
    print("           provenance " + run["mesh_provenance"]
          + " | portable " + str(run["mesh_portable"])
          + " | kind " + run["store_kind"])
    print("axis     : " + run["axis"] + " -- this reports where the mesh is,")
    print("           not which route a manifest declared")
    print("           " + run["why"])
    print("route    : local-versus-production for an SDK caller is decided by")
    print("           " + run["route_axis_field"] + ", owned by " + run["route_axis_owner"])
    print('live     : ordering ' + rendered["live"]["ordering"]
          + "; visible " + rendered["live"]["becomes_visible"])
    print("")
    if not rendered["transitions"]:
        # An empty console is not an idle ecosystem; it is this reader, reading
        # this mesh. Said, because a blank screen is the easiest thing to
        # misread in the whole surface.
        print("no transitions on this chain -- which is a statement about this")
        print("mesh and this reader, not about the ecosystem being still")
        return 0
    for line in rendered["lines"]:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
