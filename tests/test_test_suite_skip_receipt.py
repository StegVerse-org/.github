"""test_suite_skip_receipt.py: every skip on a head is listed and fails closed.

Synthetic JUnit XML in a temporary directory only. Nothing here is skipped.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "test_suite_skip_receipt", ROOT / "scripts" / "test_suite_skip_receipt.py")
receipt_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(receipt_module)
TVC_SPEC = importlib.util.spec_from_file_location(
    "tvc_conformance_receipt", ROOT / "resident-runtime" / "tvc_conformance_receipt.py")
tvc_module = importlib.util.module_from_spec(TVC_SPEC)
TVC_SPEC.loader.exec_module(tvc_module)
TVC_CONTRACT = json.loads(
    (ROOT / ".stegverse" / "verification-inputs" / "tvc-conformance-receipt.json").read_text(encoding="utf-8"))
SKIP_ITEMS = json.loads((ROOT / "data" / "test-suite-skip-items.json").read_text(encoding="utf-8"))["items"]

SIX = receipt_module.SIX


def junit(cases: str) -> str:
    return f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{cases}</testsuite></testsuites>'


PASS = '<testcase classname="tests.test_a" name="test_ok" time="0.1"/>'
SKIP = ('<testcase classname="tests.test_b.K" name="test_needs_x" time="0">'
        '<skipped type="pytest.skip" message="X is not installed">tests/test_b.py:12: X is not installed</skipped></testcase>')
FAIL = '<testcase classname="tests.test_c" name="test_bad"><failure message="boom"/></testcase>'
ERR = '<testcase classname="" name="tests.test_d"><error message="collection failure"/></testcase>'
XFAIL = '<testcase classname="tests.test_e" name="test_x"><skipped type="pytest.xfail" message="known"/></testcase>'


class SkipReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def build(self, cases: str, items=(), base_cases: str | None = None) -> dict:
        base = self.write("base.xml", junit(base_cases)) if base_cases is not None else None
        return receipt_module.build(self.write("head.xml", junit(cases)), "h" * 40, "retry",
                                    "goal", list(items), base, "b" * 40 if base else None)

    def test_zero_skipped_and_no_failure_is_allow(self):
        r = self.build(PASS)
        self.assertEqual(r["disposition"], "ALLOW")
        self.assertEqual(r["counts"]["skipped"], 0)
        self.assertEqual(r["refusals"], [])

    def test_a_skip_fails_closed_with_the_six_fields_and_is_listed_with_its_reason(self):
        r = self.build(PASS + SKIP)
        self.assertEqual(r["disposition"], "FAIL_CLOSED")
        self.assertEqual(r["counts"]["skipped"], 1)
        (ref,) = r["refusals"]
        self.assertEqual(ref["failure_code"], "TEST_SUITE_SKIPPED_ON_HEAD")
        self.assertEqual(set(ref), set(SIX))
        self.assertTrue(all(ref[k] for k in SIX))
        (row,) = r["skipped"]
        self.assertEqual(row["test"], "tests.test_b.K::test_needs_x")
        self.assertEqual(row["reason"], "X is not installed")
        self.assertEqual(row["location"], "tests/test_b.py:12")

    def test_an_unrecorded_skip_still_fails_closed_and_says_it_has_no_owner(self):
        row = self.build(SKIP)["skipped"][0]
        self.assertEqual(row["item"]["failure_code"], "TEST_SUITE_SKIP_UNCLASSIFIED")
        self.assertEqual(row["item"]["owning_existing_goal"], "UNRECORDED")

    def test_a_recorded_owner_item_never_converts_the_skip(self):
        item = dict(zip(SIX, ("C", "P", "R", "E", "G", "N")), test_prefix="tests.test_b.",
                    classification="K")
        r = self.build(SKIP, items=[item])
        self.assertEqual(r["disposition"], "FAIL_CLOSED")
        self.assertEqual(r["counts"]["skipped"], 1)
        self.assertEqual(r["skipped"][0]["item"]["owning_existing_goal"], "G")

    def test_xfail_is_listed_apart_from_skips(self):
        r = self.build(PASS + XFAIL)
        self.assertEqual((r["counts"]["skipped"], r["counts"]["xfailed"]), (0, 1))

    def test_failures_are_listed_but_not_judged_without_a_base(self):
        r = self.build(PASS + FAIL + ERR)
        self.assertEqual(r["disposition"], "ALLOW")
        self.assertEqual(r["failing_on_head"], ["tests.test_c::test_bad", "tests.test_d"])

    def test_a_failure_the_base_already_had_is_receipted_and_does_not_block(self):
        r = self.build(PASS + FAIL, base_cases=PASS + FAIL)
        self.assertEqual(r["disposition"], "ALLOW")
        self.assertEqual(r["pre_existing_on_base_not_blocking"], ["tests.test_c::test_bad"])
        self.assertEqual(r["new_failures_on_head"], [])

    def test_a_failure_the_base_did_not_have_fails_closed(self):
        r = self.build(PASS + FAIL, base_cases=PASS)
        self.assertEqual([x["failure_code"] for x in r["refusals"]], ["TEST_SUITE_NEW_FAILURE_ON_HEAD"])

    def test_an_unreadable_run_is_never_allow(self):
        bad = self.write("bad.xml", "<not-xml")
        r = receipt_module.build(bad, "h", "retry", "goal", [])
        self.assertEqual(r["disposition"], "FAIL_CLOSED")
        self.assertEqual(r["refusals"][0]["failure_code"], "TEST_SUITE_NOT_OBSERVED_ON_HEAD")
        missing = receipt_module.build(self.dir / "absent.xml", "h", "retry", "goal", [])
        self.assertEqual(missing["disposition"], "FAIL_CLOSED")

    def test_an_empty_run_is_never_allow(self):
        r = self.build("")
        self.assertEqual(r["refusals"][0]["failure_code"], "TEST_SUITE_NOT_OBSERVED_ON_HEAD")

    def test_main_writes_the_receipt_and_exits_nonzero_on_a_skip(self):
        out = self.dir / "r.json"
        rc = receipt_module.main(["--junit", str(self.write("j.xml", junit(SKIP))), "--head", "h",
                                  "--out", str(out), "--retry-entrypoint", "e", "--owning-goal", "g"])
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out.read_text())["counts"]["skipped"], 1)

    def test_the_receipt_is_deterministic(self):
        self.assertEqual(self.build(PASS + SKIP + FAIL), self.build(PASS + SKIP + FAIL))

    def selection(self, selected, not_selected=()):
        return {"selected_tests": list(selected), "not_selected_for_this_change": list(not_selected),
                "selected_because": {}, "changed_paths": [], "unmapped_changed_paths": []}

    def test_only_skips_in_the_selected_tests_fail_closed(self):
        head = self.write("head.xml", junit(PASS + SKIP))
        r = receipt_module.build(head, "h", "retry", "goal", [],
                                 selection=self.selection(["tests/test_a.py"], ["tests/test_b.py"]))
        self.assertEqual(r["disposition"], "ALLOW")
        self.assertEqual(r["counts"]["skipped"], 0)
        self.assertEqual(r["not_selected_for_this_change"], ["tests/test_b.py"])
        r = receipt_module.build(head, "h", "retry", "goal", [],
                                 selection=self.selection(["tests/test_a.py", "tests/test_b.py"]))
        self.assertEqual(r["refusals"][0]["failure_code"], "TEST_SUITE_SKIPPED_ON_HEAD")
        self.assertEqual(r["refusals"][0]["failed_predicate"], "SELECTED_TESTS_ON_EXACT_HEAD_ZERO_SKIPPED")

    def test_a_change_that_selects_nothing_runs_nothing_and_reports_no_pass(self):
        r = receipt_module.build(self.dir / "absent.xml", "h", "retry", "goal", [],
                                 selection=self.selection([], ["tests/test_a.py"]))
        self.assertEqual(r["disposition"], "ALLOW")
        self.assertEqual(r["counts"], {"tests": 0, "skipped": 0})
        self.assertNotIn("passed", r["counts"])

    def test_a_selected_module_that_fails_to_import_is_counted(self):
        r = receipt_module.build(self.write("h.xml", junit(ERR)), "h", "retry", "goal", [],
                                 selection=self.selection(["tests/test_d.py"]))
        self.assertEqual(r["failing_on_head"], ["tests.test_d"])


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canon(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sealed(body: dict) -> dict:
    body = {k: v for k, v in body.items() if k != "receipt_sha256"}
    return body | {"receipt_sha256": "sha256:" + hashlib.sha256(canon(body)).hexdigest()}


def write_ledger(root: Path, sources: list[dict]) -> None:
    """A POSIX organization ledger retaining the given source receipts, oldest first."""
    previous = None
    for i, source in enumerate(sources):
        source = sealed(source)
        (root / "source-receipts").mkdir(parents=True, exist_ok=True)
        (root / "source-receipts" / (source["receipt_sha256"][7:] + ".json")).write_text(json.dumps(source))
        org = sealed({"schema": "stegverse.organization-transition-receipt/v1", "authority_effect": "NONE",
                      "previous_receipt_sha256": previous, "source_transition_sha256": source["receipt_sha256"],
                      "source_receipt_schema": source.get("schema"), "source_transition_id": f"T{i}"})
        (root / "receipts").mkdir(parents=True, exist_ok=True)
        (root / "receipts" / (org["receipt_sha256"][7:] + ".json")).write_text(json.dumps(org))
        previous = org["receipt_sha256"]
    (root / "HEAD.json").write_text(json.dumps({"receipt_sha256": previous}))


TVC_FILE = "tests/test_origin_attestation_tvc_conformance.py"
TVC_CLASS = "tests.test_origin_attestation_tvc_conformance.TvcConformanceTests"
TVC_REASON = "TV/TVC is not checked out; set STEGVERSE_TVC_ROOT to run the conformance exchange."
TVC_ITEM = next(i for i in SKIP_ITEMS if i["failure_code"] == "TEST_SUITE_SKIP_TVC_SOURCE_PRIVATE")
RS_ITEM = next(i for i in SKIP_ITEMS if i["failure_code"] == "TEST_SUITE_SKIP_REPO_STANDARDS_PRIVATE_CROSS_ORG")


def skip_case(classname: str, name: str, reason: str) -> str:
    return (f'<testcase classname="{classname}" name="{name}">'
            f'<skipped type="unittest.skip" message="{reason}"/></testcase>')


class LedgerReceiptSatisfactionTests(unittest.TestCase):
    """#162 D2 option (d): only a sealed, push-sourced, surface-bound ledger receipt satisfies a private-input skip."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.head = self.dir / "head"
        self.surface = {"org-kernel/kernel.py": b"k = 1\n", TVC_FILE: b"t = 1\n"}
        for path, data in self.surface.items():
            (self.head / path).parent.mkdir(parents=True, exist_ok=True)
            (self.head / path).write_bytes(data)
        self.contract = dict(TVC_CONTRACT, surface_paths=sorted(self.surface), tests=[TVC_FILE])

    def tearDown(self):
        self.tmp.cleanup()

    def tvc_receipt(self, **over) -> dict:
        body = {"schema": "stegverse.test-suite-skip-receipt/v1", "receipt_kind": "TVC_ORG_CONFORMANCE_TEST_RECEIPT",
                "suite": "TVC_ORG_CONFORMANCE", "repository": "StegVerse-Labs/TVC", "head_sha": "c" * 40,
                "event": "push", "disposition": "ALLOW", "refusals": [], "counts": {"tests": 2, "skipped": 0},
                "test_ids": [f"{TVC_CLASS}::test_a", f"{TVC_CLASS}::test_b"],
                "ledger_candidate": {"candidate": True, "appended_by_this_job": False},
                "consumed_source": {"repository": "StegVerse-org/.github", "commit": "d" * 40,
                                    "observed_surface": {p: sha(d) for p, d in self.surface.items()}}}
        return body | over

    def consumption(self, sources: list[dict] | None) -> dict:
        """The real consumer's record over a fixture ledger (None: no ledger at all)."""
        ledger = self.dir / "ledger"
        if sources is not None:
            write_ledger(ledger, sources)
        return tvc_module.consume(self.contract, str(ledger), self.head, None)

    def receipt(self, cases: str, consumptions: dict, items=(TVC_ITEM, RS_ITEM)) -> dict:
        head = self.dir / "head.xml"
        head.write_text(junit(cases), encoding="utf-8")
        return receipt_module.build(head, "h" * 40, "retry", "goal", list(items),
                                    consumptions=consumptions, root=self.head)

    def assert_fails_closed(self, r: dict, why: str) -> None:
        self.assertEqual(r["disposition"], "FAIL_CLOSED")
        (row,) = r["refusals"]
        self.assertEqual(tuple(row), SIX)
        self.assertTrue(all(row[k] for k in SIX))
        self.assertEqual(row["failure_code"], "TEST_SUITE_SKIPPED_ON_HEAD")
        self.assertEqual(r["counts"]["skipped_satisfied_by_ledger_receipt"], 0)
        self.assertIn(why, " ".join(r["skipped"][0].get("receipt_satisfaction_refused", ["<not eligible>"])))

    def tvc_skips(self) -> str:
        return (skip_case(TVC_CLASS, "test_a", TVC_REASON) + skip_case(TVC_CLASS, "test_b", TVC_REASON)
                + PASS)

    def test_an_allow_receipt_bound_to_this_surface_satisfies_the_tvc_skips_and_keeps_them_listed(self):
        record = self.consumption([{"schema": "other/v1"}, self.tvc_receipt()])
        self.assertEqual(record["disposition"], "ALLOW")
        self.assertEqual(record["bound_surface"], {p: sha(d) for p, d in self.surface.items()})
        self.assertEqual(record["bound_event"], "push")
        r = self.receipt(self.tvc_skips(), {"tvc": record})
        self.assertEqual(r["disposition"], "ALLOW")
        self.assertEqual(r["refusals"], [])
        self.assertEqual(r["counts"]["skipped"], 2)
        self.assertEqual(r["counts"]["skipped_satisfied_by_ledger_receipt"], 2)
        self.assertTrue(r["skips_are_never_converted_or_deselected"])
        for row in r["skipped"]:
            bound = row["satisfied_by_ledger_receipt"]
            self.assertEqual(bound["input"], "tvc")
            self.assertEqual(bound["bound_receipt_sha256"], record["bound_receipt_sha256"])
            self.assertEqual(bound["surface_files_matched"], 2)

    def test_a_receipt_from_a_pull_request_run_is_refused(self):
        record = self.consumption([self.tvc_receipt(
            event="pull_request", ledger_candidate={"candidate": False, "why": "a pull_request run"})])
        self.assertEqual(record["disposition"], "FAIL_CLOSED")
        self.assert_fails_closed(self.receipt(self.tvc_skips(), {"tvc": record}), "consumption disposition")
        # and a record claiming ALLOW for a pull_request-sourced receipt is refused here too
        forged = self.consumption([self.tvc_receipt()]) | {"bound_event": "pull_request",
                                                           "bound_ledger_candidate": False}
        self.assert_fails_closed(self.receipt(self.tvc_skips(), {"tvc": forged}),
                                 "not a ledger candidate from a push")

    def test_a_receipt_for_a_different_surface_is_refused(self):
        other = dict(self.surface, **{"org-kernel/kernel.py": b"k = 2\n"})
        receipt = self.tvc_receipt(consumed_source={"repository": "StegVerse-org/.github", "commit": "e" * 40,
                                                    "observed_surface": {p: sha(d) for p, d in other.items()}})
        record = self.consumption([receipt])
        self.assertEqual(record["disposition"], "FAIL_CLOSED")
        self.assert_fails_closed(self.receipt(self.tvc_skips(), {"tvc": record}), "consumption disposition")

    def test_a_head_whose_bytes_moved_after_consumption_is_refused(self):
        record = self.consumption([self.tvc_receipt()])
        (self.head / "org-kernel/kernel.py").write_bytes(b"k = 3\n")
        self.assert_fails_closed(self.receipt(self.tvc_skips(), {"tvc": record}),
                                 "bound surface path(s) differ at this head (org-kernel/kernel.py)")

    def test_an_absent_receipt_fails_closed_unchanged(self):
        for consumptions in ({}, {"tvc": None}, {"tvc": self.consumption(None)},
                             {"tvc": self.consumption([{"schema": "other/v1"}])}):
            with self.subTest(consumptions=list(consumptions)):
                r = self.receipt(self.tvc_skips(), consumptions)
                self.assertEqual(r["disposition"], "FAIL_CLOSED")
                self.assertEqual(r["refusals"][0]["failure_code"], "TEST_SUITE_SKIPPED_ON_HEAD")
                self.assertEqual(r["counts"]["skipped"], 2)
                self.assertEqual(r["counts"]["skipped_satisfied_by_ledger_receipt"], 0)

    def test_a_skipped_test_the_receipt_did_not_run_is_refused(self):
        record = self.consumption([self.tvc_receipt(test_ids=[f"{TVC_CLASS}::test_a"])])
        r = self.receipt(self.tvc_skips(), {"tvc": record})
        self.assertEqual(r["disposition"], "FAIL_CLOSED")
        self.assertEqual(r["counts"]["skipped_satisfied_by_ledger_receipt"], 1)
        refused = [row for row in r["skipped"] if "receipt_satisfaction_refused" in row]
        self.assertEqual([row["test"] for row in refused], [f"{TVC_CLASS}::test_b"])
        self.assertIn("1 skipped", r["refusals"][0]["required_evidence_or_repair"])

    def test_another_inputs_record_or_another_reason_does_not_satisfy(self):
        record = self.consumption([self.tvc_receipt()])
        self.assert_fails_closed(self.receipt(self.tvc_skips(), {"repo-standards": record}), "no readable tvc")
        wrong_schema = record | {"schema": "stegverse.repo-standards-owner-drift-receipt-consumption/v1"}
        self.assert_fails_closed(self.receipt(self.tvc_skips(), {"tvc": wrong_schema}), "consumption schema")
        other_reason = skip_case(TVC_CLASS, "test_a", "something else is missing")
        self.assert_fails_closed(self.receipt(other_reason, {"tvc": record}), "not the private-input skip")

    def test_the_gate_is_not_relaxed_for_any_other_skip(self):
        record = self.consumption([self.tvc_receipt()])
        r = self.receipt(self.tvc_skips() + SKIP, {"tvc": record})
        self.assertEqual(r["disposition"], "FAIL_CLOSED")
        self.assertEqual(r["counts"]["skipped"], 3)
        self.assertEqual(r["counts"]["skipped_satisfied_by_ledger_receipt"], 2)
        self.assertIn("1 skipped", r["refusals"][0]["required_evidence_or_repair"])
        # an item that declares no receipt input is never satisfied, whatever record is supplied
        bare = {k: v for k, v in TVC_ITEM.items() if k != "satisfiable_by_receipt"}
        self.assertEqual(self.receipt(self.tvc_skips(), {"tvc": record}, items=[bare])["disposition"],
                         "FAIL_CLOSED")
        # failures are judged as before: a receipt-satisfied skip does not hide a failure
        r = self.receipt(self.tvc_skips() + FAIL, {"tvc": record})
        self.assertEqual(r["failing_on_head"], ["tests.test_c::test_bad"])

    def test_a_class_level_skip_is_satisfied_only_when_the_receipt_ran_that_class(self):
        rs_file = "tests/test_task_registry_schema_conformance.py"
        rs_class = "tests.test_task_registry_schema_conformance.OwnerDriftTests"
        (self.head / rs_file).write_bytes(b"rs = 1\n")
        record = {"schema": RS_ITEM["satisfiable_by_receipt"]["consumption_schema"], "disposition": "ALLOW",
                  "refusals": [], "bound_receipt_sha256": "sha256:" + "f" * 64, "bound_event": "push",
                  "bound_ledger_candidate": True, "bound_surface": {rs_file: sha(b"rs = 1\n")},
                  "bound_test_ids": [f"{rs_class}::test_the_copy_is_byte_identical_to_the_owners_schema"]}
        case = skip_case(rs_class, "setUpClass", "repo-standards is not reachable here; attach it")
        self.assertEqual(self.receipt(case, {"repo-standards": record})["disposition"], "ALLOW")
        other = record | {"bound_test_ids": ["tests.test_task_registry_schema_conformance.ConformanceTests::t"]}
        self.assert_fails_closed(self.receipt(case, {"repo-standards": other}), "not among the test ids")

    def test_the_cli_reads_consumption_files_and_an_unreadable_one_satisfies_nothing(self):
        record = self.consumption([self.tvc_receipt()])
        good = self.dir / "c.json"
        good.write_text(json.dumps(record), encoding="utf-8")
        junit_path = self.dir / "j.xml"
        junit_path.write_text(junit(self.tvc_skips()), encoding="utf-8")
        items = self.dir / "items.json"
        items.write_text(json.dumps({"items": [TVC_ITEM]}), encoding="utf-8")
        for path, rc in ((good, 0), (self.dir / "absent.json", 1)):
            with self.subTest(path=path.name):
                out = self.dir / "r.json"
                self.assertEqual(receipt_module.main([
                    "--junit", str(junit_path), "--head", "h", "--out", str(out), "--retry-entrypoint", "e",
                    "--owning-goal", "g", "--skip-items", str(items), "--root", str(self.head),
                    "--receipt-consumption", f"tvc={path}"]), rc)

    def test_the_selected_tests_step_runs_both_consumers_at_the_exact_head_and_passes_them(self):
        step = (ROOT / "tools" / "tasks" / "steps" / "test-suite-selected.selected"
                / "08-receipt-the-selected-set-a-skip-in-it-or-a-new-f.sh").read_text(encoding="utf-8")
        self.assertIn('test "$(git rev-parse HEAD)" = "$HEAD_SHA"', step)
        for item in (TVC_ITEM, RS_ITEM):
            want = item["satisfiable_by_receipt"]
            self.assertIn(f"python3 {want['consumer']} consume", step)
            self.assertIn(f'--receipt-consumption "{want["input"]}=', step)
            self.assertTrue((ROOT / want["consumer"]).is_file())


if __name__ == "__main__":
    unittest.main()
