"""H39 residual: the emit.py and governance_decision_return.py --hb-epoch CLIs take the text.

`type=int` coerced '+33', ' 33' and '3_3' into 33. Here each CLI hands the
text to the shared rule (`capability_ingress.direct_epoch_refusal`, built on
`supplied_epoch_failure`); a malformed one exits 1 with the six-field
HB_EPOCH_INVALID refusal before anything is read or appended. An absent
--hb-epoch is unchanged.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair",
       "retry_entrypoint", "owning_existing_goal", "next_attempt")
MISSING = "/nonexistent/h39"
CLIS = {
    ".stegverse/transition-ledger/emit.py": [
        "--transition-id", "h39", "--transition-class", "H39", "--predecessor-state-sha256",
        "sha256:" + "0" * 64, "--successor-state-sha256", "sha256:" + "1" * 64],
    "resident-runtime/governance_decision_return.py": [
        "--manifest", MISSING, "--packet-id", "h39", "--communication-id", "h39",
        "--mesh-root", MISSING],
}
# aggregate_repo_transition.py and propagate_repository_receipts.py keep
# --hb-epoch type=int here: they are FC-10, Lane B's, and are not migrated.


class CliEpochTextTests(unittest.TestCase):
    def run_cli(self, relative, args, epoch):
        with tempfile.TemporaryDirectory() as work:
            env = dict(os.environ, STEGVERSE_REPO_LEDGER_ROOT=work + "/r",
                       STEGVERSE_ORG_LEDGER_ROOT=work + "/o")
            cli = subprocess.run([sys.executable, str(ROOT / relative), *args, "--hb-epoch=" + epoch],
                                 cwd=ROOT, env=env, capture_output=True, text=True, check=False)
            written = list(Path(work).rglob("*"))
        return cli, written

    def test_a_malformed_epoch_is_refused_by_the_shared_rule(self):
        for relative, args in CLIS.items():
            for epoch in ("+33", " 33", "3_3", "31", "-33"):
                with self.subTest(cli=relative, epoch=epoch):
                    cli, written = self.run_cli(relative, args, epoch)
                    self.assertEqual(cli.returncode, 1, cli.stderr[-800:])
                    out = json.loads(cli.stdout.strip().splitlines()[-1])
                    self.assertEqual(out["disposition"], "FAIL_CLOSED")
                    self.assertEqual(out["failure_code"], "HB_EPOCH_INVALID")
                    self.assertEqual(out["failed_predicate"], "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH")
                    self.assertEqual(out["retry_entrypoint"], relative + "::main")
                    for field in SIX:
                        self.assertTrue(isinstance(out.get(field), str) and out[field].strip(), field)
                    self.assertEqual(written, [])

    def test_the_cli_no_longer_coerces_with_int(self):
        for relative in CLIS:
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotRegex(text, r'"--hb-epoch",\s*type=int')


if __name__ == "__main__":
    unittest.main()
