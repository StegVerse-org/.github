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


roots = {"repo_ledger_root": os.environ["STEGVERSE_REPO_LEDGER_ROOT"],
         "org_ledger_root": os.environ["STEGVERSE_ORG_LEDGER_ROOT"]}
ledger_files = lambda: sorted(str(p) for p in (WORK / "repo").rglob("*") if p.is_file()) + \
    sorted(str(p) for p in (WORK / "org").rglob("*") if p.is_file())


def receipts_for(packet_id):
    found = []
    for f in ledger_files():
        try:
            doc = json.loads(Path(f).read_text())
        except ValueError:
            continue
        if isinstance(doc, dict) and isinstance(doc.get("hb_reference"), dict) and packet_id in json.dumps(doc):
            found.append({"schema": doc.get("schema"), "hb_reference": doc["hb_reference"]})
    return found


# B-P36m: a frame whose CARRIED claim names this organization's current
# supplied org-ledger head is consumed, and every receipt it produces keeps
# the claim (source, head_receipt_sha) -- never stripped to SUPPLIED.
custody = kernel.crossing_custody(ROOT, **roots)
org_store, ls = custody["organization_store"], custody["emitter"].ledger_store
head_sha = org_store.get(ls.HEAD_KEY)["receipt_sha256"]
head_epoch = org_store.get(ls.receipt_key(head_sha))["hb_reference"]["epoch"]
cmesh = WORK / "c-mesh"
cmesh.mkdir()
carried = addressed("c-carried-verified")
kernel.publish_packet(carried, root=cmesh, epoch=head_epoch,
                      provenance={"source": "CARRIED:ORGANIZATION_LEDGER_HEAD", "head_receipt_sha": head_sha})
start = CALLS["n"]
carried_rows = kernel.consume_and_respond(ROOT, mesh_root=cmesh, node_state_root=WORK / "c-node", **roots)
phases["carried_clock_calls"] = CALLS["n"] - start
carried_out = {"status": [(r.get("result") or {}).get("status") for r in carried_rows],
               "receipts": receipts_for(carried["packet_id"])}

# B-P36j/k + NARROW S1: CLOCK frames (a communication and a monitor request)
# are consumed but lend no epoch; a forged CARRIED claim is quarantined.
qmesh = WORK / "q-mesh"
qmesh.mkdir()
clock_comm = addressed("c-clock-frame")
clock_monitor = kernel.build_packet(origin_org="Probe-Origin", origin_service="probe-origin.org-control",
                                    destination_org=registry["organization"],
                                    destination_service=kernel.organization_slug(registry["organization"]) + ".org-control",
                                    payload={"communication_id": "c-clock-monitor", "message_class": "ecosystem.monitor.request",
                                             "subject": "s", "body": {}},
                                    standing={"mode": "ESTABLISH_GENESIS", "node_ref": "clock-probe", "predecessor": None})
kernel.publish_packet(clock_comm, root=qmesh)       # stamped from the (fixed) clock
kernel.publish_packet(clock_monitor, root=qmesh)    # stamped from the (fixed) clock
forged = addressed("c-forged-carried")
kernel.publish_packet(forged, root=qmesh, epoch=4096,
                      provenance={"source": "CARRIED:ORGANIZATION_LEDGER_HEAD", "head_receipt_sha": "sha256:" + "f" * 64})
valid = addressed("c-valid")
kernel.publish_packet(valid, root=qmesh, epoch=4096)
before_ledgers = ledger_files()
start = CALLS["n"]
first = kernel.consume_and_respond(ROOT, mesh_root=qmesh, node_state_root=WORK / "q-node", **roots)
second = kernel.consume_and_respond(ROOT, mesh_root=qmesh, node_state_root=WORK / "q-node", **roots)
phases["quarantine_clock_calls"] = CALLS["n"] - start
by_id = {packet_id: name for packet_id, name in ((clock_comm["packet_id"], "clock"), (clock_monitor["packet_id"], "clock_monitor"),
                                                 (forged["packet_id"], "forged"), (valid["packet_id"], "valid"))}
rows = {}
for r in first:
    result = r.get("result") or {}
    packet_id = result.get("packet_id") or (result.get("packet") or {}).get("packet_id")
    rows[by_id.get(packet_id, packet_id)] = {
        "status": result.get("status"), "failure_code": result.get("failure_code"),
        "epoch_lent": result.get("epoch_lent", "absent"),
        "organization_record_code": (r.get("organization_record") or {}).get("failure_code"),
        "response": r.get("response_publication") is not None,
        "monitor_status": ((result.get("execution_result") or {}).get("application_result") or {}).get("monitor_status")}
markers = [json.loads(p.read_text()) for p in (WORK / "q-node").rglob("*.json")]
quarantine = {
    "rows": rows,
    "second_offered": len(second),
    "new_ledger_files": len([f for f in ledger_files() if f not in before_ledgers]),
    "clock_or_forged_in_ledgers": sum(len(receipts_for(p["packet_id"])) for p in (clock_comm, clock_monitor, forged)),
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
print(json.dumps({"phases": phases, "references": found, "responses": responses, "quarantine": quarantine,
                  "carried": carried_out}, sort_keys=True))
