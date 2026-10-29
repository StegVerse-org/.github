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
# Without a cycle epoch this destination does not stamp from a carried epoch.
refused_rows = kernel.consume_and_respond(ROOT, mesh_root=cmesh, node_state_root=WORK / "c-node-0", **roots)
# In a cycle with its own supplied epoch the claim is verified at admission and
# kept as inbound provenance; every receipt is stamped with the cycle epoch.
carried_rows = kernel.consume_and_respond(ROOT, mesh_root=cmesh, node_state_root=WORK / "c-node", **roots,
                                          hb_epoch=4096)
phases["carried_clock_calls"] = CALLS["n"] - start
carried_out = {"status": [(r.get("result") or {}).get("status") for r in carried_rows],
               "in_cycle_failure_code": [(r.get("result") or {}).get("failure_code") for r in carried_rows],
               "refused_without_cycle_epoch": [(r.get("result") or {}).get("failure_code") for r in refused_rows],
               "head_epoch": head_epoch, "head_receipt_sha": head_sha,
               "receipts": receipts_for(carried["packet_id"])}

# F1: a cycle at supplied 4096 consuming a frame at 77. This organization's
# receipts are stamped 4096 with the frame's 77 only in evidence.frame_reference;
# its answer has no resolution rule, so it is HB_EPOCH_CONFLICT and not published.
fmesh = WORK / "f1-mesh"
fmesh.mkdir()
at77 = addressed("c-frame-at-77")
kernel.publish_packet(at77, root=fmesh, epoch=77)
start = CALLS["n"]
f1_rows = kernel.consume_and_respond(ROOT, mesh_root=fmesh, node_state_root=WORK / "f1-node", **roots, hb_epoch=4096,
                                     hb_epoch_source={"source": "COMMITTED_REQUEST", "request_sha256": "sha256:" + "d" * 64})
phases["f1_clock_calls"] = CALLS["n"] - start


def full_receipts_for(packet_id):
    found = []
    for f in ledger_files():
        try:
            doc = json.loads(Path(f).read_text())
        except ValueError:
            continue
        if isinstance(doc, dict) and isinstance(doc.get("hb_reference"), dict) and packet_id in json.dumps(doc) \
                and "receipt_sha256" in doc and not f.endswith("HEAD.json"):
            found.append(doc)
    return found


f1 = {"status": [(r.get("result") or {}).get("status") for r in f1_rows],
      "response_published": [r.get("response_publication") is not None for r in f1_rows],
      "answers": [{"epoch": item["frame"]["heartbeat_reference"]["epoch"],
                   "derived_from_clock": item["frame"]["heartbeat_reference"]["derived_from_clock"],
                   "request_frame_reference": (kernel.recover_packet(item["frame"]).get("payload") or {})
                   .get("request_frame_reference")}
                  for item in kernel.scan_addressed_frames("Probe-Origin", root=fmesh)],
      "receipts": [{"schema": d.get("schema"), "epoch": d["hb_reference"].get("epoch"),
                    "derived_from_clock": d["hb_reference"].get("derived_from_clock"),
                    "frame_reference": ((d.get("evidence") or d.get("boundary_evidence") or {})
                                        .get("frame_reference"))}
                   for d in full_receipts_for(at77["packet_id"])],
      "mesh_answers": len(kernel.scan_addressed_frames("Probe-Origin", root=fmesh))}
carried_out["frame_references"] = [((d.get("evidence") or d.get("boundary_evidence") or {}).get("frame_reference"))
                                   for d in full_receipts_for(carried["packet_id"])]

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

# B-P36o / F-S1a: frames that cannot be ingested -- an incoherent heartbeat
# reference, a tampered digest, a clock frame with a malformed epoch -- are
# each a six-field refusal and quarantined; the valid frame beside them is
# consumed and ledgered, and a second cycle offers none of the bad ones.
import copy, hashlib as _hashlib


def reseal(frame):
    body = {k: v for k, v in frame.items() if k != "frame_sha256"}
    return {**body, "frame_sha256": "sha256:" + _hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()}


imesh = WORK / "i-mesh"
imesh.mkdir()
bad = {}
base = kernel.carrier_frame(addressed("c-gen"), epoch=4096)
generation = copy.deepcopy(base); generation["heartbeat_reference"]["generation"] = 4097
bad["generation"] = reseal(generation)
heartbeat_id = copy.deepcopy(kernel.carrier_frame(addressed("c-hbid"), epoch=4096))
heartbeat_id["heartbeat_reference"]["heartbeat_id"] = "HB:1"
bad["heartbeat_id"] = reseal(heartbeat_id)
tampered = kernel.carrier_frame(addressed("c-hash"), epoch=4096)
tampered["frame_sha256"] = "sha256:" + "0" * 64
bad["frame_hash"] = tampered
for epoch in ("abc", 5):
    clock_bad = copy.deepcopy(kernel.carrier_frame(addressed("c-clock-" + str(epoch)), epoch=4096))
    clock_bad["heartbeat_reference"]["epoch"] = epoch
    clock_bad["heartbeat_reference"]["derived_from_clock"] = True
    bad["clock_epoch_" + str(epoch)] = reseal(clock_bad)
# B-P36o on a CLOCK frame: an incoherent reference is refused explicitly before
# the CLOCK branch, never consumed as a clock frame. F11: a self-asserted CARRIED
# claim on an unflagged sampled frame is checked before CLOCK is returned.
clock_generation = copy.deepcopy(kernel.carrier_frame(addressed("c-clock-gen"), now_ns=FIXED_NS))
clock_generation["heartbeat_reference"]["generation"] = clock_generation["heartbeat_reference"]["epoch"] + 1
bad["clock_generation"] = reseal(clock_generation)
forged_sampled = copy.deepcopy(kernel.carrier_frame(addressed("c-clock-forged"), now_ns=FIXED_NS))
del forged_sampled["heartbeat_reference"]["derived_from_clock"]
forged_sampled["heartbeat_reference"].update({"source": "CARRIED:ORGANIZATION_LEDGER_HEAD",
                                              "head_receipt_sha": "sha256:" + "f" * 64})
bad["clock_forged_carried"] = reseal(forged_sampled)
# F-SCAN-RECURSION inside a frame: a packet whose bytes are too deeply nested to
# parse. Its digests hold, so recovery reaches the parse and raises RecursionError
# (a RuntimeError) -- the frame's defect, quarantined, never a pending writer fault.
deep_packet = copy.deepcopy(kernel.carrier_frame(addressed("c-deep-packet"), epoch=4096))
deep_raw = ('{"a":' + "[" * 200000).encode()
deep_packet["packet_base64"] = __import__("base64").b64encode(deep_raw).decode()
deep_packet["packet_sha256"] = kernel.sha(deep_raw)
bad["deep_packet"] = reseal(deep_packet)
for frame in bad.values():
    kernel.publish_frame(frame, root=imesh)
good = addressed("c-integrity-valid")
kernel.publish_packet(good, root=imesh, epoch=4096)
before_ledgers = ledger_files()
start = CALLS["n"]
first = kernel.consume_and_respond(ROOT, mesh_root=imesh, node_state_root=WORK / "i-node", **roots)
second = kernel.consume_and_respond(ROOT, mesh_root=imesh, node_state_root=WORK / "i-node", **roots)
phases["integrity_clock_calls"] = CALLS["n"] - start
names = {frame["packet_id"]: name for name, frame in bad.items()}
names[good["packet_id"]] = "valid"
integrity = {"rows": {names.get((r.get("result") or {}).get("packet_id")
                                or ((r.get("result") or {}).get("packet") or {}).get("packet_id"), "?"):
                      {"status": (r.get("result") or {}).get("status"),
                       "failure_code": (r.get("result") or {}).get("failure_code")} for r in first},
             "second_offered": len(second),
             "valid_in_ledgers": len(receipts_for(good["packet_id"])),
             "bad_in_ledgers": sum(len(receipts_for(f["packet_id"])) for f in bad.values())}

# F12 / B-P36p: frames.d entries that are not readable frames -- a read error,
# bytes that are not UTF-8, text that is not a JSON object, an oversized entry,
# a directory named *.json -- sort before a valid frame. Each is quarantined by
# its file name as six-field FRAME_INGEST_FAILED with no clock read and no
# ledger file, and the valid frame behind them is still consumed and ledgered.
def corrupt_mesh(name):
    root = WORK / name
    frames = root / "frames.d"
    frames.mkdir(parents=True)
    (frames / "0000-not-json.json").write_text("{not json")
    (frames / "0001-a-list.json").write_text("[1,2,3]")
    (frames / "0002-not-utf8.json").write_bytes(b"\xff\xfe{}")
    (frames / "0003-oversized.json").write_text('{"pad": "' + "x" * (kernel.FRAME_ENTRY_LIMIT_BYTES + 1) + '"}')
    (frames / "0004-a-directory.json").mkdir()
    (frames / "0005-read-error.json").write_text("{}")
    # F-SCAN-RECURSION: under the size cap, too deep for the parser.
    (frames / "0006-too-deep.json").write_text('{"a":' + "[" * 200000)
    return root


real_read = kernel.node_store_module.PosixStateStore.read_bounded


def failing_read(self, key, limit):
    if key.endswith("0005-read-error.json"):
        raise PermissionError(13, "Permission denied", key)
    return real_read(self, key, limit)


kernel.node_store_module.PosixStateStore.read_bounded = failing_read
corrupt_only = corrupt_mesh("s0-mesh")
before_ledgers = ledger_files()
start = CALLS["n"]
only_rows = kernel.consume_and_respond(ROOT, mesh_root=corrupt_only, node_state_root=WORK / "s0-node", **roots)
corrupt_only_ledger_files = len([f for f in ledger_files() if f not in before_ledgers])
smesh = corrupt_mesh("s-mesh")
scan_valid = addressed("c-scan-valid")
kernel.publish_packet(scan_valid, root=smesh, epoch=4096)
first = kernel.consume_and_respond(ROOT, mesh_root=smesh, node_state_root=WORK / "s-node", **roots)
second = kernel.consume_and_respond(ROOT, mesh_root=smesh, node_state_root=WORK / "s-node", **roots)
phases["scan_clock_calls"] = CALLS["n"] - start
kernel.node_store_module.PosixStateStore.read_bounded = real_read
scan_markers = {m["frame_name"]: m for m in (json.loads(p.read_text()) for p in (WORK / "s-node").rglob("*.json"))
                if isinstance(m, dict) and "frame_name" in m}
def scan_row_name(r):
    result = r.get("result") or {}
    packet_id = result.get("packet_id") or (result.get("packet") or {}).get("packet_id")
    return "valid" if packet_id == scan_valid["packet_id"] else Path(str(r["path"])).name


scan = {"rows": {scan_row_name(r):
                 {"status": (r.get("result") or {}).get("status"),
                  "failure_code": (r.get("result") or {}).get("failure_code")} for r in first},
        "order": [Path(str(r["path"])).name for r in first],
        "corrupt_only_rows": len(only_rows),
        "corrupt_only_ledger_files": corrupt_only_ledger_files,
        "valid_in_ledgers": len(receipts_for(scan_valid["packet_id"])),
        "second_offered": len(second),
        "markers": scan_markers}

# F-TYPE: a field that is decoded or hashed carrying the wrong type, before and
# after a valid frame. The guard is total: each is FRAME_INGEST_FAILED with its
# exception class, quarantined, never re-offered; the valid frame is ledgered.
tmesh = WORK / "t-mesh"
tmesh.mkdir()
typed = {}
for label, value in (("int", 123), ("null", None), ("list", [1]), ("dict", {"a": 1})):
    frame = copy.deepcopy(kernel.carrier_frame(addressed("c-type-" + label), epoch=4096))
    frame["packet_base64"] = value
    typed[label] = reseal(frame)
typed_names = {}
for label, frame in typed.items():
    typed_names[frame["packet_id"]] = label
    kernel.publish_frame(frame, root=tmesh)
# Two more, named to sort before and after every content-addressed frame name.
for label, name in (("first", "0000-wrong-type-first.json"), ("last", "zzzz-wrong-type-last.json")):
    frame = copy.deepcopy(kernel.carrier_frame(addressed("c-type-" + label), epoch=4096))
    frame["packet_base64"] = 7
    typed[label] = reseal(frame)
    typed_names[typed[label]["packet_id"]] = label
    (tmesh / "frames.d" / name).write_text(json.dumps(typed[label]))
type_valid = addressed("c-type-valid")
kernel.publish_packet(type_valid, root=tmesh, epoch=4096)
typed_names[type_valid["packet_id"]] = "valid"
start = CALLS["n"]
first = kernel.consume_and_respond(ROOT, mesh_root=tmesh, node_state_root=WORK / "t-node", **roots, hb_epoch=4096)
second = kernel.consume_and_respond(ROOT, mesh_root=tmesh, node_state_root=WORK / "t-node", **roots, hb_epoch=4096)
phases["type_clock_calls"] = CALLS["n"] - start
type_markers = {m.get("packet_id"): m for m in (json.loads(p.read_text()) for p in (WORK / "t-node").rglob("*.json"))
                if isinstance(m, dict) and "frame_name" in m}
ftype = {"rows": {typed_names.get(scan_packet_id, "?"): {"status": (r.get("result") or {}).get("status"),
                                                          "failure_code": (r.get("result") or {}).get("failure_code"),
                                                          "failed_predicate": (r.get("result") or {}).get("failed_predicate")}
                  for r in first for scan_packet_id in [(r.get("result") or {}).get("packet_id")
                                                        or ((r.get("result") or {}).get("packet") or {}).get("packet_id")]},
         "order": [typed_names.get(r["result"].get("packet_id") or (r["result"].get("packet") or {}).get("packet_id"))
                   for r in first],
         "valid_in_ledgers": len(receipts_for(type_valid["packet_id"])),
         "bad_in_ledgers": sum(len(receipts_for(f["packet_id"])) for f in typed.values()),
         "second_offered": len(second),
         "six_field_markers": all(type_markers.get(f["packet_id"], {}).get(k) for f in typed.values()
                                  for k in ("refusal_failure_code", "failed_predicate", "required_evidence_or_repair",
                                            "retry_entrypoint", "owning_existing_goal", "next_attempt"))}

# The same total guard and a seen-store on consume_addressed_frames.
amesh = WORK / "a-mesh"
amesh.mkdir()
a_bad = copy.deepcopy(kernel.carrier_frame(addressed("c-addressed-bad"), epoch=4096))
a_bad["packet_base64"] = 123
a_bad = reseal(a_bad)
(amesh / "frames.d").mkdir()
(amesh / "frames.d" / "0000-addressed-bad.json").write_text(json.dumps(a_bad))
a_valid = addressed("c-addressed-valid")
kernel.publish_packet(a_valid, root=amesh, epoch=4096)
start = CALLS["n"]
a_first = kernel.consume_addressed_frames(ROOT, mesh_root=amesh, node_state_root=WORK / "a-node", **roots)
a_second = kernel.consume_addressed_frames(ROOT, mesh_root=amesh, node_state_root=WORK / "a-node", **roots)
phases["addressed_clock_calls"] = CALLS["n"] - start
addressed_out = {"first": [((r.get("result") or {}).get("status"), (r.get("result") or {}).get("failure_code"),
                            (r.get("result") or {}).get("quarantined")) for r in a_first],
                 "second_packet_ids": [(r.get("result") or {}).get("packet_id")
                                       or ((r.get("result") or {}).get("packet") or {}).get("packet_id") for r in a_second],
                 "bad_packet_id": a_bad["packet_id"], "valid_in_ledgers": len(receipts_for(a_valid["packet_id"]))}

# F-TRANSIENT-RT: a fault writing this node's own state -- an OSError on the
# repository append, a lost compare-and-swap on the organization append, a store
# collision on the seen-marker -- is a non-terminal FRAME_DISPATCH_IO_FAILED: no
# marker, the frame stays pending, and the next pass consumes it exactly once.
real_custody = kernel.crossing_custody


class Faulting:
    def __init__(self, target, method, exc):
        self._target, self._method, self._exc = target, method, exc

    def __getattr__(self, name):
        attribute = getattr(self._target, name)
        if name != self._method or self._exc is None:
            return attribute

        def faulting(*args, **kwargs):
            exc, self._exc = self._exc, None
            raise exc
        return faulting


io = {}
for label, part, method, exc in (
        ("oserror_repo_append", "emitter", "append", OSError(5, "Input/output error")),
        ("lost_comparison_org_append", "organization_ledger", "append",
         RuntimeError("ledger_append_lost_comparison")),
        ("collision_seen_marker", None, None, None),
        # B-P36q torn write: the receipt is written and the HEAD write fails.
        ("torn_head_repo_append", "repository_store", "HEAD", OSError(5, "Input/output error")),
        ("torn_head_org_append", "organization_store", "HEAD", OSError(5, "Input/output error"))):
    imesh2 = WORK / ("io-mesh-" + label)
    imesh2.mkdir()
    victim = addressed("c-io-" + label)
    kernel.publish_packet(victim, root=imesh2, epoch=4096)
    faults = {"armed": True}

    def faulting_custody(*args, _part=part, _method=method, _exc=exc, **kwargs):
        custody = real_custody(*args, **kwargs)
        if _part is not None and faults["armed"] and _method == "HEAD":
            faults["armed"] = False
            store = custody[_part]
            real_put = store.put

            def torn_put(key, value, _armed={"on": True}):
                if key == "HEAD.json" and _armed["on"]:
                    _armed["on"] = False
                    raise _exc
                return real_put(key, value)
            store.put = torn_put
        elif _part is not None and faults["armed"]:
            faults["armed"] = False
            custody = {**custody, _part: Faulting(custody[_part], _method, _exc)}
        return custody

    real_mark = kernel.mark_federation_frame_seen
    if label == "collision_seen_marker":
        def faulting_mark(*args, **kwargs):
            if faults["armed"]:
                faults["armed"] = False
                raise kernel.node_store_module.WriteOnceCollision("federation_seen_marker_collision")
            return real_mark(*args, **kwargs)
        kernel.mark_federation_frame_seen = faulting_mark
    kernel.crossing_custody = faulting_custody
    node = WORK / ("io-node-" + label)
    start = CALLS["n"]
    try:
        first = kernel.consume_and_respond(ROOT, mesh_root=imesh2, node_state_root=node, **roots, hb_epoch=4096)
        markers_after_first = len([p for p in node.rglob("*.json") if "seen.d" in p.parts])
        second = kernel.consume_and_respond(ROOT, mesh_root=imesh2, node_state_root=node, **roots, hb_epoch=4096)
        third = kernel.consume_and_respond(ROOT, mesh_root=imesh2, node_state_root=node, **roots, hb_epoch=4096)
    finally:
        kernel.crossing_custody = real_custody
        kernel.mark_federation_frame_seen = real_mark
    phases["io_" + label + "_clock_calls"] = CALLS["n"] - start
    receipts = full_receipts_for(victim["packet_id"])
    heads = {}
    for name, root_dir in (("repo", WORK / "repo"), ("org", WORK / "org")):
        head_doc = json.loads((root_dir / "HEAD.json").read_text())
        heads[name] = (root_dir / "receipts" / (head_doc["receipt_sha256"][7:] + ".json")).is_file()
    io[label] = {"heads_consistent": heads,
                 "responses": len(kernel.scan_addressed_frames("Probe-Origin", root=imesh2)),
                 "first": [(r.get("result") or {}).get(k) for r in first
                           for k in ("status", "failure_code", "terminal")],
                 "first_record": (first[0].get("result") if first else None),
                 "first_marker": first[0].get("seen_marker") if first else "absent",
                 "markers_after_first": markers_after_first,
                 "second": [(r.get("result") or {}).get("status") for r in second],
                 "third_offered": len(third),
                 "receipt_shas": sorted({d["receipt_sha256"] for d in receipts}),
                 "receipt_schemas": sorted(d.get("schema") or "" for d in receipts)}

# F-REPUB keying: request A is answered; request B reuses A's packet id with
# different content. B is RESPONSE_ID_COLLISION before anything is ledgered or
# answered, and exactly one response exists.
dmesh = WORK / "dup-mesh"
dmesh.mkdir()
dup = {}
for label, subject in (("a", "first content"), ("b", "different content")):
    dup[label] = kernel.build_packet(origin_org="Probe-Origin", origin_service="probe-origin.org-control",
                                     destination_org=registry["organization"],
                                     destination_service=kernel.organization_slug(registry["organization"]) + ".org-control",
                                     payload={"communication_id": "c-dup", "message_class": "ecosystem.communication",
                                              "subject": subject, "body": {}},
                                     standing={"mode": "ESTABLISH_GENESIS", "node_ref": "clock-probe", "predecessor": None},
                                     packet_id="pkt-duplicate-request-id")
# Published one at a time, so A is answered before B arrives.
kernel.publish_packet(dup["a"], root=dmesh, epoch=4096)
dup_first = kernel.consume_and_respond(ROOT, mesh_root=dmesh, node_state_root=WORK / "dup-node", **roots, hb_epoch=4096)
kernel.publish_packet(dup["b"], root=dmesh, epoch=4096)
dup_second = kernel.consume_and_respond(ROOT, mesh_root=dmesh, node_state_root=WORK / "dup-node", **roots, hb_epoch=4096)
dup_third = kernel.consume_and_respond(ROOT, mesh_root=dmesh, node_state_root=WORK / "dup-node", **roots, hb_epoch=4096)
duplicate = {"first": [(r.get("result") or {}).get("status") for r in dup_first],
             "second": [((r.get("result") or {}).get("status"), (r.get("result") or {}).get("failure_code"))
                        for r in dup_second],
             "third_offered": len(dup_third),
             "responses": len(kernel.scan_addressed_frames("Probe-Origin", root=dmesh)),
             "receipt_shas": len({d["receipt_sha256"] for d in full_receipts_for("pkt-duplicate-request-id")})}

# PB-EXIT-SPLIT: the boundary processor's exit codes are kept apart by the
# caller. Its own --out write faulting (exit 75) is a non-terminal writer fault:
# no marker, no receipt, the frame consumed exactly once on the next pass. A
# frame the boundary refuses (exit 65) is terminal: FRAME_INGEST_FAILED,
# recorded DENY and marked, never offered again.
def endpoint_packet(capability, communication_id):
    return kernel.build_packet(origin_org="Probe-Origin", origin_service="probe-origin.org-control",
                               destination_org=registry["organization"], destination_service="stegverse-org.task-registry-disclosure",
                               payload={"communication_id": communication_id, "manifest": {"processing": {
                                   "capability": capability, "route_id": "stegverse.route.ecosystem-diagnostic.v1"}}},
                               standing={"mode": "ESTABLISH_GENESIS", "node_ref": "clock-probe", "predecessor": None})


pb = {}
for label, capability, fault in (("write_fault", "ecosystem_diagnostic", True), ("input_fault", "governance", False)):
    pmesh = WORK / ("pb-mesh-" + label)
    pmesh.mkdir()
    victim = endpoint_packet(capability, "c-pb-" + label)
    kernel.publish_packet(victim, root=pmesh, epoch=4096)
    node = WORK / ("pb-node-" + label)
    saved = {k: os.environ.get(k) for k in ("PYTHONPATH", "STEGVERSE_TEST_FAULT_REPLACE_SUFFIX",
                                            "STEGVERSE_TEST_FAULT_REPLACE_MARKER")}
    if fault:
        os.environ.update(PYTHONPATH=str(ROOT / "tests/fixtures/write-fault"),
                          STEGVERSE_TEST_FAULT_REPLACE_SUFFIX="execution.json",
                          STEGVERSE_TEST_FAULT_REPLACE_MARKER=str(WORK / ("pb-faulted-" + label)))
    start = CALLS["n"]
    try:
        first = kernel.consume_and_respond(ROOT, mesh_root=pmesh, node_state_root=node, **roots, hb_epoch=4096)
        markers_after_first = len([p for p in node.rglob("*.json") if "seen.d" in p.parts])
        receipts_after_first = len({d["receipt_sha256"] for d in full_receipts_for(victim["packet_id"])})
        second = kernel.consume_and_respond(ROOT, mesh_root=pmesh, node_state_root=node, **roots, hb_epoch=4096)
        third = kernel.consume_and_respond(ROOT, mesh_root=pmesh, node_state_root=node, **roots, hb_epoch=4096)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    phases["pb_" + label + "_clock_calls"] = CALLS["n"] - start
    result = (first[0].get("result") or {}) if first else {}
    pb[label] = {"faulted": (WORK / ("pb-faulted-" + label)).exists(),
                 "first": [result.get(k) for k in ("status", "disposition", "failure_code", "terminal")],
                 "first_record": result, "first_marker": first[0].get("seen_marker") if first else "absent",
                 "markers_after_first": markers_after_first, "receipts_after_first": receipts_after_first,
                 "second": [(r.get("result") or {}).get("status") for r in second],
                 "third_offered": len(third),
                 "receipt_shas": len({d["receipt_sha256"] for d in full_receipts_for(victim["packet_id"])})}

# After every injected fault, a later frame is consumed and ledgered normally.
later_mesh = WORK / "io-later-mesh"
later_mesh.mkdir()
later = addressed("c-io-later")
kernel.publish_packet(later, root=later_mesh, epoch=4096)
later_rows = kernel.consume_and_respond(ROOT, mesh_root=later_mesh, node_state_root=WORK / "io-later-node", **roots,
                                        hb_epoch=4096)
io_later = {"status": [(r.get("result") or {}).get("status") for r in later_rows],
            "receipts": len({d["receipt_sha256"] for d in full_receipts_for(later["packet_id"])})}

# A frame-only publication with no epoch: the WU-B13 helper default, marked.
start = CALLS["n"]
kernel.publish_packet(dict(packet, packet_id="probe-frame-only"), root=WORK / "frame-only-mesh")
phases["frame_only_clock_calls"] = CALLS["n"] - start

found = []
# Every reference this run wrote; the deliberately forged or off-epoch input
# frames (i-, s-, t- and f1-mesh) are inputs, not something the system wrote.
for path in (p for p in WORK.rglob("*.json") if p.is_file() and not {"i-mesh", "s-mesh", "s0-mesh", "t-mesh", "f1-mesh", "a-mesh"} & set(p.parts)):
    try:
        references(json.loads(path.read_text()), found)
    except ValueError:
        pass
print(json.dumps({"phases": phases, "references": found, "responses": responses, "quarantine": quarantine,
                  "carried": carried_out, "integrity": integrity, "scan": scan,
                  "f1": f1, "ftype": ftype, "io": io, "io_later": io_later, "addressed": addressed_out,
                  "duplicate": duplicate, "pb": pb}, sort_keys=True, default=str))
