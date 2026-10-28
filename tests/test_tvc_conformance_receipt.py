"""The full-suite tvc input consumes TVC's org conformance receipt from the organization ledger chain only.

Ported from StegVerse-Labs/.github#3332 tests/test_tvc_conformance_receipt.py (acc4adf6).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("tvc_conformance_receipt", ROOT / "resident-runtime" / "tvc_conformance_receipt.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

CONTRACT = json.loads((ROOT / ".stegverse" / "verification-inputs" / "tvc-conformance-receipt.json").read_text(encoding="utf-8"))
SPEC_DOC = json.loads((ROOT / ".stegverse" / "test-set-spec.json").read_text(encoding="utf-8"))
FETCH = (ROOT / "tools" / "tasks" / "steps" / "required-verification.full-suite" / "02-declared-inputs-this-repository-already-supplies.sh").read_text(encoding="utf-8")
TESTS = CONTRACT["tests"]


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sealed(body):
    body = {k: v for k, v in body.items() if k != "receipt_sha256"}
    return body | {"receipt_sha256": "sha256:" + hashlib.sha256(canon(body)).hexdigest()}


def fsha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


SELECTED = {"selected": [{"id": TESTS[0] + "[tvc]", "inputs": [{"id": "tvc", "available": False}]}]}
NOT_SELECTED = {"selected": [{"id": "tests/test_x.py", "inputs": []}]}


class Ledger:
    """A POSIX organization ledger holding the given source receipts, oldest first."""

    def __init__(self, root: Path, sources: list[dict]):
        previous = None
        for i, source in enumerate(sources):
            source = sealed(source)
            digest = source["receipt_sha256"]
            (root / "source-receipts").mkdir(parents=True, exist_ok=True)
            (root / "source-receipts" / (digest.split(":", 1)[1] + ".json")).write_text(json.dumps(source))
            org = sealed({"schema": "stegverse.organization-transition-receipt/v1", "authority_effect": "NONE",
                          "previous_receipt_sha256": previous, "source_transition_sha256": digest,
                          "source_receipt_schema": source.get("schema"), "source_transition_id": f"T{i}"})
            (root / "receipts").mkdir(parents=True, exist_ok=True)
            (root / "receipts" / (org["receipt_sha256"].split(":", 1)[1] + ".json")).write_text(json.dumps(org))
            previous = org["receipt_sha256"]
        (root / "HEAD.json").write_text(json.dumps({"receipt_sha256": previous}))


class ConsumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.head = base / "head"
        self.ledger = base / "ledger"
        self.ledger.mkdir()
        self.surface = {"org-kernel/x.py": b"x = 1\n", TESTS[0]: b"t0\n"}
        for path, data in self.surface.items():
            (self.head / path).parent.mkdir(parents=True, exist_ok=True)
            (self.head / path).write_bytes(data)
        self.contract = dict(CONTRACT, surface_paths=sorted(self.surface))

    def tearDown(self):
        self.tmp.cleanup()

    def receipt(self, **over):
        body = {"schema": "stegverse.test-suite-skip-receipt/v1", "receipt_kind": "TVC_ORG_CONFORMANCE_TEST_RECEIPT",
                "suite": "TVC_ORG_CONFORMANCE", "repository": "StegVerse-Labs/TVC", "head_sha": "c" * 40,
                "disposition": "ALLOW", "refusals": [], "counts": {"tests": 1, "skipped": 0},
                "test_ids": [mod.module_of(TESTS[0]) + ".T::a"],
                "ledger_candidate": {"candidate": True, "appended_by_this_job": False},
                "consumed_source": {"repository": "StegVerse-org/.github", "commit": "d" * 40,
                                    "observed_surface": {p: fsha(d) for p, d in self.surface.items()}}}
        return body | over

    def consume(self, sources, selection=SELECTED):
        Ledger(self.ledger, sources)
        return mod.consume(self.contract, str(self.ledger), self.head, selection)

    def assert_unavailable(self, record, predicate):
        self.assertEqual(record["disposition"], "FAIL_CLOSED")
        (row,) = record["refusals"]
        self.assertEqual(tuple(row), mod.SIX)
        self.assertTrue(all(row[k] for k in mod.SIX))
        self.assertEqual(row["failure_code"], "REQUIRED_VERIFICATION_INPUT_UNAVAILABLE")
        self.assertEqual(row["failed_predicate"], predicate)

    def test_a_change_selecting_no_tvc_set_is_still_evaluated_never_waived(self):
        record = mod.consume(self.contract, str(self.ledger / "absent"), self.head, NOT_SELECTED)
        self.assertEqual(record["disposition"], "FAIL_CLOSED")
        self.assertTrue(record["refusals"])

    def test_matching_receipt_on_the_chain_is_bound_with_the_ledger_head_epoch(self):
        record = self.consume([{"schema": "other/v1", "n": 1}, self.receipt()])
        self.assertEqual(record["disposition"], "ALLOW")
        self.assertTrue(record["bound_receipt_sha256"].startswith("sha256:"))
        self.assertTrue(record["epoch_from_ledger_head"].startswith("sha256:"))
        self.assertFalse(record["derived_from_clock"])

    def test_unreadable_ledger_is_unavailable(self):
        record = mod.consume(self.contract, str(self.ledger / "absent"), self.head, SELECTED)
        self.assert_unavailable(record, "ORGANIZATION_LEDGER_CHAIN_READABLE")

    def test_unreadable_selection_is_evaluated_as_selected(self):
        record = mod.consume(self.contract, str(self.ledger / "absent"), self.head, None)
        self.assertEqual(record["disposition"], "FAIL_CLOSED")

    def test_no_receipt_on_the_chain_is_unavailable(self):
        record = self.consume([{"schema": "other/v1", "n": 1}])
        self.assert_unavailable(record, "TVC_CONFORMANCE_RECEIPT_ON_ORGANIZATION_LEDGER")

    def test_skipped_failed_or_non_candidate_receipts_never_bind(self):
        for over in ({"counts": {"tests": 1, "skipped": 1}}, {"disposition": "FAIL_CLOSED"},
                     {"ledger_candidate": {"candidate": False}}, {"test_ids": []}):
            with self.subTest(over=over):
                for p in self.ledger.iterdir():
                    if p.is_dir():
                        for f in p.iterdir():
                            f.unlink()
                record = self.consume([self.receipt(**over)])
                self.assert_unavailable(record, "TVC_CONFORMANCE_RECEIPT_ON_ORGANIZATION_LEDGER")
                self.assertTrue(record["rejected_receipts"])

    def test_a_changed_surface_file_makes_the_receipt_stale(self):
        (self.head / "org-kernel/x.py").write_bytes(b"x = 2\n")
        record = self.consume([self.receipt()])
        self.assert_unavailable(record, "TVC_CONFORMANCE_RECEIPT_MATCHES_HEAD_SURFACE")
        self.assertIn("org-kernel/x.py", record["stale_receipts"][0]["differs"])

    def test_a_declared_path_the_receipt_does_not_cover_makes_it_stale(self):
        self.contract["surface_paths"] = sorted(self.surface) + ["org-kernel/node_store.py"]
        record = self.consume([self.receipt()])
        self.assert_unavailable(record, "TVC_CONFORMANCE_RECEIPT_MATCHES_HEAD_SURFACE")

    def test_a_forged_unsealed_source_breaks_the_chain_read(self):
        Ledger(self.ledger, [self.receipt()])
        src = next((self.ledger / "source-receipts").iterdir())
        doc = json.loads(src.read_text())
        doc["counts"]["skipped"] = 0
        doc["head_sha"] = "e" * 40
        src.write_text(json.dumps(doc))
        record = mod.consume(self.contract, str(self.ledger), self.head, SELECTED)
        self.assert_unavailable(record, "ORGANIZATION_LEDGER_CHAIN_READABLE")

    def test_every_predicate_declares_e0(self):
        for row in mod.PREDICATES:
            self.assertEqual(row["lowest_mode"], "E0")
            self.assertTrue(row["degraded_form"].startswith("E0"))


class ContractTests(unittest.TestCase):
    def test_surface_paths_are_sorted_present_and_include_both_tests(self):
        paths = CONTRACT["surface_paths"]
        self.assertEqual(paths, sorted(set(paths)))
        for t in TESTS:
            self.assertIn(t, paths)
        for p in paths:
            self.assertTrue((ROOT / p).is_file(), p)

    def test_the_receipt_identity_is_tvcs_org_conformance_receipt(self):
        self.assertEqual(CONTRACT["receipt"]["receipt_kind"], "TVC_ORG_CONFORMANCE_TEST_RECEIPT")
        self.assertEqual(CONTRACT["receipt"]["repository"], "StegVerse-Labs/TVC")
        self.assertEqual(TESTS, ["tests/test_origin_attestation_tvc_conformance.py"])

    def test_the_spec_tvc_input_is_this_receipt_consumer(self):
        check = SPEC_DOC["inputs"]["tvc"]["check"]
        self.assertEqual(check["kind"], "receipt_consumer")
        self.assertEqual(check["consumer"], "resident-runtime/tvc_conformance_receipt.py")
        self.assertEqual(check["allow"], "ALLOW")
        self.assertEqual(check["argv"][:3], ["consume", "--ledger", "git+{root}#refs/stegverse/organization-ledger"])
        self.assertNotIn("env", check)
        for split in SPEC_DOC["splits"]:
            if "tvc" in split.get("inputs", []):
                self.assertIn(split["file"], TESTS)

    def test_the_full_suite_job_fetches_the_ledger_ref_anonymously_and_never_writes(self):
        self.assertIn("+refs/stegverse/organization-ledger:refs/stegverse/organization-ledger", FETCH)
        source = (ROOT / "resident-runtime" / "tvc_conformance_receipt.py").read_text(encoding="utf-8")
        for value in ("git push", "update-ref", "secrets.", "GITHUB_TOKEN", "os.environ"):
            self.assertNotIn(value, source)


if __name__ == "__main__":
    unittest.main()
