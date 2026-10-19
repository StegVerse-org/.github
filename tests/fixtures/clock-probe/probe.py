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
                             standing={"mode": "ESTABLISH_GENESIS", "node_ref": "clock-probe", "predecessor": None})
kernel.publish_packet(packet, root=mesh, epoch=4096)
# A monitor request reaches resident_status, whose no-epoch default reads the clock.
monitor = kernel.build_packet(origin_org="Probe-Origin", origin_service="probe-origin.org-control",
                              destination_org=registry["organization"],
                              destination_service=kernel.organization_slug(registry["organization"]) + ".org-control",
                              payload={"communication_id": "c-monitor", "message_class": "ecosystem.monitor.request",
                                       "subject": "s", "body": {}},
                              standing={"mode": "ESTABLISH_GENESIS", "node_ref": "clock-probe", "predecessor": None})
kernel.publish_packet(monitor, root=mesh, epoch=4096)
import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    cycle.main(mesh_root=mesh, node_state_root=WORK / "node", hb_epoch="4096")
phases["supplied_writer_clock_calls"] = CALLS["n"] - start
responses = []
for item in kernel.scan_addressed_frames("Probe-Origin", root=mesh):
    body = (kernel.recover_packet(item["frame"]).get("payload") or {})
    responses.append({"message_class": body.get("message_class"),
                      "heartbeat_reference": item["frame"]["heartbeat_reference"],
                      "monitor_heartbeat": (((body.get("body") or {}).get("application_result") or {})
                                            .get("monitor_status") or {}).get("heartbeat_reference")})

# B-P36j/k: a CLOCK frame and a forged CARRIED claim beside a valid frame.
# Both are quarantined (terminal) with no clock read, and a second cycle
# proceeds without offering them again.
def addressed(communication_id):
    return kernel.build_packet(origin_org="Probe-Origin", origin_service="probe-origin.org-control",
                               destination_org=registry["organization"],
                               destination_service=kernel.organization_slug(registry["organization"]) + ".org-control",
                               payload={"communication_id": communication_id, "message_class": "ecosystem.communication",
                                        "subject": "s", "body": {}},
                               standing={"mode": "ESTABLISH_GENESIS", "node_ref": "clock-probe", "predecessor": None})


qmesh = WORK / "q-mesh"
qmesh.mkdir()
kernel.publish_packet(addressed("c-clock-frame"), root=qmesh)  # stamped from the (fixed) clock
kernel.publish_packet(addressed("c-forged-carried"), root=qmesh, epoch=4096,
                      provenance={"source": "CARRIED:ORGANIZATION_LEDGER_HEAD", "head_receipt_sha": "sha256:" + "f" * 64})
kernel.publish_packet(addressed("c-valid"), root=qmesh, epoch=4096)
ledger_files = lambda: sorted(str(p) for p in (WORK / "repo").rglob("*") if p.is_file()) + \
    sorted(str(p) for p in (WORK / "org").rglob("*") if p.is_file())
before_ledgers = ledger_files()
start = CALLS["n"]
roots = {"repo_ledger_root": os.environ["STEGVERSE_REPO_LEDGER_ROOT"],
         "org_ledger_root": os.environ["STEGVERSE_ORG_LEDGER_ROOT"]}
first = kernel.consume_and_respond(ROOT, mesh_root=qmesh, node_state_root=WORK / "q-node", **roots)
second = kernel.consume_and_respond(ROOT, mesh_root=qmesh, node_state_root=WORK / "q-node", **roots)
phases["quarantine_clock_calls"] = CALLS["n"] - start


def communication(row):
    packet_id = (row.get("result") or {}).get("packet_id") or ""
    return packet_id.split(":")[0] if ":" in packet_id else packet_id


markers = [json.loads(p.read_text()) for p in (WORK / "q-node").rglob("*.json")]
quarantine = {
    "first": [{"packet_id": (r.get("result") or {}).get("packet_id"),
               "status": (r.get("result") or {}).get("status"),
               "failure_code": (r.get("result") or {}).get("failure_code")} for r in first],
    "second_offered": len(second),
    "new_ledger_files": len([f for f in ledger_files() if f not in before_ledgers]),
    "refused_in_new_ledger_files": sum(
        1 for f in ledger_files() if f not in before_ledgers
        for r in first if (r.get("result") or {}).get("status") == "REFUSED"
        if (r.get("result") or {}).get("packet_id") in Path(f).read_text()),
    "markers": markers,
}

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
print(json.dumps({"phases": phases, "references": found, "responses": responses, "quarantine": quarantine},
                 sort_keys=True))
