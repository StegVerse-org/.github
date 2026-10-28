"""P1-FC-10 HB_EPOCH_INVALID_COERCED: --hb-epoch is taken as typed, never coerced by int().

The shared supplied-epoch rule (`supplied_epoch_failure`, sha256 pinned in
tests/test_p1_supplied_epoch_and_ledger_paths.py) admits ASCII [0-9]+ with
value >= 32 only. argparse `type=int` runs `int()` first, and `int()` accepts
' 32', '+32', '3_2' and non-ASCII digits ('\u0663\u0662'), so a CLI declared
`type=int` handed the rule an epoch it would have refused. These CLIs now take
the raw text (`type=str`), check it with the shared rule, and refuse FAIL_CLOSED
in six fields with nothing appended. An absent --hb-epoch is unchanged.

The two org CLIs still on `type=int` that other open drafts edit
(aggregate_repo_transition.py, org#189; governance_decision_return.py, org#186)
are follow-ups after those land, and are deliberately not asserted here.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
       "owning_existing_goal", "next_attempt")
COERCED = (" 32", "+32", "3_2", "\u0663\u0662")
BELOW_ANCHOR = ("31",)
SUPPLIED = "32"
PREDICATE = "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH"
#: (relative path, retry_entrypoint) of each CLI this change covers.
CLIS = {
    "emit": (".stegverse/transition-ledger/emit.py", ".stegverse/transition-ledger/emit.py (--hb-epoch)"),
    "propagate": ("resident-runtime/propagate_repository_receipts.py",
                  "resident-runtime/propagate_repository_receipts.py (--hb-epoch)"),
}


def _module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RULE = _module("fc10_egress_boundary", "resident-runtime/organization_egress_boundary.py").supplied_epoch_failure


class CoercionIsTheDefectTests(unittest.TestCase):
    """The invariant that decides P1-FC-10: int() admits what the rule refuses."""

    def test_int_coerces_each_value_the_rule_refuses(self):
        for value in COERCED:
            with self.subTest(value=value):
                self.assertEqual(int(value), 32)
                self.assertEqual(RULE(value)[0], "HB_EPOCH_INVALID")

    def test_no_covered_cli_declares_hb_epoch_type_int(self):
        for relative, _ in CLIS.values():
            with self.subTest(cli=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"""["']--hb-epoch["']\s*,\s*type\s*=\s*int""", source))
                self.assertRegex(source, r"""["']--hb-epoch["']\s*,\s*type\s*=\s*str""")


class CliEpochTests(unittest.TestCase):
    def setUp(self):
        self._state = tempfile.TemporaryDirectory()
        self.addCleanup(self._state.cleanup)
        self.state = Path(self._state.name)

    def env(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("STEGVERSE_")}
        env["STEGVERSE_REPO_LEDGER_ROOT"] = str(self.state / "repo")
        env["STEGVERSE_REPO_LEDGER_HOME"] = str(self.state / "repo-ledgers")
        env["STEGVERSE_ORG_LEDGER_ROOT"] = str(self.state / "org")
        return env

    def written(self):
        return sorted(p for p in self.state.rglob("*") if p.is_file())

    def run_cli(self, name, epoch):
        relative, _ = CLIS[name]
        args = [sys.executable, str(ROOT / relative)]
        if name == "emit":
            args += ["--transition-id", "fc10-cli-epoch", "--transition-class", "FC10_CLI_EPOCH",
                     "--predecessor-state-sha256", "sha256:" + "0" * 64,
                     "--successor-state-sha256", "sha256:" + "1" * 64]
        out = self.state / "out.json"
        if name == "propagate":
            args += ["--out", str(out)]
        args.append("--hb-epoch=" + epoch)
        return subprocess.run(args, cwd=ROOT, env=self.env(), capture_output=True, text=True,
                              check=False), out

    def assert_refused(self, name, epoch):
        completed, out = self.run_cli(name, epoch)
        self.assertEqual(completed.returncode, 1, completed.stdout[-2000:] + completed.stderr[-2000:])
        refused = json.loads(completed.stdout.strip().splitlines()[-1])
        for field in SIX:
            self.assertIsInstance(refused.get(field), str, field)
            self.assertTrue(refused[field].strip(), field)
        self.assertEqual(refused["disposition"], "FAIL_CLOSED")
        self.assertEqual(refused["failure_code"], "HB_EPOCH_INVALID")
        self.assertEqual(refused["failed_predicate"], PREDICATE)
        self.assertEqual(refused["retry_entrypoint"], CLIS[name][1])
        self.assertEqual(refused["owning_existing_goal"], "INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001")
        self.assertFalse(out.exists(), "a refused run wrote --out")
        self.assertEqual(self.written(), [], "a refused run wrote ledger state")

    def test_coerced_and_below_anchor_epochs_are_refused_in_six_fields(self):
        for name in CLIS:
            for epoch in COERCED + BELOW_ANCHOR:
                with self.subTest(cli=name, epoch=epoch):
                    self.assert_refused(name, epoch)

    def test_emit_admits_32_as_supplied(self):
        completed, _ = self.run_cli("emit", SUPPLIED)
        self.assertEqual(completed.returncode, 0, completed.stdout[-2000:] + completed.stderr[-2000:])
        receipt = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertEqual(receipt["hb_reference"]["epoch"], 32)
        self.assertIs(receipt["hb_reference"].get("derived_from_clock", False), False)

    def test_propagate_admits_32_as_supplied(self):
        completed, out = self.run_cli("propagate", SUPPLIED)
        self.assertEqual(completed.returncode, 0, completed.stdout[-2000:] + completed.stderr[-2000:])
        summary = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertNotIn("failure_code", summary)
        self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
