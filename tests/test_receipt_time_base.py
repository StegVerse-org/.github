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
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
EMIT = ROOT / ".stegverse/transition-ledger/emit.py"
REPO_CONTRACT = json.loads((ROOT / ".stegverse/transition-ledger/contract.json").read_text())

spec = importlib.util.spec_from_file_location("org_append_time", ROOT / "resident-runtime/aggregate_repo_transition.py")
org = importlib.util.module_from_spec(spec)
spec.loader.exec_module(org)


def load_module(name, relative):
    module_spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module

EPOCH = 4_200
STATE_BEFORE = "sha256:" + "a" * 64
STATE_AFTER = "sha256:" + "b" * 64
CLOCK_FIELDS = ("observed_at", "timestamp", "emitted_at", "sampled_at")


def repo_receipt(transition_id="time-base-1"):
    body = {
        "schema": "stegverse.repo-transition-receipt/v1", "hb_reference": {"epoch": 4096, "generation": 4096, "heartbeat_id": "HB:4096", "phase_offset_ns": 0, "frequency_hz": 100, "progression_dependency": "OSCILLATOR_ONLY", "derived_from_clock": False, "authority_effect": "NONE"},
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

    def test_without_a_supplied_epoch_the_executor_refuses_and_writes_nothing(self):
        """F7: refused six-field at the top level, before the cycle runs; no state record is written."""
        for epoch in (None, "", "+33", "31"):
            with self.subTest(epoch=epoch), tempfile.TemporaryDirectory() as work:
                mesh, state = Path(work) / "mesh", Path(work) / "state"
                mesh.mkdir()
                hosted = ("GITHUB_ACTIONS", "CI", "RENDER", "VERCEL", "CF_PAGES", "CLOUDFLARE_WORKERS")
                env = {k: v for k, v in os.environ.items() if k not in hosted and not k.startswith("STEGVERSE_")}
                env.update(STEGVERSE_ORG_LEDGER_ROOT=str(Path(work) / "org"),
                           STEGVERSE_REPO_LEDGER_ROOT=str(Path(work) / "repo"))
                command = [sys.executable, "-B", str(ROOT / "resident-runtime/resident_executor.py"),
                           "--mesh-root", str(mesh), "--node-state-root", str(state)]
                if epoch is not None:
                    command += ["--hb-epoch", epoch]
                completed = subprocess.run(command, capture_output=True, text=True, env=env, cwd=work, timeout=180)
                self.assertEqual(completed.returncode, 1, completed.stderr)
                refusal = json.loads(completed.stdout.strip().splitlines()[-1])
                self.assertEqual(refusal["failure_code"],
                                 "HB_EPOCH_NOT_SUPPLIED" if epoch is None else "HB_EPOCH_INVALID")
                for field in SIX_FIELDS:
                    self.assertTrue(refusal[field], field)
                self.assertEqual([p for p in Path(work).rglob("*") if p.is_file()], [])


INTR = ROOT / "resident-runtime/intr_destination_ingress.py"
FIXED_CLOCK_NS = org.kernel.HB_ANCHOR_UNIX_NS + 7_000_000_000


class SharedRuleReferenceTests(unittest.TestCase):
    """The FINAL shared rule on a carrier reference: CLOCK and unmarked are refused; false passes."""

    def setUp(self):
        self.supplied = org.kernel.hb_reference(epoch=4096)
        self.no_flag = {k: v for k, v in self.supplied.items() if k != "derived_from_clock"}

    def code(self, reference):
        failure = org.supplied_epoch_failure(4096, reference)
        return failure[0] if failure else None

    def test_no_flag_with_a_sample_is_clock(self):
        self.assertEqual(self.code({**self.no_flag, "sampled_unix_ns": FIXED_CLOCK_NS}), "HB_EPOCH_INVALID")

    def test_a_fabricated_carried_claim_without_a_flag_is_unmarked(self):
        forged = {**self.no_flag, "source": "CARRIED:ORGANIZATION_LEDGER_HEAD", "head_receipt_sha": "sha256:" + "f" * 64}
        self.assertEqual(self.code(forged), "HB_EPOCH_PROVENANCE_UNMARKED")

    def test_false_with_a_sample_is_clock(self):
        self.assertEqual(self.code({**self.supplied, "sampled_unix_ns": FIXED_CLOCK_NS}), "HB_EPOCH_INVALID")

    def test_false_passes_whatever_its_source(self):
        self.assertIsNone(self.code({**self.supplied, "source": "X"}))
        self.assertIsNone(self.code(self.supplied))

    def test_the_rule_is_the_same_text_in_all_four_copies(self):
        import hashlib, inspect
        from tests.test_p1_supplied_epoch_and_ledger_paths import SHARED_VALIDATOR_SHA256
        self.assertEqual(hashlib.sha256(inspect.getsource(org.supplied_epoch_failure).encode()).hexdigest(),
                         SHARED_VALIDATOR_SHA256)
        self.assertFalse(hasattr(org, "reference_provenance_failure"))


class WriterCarriedProvenanceTests(unittest.TestCase):
    """A writer handed CARRIED provenance verifies it against the named ledger head, or writes nothing."""

    def seeded_org_store(self, root):
        store = org.open_store(org.parse_locator(root))
        os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = root
        try:
            head = org.append(repo_receipt("carried-head"), "REPO_STATE_PROPAGATION", "GENESIS", STATE_AFTER,
                              {}, "NONE", hb_epoch=4096, store=store)
        finally:
            os.environ.pop("STEGVERSE_ORG_LEDGER_ROOT", None)
        return store, head

    def test_an_invented_head_sha_is_refused_by_both_writers_and_nothing_written(self):
        spec = importlib.util.spec_from_file_location("repo_emit_carried", EMIT)
        emit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(emit)
        invented = {"source": "CARRIED:ORGANIZATION_LEDGER_HEAD", "head_receipt_sha": "sha256:" + "f" * 64}
        with tempfile.TemporaryDirectory() as org_root, tempfile.TemporaryDirectory() as repo_root:
            org_store, _ = self.seeded_org_store(org_root)
            before = files_under(org_root)
            repo_store = emit.ledger_store.open_store(emit.ledger_store.parse_locator(repo_root))
            with self.assertRaises(emit.RepoLedgerEpochRefused) as caught:
                emit.append("t-c", "TEST", STATE_BEFORE, STATE_AFTER, hb_epoch=4096, store=repo_store,
                            hb_provenance=invented, provenance_head_store=org_store)
            self.assertEqual(caught.exception.refusal["failure_code"], "CARRIED_PROVENANCE_UNVERIFIED")
            self.assertEqual(files_under(repo_root), [])
            with self.assertRaises(org.OrgLedgerEpochRefused) as caught:
                org.append(repo_receipt("carried-2"), "REPO_STATE_PROPAGATION", "FROM_HEAD", STATE_AFTER, {}, "NONE",
                           hb_epoch=4096, store=org_store, hb_provenance=invented)
            refusal = caught.exception.refusal
            self.assertEqual(refusal["failure_code"], "CARRIED_PROVENANCE_UNVERIFIED")
            for field in SIX_FIELDS:
                self.assertTrue(refusal[field], field)
            self.assertEqual(files_under(org_root), before)

    def test_the_current_head_is_carried_with_its_provenance(self):
        with tempfile.TemporaryDirectory() as org_root:
            org_store, head = self.seeded_org_store(org_root)
            claim = {"source": "CARRIED:ORGANIZATION_LEDGER_HEAD", "head_receipt_sha": head["receipt_sha256"]}
            receipt = org.append(repo_receipt("carried-3"), "REPO_STATE_PROPAGATION", "FROM_HEAD", STATE_AFTER, {},
                                 "NONE", hb_epoch=4096, store=org_store, hb_provenance=claim)
            self.assertEqual({k: receipt["hb_reference"][k] for k in ("source", "head_receipt_sha", "derived_from_clock")},
                             {**claim, "derived_from_clock": False})


class SourceReceiptProvenanceTests(unittest.TestCase):
    """F5 / F4: the organization writer refuses an unmarked source, and verifies a CARRIED one."""

    def source(self, reference, transition_id="src-1"):
        body = {"schema": "stegverse.repo-transition-receipt/v1", "repository": REPO_CONTRACT["repository"],
                "transition_id": transition_id}
        if reference is not None:
            body["hb_reference"] = reference
        return {**body, "receipt_sha256": org.sha(body)}

    def append(self, root, receipt, predecessor="GENESIS"):
        os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = root
        try:
            return org.append(receipt, "REPO_STATE_PROPAGATION", predecessor, STATE_AFTER, {}, "NONE", hb_epoch=4096)
        finally:
            os.environ.pop("STEGVERSE_ORG_LEDGER_ROOT", None)

    def test_an_unmarked_source_reference_is_refused_and_nothing_written(self):
        unmarked = {k: v for k, v in org.kernel.hb_reference(epoch=4096).items() if k != "derived_from_clock"}
        for reference in (unmarked, None):
            with self.subTest(reference=reference), tempfile.TemporaryDirectory() as root:
                with self.assertRaises(org.SourceReceiptRefused) as caught:
                    self.append(root, self.source(reference))
                self.assertEqual(caught.exception.refusal["failure_code"], "HB_EPOCH_PROVENANCE_UNMARKED")
                for field in SIX_FIELDS:
                    self.assertTrue(caught.exception.refusal[field], field)
                self.assertEqual(files_under(root), [])

    def test_a_source_claiming_carried_provenance_is_verified_against_the_head(self):
        with tempfile.TemporaryDirectory() as root:
            head = self.append(root, self.source(org.kernel.hb_reference(epoch=4096), "src-head"))
            before = files_under(root)
            forged = {**org.kernel.hb_reference(epoch=4096), "source": "CARRIED:ORGANIZATION_LEDGER_HEAD",
                      "head_receipt_sha": "sha256:" + "f" * 64}
            with self.assertRaises(org.OrgLedgerEpochRefused) as caught:
                self.append(root, self.source(forged, "src-forged"), predecessor="FROM_HEAD")
            self.assertEqual(caught.exception.refusal["failure_code"], "CARRIED_PROVENANCE_UNVERIFIED")
            self.assertEqual(files_under(root), before)
            honest = {**forged, "head_receipt_sha": head["receipt_sha256"]}
            receipt = self.append(root, self.source(honest, "src-honest"), predecessor="FROM_HEAD")
            self.assertEqual(receipt["previous_receipt_sha256"], head["receipt_sha256"])


class MarkerVocabularyTests(unittest.TestCase):
    """SUPPLIED is derived_from_clock false with no sample; CLOCK is true with its sample."""

    def test_a_supplied_epoch_is_marked_supplied_and_reads_no_clock(self):
        class NoClock:
            @staticmethod
            def now(*_):
                raise AssertionError("clock read")

        clock = org.kernel.datetime
        org.kernel.datetime = NoClock
        try:
            reference = org.kernel.hb_reference(epoch=4096)
            packet = org.kernel.build_packet(origin_org="O", origin_service="o.org-control", destination_org="D",
                                             destination_service="d.org-control", payload={"body": {}},
                                             standing={"mode": "ESTABLISH_GENESIS", "node_ref": "m", "predecessor": None})
            frame = org.kernel.carrier_frame(packet, epoch=4096)
        finally:
            org.kernel.datetime = clock
        for ref in (reference, frame["heartbeat_reference"]):
            self.assertIs(ref["derived_from_clock"], False)
            self.assertNotIn("sampled_unix_ns", ref)
            self.assertEqual(ref["epoch"], 4096)

    def test_a_clock_sample_is_marked_clock(self):
        clocked = org.kernel.hb_reference(now_ns=FIXED_CLOCK_NS)
        self.assertIs(clocked["derived_from_clock"], True)
        self.assertEqual(clocked["sampled_unix_ns"], FIXED_CLOCK_NS)


class ClockSourceReceiptTests(unittest.TestCase):
    """O-1: the organization writer does not consume a clock-provenance repository receipt."""

    def test_a_clock_repository_receipt_is_refused_and_nothing_written(self):
        for reference in (org.kernel.hb_reference(now_ns=FIXED_CLOCK_NS),
                          {"epoch": 33, "sampled_unix_ns": FIXED_CLOCK_NS}):
            with self.subTest(reference=reference), tempfile.TemporaryDirectory() as root:
                body = {"schema": "stegverse.repo-transition-receipt/v1",
                        "repository": REPO_CONTRACT["repository"], "transition_id": "legacy-1",
                        "hb_reference": reference}
                legacy = {**body, "receipt_sha256": org.sha(body)}
                os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = root
                try:
                    with self.assertRaises(org.SourceReceiptRefused) as caught:
                        org.append(legacy, "REPO_STATE_PROPAGATION", "GENESIS", STATE_AFTER, {}, "NONE",
                                   hb_epoch=4096)
                finally:
                    os.environ.pop("STEGVERSE_ORG_LEDGER_ROOT", None)
                refusal = caught.exception.refusal
                self.assertEqual(refusal["failure_code"], "SOURCE_RECEIPT_IS_CLOCK_PROVENANCE")
                self.assertIn("CARRIED:LEGACY_CLOCK_RECEIPT", refusal["required_evidence_or_repair"])
                for field in SIX_FIELDS:
                    self.assertTrue(refusal[field], field)
                self.assertEqual([p for p in Path(root).rglob("*") if p.is_file()], [])


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
        self.assertEqual(refusal["failure_code"], "SOURCE_RECEIPT_IS_CLOCK_PROVENANCE")
        for field in SIX_FIELDS:
            self.assertTrue(refusal[field], field)
        self.assertEqual(self.org_receipts(), [])


class ClockProbeTests(unittest.TestCase):
    """B-P36g marker rule: under a fixed clock, no writer route reads it, and every clock value is marked."""

    def test_supplied_routes_read_no_clock_and_every_reference_is_supplied_or_marked(self):
        hosted = ("GITHUB_ACTIONS", "CI", "RENDER", "VERCEL", "CF_PAGES", "CLOUDFLARE_WORKERS")
        env = {k: v for k, v in os.environ.items() if k not in hosted and not k.startswith("STEGVERSE_")}
        env["PROBE_FIXED_CLOCK_NS"] = str(FIXED_CLOCK_NS)
        completed = subprocess.run([sys.executable, "-I", str(ROOT / "tests/fixtures/clock-probe/probe.py"), str(ROOT)],
                                   capture_output=True, text=True, env=env, timeout=180)
        self.assertEqual(completed.returncode, 0, completed.stderr[-1500:])
        probe = json.loads(completed.stdout.splitlines()[-1])
        self.assertEqual(probe["phases"]["supplied_writer_clock_calls"], 0)
        self.assertEqual(probe["phases"]["frame_only_clock_calls"], 1)
        self.assertTrue(probe["references"])
        # A response is published at the validated epoch of the frame it answers,
        # and a monitor answer's resident_status carries it: no clock default.
        classes = {r["message_class"]: r for r in probe["responses"]}
        self.assertEqual(set(classes), {"ecosystem.communication.ack", "ecosystem.monitor.response"})
        for response in classes.values():
            self.assertEqual(response["heartbeat_reference"]["epoch"], 4096)
            self.assertIs(response["heartbeat_reference"]["derived_from_clock"], False)
        self.assertEqual(classes["ecosystem.monitor.response"]["monitor_heartbeat"]["epoch"], 4096)
        # NARROW S1 / B-P36j / B-P36k: CLOCK frames (a communication and a
        # monitor request) are consumed but lend no epoch -- recording refuses
        # NOT_SUPPLIED, no answer is published, the monitor status is refused
        # rather than sampled -- and are marked seen. A forged CARRIED claim
        # (head ff..ff) is refused UNVERIFIED and quarantined. Nothing of either
        # reaches a ledger, no clock is read, and a second cycle offers neither.
        quarantine = probe["quarantine"]
        rows = quarantine["rows"]
        self.assertEqual(probe["phases"]["quarantine_clock_calls"], 0)
        for name in ("clock", "clock_monitor"):
            self.assertEqual(rows[name]["status"], "CONSUMED", name)
            self.assertIsNone(rows[name]["epoch_lent"], name)
            self.assertEqual(rows[name]["organization_record_code"], "HB_EPOCH_NOT_SUPPLIED", name)
            self.assertIs(rows[name]["response"], False, name)
        self.assertEqual(rows["clock_monitor"]["monitor_status"]["failure_code"], "HB_EPOCH_NOT_SUPPLIED")
        self.assertEqual((rows["forged"]["status"], rows["forged"]["failure_code"]),
                         ("REFUSED", "CARRIED_PROVENANCE_UNVERIFIED"))
        self.assertEqual((rows["valid"]["status"], rows["valid"]["response"]), ("CONSUMED", True))
        self.assertEqual(quarantine["second_offered"], 0)
        self.assertGreater(quarantine["new_ledger_files"], 0)
        self.assertEqual(quarantine["clock_or_forged_in_ledgers"], 0)
        quarantined = [m for m in quarantine["markers"] if m.get("status") == "REFUSED"]
        self.assertEqual(len(quarantined), 1)
        for marker in quarantine["markers"]:
            for key in ("sampled_unix_ns", "derived_from_clock", "heartbeat_reference", "hb_reference"):
                self.assertNotIn(key, marker)
            self.assertNotIn(str(FIXED_CLOCK_NS), json.dumps(marker))
        marker = quarantined[0]
        self.assertEqual(marker["failure_code"], "FRAME_REFUSED_QUARANTINED")
        for field in SIX_FIELDS:
            self.assertTrue(marker[field], field)
        # B-P36o / F-S1a: each frame that cannot be ingested is its own six-field
        # refusal, quarantined with no clock read; the valid frame beside them is
        # consumed and ledgered, and a second cycle offers none of the bad ones.
        integrity = probe["integrity"]
        self.assertEqual(probe["phases"]["integrity_clock_calls"], 0)
        self.assertEqual({name: row["failure_code"] for name, row in integrity["rows"].items()},
                         {"generation": "HB_REFERENCE_INVALID", "heartbeat_id": "HB_REFERENCE_INVALID",
                          "frame_hash": "FRAME_INTEGRITY_INVALID", "clock_epoch_abc": "HB_EPOCH_INVALID",
                          "clock_epoch_5": "HB_EPOCH_INVALID",
                          # B-P36o explicit check: incoherent with its epoch on a CLOCK frame,
                          # refused before the CLOCK branch rather than consumed as clock.
                          "clock_generation": "HB_REFERENCE_INVALID",
                          # F11: a self-asserted CARRIED claim on an unflagged sampled frame.
                          "clock_forged_carried": "CARRIED_PROVENANCE_UNVERIFIED",
                          "valid": None})
        self.assertEqual(integrity["rows"]["valid"]["status"], "CONSUMED")
        self.assertGreater(integrity["valid_in_ledgers"], 0)
        self.assertEqual(integrity["bad_in_ledgers"], 0)
        self.assertEqual(integrity["second_offered"], 0)
        # F12 / B-P36p: unreadable frames.d entries sorted before a valid frame are
        # each quarantined by file name as six-field FRAME_INGEST_FAILED, with no
        # clock read and no ledger file; the valid frame is still ledgered.
        scan = probe["scan"]
        corrupt = ("0000-not-json.json", "0001-a-list.json", "0002-not-utf8.json", "0003-oversized.json",
                   "0004-a-directory.json", "0005-read-error.json")
        self.assertEqual(probe["phases"]["scan_clock_calls"], 0)
        self.assertEqual(tuple(scan["order"][:6]), corrupt)
        self.assertEqual(scan["corrupt_only_rows"], 6)
        self.assertEqual(scan["corrupt_only_ledger_files"], 0)
        for name in corrupt:
            self.assertEqual(scan["rows"][name], {"status": "REFUSED", "failure_code": "FRAME_INGEST_FAILED"}, name)
            marker = scan["markers"][name]
            self.assertEqual((marker["failure_code"], marker["refusal_failure_code"]),
                             ("FRAME_REFUSED_QUARANTINED", "FRAME_INGEST_FAILED"), name)
            for field in SIX_FIELDS:
                self.assertTrue(marker[field], (name, field))
        self.assertEqual(scan["rows"]["valid"]["status"], "CONSUMED")
        self.assertGreater(scan["valid_in_ledgers"], 0)
        self.assertEqual(scan["second_offered"], 0)
        # B-P36m (09:00Z alternative): accepts_carried_crossings is false, whether or
        # not the cycle supplies an epoch: a CARRIED frame is refused
        # CARRIED_NOT_ACCEPTED_BY_DESTINATION and nothing of it is ledgered.
        carried = probe["carried"]
        self.assertEqual(carried["refused_without_cycle_epoch"], ["CARRIED_NOT_ACCEPTED_BY_DESTINATION"])
        self.assertEqual((carried["status"], carried["in_cycle_failure_code"]),
                         (["REFUSED"], ["CARRIED_NOT_ACCEPTED_BY_DESTINATION"]))
        self.assertEqual(probe["phases"]["carried_clock_calls"], 0)
        self.assertEqual(carried["receipts"], [])
        # F1: a cycle at supplied 4096 consuming a frame at 77. Every receipt and
        # the answer are this organization's, stamped 4096; 77 is only inbound
        # provenance (frame_reference). A consumed request is always answered.
        f1 = probe["f1"]
        self.assertEqual(probe["phases"]["f1_clock_calls"], 0)
        self.assertEqual(f1["status"], ["CONSUMED"])
        self.assertEqual((f1["response_published"], f1["mesh_answers"]), ([True], 1))
        answer, = f1["answers"]
        self.assertEqual((answer["epoch"], answer["derived_from_clock"]), (4096, False))
        self.assertEqual((answer["request_frame_reference"]["epoch"], answer["request_frame_reference"]["resolution"]),
                         (77, "SUPPLIED_CYCLE_EPOCH_STAMPS_THIS_ORGANIZATION"))
        self.assertEqual(len(f1["receipts"]), 3)
        for receipt in f1["receipts"]:
            self.assertEqual((receipt["epoch"], receipt["derived_from_clock"]), (4096, False), receipt["schema"])
            self.assertEqual((receipt["frame_reference"]["epoch"], receipt["frame_reference"]["resolution"]),
                             (77, "SUPPLIED_CYCLE_EPOCH_STAMPS_THIS_ORGANIZATION"), receipt["schema"])
            self.assertEqual(receipt["frame_reference"]["cycle_epoch_source"],
                             {"source": "COMMITTED_REQUEST", "request_sha256": "sha256:" + "d" * 64})
        # F-TYPE: the per-frame guard is total. Wrong-typed packet_base64 before and
        # after a valid frame: each FRAME_INGEST_FAILED (AttributeError), quarantined
        # six-field, never re-offered; the valid frame is ledgered; no clock read.
        ftype = probe["ftype"]
        self.assertEqual(probe["phases"]["type_clock_calls"], 0)
        self.assertEqual((ftype["order"][0], ftype["order"][-1]), ("first", "last"))
        for label in ("int", "null", "list", "dict", "first", "last"):
            self.assertEqual((ftype["rows"][label]["status"], ftype["rows"][label]["failure_code"],
                              ftype["rows"][label]["failed_predicate"]),
                             ("REFUSED", "FRAME_INGEST_FAILED", "AttributeError"), label)
        self.assertEqual(ftype["rows"]["valid"]["status"], "CONSUMED")
        self.assertGreater(ftype["valid_in_ledgers"], 0)
        self.assertEqual((ftype["bad_in_ledgers"], ftype["second_offered"]), (0, 0))
        self.assertIs(ftype["six_field_markers"], True)
        # consume_addressed_frames: the same total guard, and the supplied node state
        # is its seen-store, so the quarantined frame is not offered again.
        addressed = probe["addressed"]
        self.assertEqual(probe["phases"]["addressed_clock_calls"], 0)
        self.assertEqual(addressed["first"], [["REFUSED", "FRAME_INGEST_FAILED", True], ["CONSUMED", None, None]])
        self.assertNotIn(addressed["bad_packet_id"], addressed["second_packet_ids"])
        self.assertGreater(addressed["valid_in_ledgers"], 0)
        # F-TRANSIENT-RT: an OSError on the repository append, a lost compare-and-swap
        # on the organization append, a collision writing the seen-marker: each a
        # non-terminal six-field FRAME_DISPATCH_IO_FAILED, no marker, the frame stays
        # pending, and the next pass consumes it exactly once (one repository and one
        # organization receipt, no duplicate or orphan).
        for label, row in probe["io"].items():
            with self.subTest(io=label):
                self.assertEqual(probe["phases"]["io_" + label + "_clock_calls"], 0)
                self.assertEqual(row["first"], ["PENDING", "FRAME_DISPATCH_IO_FAILED", False])
                for field in SIX_FIELDS:
                    self.assertTrue(row["first_record"][field], field)
                self.assertIsNone(row["first_marker"])
                self.assertEqual(row["markers_after_first"], 0)
                self.assertEqual((row["second"], row["third_offered"]), (["CONSUMED"], 0))
                self.assertEqual(len(row["receipt_shas"]), 2)
                self.assertEqual(sorted(set(row["receipt_schemas"])),
                                 ["stegverse.organization-transition-receipt/v1", "stegverse.repo-transition-receipt/v1"])
                self.assertEqual(row["heads_consistent"], {"repo": True, "org": True})
                # F-REPUB: a fault after the answer is published never yields a second one.
                self.assertEqual(row["responses"], 1)
        self.assertIn("torn_head_repo_append", probe["io"])
        self.assertIn("torn_head_org_append", probe["io"])
        self.assertEqual((probe["io_later"]["status"], probe["io_later"]["receipts"]), (["CONSUMED"], 2))
        # F-REPUB keying / RESPONSE_ID_COLLISION: B reuses A's request id with other
        # content; refused before anything is ledgered or answered; one response.
        duplicate = probe["duplicate"]
        self.assertEqual(duplicate["first"], ["CONSUMED"])
        self.assertEqual(duplicate["second"], [["REFUSED", "RESPONSE_ID_COLLISION"]])
        self.assertEqual((duplicate["third_offered"], duplicate["responses"], duplicate["receipt_shas"]), (0, 1, 2))
        self.assertIs(classes["ecosystem.monitor.response"]["monitor_heartbeat"]["derived_from_clock"], False)
        for reference in probe["references"]:
            if reference.get("derived_from_clock") is False:
                self.assertEqual(reference["epoch"], 4096, reference)
                self.assertNotIn("sampled_unix_ns", reference)
            else:
                self.assertIs(reference.get("derived_from_clock"), True, reference)
                self.assertEqual(reference.get("sampled_unix_ns"), FIXED_CLOCK_NS, reference)


SUBMITTER = ROOT / "resident-runtime/submit_org_transition_to_master_records.py"


class ReleasedSegmentHeadEpochTests(unittest.TestCase):
    """The downstream release stamps its frame with the head receipt's epoch only when it was supplied."""

    def head(self, reference, previous=None, transition_id="T-head"):
        body = {"schema": "stegverse.organization-transition-receipt/v1", "organization": "StegVerse-org",
                "transition_id": transition_id, "previous_receipt_sha256": previous, "hb_reference": reference}
        return {**body, "receipt_sha256": org.sha(body)}

    def ledger(self, work, *receipts):
        """An organization ledger holding `receipts` as its chain, the last one its HEAD."""
        root = Path(work) / "org-ledger"
        store = org.open_store(org.parse_locator(str(root)))
        for receipt in receipts:
            store.put(org.receipt_key(receipt["receipt_sha256"]), receipt)
        if receipts:
            store.put(org.HEAD_KEY, {"organization": "StegVerse-org", "receipt_sha256": receipts[-1]["receipt_sha256"]})
        return root

    def release(self, work, reference, *, released=None, ledger=None):
        head = released or self.head(reference)
        receipt = Path(work) / "head.json"
        receipt.write_text(json.dumps(head))
        standing = Path(work) / "standing.json"
        standing.write_text(json.dumps({"mode": "GENESIS", "node_ref": "t", "predecessor": None}))
        mesh = Path(work) / "mesh"
        ledger = ledger if ledger is not None else self.ledger(work, head)
        env = {k: v for k, v in os.environ.items() if k != "STEGVERSE_ORG_LEDGER_ROOT"}
        completed = subprocess.run([sys.executable, str(SUBMITTER), "--org-receipt", str(receipt),
                                    "--predecessor-ecosystem-state-sha256", "sha256:" + "1" * 64,
                                    "--successor-ecosystem-state-sha256", "sha256:" + "2" * 64,
                                    "--standing", str(standing), "--mesh-root", str(mesh),
                                    "--org-ledger-root", str(ledger)],
                                   capture_output=True, text=True, cwd=str(ROOT), env=env)
        frames = [json.loads(p.read_text()) for p in mesh.rglob("*.json")] if mesh.exists() else []
        return completed, frames

    def test_a_segment_not_on_the_organization_ledger_is_unverified_and_nothing_published(self):
        """F4: --org-receipt is verified against the ledger chain, never trusted."""
        supplied = org.kernel.hb_reference(epoch=4096)
        with tempfile.TemporaryDirectory() as work:
            other = self.head(supplied, transition_id="T-other")
            completed, frames = self.release(work, supplied, ledger=self.ledger(work, other))
            self.assertEqual(completed.returncode, 3, completed.stderr)
            refusal = json.loads(completed.stdout)
            self.assertEqual((refusal["failure_code"], refusal["failed_predicate"]),
                             ("CARRIED_PROVENANCE_UNVERIFIED", "RELEASED_SEGMENT_IS_DURABLE_ORGANIZATION_LEDGER_STATE"))
            for field in SIX_FIELDS:
                self.assertTrue(refusal[field], field)
            self.assertEqual(frames, [])

    def test_a_declared_verified_segment_head_need_not_be_the_tip(self):
        supplied = org.kernel.hb_reference(epoch=4096)
        with tempfile.TemporaryDirectory() as work:
            head = self.head(supplied)
            tip = self.head(supplied, previous=head["receipt_sha256"], transition_id="T-tip")
            completed, frames = self.release(work, supplied, released=head, ledger=self.ledger(work, head, tip))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            reference = frames[0]["heartbeat_reference"]
            self.assertEqual((reference["source"], reference["head_receipt_sha"]),
                             ("CARRIED:SEGMENT_HEAD", head["receipt_sha256"]))
        manifest = json.loads((ROOT / "resident-runtime/activation-manifest.json").read_text())
        self.assertIn("CARRIED:SEGMENT_HEAD", manifest["epoch_binding"]["carried_sources"])

    def test_without_a_ledger_location_nothing_is_published(self):
        with tempfile.TemporaryDirectory() as work:
            completed, frames = self.release(work, org.kernel.hb_reference(epoch=4096), ledger="")
            self.assertEqual(completed.returncode, 3, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["failed_predicate"], "ORGANIZATION_LEDGER_LOCATION_SUPPLIED")
            self.assertEqual(frames, [])

    def test_a_clock_flagged_absent_or_invalid_head_epoch_is_refused_and_nothing_published(self):
        clocked = org.kernel.hb_reference(now_ns=FIXED_CLOCK_NS)
        for reference in (clocked, None, {"epoch": 31, "derived_from_clock": False},
                          {k: v for k, v in org.kernel.hb_reference(epoch=4096).items() if k != "derived_from_clock"}):
            with self.subTest(reference=reference), tempfile.TemporaryDirectory() as work:
                completed, frames = self.release(work, reference)
                self.assertEqual(completed.returncode, 3, completed.stderr)
                refusal = json.loads(completed.stdout)
                self.assertEqual(refusal["failed_predicate"], "RELEASED_SEGMENT_HEAD_CARRIES_A_SUPPLIED_EPOCH")
                for field in SIX_FIELDS:
                    self.assertTrue(refusal[field], field)
                self.assertEqual(frames, [])

    def test_a_supplied_head_epoch_is_carried_with_its_provenance(self):
        with tempfile.TemporaryDirectory() as work:
            head = self.head(org.kernel.hb_reference(epoch=4096))
            completed, frames = self.release(work, head["hb_reference"])
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0]["heartbeat_reference"]["epoch"], 4096)
            self.assertIs(frames[0]["heartbeat_reference"]["derived_from_clock"], False)
            reference = frames[0]["heartbeat_reference"]
            self.assertEqual((reference["source"], reference["head_receipt_sha"]),
                             ("CARRIED:SEGMENT_HEAD", head["receipt_sha256"]))
            self.assertNotIn("sampled_unix_ns", reference)
            self.assertIsNone(org.supplied_epoch_failure(reference["epoch"], reference))
            payload = org.kernel.recover_packet(frames[0])["payload"]
            self.assertEqual(payload["hb_epoch_provenance"],
                             {"source": "CARRIED:SEGMENT_HEAD",
                              "head_receipt_sha": head["receipt_sha256"], "derived_from_clock": False})

    def test_carried_provenance_needs_a_supplied_epoch_and_only_its_two_keys(self):
        packet = org.kernel.build_packet(origin_org="O", origin_service="o.org-control", destination_org="D",
                                         destination_service="d.org-control", payload={"body": {}},
                                         standing={"mode": "ESTABLISH_GENESIS", "node_ref": "m", "predecessor": None})
        good = {"source": "CARRIED:X", "head_receipt_sha": "sha256:" + "a" * 64}
        for kwargs in ({"provenance": good}, {"epoch": 4096, "provenance": {**good, "derived_from_clock": False}},
                       {"epoch": 4096, "provenance": {**good, "source": "SUPPLIED"}}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                org.kernel.carrier_frame(packet, **kwargs)


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


class GovernanceReturnEpochTests(unittest.TestCase):
    """F10: a governance closure is never stamped from a consumed CLOCK answer; §Q: no epoch, nothing consumed."""

    COMMUNICATION = "governance:" + "a" * 64

    def setUp(self):
        self.fed = load_module("f10_federation_cycle", "resident-runtime/federation_cycle.py")
        self.kernel = self.fed.K
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.mesh = Path(self.work.name) / "mesh"
        self.mesh.mkdir()
        registry = self.kernel.load_registry(ROOT)
        self.packet = self.kernel.build_packet(
            origin_org="Probe-Origin", origin_service="probe-origin.org-control",
            destination_org=registry["organization"],
            destination_service=self.kernel.organization_slug(registry["organization"]) + ".org-control",
            payload={"communication_id": self.COMMUNICATION, "message_class": "ecosystem.communication.ack",
                     "subject": "s", "body": {"request_packet_id": "pkt-request"}},
            standing={"mode": "ESTABLISH_GENESIS", "node_ref": "f10", "predecessor": None})

    def consumed(self, **result):
        item = self.kernel.scan_addressed_frames(self.packet["destination"]["org"], root=self.mesh)[0]
        return [{"path": item["path"], "result": {"status": "CONSUMED", "packet": self.packet, **result}}]

    def returns(self, results):
        # The return operation (and the SDK it imports) is never loaded for a CLOCK answer.
        with mock.patch.object(self.fed.importlib.util, "spec_from_file_location",
                               side_effect=AssertionError("governance_decision_return loaded")):
            return self.fed.returns_for_consumed(results, mesh_root=self.mesh)

    def assert_not_supplied(self, returned):
        self.assertEqual(len(returned), 1)
        refusal = returned[0]
        self.assertEqual((refusal["disposition"], refusal["failure_code"], refusal["decision_returned"]),
                         ("FAIL_CLOSED", "HB_EPOCH_NOT_SUPPLIED", False))
        for field in SIX_FIELDS:
            self.assertTrue(refusal[field], field)
        self.assertNotIn(str(FIXED_CLOCK_NS), json.dumps(refusal))

    def test_a_consumed_clock_answer_lends_the_closure_no_epoch(self):
        self.kernel.publish_packet(self.packet, root=self.mesh, now_ns=FIXED_CLOCK_NS)
        self.assert_not_supplied(self.returns(self.consumed(epoch_lent=None)))

    def test_a_clock_flagged_or_unmarked_answer_frame_is_not_a_supplied_epoch(self):
        self.kernel.publish_packet(self.packet, root=self.mesh, now_ns=FIXED_CLOCK_NS)
        self.assert_not_supplied(self.returns(self.consumed()))

    def test_a_cycle_without_a_supplied_epoch_consumes_nothing_and_marks_nothing(self):
        cycle = load_module("q_governance_return_cycle", "resident-runtime/governance_return_cycle.py")
        self.kernel.publish_packet(self.packet, root=self.mesh, epoch=4096)
        for epoch, code in ((None, "HB_EPOCH_NOT_SUPPLIED"), ("abc", "HB_EPOCH_INVALID"), ("31", "HB_EPOCH_INVALID")):
            with self.subTest(epoch=epoch):
                node = Path(self.work.name) / ("node-" + str(epoch))
                with mock.patch.object(cycle.K, "consume_and_respond",
                                       side_effect=AssertionError("consumed without an epoch")):
                    refused = cycle.run(mesh_root=self.mesh, node_state_root=node, hb_epoch=epoch)
                self.assertEqual((refused["disposition"], refused["failure_code"]), ("FAIL_CLOSED", code))
                for field in SIX_FIELDS:
                    self.assertTrue(refused[field], field)
                self.assertEqual(refused["retry_entrypoint"], cycle.RETRY_ENTRYPOINT)
                # Pending: no quarantine, no seen-marker, the frame is still offered.
                self.assertFalse(node.exists())
                self.assertEqual(len(self.kernel.scan_addressed_frames(self.packet["destination"]["org"],
                                                                       root=self.mesh)), 1)


class RequestEpochResolutionTests(unittest.TestCase):
    """Trigger probe: a push-triggered run's committed request carries its own hb_epoch, gate first."""

    def setUp(self):
        self.inputs = load_module("probe_run_inputs", "resident-runtime/manifest_directed_run_inputs.py")

    def test_a_request_without_a_supplied_epoch_fails_closed_with_six_fields(self):
        cases = (({}, "", "HB_EPOCH_NOT_SUPPLIED"), ({"hb_epoch": "+33"}, "", "HB_EPOCH_INVALID"),
                 ({"hb_epoch": 31}, "", "HB_EPOCH_INVALID"), ({}, "abc", "HB_EPOCH_INVALID"),
                 ({"hb_epoch": "4096"}, "4097", "HB_EPOCH_INVALID"))
        for request, dispatch, code in cases:
            with self.subTest(request=request, dispatch=dispatch):
                refused = self.inputs.request_epoch(dispatch, request, "entry")
                self.assertEqual((refused["disposition"], refused["failure_code"]), ("FAIL_CLOSED", code))
                for field in SIX_FIELDS:
                    self.assertTrue(refused[field], field)

    def test_the_request_or_the_dispatch_supplies_it(self):
        for request, dispatch, source in (({"hb_epoch": 4096}, "", "COMMITTED_REQUEST"),
                                          ({}, "4096", "WORKFLOW_DISPATCH"),
                                          ({"hb_epoch": "4096"}, "4096", "WORKFLOW_DISPATCH")):
            with self.subTest(request=request, dispatch=dispatch):
                resolved = self.inputs.request_epoch(dispatch, request, "entry")
                self.assertEqual((resolved["disposition"], resolved["hb_epoch"], resolved["source"]),
                                 ("ALLOW", "4096", source))
                digest = "sha256:" + __import__("hashlib").sha256(json.dumps(
                    request, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
                self.assertEqual(resolved["hb_epoch_source"], {"source": source, "request_sha256": digest})

    def test_a_governance_return_request_without_an_epoch_is_refused_before_anything_runs(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / ".stegverse/governance-return-requests/r.json"
            path.parent.mkdir(parents=True)
            request = {"schema": self.inputs.RETURN_REQUEST_SCHEMA, "owning_existing_goal": "G",
                       "mesh_root": "git+a#refs/m", "peer_mesh": "git+b#refs/m"}
            path.write_text(json.dumps(request))
            cwd = os.getcwd()
            os.chdir(work)
            try:
                refused = self.inputs.governance_return_inputs({}, [".stegverse/governance-return-requests/r.json"])
                path.write_text(json.dumps({**request, "hb_epoch": "4096"}))
                allowed = self.inputs.governance_return_inputs({}, [".stegverse/governance-return-requests/r.json"])
            finally:
                os.chdir(cwd)
        self.assertEqual((refused["disposition"], refused["failure_code"]), ("FAIL_CLOSED", "HB_EPOCH_NOT_SUPPLIED"))
        for field in SIX_FIELDS:
            self.assertTrue(refused[field], field)
        self.assertEqual((allowed["disposition"], allowed["hb_epoch"]), ("ALLOW", "4096"))


def workflow_triggers(path):
    import re
    text = path.read_text(encoding="utf-8")
    on = text.split("\non:\n", 1)[1].split("\n\n", 1)[0] if "\non:\n" in text else ""
    return {name for name in ("push", "schedule", "workflow_dispatch", "pull_request")
            if re.search(r"^  " + name + r":", on, re.M)}, text


class WorkflowTriggerProbeTests(unittest.TestCase):
    """No push or schedule trigger reaches an epoch-requiring production entrypoint without a gate first."""

    def test_the_resident_entrypoints_are_dispatched_in_tree_and_only_by_dispatch(self):
        manifest = json.loads((ROOT / "resident-runtime/activation-manifest.json").read_text())
        binding = manifest["epoch_binding"]
        self.assertEqual(binding["entrypoints"], ["resident-runtime/resident_executor.py",
                                                  "resident-runtime/federation_cycle.py"])
        self.assertEqual((binding["hb_epoch"], binding["clock_fallback"]), ("SUPPLIED_BY_DISPATCH", "NONE"))
        self.assertEqual(binding["runtime_dispatcher"]["status"], "PENDING_SUBSTRATE")
        self.assertIs(binding["accepts_carried_crossings"], False)
        self.assertIs(org.kernel.ACCEPTS_CARRIED_CROSSINGS, binding["accepts_carried_crossings"])
        for record in binding["open_records"]:
            with self.subTest(open_record=record["failure_code"]):
                self.assertEqual(record["state"], "OPEN")
                for field in SIX_FIELDS:
                    self.assertTrue(record[field], field)
        self.assertEqual({r["failure_code"] for r in binding["open_records"]},
                         {"MERGE_TRANSFER_PROVENANCE_PENDING_206", "PROPAGATE_MISSING_LEDGER_ROOT_IS_SILENT",
                          "IDENTICAL_REQUEST_AT_TWO_EPOCHS_ANSWERED_TWICE",
                          "DIRECT_KERNEL_CONSUME_STAMPS_THE_FRAME_EPOCH", "KERNEL_LEGACY_DIRECT_CALL_PATHS"})
        pending, = [r for r in binding["open_records"] if r["failure_code"] == "MERGE_TRANSFER_PROVENANCE_PENDING_206"]
        self.assertEqual((pending["state"], pending["owning_existing_goal"]), ("OPEN", "StegVerse-org/.github#206"))
        for field in SIX_FIELDS:
            self.assertTrue(pending[field], field)
        dispatcher = ROOT / binding["dispatcher"]
        self.assertTrue(dispatcher.is_file())
        triggers, text = workflow_triggers(dispatcher)
        self.assertEqual(triggers, {"workflow_dispatch"})
        gate = text.index("Gate the supplied epoch before any entrypoint")
        self.assertLess(gate, text.index("resident-runtime/resident_dispatch.py"))
        names = [(w, step) for w, step, _ in workflow_epoch_gates()]
        self.assertIn(("resident-runtime-dispatch.yml", "Gate the supplied epoch before any entrypoint"), names)
        # Nothing else triggers the resident entrypoints. (The push-triggered
        # governance return is gated on its request's own epoch, tested below.)
        for path in sorted(WORKFLOWS.glob("*.yml")):
            triggers, text = workflow_triggers(path)
            if triggers & {"push", "schedule"}:
                for entrypoint in ("resident_executor.py", "resident_dispatch.py", "federation_cycle.py"):
                    self.assertNotIn("python resident-runtime/" + entrypoint, text, path.name)

    def test_push_triggered_production_writers_resolve_the_request_epoch_first(self):
        _, transition = workflow_triggers(WORKFLOWS / "organization-ledger-transition.yml")
        loop = transition.split('while IFS= read -r request; do', 1)[1]
        self.assertLess(loop.index("manifest_directed_run_inputs.py request-epoch"),
                        loop.index("from stegverse.manifest_builder import build_manifest"))
        self.assertIn('epoch_args=(--hb-epoch "$request_epoch" --hb-epoch-source-json "$epoch_source")', loop)
        self.assertIn("Fail a run whose committed request carried no supplied epoch", transition)
        _, ret = workflow_triggers(WORKFLOWS / "organization-governance-return.yml")
        self.assertLess(ret.index("--dispatch-hb-epoch"), ret.index("python resident-runtime/peer_mesh_intake.py"))
        self.assertIn('--hb-epoch "$RETURN_HB_EPOCH"', ret)
        self.assertIn('--hb-epoch-source-json "$RETURN_HB_EPOCH_SOURCE_JSON"', ret)
        self.assertNotIn("schedule:", transition + ret)


class ResidentDispatchTests(unittest.TestCase):
    """B-P36n: the in-tree dispatcher gates first and hands each entrypoint the supplied epoch."""

    def setUp(self):
        self.dispatch = load_module("probe_resident_dispatch", "resident-runtime/resident_dispatch.py")

    def test_an_absent_or_invalid_epoch_is_refused_and_nothing_runs(self):
        for epoch, code in ((None, "HB_EPOCH_NOT_SUPPLIED"), ("", "HB_EPOCH_NOT_SUPPLIED"), ("+33", "HB_EPOCH_INVALID")):
            with self.subTest(epoch=epoch):
                refused = self.dispatch.dispatch(hb_epoch=epoch, mesh_root="m", node_state_root="n",
                                                 run=mock.Mock(side_effect=AssertionError("ran")))
                self.assertEqual((refused["disposition"], refused["failure_code"]), ("FAIL_CLOSED", code))
                for field in SIX_FIELDS:
                    self.assertTrue(refused[field], field)

    def test_the_manifest_is_not_runtime_authority_so_the_substrate_is_pending_and_nothing_is_executed(self):
        result = self.dispatch.dispatch(hb_epoch="4096", mesh_root="m", node_state_root="n",
                                        run=mock.Mock(side_effect=AssertionError("ran")))
        self.assertEqual((result["disposition"], result["executed"]), ("ALLOW", False))
        self.assertEqual([i["entrypoint"] for i in result["invocations"]],
                         ["resident-runtime/resident_executor.py", "resident-runtime/federation_cycle.py"])
        for invocation in result["invocations"]:
            argv = invocation["argv"]
            self.assertEqual(argv[argv.index("--hb-epoch") + 1], "4096")
        pending = result["runtime_dispatcher"]
        self.assertEqual((pending["failure_code"], pending["state"], pending["status"], pending["line"], pending["blocking"]),
                         ("MANIFEST_DISPATCHER_PROHIBITED_ON_HOSTED", "OPEN", "PENDING_SUBSTRATE",
                          "RUNTIME_DISPATCHER_PENDING_SUBSTRATE", False))
        self.assertEqual(pending["owning_existing_goal"], "WU-B13 activation (StegVerse-Labs/.github#3183)")
        self.assertEqual(pending["next_attempt"], "the canonical runtime substrate dispatcher")
        for field in SIX_FIELDS:
            self.assertTrue(pending[field], field)
        # The prohibition the record names is real in the tree.
        executor = (ROOT / "resident-runtime/resident_executor.py").read_text()
        self.assertIn('HOSTED=("GITHUB_ACTIONS","CI"', executor)
        self.assertIn('raise SystemExit("hosted runtime prohibited: "', executor)

    def test_a_runtime_authority_runs_the_executor_with_the_supplied_epoch(self):
        manifest = json.loads((ROOT / "resident-runtime/activation-manifest.json").read_text())
        run = mock.Mock(return_value=mock.Mock(returncode=0))
        result = self.dispatch.dispatch(hb_epoch="4096", mesh_root="m", node_state_root="n",
                                        manifest={**manifest, "github_actions_is_runtime_authority": True}, run=run)
        self.assertEqual((result["disposition"], result["executed"]), ("ALLOW", True))
        argv = run.call_args[0][0]
        self.assertTrue(argv[1].endswith("resident_executor.py"))
        self.assertEqual(argv[argv.index("--hb-epoch") + 1], "4096")


SDK_IMPORTING_CLIS = ("resident-runtime/governance_decision_return.py",
                      "resident-runtime/organization_manifest_ingress.py")


class WriterCliTraceTests(unittest.TestCase):
    """F-WRITER-TRACE / B-P36q: a writer CLI whose own write faults prints six fields, no traceback;
    the same invocation run again completes exactly once."""

    FAULT = ROOT / "tests/fixtures/write-fault"

    def run_cli(self, work, command, env_extra, mode="STEGVERSE_TEST_FAULT_HEAD_ONCE"):
        env = {k: v for k, v in os.environ.items() if not k.startswith("STEGVERSE_")}
        env.update(env_extra, PYTHONPATH=str(self.FAULT))
        env[mode] = str(Path(work) / "faulted")
        return subprocess.run([sys.executable, *command], capture_output=True, text=True, cwd=str(ROOT), env=env)

    def assert_fault_then_once(self, work, command, env_extra, ledger, mode="STEGVERSE_TEST_FAULT_HEAD_ONCE"):
        faulted = self.run_cli(work, command, env_extra, mode)
        self.assertTrue((Path(work) / "faulted").exists(), "the HEAD write was not reached")
        self.assertEqual(faulted.returncode, 75, faulted.stdout + faulted.stderr)
        self.assertNotIn("Traceback", faulted.stderr)
        record = json.loads(faulted.stdout.strip().splitlines()[-1])
        self.assertEqual((record["failure_code"], record["terminal"]), ("WRITE_FAILED", False))
        for field in SIX_FIELDS:
            self.assertTrue(record[field], field)
        self.assertNotIn("nothing was written", record["next_attempt"])
        again = self.run_cli(work, command, env_extra, mode)
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        receipts = sorted((Path(ledger) / "receipts").glob("*.json"))
        self.assertEqual(len(receipts), 1)
        head = json.loads((Path(ledger) / "HEAD.json").read_text())
        self.assertEqual(head["receipt_sha256"][7:] + ".json", receipts[0].name)
        # The retry returns the recorded receipt itself.
        self.assertEqual(json.loads(again.stdout.strip().splitlines()[-1])["receipt_sha256"], head["receipt_sha256"])

    def emit_command(self):
        return [str(EMIT), "--transition-id", "t-fault", "--transition-class", "TEST",
                "--predecessor-state-sha256", STATE_BEFORE, "--successor-state-sha256", STATE_AFTER,
                "--hb-epoch", str(EPOCH), "--evidence-json", '{"k": 1}']

    def org_command(self, work):
        source = Path(work) / "repo-receipt.json"
        source.write_text(json.dumps(repo_receipt("t-org-fault")))
        return [str(ROOT / "resident-runtime/aggregate_repo_transition.py"), "--repo-receipt", str(source),
                "--predecessor-org-state-sha256", "GENESIS", "--successor-org-state-sha256", STATE_AFTER,
                "--hb-epoch", str(EPOCH)]

    def test_a_fault_after_head_is_committed_is_retried_into_the_recorded_receipt(self):
        """F-POST-HEAD: HEAD was replaced, then a durability step failed; the rerun mints nothing new."""
        for name, ledger_var in (("repo", "STEGVERSE_REPO_LEDGER_ROOT"), ("org", "STEGVERSE_ORG_LEDGER_ROOT")):
            with self.subTest(writer=name), tempfile.TemporaryDirectory() as work:
                ledger = Path(work) / name
                command = self.emit_command() if name == "repo" else self.org_command(work)
                self.assert_fault_then_once(work, command, {ledger_var: str(ledger)}, ledger,
                                            mode="STEGVERSE_TEST_FAULT_AFTER_HEAD_ONCE")

    def test_an_exact_rerun_returns_the_recorded_receipt_and_another_transition_collides(self):
        with tempfile.TemporaryDirectory() as work:
            ledger = Path(work) / "repo"
            env = {k: v for k, v in os.environ.items() if not k.startswith("STEGVERSE_")}
            env["STEGVERSE_REPO_LEDGER_ROOT"] = str(ledger)
            first, second = (subprocess.run([sys.executable, *self.emit_command()], capture_output=True, text=True,
                                            cwd=str(ROOT), env=env) for _ in range(2))
            self.assertEqual((first.returncode, second.returncode), (0, 0))
            self.assertEqual(len(list((ledger / "receipts").glob("*.json"))), 1)
            other = [*self.emit_command()[:-1], '{"k": 2}']
            collided = subprocess.run([sys.executable, *other], capture_output=True, text=True, cwd=str(ROOT), env=env)
            self.assertEqual(collided.returncode, 1)
            self.assertNotIn("Traceback", collided.stderr)
            record = json.loads(collided.stdout.strip().splitlines()[-1])
            self.assertEqual((record["failure_code"], record["terminal"]), ("LEDGER_RECEIPT_COLLISION", True))
            self.assertEqual(len(list((ledger / "receipts").glob("*.json"))), 1)

    def test_an_unusable_input_file_is_terminal_and_writes_nothing(self):
        """F-INPUT-TRACE: a missing, non-JSON, non-UTF-8, directory or non-object input; six fields, terminal."""
        clis = {"resident-runtime/aggregate_repo_transition.py": ["--repo-receipt"],
                "resident-runtime/governance_decision_return.py": ["--manifest"],
                "resident-runtime/intr_destination_ingress.py": ["--payload", "--registry"],
                "resident-runtime/organization_egress_boundary.py": ["--payload", "--standing"],
                "resident-runtime/organization_manifest_ingress.py": ["--manifest", "--registry", "--standing"],
                "resident-runtime/submit_org_transition_to_master_records.py": ["--org-receipt", "--standing"]}
        with tempfile.TemporaryDirectory() as work:
            bad = {"missing": Path(work) / "absent.json", "directory": Path(work)}
            for name, content in (("not-json", b"{not json"), ("not-utf8", b"\xff\xfe{}"), ("a-list", b"[1,2,3]")):
                bad[name] = Path(work) / (name + ".json")
                bad[name].write_bytes(content)
            ledgers = Path(work) / "ledgers"
            env = {k: v for k, v in os.environ.items() if not k.startswith("STEGVERSE_")}
            env.update(STEGVERSE_REPO_LEDGER_ROOT=str(ledgers / "repo"), STEGVERSE_ORG_LEDGER_ROOT=str(ledgers / "org"))
            # Two of these import the pinned SDK at module load; a workflow that does not
            # install it cannot start them at all, so they are exercised where it is.
            sdk_present = importlib.util.find_spec("stegverse") is not None
            for cli, flags in clis.items():
                if cli in SDK_IMPORTING_CLIS and not sdk_present:
                    continue
                for flag in flags:
                    for label, path in bad.items():
                        with self.subTest(cli=cli, flag=flag, input=label):
                            completed = subprocess.run([sys.executable, str(ROOT / cli), flag, str(path)],
                                                       capture_output=True, text=True, cwd=str(ROOT), env=env)
                            self.assertNotEqual(completed.returncode, 0)
                            self.assertNotIn("Traceback", completed.stderr)
                            record = json.loads(completed.stdout.strip().splitlines()[-1])
                            self.assertIs(record["terminal"], True)
                            self.assertIn(record["failure_code"], ("INPUT_UNREADABLE", "INPUT_INVALID"))
                            for field in SIX_FIELDS:
                                self.assertTrue(record[field], field)
            self.assertFalse(ledgers.exists())

    def test_the_repository_emitter(self):
        with tempfile.TemporaryDirectory() as work:
            ledger = Path(work) / "repo"
            self.assert_fault_then_once(work, self.emit_command(), {"STEGVERSE_REPO_LEDGER_ROOT": str(ledger)}, ledger)

    def test_the_organization_writer(self):
        with tempfile.TemporaryDirectory() as work:
            ledger = Path(work) / "org"
            self.assert_fault_then_once(work, self.org_command(work), {"STEGVERSE_ORG_LEDGER_ROOT": str(ledger)}, ledger)

    def test_every_writer_cli_runs_through_the_six_field_wrapper(self):
        for relative in (".stegverse/transition-ledger/emit.py", "resident-runtime/aggregate_repo_transition.py",
                         "resident-runtime/federation_cycle.py", "resident-runtime/governance_decision_return.py",
                         "resident-runtime/governance_return_cycle.py", "resident-runtime/intr_destination_ingress.py",
                         "resident-runtime/organization_egress_boundary.py",
                         "resident-runtime/organization_manifest_ingress.py",
                         "resident-runtime/propagate_repository_receipts.py", "resident-runtime/resident_dispatch.py",
                         "resident-runtime/resident_executor.py",
                         "resident-runtime/submit_org_transition_to_master_records.py"):
            with self.subTest(cli=relative):
                main_block = (ROOT / relative).read_text().split('__name__', )[-1]
                self.assertIn("_writer.run(", main_block)

    def test_the_wrapper_classifies_each_failure(self):
        writer = load_module("probe_writer_cli", "resident-runtime/writer_cli.py")
        cases = ((OSError(5, "io"), "WRITE_FAILED", 75), (RuntimeError("ledger_append_lost_comparison"), "WRITE_FAILED", 75),
                 (ValueError("ledger_receipt_collision"), "LEDGER_RECEIPT_COLLISION", 1),
                 (SystemExit("ORG_LEDGER_APPEND_CONTENTION_EXHAUSTED"), "WRITE_FAILED", 75),
                 (SystemExit("ORG_LEDGER_HEAD_INVALID"), "ORG_LEDGER_HEAD_INVALID", 1),
                 (KeyError("manifest"), "WRITER_INPUT_REFUSED", 1))
        for exc, code, exit_code in cases:
            with self.subTest(exc=type(exc).__name__), contextlib.redirect_stdout(io.StringIO()) as out, \
                    contextlib.redirect_stderr(io.StringIO()):
                def failing():
                    raise exc
                self.assertEqual(writer.run(failing, "entry"), exit_code)
                record = json.loads(out.getvalue().splitlines()[-1])
                self.assertEqual(record["failure_code"], code)
                for field in SIX_FIELDS:
                    self.assertTrue(record[field], field)
        with self.assertRaises(SystemExit) as passed:
            writer.run(lambda: (_ for _ in ()).throw(SystemExit(2)), "entry")
        self.assertEqual(passed.exception.code, 2)


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
