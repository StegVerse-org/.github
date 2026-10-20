"""Every capability-ingress entrypoint refuses an absent epoch before anything else (Q-N-2).

`capability_ingress.INGRESS_REFUSAL_PRECEDENCE` declares one order for the
entrypoints in `INGRESS_ENTRYPOINTS`: input refusals precede state refusals,
and the supplied epoch is checked first. A call that is missing its epoch and
is also malformed in some other way is refused HB_EPOCH_NOT_SUPPLIED, and
nothing is appended. The egress `close` declares the same order as
CLOSE_REFUSAL_PRECEDENCE.

Ledger roots are temporary per test. Source validation only.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDICATE = "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH"


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capability = _load("capability_ingress_precedence", "org-boundary/runtime/capability_ingress.py")
ingress = _load("organization_manifest_ingress_precedence", "resident-runtime/organization_manifest_ingress.py")
destination = _load("intr_destination_ingress_precedence", "resident-runtime/intr_destination_ingress.py")


class DeclarationTests(unittest.TestCase):
    def test_the_epoch_is_the_first_input_and_inputs_precede_state(self):
        order = capability.INGRESS_REFUSAL_PRECEDENCE
        self.assertEqual(order[0], (PREDICATE, "INPUT"))
        kinds = [kind for _, kind in order]
        self.assertEqual(kinds, sorted(kinds, key=lambda k: k != "INPUT"))

    def test_each_entrypoint_checks_its_epoch_before_any_other_statement(self):
        for entry in capability.INGRESS_ENTRYPOINTS:
            path, function = entry.split("::")
            tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
            node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function)
            body = [n for n in node.body
                    if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
            body = [n for n in body if not (isinstance(n, ast.Delete))]
            first = ast.unparse(body[0])
            with self.subTest(entry=entry):
                self.assertTrue("epoch_refusal(" in first, first)


class MissingEpochAndAnotherBadInputTests(unittest.TestCase):
    LEDGER_ROOTS = ("STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT")

    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.work = Path(work.name)
        previous = {name: os.environ.get(name) for name in self.LEDGER_ROOTS}
        for name in self.LEDGER_ROOTS:
            os.environ[name] = str(self.work / name.lower())
        self.addCleanup(lambda: [os.environ.pop(n, None) if v is None else os.environ.__setitem__(n, v)
                                 for n, v in previous.items()])

    def assert_epoch_refused(self, out):
        self.assertEqual(out["disposition"], "FAIL_CLOSED")
        self.assertEqual(out["failure_code"], "HB_EPOCH_NOT_SUPPLIED")
        self.assertEqual(out["failed_predicate"], PREDICATE)
        self.assertEqual(list(self.work.rglob("*.json")), [], "nothing is appended")

    def test_c7_receive_with_a_malformed_manifest(self):
        self.assert_epoch_refused(ingress.receive("not a manifest", registry="not a registry",
                                                  packet_id="precedence-c7"))

    def test_c8_receive_with_a_malformed_registry(self):
        self.assert_epoch_refused(destination.receive("not a payload", registry="not a registry",
                                                      packet_id="precedence-c8-r"))

    def test_c8_closure_with_no_communication_id(self):
        self.assert_epoch_refused(destination.closure(None, registry="not a registry", packet_id=None))

    def test_kernel_path_receive_raises_the_epoch_refusal_before_resolving(self):
        with self.assertRaises(capability.EpochRefused) as refused:
            capability.receive(self.work / "no-such-root", {"service_id": "unknown"}, {},
                               registry="not a registry")
        self.assertEqual(refused.exception.refusal["failure_code"], "HB_EPOCH_NOT_SUPPLIED")
        self.assertEqual(list(self.work.rglob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
