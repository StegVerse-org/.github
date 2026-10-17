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

import hashlib
import importlib.util
import inspect
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
        for value in (31, True, "+33", " 33", "3_3", -1):
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

    def test_a_digit_string_epoch_with_leading_zeros_appends_at_its_value(self):
        out = self.emit(hb_epoch="0041")
        self.assertEqual(out["disposition"], "ALLOW")
        receipts = [json.loads(p.read_text()) for p in self.written()]
        self.assertEqual({r["hb_reference"]["epoch"] for r in receipts if "hb_reference" in r}, {41})

    def test_no_clock_is_read_on_the_refusal(self):
        original = kernel.hb_reference
        def no_clock(*args, **kwargs):  # pragma: no cover - asserted not called
            raise AssertionError("a clock-derived epoch was requested")
        egress.kernel.hb_reference = no_clock
        self.addCleanup(setattr, egress.kernel, "hb_reference", original)
        self.assert_six_fields(self.emit(hb_epoch=None), "HB_EPOCH_NOT_SUPPLIED")


#: sha256 of `supplied_epoch_failure`'s source text. The same pin is asserted in
#: StegVerse-org/.github#185 and StegVerse-Labs/.github#3212 / #3213, so the
#: validator is byte-identical across the three.
SHARED_VALIDATOR_SHA256 = "7f36f0e697cadc91acd27af121eee3fc460b887ec67cfa258727bfccec0ca5f8"
#: Not ASCII [0-9]+ (or below 32): each is refused, never coerced to an epoch.
COERCED_EPOCHS = ("+33", " 33", "33 ", "3_3", "33.0", "33\n", "", "\u0663\u0663", "0x21",
                  True, False, 33.0, 31, "31", -33, "-33", [33])


class SharedEpochValidatorTests(unittest.TestCase):
    """One supplied-epoch rule at the egress boundary and the capability resolver."""

    def test_one_validator_text_everywhere(self):
        for module in (egress, capability):
            source = inspect.getsource(module.supplied_epoch_failure)
            self.assertEqual(hashlib.sha256(source.encode()).hexdigest(), SHARED_VALIDATOR_SHA256,
                             module.__name__)

    def test_coerced_epochs_are_refused_invalid_at_both_boundaries(self):
        for value in COERCED_EPOCHS:
            with self.subTest(value=value):
                for refusal in (egress.epoch_refusal(value, "entrypoint"), capability.epoch_refusal(value)):
                    self.assertEqual(refusal["failure_code"], "HB_EPOCH_INVALID")
                    self.assertEqual(refusal["failed_predicate"], "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH")

    def test_ascii_digits_are_supplied_leading_zeros_included(self):
        # As TVC#517 require_hb_epoch: [0-9]+ fullmatch, then int() >= 32.
        for value in (32, 33, "32", "33", "0033", "032", 10 ** 12):
            with self.subTest(value=value):
                self.assertIsNone(egress.epoch_refusal(value, "entrypoint"))
                self.assertIsNone(capability.epoch_refusal(value))

    def test_absent_is_not_supplied(self):
        self.assertEqual(egress.epoch_refusal(None, "entrypoint")["failure_code"], "HB_EPOCH_NOT_SUPPLIED")
        self.assertEqual(capability.epoch_refusal(None)["failure_code"], "HB_EPOCH_NOT_SUPPLIED")

    def test_a_carried_derived_from_clock_must_be_exactly_false(self):
        rule = egress.supplied_epoch_failure
        self.assertIsNone(rule(33, {"derived_from_clock": False}))
        self.assertIsNone(rule(33, {}))
        for value in (True, None, 0, "false"):
            with self.subTest(derived_from_clock=value):
                self.assertEqual(rule(33, {"derived_from_clock": value})[0], "HB_EPOCH_INVALID")
        self.assertEqual(rule(33, "HB:33")[0], "HB_EPOCH_INVALID")


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


def _cli_env() -> dict:
    return dict(os.environ)


REFUSING_WRITER = '''"""A ledger writer that refuses every use as ledger_common.LedgerRefusal does (test stub)."""
import json

REFUSAL = {"schema": "stegverse.organization-ledger-append-refusal/v1",
           "disposition": "FAIL_CLOSED", "failure_code": "HB_EPOCH_NOT_SUPPLIED",
           "failed_predicate": "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH",
           "detail": "no hb_epoch was supplied; the ledger writer reads no clock",
           "required_evidence_or_repair": "supply hb_epoch; the ledger writer reads no clock",
           "retry_entrypoint": "emit.py::append", "owning_existing_goal": "StegVerse-org/.github#163",
           "next_attempt": "append again with a supplied epoch",
           "consequence_committed": False, "authority_effect": "NONE"}

class LedgerRefusal(SystemExit):
    """As the writer's: a SystemExit carrying .refusal, .failure_code, .failed_predicate and .code."""
    def __init__(self, refusal):
        super().__init__(json.dumps(refusal, sort_keys=True))
        self.refusal = refusal
        self.failure_code = refusal["failure_code"]
        self.failed_predicate = refusal["failed_predicate"]

def _refuse():
    raise LedgerRefusal(dict(REFUSAL))

class _RefusingContract(dict):
    """A contract every read of which is the writer's refusal."""
    def __getitem__(self, key):
        _refuse()

    def get(self, key, default=None):
        _refuse()

ROOT = None
C = _RefusingContract()

def __getattr__(name):
    # Introspection (a test harness's locus hook) is not a ledger use.
    if name.startswith("__") or name == "declared_ledger_locus":
        raise AttributeError(name)
    _refuse()
'''

#: An old-layout writer: a plain SystemExit(message), no .refusal.
OLD_LAYOUT_WRITER = REFUSING_WRITER.replace(
    "def _refuse():\n    raise LedgerRefusal(dict(REFUSAL))",
    "def _refuse():\n    raise SystemExit(\"HB_EPOCH_NOT_SUPPLIED: no hb_epoch was supplied; no clock is read\")")


def _flat_component(path: Path, source: str | None = None) -> Path:
    """The flat layout: emit.py and aggregate_repo_transition.py as siblings."""
    path.mkdir(parents=True)
    for name in ("emit.py", "aggregate_repo_transition.py"):
        (path / name).write_text(source if source is not None else "ROOT = None\nC = None\n")
    return path


class LedgerComponentLayoutTests(TemporaryLedgers):
    """--ledger-component accepts the nested and the flat layout, and refuses anything else."""
    MODULES = (("resident-runtime/organization_manifest_ingress.py", "org_ingress_p1_layouts"),
               ("resident-runtime/intr_destination_ingress.py", "intr_destination_p1_layouts"))

    def consumer(self):
        consumer = self.work / "consumer"
        if not consumer.exists():
            shutil.copytree(ROOT / ".stegverse/transition-ledger", consumer / ".stegverse/transition-ledger",
                            ignore=shutil.ignore_patterns("__pycache__", "*.py"))
        return consumer

    def test_the_nested_layout_is_accepted(self):
        component = _copy_component(self.work / "nested")
        for relative, name in self.MODULES:
            with self.subTest(module=relative):
                module = _load(name, relative)
                bound = module.bind_ledger_writers(component, self.consumer())
                self.assertEqual(bound["ledger_component_layout"], "NESTED")
                self.assertEqual(Path(module.repository_ledger.__file__).resolve(),
                                 (component / ".stegverse/transition-ledger/emit.py").resolve())

    def test_the_flat_layout_is_accepted(self):
        component = _flat_component(self.work / "flat")
        for relative, name in self.MODULES:
            with self.subTest(module=relative):
                module = _load(name, relative)
                bound = module.bind_ledger_writers(component, self.consumer())
                self.assertEqual(bound["ledger_component_layout"], "FLAT")
                self.assertEqual(Path(module.repository_ledger.__file__).resolve(),
                                 (component / "emit.py").resolve())
                self.assertEqual(Path(module.organization_ledger.__file__).resolve(),
                                 (component / "aggregate_repo_transition.py").resolve())
                self.assertEqual(Path(module.organization_ledger.ROOT), self.consumer().resolve())

    def test_a_path_in_neither_layout_is_refused(self):
        half = self.work / "half"
        half.mkdir()
        (half / "emit.py").write_text("ROOT = None\n")
        for relative, name in self.MODULES:
            module = _load(name, relative)
            before = (module.repository_ledger, module.organization_ledger)
            for path in (half, self.work / "missing"):
                with self.subTest(module=relative, path=path.name):
                    with self.assertRaises(module.LedgerPathRefused) as refused:
                        module.bind_ledger_writers(path)
                    self.assert_six_fields(refused.exception.refusal, "LEDGER_COMPONENT_PATH_INVALID")
                    self.assertIn("as siblings", refused.exception.refusal["detail"])
                    self.assertEqual((module.repository_ledger, module.organization_ledger), before)


class LedgerWriterRefusalTests(TemporaryLedgers):
    """The C7/C8 CLIs print a ledger writer's refusal, write nothing and exit 1."""

    def run_cli(self, relative, *args):
        return subprocess.run([sys.executable, str(ROOT / relative), *args], cwd=ROOT,
                              env=_cli_env(), capture_output=True, text=True, check=False)

    def writer(self):
        namespace = {}
        exec(compile(REFUSING_WRITER, "refusing_writer", "exec"), namespace)
        return namespace

    def assert_nothing_written(self, completed, out):
        self.assertEqual(completed.returncode, 1, completed.stdout[-2000:] + completed.stderr[-2000:])
        self.assertFalse(out.exists(), "a refused run wrote --out")
        self.assertEqual(self.written(), [])

    def assert_carried(self, completed, out):
        # The writer's .refusal is printed exactly as given, not rebuilt.
        self.assert_nothing_written(completed, out)
        refusal = self.writer()["REFUSAL"]
        self.assertEqual(completed.stdout.strip().splitlines()[-1], json.dumps(refusal))
        self.assertEqual(json.loads(completed.stdout.strip().splitlines()[-1]), refusal)

    def assert_built(self, completed, out):
        # A plain SystemExit(message) gets the six fields built from its message.
        self.assert_nothing_written(completed, out)
        printed = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assert_six_fields(printed, "HB_EPOCH_NOT_SUPPLIED")
        self.assertEqual(printed["refusal_source"], "LEDGER_WRITER")
        self.assertIn("no clock is read", printed["detail"])

    def ingress(self, source, name):
        component = _flat_component(self.work / name, source)
        out = self.work / (name + "-ingress-out.json")
        return self.run_cli(
            "resident-runtime/organization_manifest_ingress.py",
            "--registry", str(ROOT / "org-boundary/registry/services.json"), "--manifest", str(MANIFEST),
            "--standing", str(GENESIS_PATH), "--packet-id", "p1-ledger-refusal", "--hb-epoch", "32",
            "--ledger-component", str(component), "--out", str(out)), out

    def self_close(self, source, name):
        component = _flat_component(self.work / name, source)
        out = self.work / (name + "-self-close-out.json")
        return self.run_cli(
            "resident-runtime/intr_destination_ingress.py", "--self-close",
            "--registry", str(ROOT / "org-boundary/registry/services.json"),
            "--communication-id", "p1-ledger-refusal", "--packet-id", "p1-ledger-refusal",
            "--hb-epoch", "32", "--ledger-component", str(component), "--out", str(out)), out

    def test_the_ingress_cli_prints_the_writers_refusal_as_given(self):
        self.assert_carried(*self.ingress(REFUSING_WRITER, "refusing"))

    def test_the_self_close_cli_prints_the_writers_refusal_as_given(self):
        self.assert_carried(*self.self_close(REFUSING_WRITER, "refusing"))

    def test_the_ingress_cli_builds_six_fields_for_an_old_layout_writer(self):
        self.assert_built(*self.ingress(OLD_LAYOUT_WRITER, "old-layout"))

    def test_the_self_close_cli_builds_six_fields_for_an_old_layout_writer(self):
        self.assert_built(*self.self_close(OLD_LAYOUT_WRITER, "old-layout"))

    def test_the_refusal_is_read_from_the_systemexit_only(self):
        writer = self.writer()
        refusal = writer["LedgerRefusal"](dict(writer["REFUSAL"]))
        self.assertIsInstance(refusal, SystemExit)
        self.assertNotIsInstance(refusal, Exception)
        self.assertEqual((refusal.failure_code, refusal.failed_predicate),
                         ("HB_EPOCH_NOT_SUPPLIED", "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH"))
        self.assertEqual(json.loads(refusal.code), writer["REFUSAL"])
        for relative, name in (("resident-runtime/organization_manifest_ingress.py", "org_ingress_p1_refusal"),
                               ("resident-runtime/intr_destination_ingress.py", "intr_destination_p1_refusal")):
            with self.subTest(module=relative):
                module = _load(name, relative)
                carried, is_carried = module.ledger_writer_refusal(refusal, "entry", "goal")
                self.assertIs(carried, refusal.refusal)
                self.assertIs(is_carried, True)
                built, is_carried = module.ledger_writer_refusal(
                    SystemExit("HB_EPOCH_INVALID: hb_epoch '+33'"), "entry", "goal")
                self.assertIs(is_carried, False)
                self.assert_six_fields(built, "HB_EPOCH_INVALID")
                self.assertEqual(module.ledger_writer_refusal(SystemExit("no code here"), "e", "g")[0]
                                 ["failure_code"], "LEDGER_WRITER_REFUSED")
                for ordinary in (SystemExit(0), SystemExit(1), SystemExit()):
                    self.assertIsNone(module.ledger_writer_refusal(ordinary, "entry", "goal"))


class CliRawEpochTests(TemporaryLedgers):
    """Every --hb-epoch is type=str: the shared validator sees the raw text."""
    INVALID = ("+33", " 33", "3_3")

    def run_cli(self, relative, *args):
        return subprocess.run([sys.executable, str(ROOT / relative), *args], cwd=ROOT,
                              env=_cli_env(), capture_output=True, text=True, check=False)

    def ingress(self, epoch, out):
        return self.run_cli(
            "resident-runtime/organization_manifest_ingress.py",
            "--registry", str(ROOT / "org-boundary/registry/services.json"), "--manifest", str(MANIFEST),
            "--standing", str(GENESIS_PATH), "--packet-id", "p1-raw-epoch", "--hb-epoch=" + epoch,
            "--out", str(out))

    def self_close(self, epoch, out):
        return self.run_cli(
            "resident-runtime/intr_destination_ingress.py", "--self-close",
            "--registry", str(ROOT / "org-boundary/registry/services.json"),
            "--communication-id", "p1-raw-epoch", "--packet-id", "p1-raw-epoch",
            "--hb-epoch=" + epoch, "--out", str(out))

    def egress(self, epoch, out):
        payload = self.work / "payload.json"
        payload.write_text(json.dumps({"message_class": "ecosystem.communication",
                                       "communication_id": "p1-raw-epoch", "body": {}}))
        standing = self.work / "standing.json"
        standing.write_text(json.dumps(GENESIS))
        env = _cli_env()
        return subprocess.run(
            [sys.executable, str(ROOT / "resident-runtime/organization_egress_boundary.py"),
             "--destination-organization", PEER, "--payload", str(payload), "--standing", str(standing),
             "--hb-epoch=" + epoch, "--out", str(out)],
            cwd=ROOT, env=env, capture_output=True, text=True, check=False)

    def assert_invalid(self, completed, out, writes_out=False):
        self.assertEqual(completed.returncode, 1, completed.stdout[-2000:] + completed.stderr[-2000:])
        printed = json.loads(completed.stdout) if completed.stdout.lstrip().startswith("{\n") \
            else json.loads(completed.stdout.strip().splitlines()[-1])
        self.assert_six_fields(printed, "HB_EPOCH_INVALID")
        self.assertEqual(printed["failed_predicate"], "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH")
        if not writes_out:
            self.assertFalse(out.exists(), "a refused run wrote --out")
        self.assertEqual(self.written(), [])

    def epochs(self):
        receipts = [json.loads(p.read_text()) for p in self.written()]
        return {r["hb_reference"]["epoch"] for r in receipts if "hb_reference" in r}

    def test_the_ingress_cli_refuses_coerced_epochs(self):
        for epoch in self.INVALID:
            with self.subTest(epoch=epoch):
                self.assert_invalid(self.ingress(epoch, self.work / "ingress-out.json"),
                                    self.work / "ingress-out.json")

    def test_the_ingress_cli_accepts_a_leading_zero_epoch(self):
        completed = self.ingress("0033", self.work / "ingress-out.json")
        self.assertEqual(completed.returncode, 0, completed.stdout[-2000:] + completed.stderr[-2000:])
        self.assertEqual(json.loads(completed.stdout.splitlines()[-1])["disposition"], "ALLOW")
        self.assertEqual(self.epochs(), {33})

    def test_the_self_close_cli_refuses_coerced_epochs(self):
        for epoch in self.INVALID:
            with self.subTest(epoch=epoch):
                self.assert_invalid(self.self_close(epoch, self.work / "close-out.json"),
                                    self.work / "close-out.json")

    def test_the_self_close_cli_accepts_a_leading_zero_epoch(self):
        completed = self.self_close("0033", self.work / "close-out.json")
        self.assertEqual(completed.returncode, 0, completed.stdout[-2000:] + completed.stderr[-2000:])
        self.assertEqual(self.epochs(), {33})

    def test_the_egress_cli_refuses_coerced_epochs(self):
        for epoch in self.INVALID:
            with self.subTest(epoch=epoch):
                # The egress CLI writes its refusal to --out, as it always has.
                self.assert_invalid(self.egress(epoch, self.work / "egress-out.json"),
                                    self.work / "egress-out.json", writes_out=True)

    def test_the_egress_cli_accepts_a_leading_zero_epoch(self):
        completed = self.egress("0033", self.work / "egress-out.json")
        printed = json.loads(completed.stdout)
        self.assertNotIn(printed.get("failure_code"), ("HB_EPOCH_INVALID", "HB_EPOCH_NOT_SUPPLIED"),
                         completed.stdout[-2000:] + completed.stderr[-2000:])
        # No mesh is materialized for the CLI here: the refusal it records is
        # stamped at the supplied epoch's value.
        self.assertEqual(self.epochs(), {33})


if __name__ == "__main__":
    unittest.main()
