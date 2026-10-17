"""P1 interface (#163): the supplied epoch reaches every ledger append, and the writers' location is an input.

(A) The shared epoch rule. An egress emission or closure, and a capability
address consumed through `kernel.dispatch`, append at both ledger levels. Each
takes the epoch it is given -- the frame's, for a consumed crossing -- and never
reads a clock: none is FAIL_CLOSED `HB_EPOCH_NOT_SUPPLIED`, a non-integer or one
below the HB32 anchor is FAIL_CLOSED `HB_EPOCH_INVALID`, each with the six
fields and nothing published or appended.

(B) `--ledger-component` names the root the ledger writers load from and
`--consumer-root` the root their contracts resolve from. Absent, both are this
checkout. A path given that does not hold them is FAIL_CLOSED
`LEDGER_COMPONENT_PATH_INVALID` / `CONSUMER_ROOT_PATH_INVALID`.

Ledger roots and the mesh are temporary per test; no secret is read.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
MANIFEST = ROOT / "tests/fixtures/sdk-manifests/task-registry-disclosure-to-llm-adapter.json"
GENESIS_PATH = ROOT / "tests/fixtures/crossing-standing-genesis.json"
GENESIS = {k: v for k, v in json.loads(GENESIS_PATH.read_text(encoding="utf-8")).items()
           if not k.startswith("_")}
PEER = "StegVerse-Labs"
ADDRESS = "stegverse-org.sdk-manifest-ingress"


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kernel = _load("kernel_p1", "org-kernel/kernel.py")
capability = _load("capability_ingress_p1", "org-boundary/runtime/capability_ingress.py")
egress = _load("organization_egress_boundary_p1", "resident-runtime/organization_egress_boundary.py")


class TemporaryLedgers(unittest.TestCase):
    LEDGER_ROOTS = ("STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT")

    def setUp(self):
        self._work = tempfile.TemporaryDirectory()
        self.addCleanup(self._work.cleanup)
        self.work = Path(self._work.name)
        self.mesh = self.work / "mesh"
        previous = {name: os.environ.get(name) for name in self.LEDGER_ROOTS}
        for name in self.LEDGER_ROOTS:
            os.environ[name] = str(self.work / name.lower())
        self.addCleanup(lambda: [os.environ.pop(n, None) if v is None else os.environ.__setitem__(n, v)
                                 for n, v in previous.items()])

    def written(self):
        return [path for name in self.LEDGER_ROOTS for path in Path(os.environ[name]).rglob("*.json")
                if Path(os.environ[name]).exists()]

    def assert_six_fields(self, refusal, code):
        self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
        self.assertEqual(refusal["failure_code"], code)
        for field in SIX_FIELDS:
            self.assertTrue(isinstance(refusal.get(field), str) and refusal[field].strip(), field)


class EgressSuppliedEpochTests(TemporaryLedgers):
    def emit(self, **overrides):
        body = {"payload": {"message_class": "ecosystem.communication",
                            "communication_id": "p1-epoch", "body": {}},
                "standing": GENESIS, "mesh_root": self.mesh, "hb_epoch": 32}
        body.update(overrides)
        return egress.emit(PEER, body.pop("payload"), **body)

    def test_no_epoch_is_refused_before_anything_is_published_or_appended(self):
        out = self.emit(hb_epoch=None)
        self.assert_six_fields(out, "HB_EPOCH_NOT_SUPPLIED")
        self.assertEqual(out["failed_predicate"], "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH")
        self.assertIs(out["emitted"], False)
        self.assertIs(out["refusal_recorded"], False)
        self.assertEqual(out["retry_entrypoint"], "resident-runtime/organization_egress_boundary.py::emit")
        self.assertFalse((self.mesh / "frames.d").exists() and any((self.mesh / "frames.d").iterdir()))
        self.assertEqual(self.written(), [])

    def test_an_invalid_epoch_is_refused_the_same_way(self):
        for value in (31, True, "32", -1):
            with self.subTest(value=value):
                out = self.emit(hb_epoch=value)
                self.assert_six_fields(out, "HB_EPOCH_INVALID")
        self.assertEqual(self.written(), [])

    def test_a_supplied_epoch_still_emits_and_appends_at_that_epoch(self):
        out = self.emit(hb_epoch=41)
        self.assertEqual(out["disposition"], "ALLOW")
        receipts = [json.loads(p.read_text()) for p in self.written()]
        epochs = {r["hb_reference"]["epoch"] for r in receipts if "hb_reference" in r}
        self.assertEqual(epochs, {41})

    def test_no_clock_is_read_on_the_refusal(self):
        original = kernel.hb_reference
        def no_clock(*args, **kwargs):  # pragma: no cover - asserted not called
            raise AssertionError("a clock-derived epoch was requested")
        egress.kernel.hb_reference = no_clock
        self.addCleanup(setattr, egress.kernel, "hb_reference", original)
        self.assert_six_fields(self.emit(hb_epoch=None), "HB_EPOCH_NOT_SUPPLIED")


class CapabilityIngressEpochTests(TemporaryLedgers):
    def packet(self, packet_id="p1-capability-epoch"):
        body = json.loads(MANIFEST.read_text(encoding="utf-8"))
        return kernel.build_packet(
            origin_org=PEER, origin_service="stegverse-labs.sdk-manifest-ingress",
            destination_org="StegVerse-org", destination_service=ADDRESS,
            payload={"schema": "stegverse.sdk-manifest-crossing-payload/v1",
                     "declared_transition_surface": "LLM_ADAPTER",
                     "manifest": body, "manifest_sha256": kernel.sha(body)},
            standing=GENESIS, transition_reference="intr:transition:p1-epoch",
            authority_effect="NONE", packet_id=packet_id)

    def test_the_resolver_refuses_no_epoch_with_six_fields_before_loading_the_operation(self):
        service = next(r for r in kernel.load_registry(ROOT)["services"] if r["service_id"] == ADDRESS)
        loaded = []
        original = capability.load_operation
        capability.load_operation = lambda resolved: loaded.append(resolved) or original(resolved)
        self.addCleanup(setattr, capability, "load_operation", original)
        with self.assertRaises(capability.EpochRefused) as refused:
            capability.receive(ROOT, service, self.packet(), registry=kernel.load_registry(ROOT))
        self.assert_six_fields(refused.exception.refusal, "HB_EPOCH_NOT_SUPPLIED")
        self.assertEqual(loaded, [])
        self.assertEqual(self.written(), [])

    def test_dispatch_without_the_frame_epoch_fails_closed_and_appends_nothing(self):
        with self.assertRaises(ValueError) as refused:
            kernel.dispatch(ROOT, self.packet(), mesh_root=self.mesh, epoch=None)
        self.assertIn("capability_ingress_refused:HB_EPOCH_NOT_SUPPLIED", str(refused.exception))
        self.assert_six_fields(refused.exception.refusal, "HB_EPOCH_NOT_SUPPLIED")
        self.assertEqual(self.written(), [])

    def test_dispatch_passes_the_frame_epoch_through_to_the_receiving_operation(self):
        result = kernel.dispatch(ROOT, self.packet(), mesh_root=self.mesh, epoch=44)
        operation = result["application_result"]["receiving_operation_result"]
        self.assertEqual(operation["disposition"], "ALLOW", operation.get("detail"))
        receipts = [json.loads(p.read_text()) for p in self.written()]
        self.assertTrue(receipts)
        self.assertEqual({r["hb_reference"]["epoch"] for r in receipts if "hb_reference" in r}, {44})

    def test_ingest_frame_hands_dispatch_the_frames_own_epoch(self):
        seen = {}
        original = kernel.dispatch
        def recording(root, packet, **kwargs):
            seen.update(kwargs)
            return {"consumed": True}
        kernel.dispatch = recording
        self.addCleanup(setattr, kernel, "dispatch", original)
        frame = kernel.carrier_frame(self.packet(), epoch=45)
        kernel.ingest_frame(ROOT, frame, mesh_root=self.mesh)
        self.assertEqual(seen["epoch"], 45)


def _copy_component(target: Path) -> Path:
    ignore = shutil.ignore_patterns("__pycache__")
    for relative in (".stegverse/transition-ledger", "org-kernel", "resident-runtime"):
        shutil.copytree(ROOT / relative, target / relative, ignore=ignore)
    return target


class LedgerPathTests(TemporaryLedgers):
    MODULES = (("resident-runtime/organization_manifest_ingress.py", "org_ingress_p1_paths"),
               ("resident-runtime/intr_destination_ingress.py", "intr_destination_p1_paths"))

    def test_absent_paths_keep_this_checkout(self):
        for relative, name in self.MODULES:
            with self.subTest(module=relative):
                module = _load(name, relative)
                self.assertEqual(Path(module.repository_ledger.__file__).resolve(),
                                 ROOT / ".stegverse/transition-ledger/emit.py")
                bound = module.bind_ledger_writers()
                self.assertIs(bound["ledger_component_is_this_checkout"], True)
                self.assertIs(bound["consumer_root_is_this_checkout"], True)
                self.assertEqual(Path(module.organization_ledger.ROOT), ROOT)

    def test_an_invalid_path_fails_closed_and_leaves_the_bound_writers(self):
        empty = self.work / "empty"
        empty.mkdir()
        for relative, name in self.MODULES:
            module = _load(name, relative)
            before = (module.repository_ledger, module.organization_ledger)
            for kwargs, code in (({"ledger_component": empty}, "LEDGER_COMPONENT_PATH_INVALID"),
                                 ({"ledger_component": self.work / "missing"}, "LEDGER_COMPONENT_PATH_INVALID"),
                                 ({"consumer_root": empty}, "CONSUMER_ROOT_PATH_INVALID")):
                with self.subTest(module=relative, code=code, kwargs=str(kwargs)):
                    with self.assertRaises(module.LedgerPathRefused) as refused:
                        module.bind_ledger_writers(**kwargs)
                    self.assert_six_fields(refused.exception.refusal, code)
                    self.assertEqual((module.repository_ledger, module.organization_ledger), before)

    def test_a_given_component_and_consumer_root_are_where_the_writers_load_and_resolve(self):
        component = _copy_component(self.work / "component")
        consumer = self.work / "consumer"
        shutil.copytree(ROOT / ".stegverse/transition-ledger", consumer / ".stegverse/transition-ledger",
                        ignore=shutil.ignore_patterns("__pycache__", "*.py"))
        for relative, name in self.MODULES:
            with self.subTest(module=relative):
                module = _load(name, relative)
                bound = module.bind_ledger_writers(component, consumer)
                self.assertIs(bound["ledger_component_is_this_checkout"], False)
                self.assertEqual(Path(module.repository_ledger.__file__).resolve(),
                                 (component / ".stegverse/transition-ledger/emit.py").resolve())
                self.assertEqual(Path(module.organization_ledger.__file__).resolve(),
                                 (component / "resident-runtime/aggregate_repo_transition.py").resolve())
                self.assertEqual(Path(module.repository_ledger.ROOT), consumer.resolve())
                self.assertEqual(Path(module.organization_ledger.ROOT), consumer.resolve())

    def run_cli(self, relative, *args):
        env = dict(os.environ)
        return subprocess.run([sys.executable, str(ROOT / relative), *args], cwd=ROOT, env=env,
                              capture_output=True, text=True, check=False)

    def test_the_ingress_cli_refuses_an_invalid_path_and_receives_with_valid_ones(self):
        common = ["--registry", str(ROOT / "org-boundary/registry/services.json"),
                  "--manifest", str(MANIFEST), "--standing", str(GENESIS_PATH),
                  "--packet-id", "p1-cli", "--hb-epoch", "32"]
        refused = self.run_cli("resident-runtime/organization_manifest_ingress.py", *common,
                               "--ledger-component", str(self.work / "missing"))
        self.assertEqual(refused.returncode, 1, refused.stderr)
        out = json.loads(refused.stdout.splitlines()[-1])
        self.assert_six_fields(out, "LEDGER_COMPONENT_PATH_INVALID")
        self.assertEqual(self.written(), [])
        component = _copy_component(self.work / "component")
        received = self.run_cli("resident-runtime/organization_manifest_ingress.py", *common,
                                "--ledger-component", str(component), "--consumer-root", str(ROOT))
        self.assertEqual(received.returncode, 0, received.stdout[-2000:] + received.stderr[-2000:])
        self.assertEqual(json.loads(received.stdout.splitlines()[-1])["disposition"], "ALLOW")

    def test_the_intr_destination_cli_refuses_an_invalid_consumer_root(self):
        refused = self.run_cli("resident-runtime/intr_destination_ingress.py", "--self-close",
                               "--registry", str(ROOT / "org-boundary/registry/services.json"),
                               "--communication-id", "p1-cli", "--hb-epoch", "32",
                               "--consumer-root", str(self.work / "missing"))
        self.assertEqual(refused.returncode, 1, refused.stderr)
        out = json.loads(refused.stdout.strip().splitlines()[-1]) if refused.stdout.strip().startswith("{") \
            and "\n" not in refused.stdout.strip() else json.loads(refused.stdout)
        self.assert_six_fields(out, "CONSUMER_ROOT_PATH_INVALID")
        self.assertEqual(self.written(), [])


if __name__ == "__main__":
    unittest.main()
