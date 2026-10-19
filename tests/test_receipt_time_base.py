"""The time base of a canonical receipt is the heartbeat, not a wall clock.

No real-world clock is necessary for the ecosystem: the heartbeat is the
reference, declared `OSCILLATOR_ONLY` in the organization boundary contract,
in every InTr envelope and in the carrier frame. The receipt emitters
contradicted that. Both stamped `datetime.now()` into the hashed body, and the
repository ledger contract went further -- it listed `observed_at` among its
required fields while leaving `hb_reference` optional, so every receipt
carried a mandatory clock reading beside a heartbeat that defaulted to null.

A receipt whose body carries a clock reading cannot be reproduced: two nodes
emitting the same transition disagree in the digest, and a replay cannot
recompute what it is checking.

`.stegverse/transition-ledger/emit.py` had no test and no workflow before
this, so the repository-receipt cases here are its first coverage.

Source validation only. No authority effect is claimed.
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMIT = ROOT / ".stegverse/transition-ledger/emit.py"
REPO_CONTRACT = json.loads((ROOT / ".stegverse/transition-ledger/contract.json").read_text())

spec = importlib.util.spec_from_file_location("org_append_time", ROOT / "resident-runtime/aggregate_repo_transition.py")
org = importlib.util.module_from_spec(spec)
spec.loader.exec_module(org)

EPOCH = 4_200
STATE_BEFORE = "sha256:" + "a" * 64
STATE_AFTER = "sha256:" + "b" * 64
CLOCK_FIELDS = ("observed_at", "timestamp", "emitted_at", "sampled_at")


def repo_receipt(transition_id="time-base-1"):
    body = {
        "schema": "stegverse.repo-transition-receipt/v1",
        "repository": "StegVerse-org/StegVerse-SDK",
        "transition_id": transition_id,
    }
    return {**body, "receipt_sha256": org.sha(body)}


def run_emit(root, transition_id="t-1", hb_epoch=EPOCH):
    command = [sys.executable, str(EMIT),
               "--transition-id", transition_id, "--transition-class", "TEST",
               "--predecessor-state-sha256", STATE_BEFORE,
               "--successor-state-sha256", STATE_AFTER]
    if hb_epoch is not None:
        command += ["--hb-epoch", str(hb_epoch)]
    environment = dict(os.environ, STEGVERSE_REPO_LEDGER_ROOT=str(root))
    return subprocess.run(command, capture_output=True, text=True, env=environment, cwd=str(ROOT))


def emit_repo_receipt(root, transition_id="t-1", hb_epoch=EPOCH):
    completed = run_emit(root, transition_id, hb_epoch)
    if completed.returncode != 0:
        raise AssertionError("emit failed: " + completed.stderr)
    return json.loads(completed.stdout.splitlines()[-1])


class RepositoryLedgerContractTests(unittest.TestCase):
    def test_the_contract_requires_the_heartbeat_and_not_a_clock(self):
        required = REPO_CONTRACT["required_fields"]
        self.assertIn("hb_reference", required)
        for field in CLOCK_FIELDS:
            self.assertNotIn(field, required)


class RepositoryReceiptTests(unittest.TestCase):
    def test_a_repository_receipt_carries_no_clock_reading(self):
        with tempfile.TemporaryDirectory() as root:
            receipt = emit_repo_receipt(root)
            for field in CLOCK_FIELDS:
                self.assertNotIn(field, receipt)
            self.assertEqual(receipt["hb_reference"]["epoch"], EPOCH)
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)

    def test_a_repository_receipt_satisfies_its_own_contract(self):
        with tempfile.TemporaryDirectory() as root:
            receipt = emit_repo_receipt(root)
            for field in REPO_CONTRACT["required_fields"]:
                self.assertIn(field, receipt, field)

    def test_the_same_repository_transition_at_the_same_tick_is_reproducible(self):
        """Two emitters of one transition must agree in the digest."""
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            a = emit_repo_receipt(first)
            b = emit_repo_receipt(second)
            self.assertEqual(a["receipt_sha256"], b["receipt_sha256"])

    def test_a_repository_receipt_without_a_tick_is_refused_and_nothing_written(self):
        """It used to be minted from the host clock and marked derived_from_clock."""
        with tempfile.TemporaryDirectory() as root:
            completed = run_emit(root, hb_epoch=None)
            self.assertEqual(completed.returncode, 1)
            refusal = json.loads(completed.stdout.splitlines()[-1])
            self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
            self.assertEqual(refusal["failure_code"], "HB_EPOCH_NOT_SUPPLIED")
            for field in SIX_FIELDS:
                self.assertTrue(refusal[field], field)
            self.assertNotIn("hb_reference", refusal)
            self.assertEqual(list(Path(root).iterdir()), [])


SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")


class RepositoryAppendEpochTests(unittest.TestCase):
    """emit.append refuses an absent or invalid epoch before the store opens; no clock is read."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("repo_emit_time", EMIT)
        cls.emit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.emit)

    def _refused(self, hb_epoch):
        class Unopenable:
            def __getattr__(self, name):
                raise AssertionError("store touched: " + name)

        class NoClock:
            @staticmethod
            def now(*_):
                raise AssertionError("clock read")

        clock = self.emit.kernel.datetime
        self.emit.kernel.datetime = NoClock
        try:
            with self.assertRaises(self.emit.RepoLedgerEpochRefused) as caught:
                self.emit.append("t-1", "TEST", STATE_BEFORE, STATE_AFTER, hb_epoch=hb_epoch,
                                 store=Unopenable())
        finally:
            self.emit.kernel.datetime = clock
        refusal = caught.exception.refusal
        self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
        self.assertEqual(refusal["failed_predicate"], "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH")
        self.assertEqual(refusal["retry_entrypoint"], ".stegverse/transition-ledger/emit.py::append")
        for field in SIX_FIELDS:
            self.assertTrue(refusal[field], field)
        return refusal

    def test_the_rule_is_the_organization_writers_not_a_copy(self):
        self.assertIs(self.emit.supplied_epoch_failure.__code__.co_filename,
                      self.emit._org_rule.supplied_epoch_failure.__code__.co_filename)
        self.assertTrue(self.emit.supplied_epoch_failure.__code__.co_filename.endswith(
            "resident-runtime/aggregate_repo_transition.py"))

    def test_an_absent_epoch_is_not_supplied(self):
        self.assertEqual(self._refused(None)["failure_code"], "HB_EPOCH_NOT_SUPPLIED")

    def test_an_invalid_epoch_is_refused(self):
        for epoch in (True, 31, "+33", " 33", "33.0", 33.0):
            with self.subTest(epoch=epoch):
                self.assertEqual(self._refused(epoch)["failure_code"], "HB_EPOCH_INVALID")

    def test_a_supplied_epoch_as_ascii_digits_is_admitted(self):
        with tempfile.TemporaryDirectory() as root:
            store = self.emit.ledger_store.open_store(self.emit.ledger_store.parse_locator(root))
            receipt = self.emit.append("t-1", "TEST", STATE_BEFORE, STATE_AFTER, hb_epoch=str(EPOCH),
                                       store=store)
            self.assertEqual(receipt["hb_reference"]["epoch"], EPOCH)
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)


AGGREGATE = ROOT / "resident-runtime/aggregate_repo_transition.py"
PROPAGATE = ROOT / "resident-runtime/propagate_repository_receipts.py"
#: Values argparse's int() used to admit as 33, plus other malformed ones.
#: A CLI can tell "" from absent, so "" is HB_EPOCH_INVALID there.
REFUSED_CLI_EPOCHS = ("+33", "\uff13\uff13", " 33", "True", "abc", "33.7", "", None)


def files_under(root):
    return sorted(str(p.relative_to(root)) for p in Path(root).rglob("*") if p.is_file())


class CliEpochParsingTests(unittest.TestCase):
    """--hb-epoch is read as typed and checked by the shared rule; a refusal writes nothing."""

    def run_cli(self, script, args, hb_epoch, env):
        command = [sys.executable, str(script), *args]
        if hb_epoch is not None:
            command += ["--hb-epoch", hb_epoch]
        return subprocess.run(command, capture_output=True, text=True, cwd=str(ROOT),
                              env=dict(os.environ, **env))

    def assert_refused(self, completed, epoch):
        self.assertEqual(completed.returncode, 1, (epoch, completed.stdout, completed.stderr))
        refusal = json.loads(completed.stdout.splitlines()[-1])
        self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
        self.assertEqual(refusal["failure_code"],
                         "HB_EPOCH_NOT_SUPPLIED" if epoch is None else "HB_EPOCH_INVALID", epoch)
        for field in SIX_FIELDS:
            self.assertTrue(refusal[field], field)

    def aggregate(self, root, hb_epoch):
        source = Path(root) / "source.json"
        source.write_text(json.dumps(repo_receipt()))
        ledger = Path(root) / "org-ledger"
        completed = self.run_cli(AGGREGATE, ["--repo-receipt", str(source),
                                             "--predecessor-org-state-sha256", "GENESIS",
                                             "--successor-org-state-sha256", STATE_AFTER],
                                 hb_epoch, {"STEGVERSE_ORG_LEDGER_ROOT": str(ledger)})
        return completed, ledger

    def test_the_organization_writer_cli_refuses_and_writes_nothing(self):
        for epoch in REFUSED_CLI_EPOCHS:
            with self.subTest(epoch=epoch), tempfile.TemporaryDirectory() as root:
                completed, ledger = self.aggregate(root, epoch)
                self.assert_refused(completed, epoch)
                self.assertEqual(files_under(ledger) if ledger.exists() else [], [])

    def test_the_organization_writer_cli_admits_ascii_digits(self):
        with tempfile.TemporaryDirectory() as root:
            completed, ledger = self.aggregate(root, "4096")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            receipt = json.loads(completed.stdout.splitlines()[-1])
            self.assertEqual(receipt["hb_reference"]["epoch"], 4096)
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)

    def propagate(self, root, hb_epoch):
        ledger = Path(root) / "org-ledger"
        repository = Path(root) / "repository-ledger"
        repository.mkdir()
        completed = self.run_cli(PROPAGATE, ["--repository", REPO_CONTRACT["repository"],
                                             "--repository-ledger-root", str(repository)],
                                 hb_epoch, {"STEGVERSE_ORG_LEDGER_ROOT": str(ledger)})
        return completed, ledger

    def test_the_propagation_cli_refuses_and_writes_nothing(self):
        for epoch in REFUSED_CLI_EPOCHS:
            with self.subTest(epoch=epoch), tempfile.TemporaryDirectory() as root:
                completed, ledger = self.propagate(root, epoch)
                self.assert_refused(completed, epoch)
                self.assertEqual(json.loads(completed.stdout.splitlines()[-1])["retry_entrypoint"],
                                 "resident-runtime/propagate_repository_receipts.py (--hb-epoch)")
                self.assertEqual(files_under(ledger) if ledger.exists() else [], [])

    def test_the_propagation_cli_admits_ascii_digits(self):
        with tempfile.TemporaryDirectory() as root:
            completed, _ = self.propagate(root, "4096")
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_no_cli_help_says_the_epoch_is_derived_from_a_clock(self):
        for script in (AGGREGATE, PROPAGATE, EMIT):
            text = subprocess.run([sys.executable, str(script), "--help"], capture_output=True,
                                  text=True, cwd=str(ROOT)).stdout
            self.assertNotIn("host clock", text, script)


FEDERATION_CYCLE = ROOT / "resident-runtime/federation_cycle.py"
EGRESS = ROOT / "resident-runtime/organization_egress_boundary.py"
#: Supplied but not admissible: each is refused before anything is written.
REFUSED_SUPPLIED_EPOCHS = ("", "+33", " 33", "\uff13\uff13", "33.0", "31", "abc")


class FederationCycleEpochTests(unittest.TestCase):
    """A supplied --hb-epoch is checked as typed and stamps the cycle record; it was ignored."""

    def run_cycle(self, work, hb_epoch):
        (Path(work) / "mesh").mkdir()
        (Path(work) / "node").mkdir()
        env = dict(os.environ, STEGVERSE_ORG_LEDGER_ROOT=str(Path(work) / "org"),
                   STEGVERSE_REPO_LEDGER_ROOT=str(Path(work) / "repo"))
        epoch = [] if hb_epoch is None else ["--hb-epoch", hb_epoch]
        return subprocess.run([sys.executable, str(FEDERATION_CYCLE), "--mesh-root", str(Path(work) / "mesh"),
                               "--node-state-root", str(Path(work) / "node"), *epoch],
                              capture_output=True, text=True, cwd=str(ROOT), env=env)

    def test_an_absent_or_inadmissible_epoch_is_refused_and_nothing_written(self):
        """Absent is HB_EPOCH_NOT_SUPPLIED: the cycle no longer stamps a record from the clock."""
        for epoch in (*REFUSED_SUPPLIED_EPOCHS, None):
            with self.subTest(epoch=epoch), tempfile.TemporaryDirectory() as work:
                completed = self.run_cycle(work, epoch)
                self.assertEqual(completed.returncode, 1, (completed.stdout, completed.stderr))
                refusal = json.loads(completed.stdout.splitlines()[-1])
                self.assertEqual((refusal["disposition"], refusal["failure_code"]),
                                 ("FAIL_CLOSED", "HB_EPOCH_NOT_SUPPLIED" if epoch is None else "HB_EPOCH_INVALID"))
                self.assertEqual(refusal["retry_entrypoint"], "resident-runtime/federation_cycle.py (--hb-epoch)")
                for field in SIX_FIELDS:
                    self.assertTrue(refusal[field], field)
                written = [p for p in Path(work).rglob("*") if p.is_file()]
                self.assertEqual(written, [])

    def test_a_supplied_epoch_stamps_the_cycle_and_no_clock_is_read(self):
        spec = importlib.util.spec_from_file_location("federation_cycle_epoch", FEDERATION_CYCLE)
        cycle = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cycle)

        class NoClock:
            @staticmethod
            def now(*_):
                raise AssertionError("clock read")

        with tempfile.TemporaryDirectory() as work:
            (Path(work) / "mesh").mkdir()
            previous = {k: os.environ.get(k) for k in ("STEGVERSE_ORG_LEDGER_ROOT", "STEGVERSE_REPO_LEDGER_ROOT")}
            os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = str(Path(work) / "org")
            os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = str(Path(work) / "repo")
            clock = cycle.K.datetime
            cycle.K.datetime = NoClock
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    receipt = cycle.main(mesh_root=Path(work) / "mesh", node_state_root=Path(work) / "node",
                                         hb_epoch="4096")
            finally:
                cycle.K.datetime = clock
                for k, v in previous.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
            self.assertEqual(receipt["heartbeat_reference"]["epoch"], 4096)
            self.assertIs(receipt["heartbeat_reference"]["derived_from_clock"], False)
            self.assertEqual(len(list((Path(work) / "node").rglob("*.json"))), 1)


class ResidentExecutorEpochTests(unittest.TestCase):
    """The executor has no epoch of its own: without one supplied, its cycle fails closed."""

    def test_without_a_supplied_epoch_the_executor_records_fail_closed_and_no_cycle(self):
        with tempfile.TemporaryDirectory() as work:
            mesh, state = Path(work) / "mesh", Path(work) / "state"
            mesh.mkdir()
            # A node materialization, not a hosted runner: the executor refuses
            # to run at all under GITHUB_ACTIONS / CI (resident_executor.HOSTED).
            hosted = ("GITHUB_ACTIONS", "CI", "RENDER", "VERCEL", "CF_PAGES", "CLOUDFLARE_WORKERS")
            env = {k: v for k, v in os.environ.items() if k not in hosted and not k.startswith("STEGVERSE_")}
            env.update(STEGVERSE_ORG_LEDGER_ROOT=str(Path(work) / "org"),
                       STEGVERSE_REPO_LEDGER_ROOT=str(Path(work) / "repo"))
            completed = subprocess.run([sys.executable, "-B", str(ROOT / "resident-runtime/resident_executor.py"),
                                        "--mesh-root", str(mesh), "--node-state-root", str(state)],
                                       capture_output=True, text=True, env=env, cwd=work, timeout=180)
            record = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(record["disposition"], "FAIL_CLOSED")
            self.assertEqual(record["failed_predicate"], "FEDERATION_CYCLE_FAILED")
            self.assertIn("HB_EPOCH_NOT_SUPPLIED", record["error"])
            self.assertEqual(list(state.rglob("cycles.d/*.json")), [])


INTR = ROOT / "resident-runtime/intr_destination_ingress.py"
FIXED_CLOCK_NS = org.kernel.HB_ANCHOR_UNIX_NS + 7_000_000_000


class CarriedEpochTests(unittest.TestCase):
    """An epoch read back from a repository receipt is CARRIED, never passed on as supplied."""

    def receipt(self, reference):
        return {"receipt_sha256": "sha256:" + "c" * 64, "hb_reference": reference}

    def test_a_supplied_reference_is_carried(self):
        self.assertEqual(org.carried_epoch(self.receipt(org.kernel.hb_reference(epoch=4096)),
                                           retry_entrypoint="t"), 4096)

    def test_a_clock_derived_or_unmarked_or_invalid_reference_is_refused_six_field(self):
        clocked = org.kernel.hb_reference(now_ns=FIXED_CLOCK_NS)
        self.assertIs(clocked["derived_from_clock"], True)
        unmarked = {k: v for k, v in org.kernel.hb_reference(epoch=4096).items() if k != "derived_from_clock"}
        for reference in (clocked, unmarked, {"epoch": 31, "derived_from_clock": False},
                          {"epoch": "+33", "derived_from_clock": False}, None, "4096"):
            with self.subTest(reference=reference):
                with self.assertRaises(org.OrgLedgerEpochRefused) as caught:
                    org.carried_epoch(self.receipt(reference), retry_entrypoint="t")
                refusal = caught.exception.refusal
                self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
                for field in SIX_FIELDS:
                    self.assertTrue(refusal[field], field)


class IngressEpochProvenanceProbe(unittest.TestCase):
    """B-P36f probe: no organization receipt says derived_from_clock false for an epoch nobody supplied."""

    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        roots = {"STEGVERSE_REPO_LEDGER_ROOT": str(Path(self.work.name) / "repo"),
                 "STEGVERSE_ORG_LEDGER_ROOT": str(Path(self.work.name) / "org")}
        previous = {k: os.environ.get(k) for k in roots}
        os.environ.update(roots)
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in previous.items()])
        spec = importlib.util.spec_from_file_location("intr_destination_ingress_probe", INTR)
        self.intr = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.intr
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(self.intr)

    def evidence(self, communication_id):
        return {"payload_sha256": "sha256:" + "e" * 64, "disposition": "ALLOW",
                "communication_id": communication_id}

    def org_receipts(self):
        root = Path(self.work.name) / "org"
        return [json.loads(p.read_text()) for p in root.rglob("*.json")
                if p.is_file() and json.loads(p.read_text()).get("schema") == "stegverse.organization-transition-receipt/v1"]

    def test_a_supplied_epoch_reaches_both_receipts(self):
        pair, replayed = self.intr._append("PROBE", "probe-1", self.evidence("c-1"), "4096")
        for name in ("repository_receipt", "organization_receipt"):
            self.assertEqual(pair[name]["hb_reference"]["epoch"], 4096, name)
            self.assertIs(pair[name]["hb_reference"]["derived_from_clock"], False, name)
        self.assertEqual([r["receipt_sha256"] for r in self.org_receipts()],
                         [pair["organization_receipt"]["receipt_sha256"]])

    def test_an_absent_epoch_writes_nothing_with_the_clock_at_a_fixed_value(self):
        class FixedClock:
            @staticmethod
            def now(tz=None):
                import datetime as _dt
                return _dt.datetime.fromtimestamp(FIXED_CLOCK_NS / 1e9, tz)

        kernel = self.intr.repository_ledger.kernel
        clock = kernel.datetime
        kernel.datetime = FixedClock
        try:
            with self.assertRaises(SystemExit) as caught:
                self.intr._append("PROBE", "probe-2", self.evidence("c-2"), None)
        finally:
            kernel.datetime = clock
        self.assertEqual(caught.exception.refusal["failure_code"], "HB_EPOCH_NOT_SUPPLIED")
        self.assertEqual(self.org_receipts(), [])

    def test_a_replayed_clock_derived_repository_receipt_is_not_laundered(self):
        # A repository receipt minted before the writers required a supplied
        # epoch carries a clock-derived reference; replaying its transition
        # returns it, and its epoch must not reach the organization receipt.
        kernel = self.intr.repository_ledger.kernel
        real = kernel.hb_reference
        kernel.hb_reference = lambda *a, **k: real(now_ns=FIXED_CLOCK_NS)
        try:
            legacy = self.intr.repository_ledger.append(
                "PROBE:probe-3", "PROBE", "sha256:" + "e" * 64,
                self.intr.sha({"disposition": "ALLOW", "packet_id": "probe-3", "communication_id": "c-3",
                               "payload_sha256": "sha256:" + "e" * 64}),
                self.evidence("c-3"), "NONE", hb_epoch=4096,
                idempotent_on=("communication_id", "payload_sha256", "disposition"))
        finally:
            kernel.hb_reference = real
        self.assertIs(legacy["hb_reference"]["derived_from_clock"], True)
        with self.assertRaises(SystemExit) as caught:
            self.intr._append("PROBE", "probe-3", self.evidence("c-3"), "4096")
        refusal = caught.exception.refusal
        self.assertEqual(refusal["failure_code"], "HB_EPOCH_INVALID")
        for field in SIX_FIELDS:
            self.assertTrue(refusal[field], field)
        self.assertEqual(self.org_receipts(), [])


class EgressCloseCliEpochTests(unittest.TestCase):
    """--close checks the epoch before resolving the destination or the mesh."""

    def test_a_bad_epoch_is_refused_six_field_not_a_resolution_error(self):
        for epoch in (*REFUSED_SUPPLIED_EPOCHS, None):
            with self.subTest(epoch=epoch), tempfile.TemporaryDirectory() as work:
                standing = Path(work) / "standing.json"
                standing.write_text(json.dumps({"predecessor": None}))
                payload = Path(work) / "payload.json"  # required by the parser, unread by --close
                payload.write_text("{}")
                command = [sys.executable, str(EGRESS), "--destination-organization", "Nowhere-Org",
                           "--payload", str(payload),
                           "--standing", str(standing), "--close", "--packet-id", "p-1",
                           "--communication-id", "c-1"]
                if epoch is not None:
                    command += ["--hb-epoch", epoch]
                completed = subprocess.run(command, capture_output=True, text=True, cwd=str(ROOT),
                                           env=dict(os.environ, STEGVERSE_ORG_LEDGER_ROOT=str(Path(work) / "org"),
                                                    STEGVERSE_REPO_LEDGER_ROOT=str(Path(work) / "repo")))
                self.assertEqual(completed.returncode, 1, completed.stderr)
                refusal = json.loads(completed.stdout)
                self.assertEqual(refusal["failure_code"],
                                 "HB_EPOCH_NOT_SUPPLIED" if epoch is None else "HB_EPOCH_INVALID")
                self.assertIs(refusal["closure_recorded"], False)
                for field in SIX_FIELDS:
                    self.assertTrue(refusal[field], field)
                self.assertEqual(sorted(p.name for p in Path(work).rglob("*") if p.is_file()),
                                 ["payload.json", "standing.json"])


WORKFLOWS = ROOT / ".github/workflows"


def workflow_epoch_gates():
    """(workflow, step, inline python) for every inline gate reading HB_EPOCH before a writer."""
    gates = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for step in path.read_text(encoding="utf-8").split("      - name: ")[1:]:
            if "HB_EPOCH" not in step or "python - <<'PY'" not in step:
                continue
            for block in step.split("python - <<'PY'\n")[1:]:
                body = block.split("\n          PY\n")[0]
                if 'os.environ.get("HB_EPOCH")' in body:
                    lines = body.splitlines()
                    gates.append((path.name, step.splitlines()[0],
                                  "\n".join(line[10:] for line in lines)))
    return gates


class WorkflowEpochGateTests(unittest.TestCase):
    """Each inline dispatch-epoch gate refuses six-field as the writers do; "4096" passes.

    A workflow_dispatch string input cannot tell empty from absent, so a gate
    reads "" as HB_EPOCH_NOT_SUPPLIED. Where the two can be told apart (function
    and CLI arguments) "" stays HB_EPOCH_INVALID.
    """

    def run_gate(self, source, hb_epoch):
        env = {k: v for k, v in os.environ.items() if k != "HB_EPOCH"}
        if hb_epoch is not None:
            env["HB_EPOCH"] = hb_epoch
        return subprocess.run([sys.executable, "-c", source], capture_output=True, text=True,
                              cwd=str(ROOT), env=env)

    def test_there_is_a_gate_in_front_of_the_self_closure_writer(self):
        names = [(workflow, step) for workflow, step, _ in workflow_epoch_gates()]
        self.assertIn(("organization-ledger-transition.yml",
                       "Close an intr-destination diagnostic against this organization"), names)

    def test_no_workflow_checks_the_epoch_with_a_shell_pattern_or_int(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn('case "$HB_EPOCH"', text, path.name)
            self.assertNotIn("int(os.environ", text.replace(" ", ""), path.name)

    def test_each_gate_refuses_six_field_and_admits_ascii_digits(self):
        expected = {"": "HB_EPOCH_NOT_SUPPLIED", None: "HB_EPOCH_NOT_SUPPLIED", "+33": "HB_EPOCH_INVALID",
                    " 33": "HB_EPOCH_INVALID", "\uff13\uff13": "HB_EPOCH_INVALID",
                    "33.0": "HB_EPOCH_INVALID", "31": "HB_EPOCH_INVALID", "abc": "HB_EPOCH_INVALID"}
        for workflow, step, source in workflow_epoch_gates():
            for epoch, code in expected.items():
                with self.subTest(workflow=workflow, epoch=epoch):
                    completed = self.run_gate(source, epoch)
                    self.assertEqual(completed.returncode, 1, completed.stderr)
                    refusal = json.loads(completed.stdout.splitlines()[-1])
                    self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
                    self.assertEqual(refusal["failure_code"], code)
                    for field in SIX_FIELDS:
                        self.assertTrue(refusal[field], field)
            with self.subTest(workflow=workflow, epoch="4096"):
                completed = self.run_gate(source, "4096")
                self.assertEqual((completed.returncode, completed.stdout), (0, ""), completed.stderr)


class OrganizationReceiptTests(unittest.TestCase):
    def _append(self, root, transition_id="time-base-1", hb_epoch=EPOCH):
        os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = root
        return org.append(repo_receipt(transition_id), "REPO_STATE_PROPAGATION",
                          STATE_BEFORE, STATE_AFTER, {}, "NONE", hb_epoch=hb_epoch)

    def test_an_organization_receipt_carries_no_clock_reading(self):
        with tempfile.TemporaryDirectory() as root:
            receipt = self._append(root)
            for field in CLOCK_FIELDS:
                self.assertNotIn(field, receipt)
            self.assertEqual(receipt["hb_reference"]["epoch"], EPOCH)
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)

    def test_the_same_organization_transition_at_the_same_tick_is_reproducible(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            a = self._append(first)
            b = self._append(second)
            self.assertEqual(a["receipt_sha256"], b["receipt_sha256"])

    def test_a_different_tick_gives_a_different_organization_receipt(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            a = self._append(first, hb_epoch=EPOCH)
            b = self._append(second, hb_epoch=EPOCH + 1)
            self.assertNotEqual(a["receipt_sha256"], b["receipt_sha256"])

    def test_an_organization_receipt_without_a_tick_is_refused_and_writes_nothing(self):
        # PR-1c (owner decision: this used to pin the clock fallback, which
        # derived the epoch and marked it derived_from_clock true).
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(org.OrgLedgerEpochRefused) as refused:
                self._append(root, hb_epoch=None)
            self.assertEqual(refused.exception.refusal["failure_code"], "HB_EPOCH_NOT_SUPPLIED")
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_the_chain_still_links_and_validates_across_appends(self):
        """Replacing the time field must not disturb the hash chain."""
        with tempfile.TemporaryDirectory() as root:
            first = self._append(root, "chain-1")
            second = self._append(root, "chain-2")
            self.assertIsNone(first["previous_receipt_sha256"])
            self.assertEqual(second["previous_receipt_sha256"], first["receipt_sha256"])
            for receipt in (first, second):
                body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
                self.assertEqual(org.sha(body), receipt["receipt_sha256"])


if __name__ == "__main__":
    unittest.main()
