"""ledger_gitstore: public readers and an operation-parametric two-level append on this org's writer surface.

Temp ledgers are the pinned published tip rebuilt from
tests/fixtures/merge-transfer-gitstore/ledger-snapshot.json (TempLedger of
tests/test_merge_transfer_gitstore.py); nothing touches the published ref.
Appended packets are SYNTHETIC_NOT_LEDGERED.
"""
from __future__ import annotations

import importlib.util
import inspect
import os
import sys
import unittest
from pathlib import Path

try:
    import pytest
    pytestmark = pytest.mark.repository_ledger_locus
except (ImportError, AttributeError):
    pass

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = _load("test_merge_transfer_gitstore_for_ledger_gitstore", "tests/test_merge_transfer_gitstore.py")
lg = _load("ledger_gitstore_under_test", "resident-runtime/ledger_gitstore.py")
TempLedger, PIN, SYNTHETIC = base.TempLedger, base.PIN, base.SYNTHETIC
OPERATIONS = (("ORGANIZATION_INTR_PATH_TRANSFER", "intr-path-transfer"),
              ("ORGANIZATION_INTR_DESTINATION_INGRESS", "intr-destination"))


def evidence(n: int) -> dict:
    return {"payload_sha256": lg.sha({"synthetic": n}), "disposition": "ALLOW", "communication_id": "cid-%d" % n,
            "label": "SYNTHETIC_NOT_LEDGERED"}


class Readers(unittest.TestCase):
    def test_the_public_readers_are_what_verify_merge_transfer_reads(self):
        with TempLedger() as ledger:
            organization, repository = lg.org_store(), lg.repo_store()
            self.assertEqual(organization.tip, ledger.tip())
            epoch, failed = lg.head_epoch(organization)
            self.assertIsNone(failed)
            self.assertIsInstance(epoch, int)
            result = lg.verify_merge_transfer(PIN["repository"], PIN["real_commit"]["merge_commit"],
                                              organization, repository)
            self.assertEqual(result["disposition"], PIN["real_state_at_ledger_tip"]["disposition"])
            named = lg.org_store(git_dir=ledger.git_dir, ref=ledger.ref)
            self.assertEqual(named.get("HEAD.json"), organization.get("HEAD.json"))

    def test_an_unbound_location_raises_with_six_fields(self):
        saved = {k: base.os.environ.pop(k, None) for k in base.ENV_KEYS}
        try:
            with self.assertRaises(lg.LedgerLocationUnbound) as caught:
                lg.org_store()
            for field in lg.SIX_FIELDS:
                self.assertTrue(caught.exception.refusal[field], field)
        finally:
            for k, v in saved.items():
                if v is not None:
                    base.os.environ[k] = v


class Append(unittest.TestCase):
    def test_each_operation_appends_a_sealed_pair_on_this_org_s_surface(self):
        for n, (operation, profile) in enumerate(OPERATIONS):
            with TempLedger() as ledger:
                epoch, _ = lg.head_epoch(lg.org_store())
                before = ledger.files()
                appended, replayed = lg.append(operation, "path-%d@cid-%d" % (n, n), evidence(n), epoch,
                                               operation=operation, profile_id=profile,
                                               boundary_extra={"path_id": "path-%d" % n, "transfer_commit": "a" * 40})
                self.assertFalse(replayed)
                self.assertEqual(appended["writer_surface"], PIN["writer_surface"])
                org, rep = appended["organization_receipt"], appended["repository_receipt"]
                self.assertTrue(lg.sealed(org) and lg.sealed(rep))
                self.assertEqual(appended["organization_receipt_sha256"], org["receipt_sha256"])
                self.assertEqual(appended["repository_receipt_sha256"], rep["receipt_sha256"])
                self.assertEqual(org["repo_receipt_sha256"], rep["receipt_sha256"])
                self.assertEqual(org["boundary_evidence"]["operation"], operation)
                self.assertEqual(org["boundary_evidence"]["profile_id"], profile)
                self.assertEqual(org["boundary_evidence"]["path_id"], "path-%d" % n)
                self.assertEqual(rep["transition_id"], operation + ":path-%d@cid-%d" % (n, n))
                self.assertEqual(rep["transition_class"], operation)
                self.assertEqual(rep["evidence"], evidence(n))
                self.assertEqual(org["hb_reference"]["epoch"], epoch)
                self.assertIs(org["hb_reference"]["derived_from_clock"], False)
                after = ledger.files()
                for name, data in before.items():
                    if not name.endswith("HEAD.json"):
                        self.assertEqual(after[name], data, name)
                organization, repository = lg.org_store(), lg.repo_store()
                self.assertEqual(organization.get("HEAD.json")["receipt_sha256"], org["receipt_sha256"])
                self.assertEqual(organization.get(lg.source_key(rep["receipt_sha256"])),
                                 repository.get(lg.receipt_key(rep["receipt_sha256"])))
                tip = ledger.tip()
                again, replayed = lg.append(operation, "path-%d@cid-%d" % (n, n), evidence(n), epoch,
                                            operation=operation, profile_id=profile,
                                            boundary_extra={"path_id": "path-%d" % n, "transfer_commit": "a" * 40})
                self.assertTrue(replayed)
                self.assertEqual(again["organization_receipt_sha256"], org["receipt_sha256"])
                self.assertEqual(ledger.tip(), tip)

    def test_a_path_receipt_can_link_the_main_merge_transfer_receipt(self):
        with TempLedger() as ledger:
            transfer = base.g.append_merge_transfer(SYNTHETIC)
            self.assertEqual(transfer["disposition"], "ALLOW", transfer)
            epoch, _ = lg.head_epoch(lg.org_store())
            linked = {**evidence(7), "merge_transfer_organization_receipt_sha256": transfer["organization_receipt_sha256"]}
            appended, _ = lg.append("ORGANIZATION_INTR_PATH_TRANSFER", "p@cid-7", linked, epoch,
                                    operation="ORGANIZATION_INTR_PATH_TRANSFER", profile_id="intr-path-transfer")
            org = appended["organization_receipt"]
            self.assertEqual(org["previous_receipt_sha256"], transfer["organization_receipt_sha256"])
            chain = [d for d, _ in lg.org_chain(lg.org_store())]
            self.assertEqual(chain[:2], [org["receipt_sha256"], transfer["organization_receipt_sha256"]])
            verified = lg.verify_merge_transfer(PIN["repository"], SYNTHETIC["merge_commit"], lg.org_store(),
                                                lg.repo_store())
            self.assertEqual(verified["disposition"], "ALLOW", verified)

    def test_a_different_body_under_a_recorded_id_is_a_collision_and_writes_nothing(self):
        with TempLedger() as ledger:
            epoch, _ = lg.head_epoch(lg.org_store())
            kw = dict(operation="ORGANIZATION_INTR_PATH_TRANSFER", profile_id="intr-path-transfer")
            lg.append("ORGANIZATION_INTR_PATH_TRANSFER", "p@cid-1", evidence(1), epoch, **kw)
            tip = ledger.tip()
            with self.assertRaises(ValueError) as caught:
                lg.append("ORGANIZATION_INTR_PATH_TRANSFER", "p@cid-1", {**evidence(1), "disposition": "DENY"},
                          epoch, **kw)
            self.assertEqual(str(caught.exception), "ledger_receipt_collision")
            self.assertEqual(ledger.tip(), tip)

    def test_missing_operation_or_evidence_fields_are_refused_before_any_write(self):
        with TempLedger() as ledger:
            tip = ledger.tip()
            for kw, ev in ((dict(operation="", profile_id="x"), evidence(1)),
                           (dict(operation="X", profile_id=""), evidence(1)),
                           (dict(operation="X", profile_id="x"), {"disposition": "ALLOW"})):
                with self.assertRaises(ValueError):
                    lg.append("X", "p", ev, 100, **kw)
            self.assertEqual(ledger.tip(), tip)


class Ingress(unittest.TestCase):
    """This org's intr_destination_ingress exposes the shared append surface with unchanged defaults."""

    def test_the_ingress_append_takes_the_operation_with_unchanged_defaults(self):
        ingress = _load("intr_destination_ingress_for_ledger_gitstore", "resident-runtime/intr_destination_ingress.py")
        signature = inspect.signature(ingress._append)
        self.assertEqual(signature.parameters["operation"].default, ingress.OPERATION_ID)
        self.assertEqual(signature.parameters["profile_id"].default, ingress.PROFILE_ID)
        self.assertIsNone(signature.parameters["boundary_extra"].default)
        for name in ("operation", "profile_id", "boundary_extra"):
            self.assertEqual(signature.parameters[name].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertTrue(hasattr(ingress, "repository_ledger") and hasattr(ingress, "organization_ledger"))

    def test_the_ingress_append_and_ledger_gitstore_append_write_the_same_pair(self):
        ingress = _load("intr_destination_ingress_for_ledger_gitstore_b", "resident-runtime/intr_destination_ingress.py")
        bodies = []
        for writer in ("ingress", "ledger_gitstore"):
            with TempLedger():
                epoch, _ = lg.head_epoch(lg.org_store())
                kw = dict(operation="ORGANIZATION_INTR_PATH_TRANSFER", profile_id="intr-path-transfer",
                          boundary_extra={"path_id": "p"})
                if writer == "ingress":
                    appended, _ = ingress._append("ORGANIZATION_INTR_PATH_TRANSFER", "p@cid-3", evidence(3), epoch, **kw)
                else:
                    appended, _ = lg.append("ORGANIZATION_INTR_PATH_TRANSFER", "p@cid-3", evidence(3), epoch, **kw)
                strip = lambda r: {k: v for k, v in r.items() if k not in ("receipt_sha256", "observed_at")}
                bodies.append((appended["repository_receipt"], strip(appended["organization_receipt"])))
        self.assertEqual(bodies[0][0], bodies[1][0])
        self.assertEqual(bodies[0][1], bodies[1][1])


# -- all or nothing: preflight before either half, rollback after the repository half ----------

WRONG_REF = "refs/stegverse/not-the-organization-ledger"
ingress = _load("intr_destination_ingress_for_ledger_gitstore_atomic", "resident-runtime/intr_destination_ingress.py")


def org_writer_name(surface) -> str:
    return {"DUAL_LEDGER": "append_organization", "AGGREGATE_TRANSITION": "aggregate_transition",
            "TWO_MODULE_APPEND": "append"}[surface.kind]


def ingress_org_writer():
    """(module, attribute) of the organization writer this checkout's ingress _append calls."""
    source = inspect.getsource(ingress._append_halves)
    if "ledger.append_organization(" in source:
        return ingress.ledger, "append_organization"
    if "organization_ledger.aggregate_transition(" in source:
        return ingress.organization_ledger, "aggregate_transition"
    return ingress.organization_ledger, "append"


class Atomic(unittest.TestCase):
    def tips(self, ledger) -> tuple:
        return tuple(ledger._git("rev-parse", "--verify", "-q", ref).strip() for ref in (ledger.ref, WRONG_REF))

    def assertUntouched(self, ledger, before):
        self.assertEqual(self.tips(ledger), before)

    def path_append(self, n, **kw):
        epoch, _ = lg.head_epoch(lg.org_store())
        return lg.append("ORGANIZATION_INTR_PATH_TRANSFER", "p@cid-%d" % n, evidence(n), epoch,
                         operation="ORGANIZATION_INTR_PATH_TRANSFER", profile_id="intr-path-transfer", **kw)

    def ingress_append(self, n):
        epoch, _ = lg.head_epoch(lg.org_store())
        return ingress._append("ORGANIZATION_INTR_PATH_TRANSFER", "i@cid-%d" % n, evidence(n), epoch,
                               operation="ORGANIZATION_INTR_PATH_TRANSFER", profile_id="intr-path-transfer")

    def test_a_wrong_organization_ref_refuses_before_either_half_is_written(self):
        for variable_set in ("root_and_git_ref", "git_ref_only"):
            for writer in ("ledger_gitstore", "ingress"):
                with self.subTest(variables=variable_set, writer=writer), TempLedger() as ledger:
                    ledger._git("update-ref", WRONG_REF, ledger.tip())
                    os.environ["STEGVERSE_ORG_LEDGER_GIT_REF"] = WRONG_REF
                    if variable_set == "root_and_git_ref":
                        os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = "git+" + ledger.git_dir + "#" + WRONG_REF
                    elif lg.writer_surface().kind != "AGGREGATE_TRANSITION":
                        continue  # only the aggregate_transition writer reads STEGVERSE_ORG_LEDGER_GIT_REF
                    before = self.tips(ledger)
                    with self.assertRaises(ValueError) as caught:  # TwoLevelAppendRefused of either module copy
                        self.path_append(1) if writer == "ledger_gitstore" else self.ingress_append(1)
                    self.assertEqual(type(caught.exception).__name__, "TwoLevelAppendRefused")
                    self.assertEqual(caught.exception.refusal["failure_code"], lg.PREFLIGHT_REFUSED)
                    for field in lg.SIX_FIELDS:
                        self.assertTrue(caught.exception.refusal[field], field)
                    self.assertUntouched(ledger, before)

    def test_a_wrong_repository_ref_refuses_before_either_half_is_written(self):
        for writer in ("ledger_gitstore", "ingress"):
            with self.subTest(writer=writer), TempLedger() as ledger:
                ledger._git("update-ref", WRONG_REF, ledger.tip())
                os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = "git+" + ledger.git_dir + "#" + WRONG_REF + ":" + ledger.ns
                before = self.tips(ledger)
                with self.assertRaises(ValueError) as caught:
                    self.path_append(2) if writer == "ledger_gitstore" else self.ingress_append(2)
                self.assertEqual(type(caught.exception).__name__, "TwoLevelAppendRefused")
                # refused by the contract check, or already by this checkout's own repository store binding
                self.assertIn(caught.exception.refusal["failed_predicate"],
                              ("REPOSITORY_LEDGER_REF_IS_THE_DECLARED_REF", "REPOSITORY_LEDGER_LOCATION_RESOLVES"))
                self.assertEqual(caught.exception.refusal["failure_code"], lg.PREFLIGHT_REFUSED)
                self.assertUntouched(ledger, before)

    def test_an_organization_write_failing_after_the_repository_write_rolls_the_repository_half_back(self):
        for failure in (ValueError("organization writer refused"), SystemExit(3)):
            for writer in ("ledger_gitstore", "ingress", "merge_transfer"):
                with self.subTest(failure=repr(failure), writer=writer), TempLedger() as ledger:
                    ledger._git("update-ref", WRONG_REF, ledger.tip())
                    before = self.tips(ledger)
                    seen = []

                    def fail(*args, **kwargs):
                        seen.append(ledger.tip())  # the repository half has already moved the ref
                        raise failure

                    surface = lg.writer_surface()
                    module, name = (ingress_org_writer() if writer == "ingress"
                                    else ((surface.dual if surface.kind == "DUAL_LEDGER" else surface.aggregate),
                                          org_writer_name(surface)))
                    original = getattr(module, name)
                    setattr(module, name, fail)
                    try:
                        if writer == "merge_transfer":
                            result = lg.append_merge_transfer(SYNTHETIC, surface=surface)
                            self.assertEqual(result["disposition"], "FAIL_CLOSED", result)
                        else:
                            with self.assertRaises(type(failure)):
                                if writer == "ledger_gitstore":
                                    self.path_append(3, surface=surface)
                                else:
                                    self.ingress_append(3)
                    finally:
                        setattr(module, name, original)
                    self.assertEqual(len(seen), 1)
                    self.assertNotEqual(seen[0], before[0], "the repository half wrote before the failure")
                    self.assertUntouched(ledger, before)

    def test_a_rollback_never_undoes_another_writers_commits(self):
        with TempLedger() as ledger:
            surface = lg.writer_surface()
            module = surface.dual if surface.kind == "DUAL_LEDGER" else surface.aggregate
            name = org_writer_name(surface)
            original = getattr(module, name)

            def fail_after_foreign_appends(*args, **kwargs):
                for n in range(2):
                    ledger.write({"foreign-%d.txt" % n: b"another writer"})
                raise ValueError("organization writer refused")

            setattr(module, name, fail_after_foreign_appends)
            try:
                with self.assertRaises(lg.TwoLevelAppendRefused) as caught:
                    self.path_append(4, surface=surface)
            finally:
                setattr(module, name, original)
            self.assertEqual(caught.exception.refusal["failure_code"], lg.ROLLBACK_FAILED)
            self.assertIn("foreign-1.txt", ledger.files())

    def test_the_guarded_append_still_appends_and_replays(self):
        with TempLedger() as ledger:
            first, replayed = self.path_append(5)
            tip = ledger.tip()
            again, replayed_again = self.path_append(5)
            self.assertEqual((replayed, replayed_again), (False, True))
            self.assertEqual(ledger.tip(), tip)
            self.assertEqual(first["organization_receipt_sha256"], again["organization_receipt_sha256"])


if __name__ == "__main__":
    unittest.main()
