"""Clock probe (B-P36g): run every receipt-writing route under a fixed, counting clock.

Run as a subprocess by tests/test_receipt_time_base.py::ClockProbeTests. The
standard library's datetime.datetime is replaced before anything is imported,
so every module's `from datetime import datetime` sees the counting clock.
Prints one JSON line: the clock calls per phase and every heartbeat reference
found in what was written.
"""
import datetime as _dt
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

CALLS = {"n": 0}
FIXED_NS = int(os.environ["PROBE_FIXED_CLOCK_NS"])


class CountingClock(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        CALLS["n"] += 1
        return _dt.datetime.fromtimestamp(FIXED_NS / 1e9, tz)


_dt.datetime = CountingClock
ROOT = Path(sys.argv[1])
WORK = Path(tempfile.mkdtemp(prefix="clock-probe-"))
os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = str(WORK / "repo")
os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = str(WORK / "org")


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def references(value, found):
    if isinstance(value, dict):
        for key in ("hb_reference", "heartbeat_reference"):
            if isinstance(value.get(key), dict):
                found.append(value[key])
        for item in value.values():
            references(item, found)
    elif isinstance(value, list):
        for item in value:
            references(item, found)
    return found


intr = load("probe_intr", "resident-runtime/intr_destination_ingress.py")
cycle = load("probe_federation_cycle", "resident-runtime/federation_cycle.py")
kernel = cycle.K
phases = {}

# Supplied epoch, every writer route.
start = CALLS["n"]
intr._append("PROBE", "probe-supplied", {"payload_sha256": "sha256:" + "e" * 64, "disposition": "ALLOW",
                                          "communication_id": "c-probe"}, "4096")
mesh = WORK / "mesh"
mesh.mkdir()
registry = kernel.load_registry(ROOT)
packet = kernel.build_packet(origin_org="Probe-Origin", origin_service="probe-origin.org-control",
                             destination_org=registry["organization"],
                             destination_service=kernel.organization_slug(registry["organization"]) + ".org-control",
                             payload={"communication_id": "c-frame", "message_class": "ecosystem.communication",
                                      "subject": "s", "body": {}},
                             standing={"mode": "GENESIS", "node_ref": "probe", "predecessor": None})
kernel.publish_packet(packet, root=mesh, epoch=4096)
import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    cycle.main(mesh_root=mesh, node_state_root=WORK / "node", hb_epoch="4096")
phases["supplied_writer_clock_calls"] = CALLS["n"] - start

# A frame-only publication with no epoch: the WU-B13 helper default, marked.
start = CALLS["n"]
kernel.publish_packet(dict(packet, packet_id="probe-frame-only"), root=WORK / "frame-only-mesh")
phases["frame_only_clock_calls"] = CALLS["n"] - start

found = []
for path in WORK.rglob("*.json"):
    try:
        references(json.loads(path.read_text()), found)
    except ValueError:
        pass
print(json.dumps({"phases": phases, "references": found}, sort_keys=True))
