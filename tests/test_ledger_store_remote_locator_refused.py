"""P1-FC-12, organization copy: a remote ledger locator is refused in six fields.

`resident-runtime/ledger_store.py` is a byte copy of the Organization Ledger
component's `org-kernel/organization-ledger/ledger_store.py` at
StegVerse-Labs/.github#3225 draft head e6ba9601 (git blob 9c50cd20, sha256
6bd217e0df6de9fee072933bf2251f24ea4bf4ca5d1eb18b4bebe226e86534cf). It must be
re-synced byte for byte if #3225 changes. A remote
location (URL, or scp-style `user@host:path` / `host:path`, bare or as the
repository of `git+`) is refused FAIL_CLOSED `LEDGER_LOCATOR_INVALID` instead
of being read as an empty local ledger.

These are the component's four `RemoteLocatorRefused` tests, with only paths
and imports adjusted for this repository. The readback and writer tests
exercise step (b) of the port (the readback and the writers re-raising the
refusal in their own six fields), which landed after StegVerse-org/.github#189
(merged c3f9fbee); both run unskipped.

Source validation only. Nothing is read from or written to any organization
ledger, and no authority effect is claimed.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "resident-runtime"
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair",
       "retry_entrypoint", "owning_existing_goal", "next_attempt")
LEDGER_REF = "refs/stegverse/organization-ledger"
NS = "repository-ledger/formalism-tests/.github"


def _load_store():
    spec = importlib.util.spec_from_file_location("ledger_store_fc12", RUNTIME / "ledger_store.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REMOTE_LOCATORS = ("https://github.com/StegVerse-org/.github", "http://example.invalid/ledger",
                   "ssh://git@github.com/StegVerse-org/.github.git", "git://github.com/StegVerse-org/.github",
                   "file:///tmp/ledger", "git@github.com:StegVerse-org/.github.git", "github.com:StegVerse-org/.github",
                   "git+https://github.com/StegVerse-org/.github#refs/stegverse/organization-ledger",
                   "git+git@github.com:StegVerse-org/.github#refs/stegverse/organization-ledger",
                   "git+ssh://github.com/StegVerse-org/.github#refs/stegverse/organization-ledger:" + NS)
LOCATOR_GOAL = "StegVerse-org/.github#163"


class RemoteLocatorRefused(unittest.TestCase):
    """P1-FC-12: a remote locator is refused in six fields, never read as an empty local ledger."""

    def assert_six(self, refusal, retry):
        for field in SIX:
            self.assertTrue(refusal.get(field), field)
            self.assertNotEqual(str(refusal.get(field)).strip(), "None", field)
        self.assertEqual((refusal["disposition"], refusal["failure_code"], refusal["owning_existing_goal"]),
                         ("FAIL_CLOSED", "LEDGER_LOCATOR_INVALID", LOCATOR_GOAL))
        self.assertEqual(refusal["retry_entrypoint"], retry)

    def test_parse_locator_refuses_every_remote_form(self):
        store = _load_store()
        for locator in REMOTE_LOCATORS:
            with self.assertRaises(ValueError) as caught:   # still a ValueError, so existing callers catch it
                store.parse_locator(locator)
            self.assertIsInstance(caught.exception, store.LedgerLocatorInvalid)
            self.assertEqual(caught.exception.failure_code, "LEDGER_LOCATOR_INVALID")
            self.assert_six(caught.exception.refusal, "resident-runtime/ledger_store.py::parse_locator")
            with self.assertRaises(store.LedgerLocatorRefused):
                store.open_store(locator)

    def test_local_locators_are_unchanged(self):
        store = _load_store()
        with tempfile.TemporaryDirectory() as tmp:
            for locator in (tmp, tmp + "/a:b", "./relative", "relative/dir"):
                self.assertIsInstance(store.parse_locator(locator), Path)
            loc = store.parse_locator("git+" + tmp + "#" + LEDGER_REF + ":" + NS)
            self.assertEqual((loc.repository, loc.ref, loc.namespace), (Path(tmp).resolve(), LEDGER_REF, NS))
            self.assertEqual(store.parse_locator("git+./rel#" + LEDGER_REF).repository, Path("rel").resolve())

    def test_readback_cli_refuses_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            for locator in REMOTE_LOCATORS:
                out = subprocess.run([sys.executable, str(RUNTIME / "organization_ledger_readback.py"),
                                      "--location", locator], capture_output=True, text=True, cwd=tmp)
                self.assertEqual(out.returncode, 1, locator)
                r = json.loads(out.stdout)
                self.assert_six(r, "resident-runtime/organization_ledger_readback.py::main")
                self.assertEqual(r["failed_predicate"], "LEDGER_LOCATOR_NAMES_A_STORE_ON_THIS_NODE")
            self.assertEqual(os.listdir(tmp), [], "nothing is created for a remote locator")

    def test_writers_refuse_a_remote_ledger_root_in_six_fields(self):
        env = dict(os.environ,
                   STEGVERSE_ORG_LEDGER_ROOT="https://github.com/StegVerse-org/.github",
                   STEGVERSE_REPO_LEDGER_ROOT="git+https://github.com/StegVerse-org/.github#refs/stegverse/repo")
        with tempfile.TemporaryDirectory() as tmp:
            script = (
                "import importlib.util, json, sys\n"
                "def load(name, path):\n"
                "    spec = importlib.util.spec_from_file_location(name, path)\n"
                "    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m\n"
                "def refusal(fn):\n"
                "    try:\n"
                "        fn()\n"
                "    except BaseException as exc:\n"
                "        return {'refused': getattr(exc, 'refusal', None) or {'detail': str(exc)}}\n"
                "    return {'refused': None}\n"
                "agg = load('agg', %r)\n"
                "emit = load('emit', %r)\n"
                "src = {'schema': 'stegverse.repo-transition-receipt/v1', 'receipt_sha256': 'sha256:' + 'b' * 64}\n"
                "print(json.dumps({'agg': refusal(lambda: agg.append(src, 'REPO_STATE_PROPAGATION', agg.GENESIS, "
                "'sha256:' + 'b' * 64, {}, 'NONE', hb_epoch=40)), 'emit': refusal(lambda: emit.lr())}))\n"
                % (str(RUNTIME / "aggregate_repo_transition.py"), str(ROOT / ".stegverse/transition-ledger/emit.py")))
            out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=tmp, env=env)
            r = json.loads(out.stdout.splitlines()[-1])
            self.assert_six(r["agg"]["refused"], "resident-runtime/aggregate_repo_transition.py::append")
            self.assertEqual(r["emit"]["refused"]["failure_code"], "LEDGER_LOCATOR_INVALID")
            self.assertEqual(r["emit"]["refused"]["owning_existing_goal"], LOCATOR_GOAL)
            self.assertFalse((Path(tmp) / "https:").exists())


if __name__ == "__main__":
    unittest.main()
