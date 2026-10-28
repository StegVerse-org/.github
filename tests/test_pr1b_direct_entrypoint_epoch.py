"""PR-1b (P1-FC-8): a direct call into a receiving operation is held to the supplied-epoch rule.

At StegVerse-org/.github main 0f9481af the kernel path refuses a missing epoch
(`capability_ingress.epoch_refusal`), but a direct call -- C7
`organization_manifest_ingress.receive` / its CLI with no `--hb-epoch`, and C8
`intr_destination_ingress.receive` / `closure` / `--self-close` -- appended at
an epoch the default writers derived from the host clock. Each now refuses
FAIL_CLOSED `HB_EPOCH_NOT_SUPPLIED` (absent) or `HB_EPOCH_INVALID` through the
shared `supplied_epoch_failure`, with the six fields and nothing appended.

Ledger roots are temporary per test; the default writers (no
--ledger-component) are the ones exercised. No secret is read.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
REGISTRY_PATH = ROOT / "org-boundary/registry/services.json"
REGISTRY = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
MANIFEST_PATH = ROOT / "tests/fixtures/sdk-manifests/task-registry-disclosure.json"
GENESIS_PATH = ROOT / "tests/fixtures/crossing-standing-genesis.json"
GENESIS = {k: v for k, v in json.loads(GENESIS_PATH.read_text(encoding="utf-8")).items()
           if not k.startswith("_")}
PREDICATE = "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH"
GOAL = "INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001"
INVALID = (31, -33, True, False, 33.0, "+33", " 33", "3_3", "33.0", "", "\u0663\u0663")
CID = "intr-selfclose-StegVerse-org-pr1b"


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capability = _load("capability_ingress_pr1b", "org-boundary/runtime/capability_ingress.py")
ingress = _load("organization_manifest_ingress_pr1b", "resident-runtime/organization_manifest_ingress.py")
destination = _load("intr_destination_ingress_pr1b", "resident-runtime/intr_destination_ingress.py")


class TemporaryLedgers(unittest.TestCase):
    LEDGER_ROOTS = ("STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT")

    def setUp(self):
        self._work = tempfile.TemporaryDirectory()
        self.addCleanup(self._work.cleanup)
        self.work = Path(self._work.name)
        previous = {name: os.environ.get(name) for name in self.LEDGER_ROOTS}
        for name in self.LEDGER_ROOTS:
            os.environ[name] = str(self.work / name.lower())
        self.addCleanup(lambda: [os.environ.pop(n, None) if v is None else os.environ.__setitem__(n, v)
                                 for n, v in previous.items()])

    def written(self):
        return [path for name in self.LEDGER_ROOTS if Path(os.environ[name]).exists()
                for path in Path(os.environ[name]).rglob("*.json")]

    def receipts(self):
        return [json.loads(path.read_text()) for path in self.written()]

    def assert_refused(self, out, code, entrypoint):
        self.assertEqual(out["disposition"], "FAIL_CLOSED")
        self.assertEqual(out["failure_code"], code)
        self.assertEqual(out["failed_predicate"], PREDICATE)
        self.assertEqual(out["retry_entrypoint"], entrypoint)
        self.assertEqual(out["owning_existing_goal"], GOAL)
        for field in SIX_FIELDS:
            self.assertTrue(isinstance(out.get(field), str) and out[field].strip(), field)
        self.assertIs(out["received"], False)
        self.assertEqual(self.written(), [], "nothing is appended on an epoch refusal")

    def assert_no_clock(self, epoch):
        receipts = self.receipts()
        self.assertTrue(receipts)
        for receipt in receipts:
            reference = receipt.get("hb_reference")
            if reference is not None:
                self.assertEqual(reference["epoch"], epoch)
                self.assertIs(reference.get("derived_from_clock"), False, reference)
                self.assertNotIn("sampled_unix_ns", reference)

    def run_cli(self, relative, *args):
        return subprocess.run([sys.executable, str(ROOT / relative), *args], cwd=ROOT,
                              env=dict(os.environ), capture_output=True, text=True, check=False)


class SharedRuleTests(unittest.TestCase):
    def test_the_direct_refusal_is_built_on_the_shared_validator(self):
        calls = []
        original = capability.supplied_epoch_failure
        capability.supplied_epoch_failure = lambda *a, **k: calls.append(a) or original(*a, **k)
        self.addCleanup(setattr, capability, "supplied_epoch_failure", original)
        capability.direct_epoch_refusal(None, "entry")
        self.assertEqual(calls, [(None,)])

    def test_the_operations_use_the_capability_module_rule(self):
        for module in (ingress, destination):
            self.assertEqual(module.capability_epoch.supplied_epoch_failure.__code__.co_code,
                             capability.supplied_epoch_failure.__code__.co_code)


class C7DirectReceiveTests(TemporaryLedgers):
    ENTRY = "resident-runtime/organization_manifest_ingress.py::receive"

    def receive(self, **epoch):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return ingress.receive(manifest, registry=REGISTRY, standing=GENESIS,
                               packet_id="pr1b-c7", **epoch)

    def test_no_epoch_is_not_supplied_and_appends_nothing(self):
        self.assert_refused(self.receive(), "HB_EPOCH_NOT_SUPPLIED", self.ENTRY)

    def test_an_invalid_epoch_is_refused(self):
        for value in INVALID:
            with self.subTest(value=value):
                self.assert_refused(self.receive(hb_epoch=value), "HB_EPOCH_INVALID", self.ENTRY)

    def test_a_supplied_epoch_is_received_at_that_epoch_with_no_clock(self):
        out = self.receive(hb_epoch="0040")
        self.assertEqual(out["disposition"], "ALLOW", out.get("detail"))
        self.assert_no_clock(40)

    def test_cli_with_no_hb_epoch_exits_1_fail_closed_on_the_default_writers(self):
        out_path = self.work / "c7.json"
        cli = self.run_cli("resident-runtime/organization_manifest_ingress.py",
                           "--registry", str(REGISTRY_PATH), "--manifest", str(MANIFEST_PATH),
                           "--standing", str(GENESIS_PATH), "--packet-id", "pr1b-c7-cli",
                           "--out", str(out_path))
        self.assertEqual(cli.returncode, 1, cli.stdout[-1500:] + cli.stderr[-1500:])
        out = json.loads(cli.stdout.strip().splitlines()[-1]) if cli.stdout.strip() else \
            json.loads(out_path.read_text())
        self.assert_refused(out, "HB_EPOCH_NOT_SUPPLIED", self.ENTRY)


class C8DirectCallTests(TemporaryLedgers):
    RECEIVE = "resident-runtime/intr_destination_ingress.py::receive"
    CLOSURE = "resident-runtime/intr_destination_ingress.py::closure"

    def payload(self):
        return {"message_class": "ecosystem.communication", "communication_id": CID,
                "body": {"schema": destination.PAYLOAD_SCHEMA, "probe": "pr1b"}}

    def test_receive_with_no_epoch_is_not_supplied(self):
        out = destination.receive(self.payload(), registry=REGISTRY, packet_id="pr1b-c8-r")
        self.assert_refused(out, "HB_EPOCH_NOT_SUPPLIED", self.RECEIVE)
        self.assertIs(out["communication_acknowledged"], False)

    def test_closure_with_no_epoch_is_not_supplied(self):
        out = destination.closure(CID, registry=REGISTRY, packet_id="pr1b-c8-c")
        self.assert_refused(out, "HB_EPOCH_NOT_SUPPLIED", self.CLOSURE)
        self.assertIs(out["self_closure"], True)

    def test_closure_with_an_invalid_epoch_is_refused(self):
        for value in INVALID:
            with self.subTest(value=value):
                out = destination.closure(CID, registry=REGISTRY, packet_id="pr1b-c8-i", hb_epoch=value)
                self.assert_refused(out, "HB_EPOCH_INVALID", self.CLOSURE)

    def test_closure_at_a_supplied_epoch_is_allow_with_no_clock(self):
        out = destination.closure(CID, registry=REGISTRY, packet_id="pr1b-c8-ok", hb_epoch="0042")
        self.assertEqual(out["disposition"], "ALLOW", out)
        self.assert_no_clock(42)

    def test_self_close_cli_with_no_hb_epoch_exits_1_fail_closed_on_the_default_writers(self):
        out_path = self.work / "closure.json"
        cli = self.run_cli("resident-runtime/intr_destination_ingress.py", "--self-close",
                           "--registry", str(REGISTRY_PATH), "--communication-id", CID,
                           "--packet-id", "pr1b-c8-cli", "--out", str(out_path))
        self.assertEqual(cli.returncode, 1, cli.stdout[-1500:] + cli.stderr[-1500:])
        out = json.loads(out_path.read_text()) if out_path.exists() else \
            json.loads(cli.stdout.strip().splitlines()[-1])
        self.assert_refused(out, "HB_EPOCH_NOT_SUPPLIED", self.CLOSURE)


if __name__ == "__main__":
    unittest.main()
