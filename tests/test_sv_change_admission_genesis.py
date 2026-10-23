"""SV_CHANGE_ADMISSION_GENESIS writer op (Lane C, #164): E0 checks, FROM_HEAD append at gen+1, verify-first.

Temp ledgers are the merge-transfer fixtures' pinned ledger tip (tests/test_merge_transfer.Ledger), never the
published ref. The genesis request fixture is TVC's config/sv-merge-admission/genesis-request.json (manifest v2.2,
TVC#534 @3019f1c2) byte for byte; it carries only the declared digest, no private manifest bytes. The ALLOW
base-state readback for this repository is synthetic (the observed one for org main 40a5d235 is FAIL_CLOSED
REGISTRY_GENERATION_NOT_DECLARED, tested as the real block). Lane B's producer is staged into a temp root at
the pinned bytes only where a test needs it; on this repository's main it is absent (the real block).
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = load("test_merge_transfer_for_genesis", "tests/test_merge_transfer.py")
G = load("sv_change_admission_genesis_under_test", "resident-runtime/sv_change_admission_genesis.py")
mt, ap = G.mt, G.ap
FIX = ROOT / "tests" / "fixtures" / "sv-change-admission-genesis"
REQUEST = (FIX / "genesis-request.json").read_bytes()
DIGEST = json.loads(REQUEST)["admission_manifest_sha256"]
ORG_READBACK = json.loads((ROOT / "tests/fixtures/admission-predicate/base-state-readback/org-main-40a5d235-producer-78a0c78e.json").read_text())
LABS_ALLOW = json.loads((ROOT / "tests/fixtures/admission-predicate/base-state-readback/labs-main-978b8880-producer-7ad6d81f.json").read_text())
HEAD = "a" * 40


def pull(repo, **over):
    p = {"number": 300, "state": "open", "merged": False, "head": {"sha": HEAD, "repo": {"full_name": repo}}, "base": {"repo": {"full_name": repo}}}
    p.update(over)
    return p


def files(**over):
    f = {"filename": G.contract()["request_path"], "status": "added", "sha": ap.git_blob_sha(REQUEST)}
    f.update(over)
    return [f]


def readback(repo, epoch, **over):
    r = {k: v for k, v in copy.deepcopy(LABS_ALLOW).items() if k != "result_sha256"}
    r["repository"] = repo
    r["sources"][0]["file"] = "orchestration/task-registry.json"
    r["hb_epoch"] = str(epoch)
    r.update(over)
    return ap.seal(r)


def receipt(**over):
    r = {"schema": "stegverse.test-suite-skip-receipt/v1", "head_sha": HEAD, "authority_effect": "NONE", "skips_are_never_converted_or_deselected": True,
         "selected_tests": ["tests/test_sv_change_admission_genesis.py"], "not_selected_for_this_change": [],
         "not_selected_are_not_run_for_this_verdict_and_not_reported_as_passing": True,
         "counts": {"passed": 9, "failed": 0, "errors": 0, "skipped": 0, "xfailed": 0, "tests": 9}, "skipped": [],
         "base_sha": "b" * 40, "new_failures_on_head": [], "pre_existing_on_base_not_blocking": [], "refusals": [], "disposition": "ALLOW"}
    r.update(over)
    return json.dumps(r).encode()


class Base(unittest.TestCase):
    def setUp(self):
        self.f = json.loads(base.FIXTURES[0].read_text())
        self.ledger = base.Ledger(self.f)
        self.addCleanup(self.ledger.close)
        self.repo = mt.repository()
        self.epoch, failed = mt.head_epoch(mt.org_store())
        assert failed is None, failed
        self.root = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.root)
        self.stage_producer()

    def stage_producer(self):
        """The producer at the pinned bytes cannot be reproduced from a pin; a test root carries a stand-in whose pins
        are patched to its own bytes (the pin check itself is tested against the real contract below)."""
        self.c = copy.deepcopy(G.contract())
        for path in self.c["test_suite_receipt"]["files"]:
            p = self.root / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"stand-in " + path.encode())
            data = p.read_bytes()
            self.c["test_suite_receipt"]["files"][path] = {"git_blob_sha": ap.git_blob_sha(data), "sha256": hashlib.sha256(data).hexdigest()}
        self._orig = G.contract
        G.contract = lambda: copy.deepcopy(self.c)
        self.addCleanup(setattr, G, "contract", self._orig)

    def go(self, fn=None, *, request=REQUEST, p=None, fl=None, rb=None, rc=None, mode="E0", root=None):
        return (fn or G.plan)(request, p or pull(self.repo), fl if fl is not None else files(), rb if rb is not None else readback(self.repo, self.epoch),
                              rc if rc is not None else receipt(), mode, root=root or self.root)

    def refused(self, out, code, disposition="FAIL_CLOSED"):
        self.assertEqual((out["disposition"], out["failure_code"]), (disposition, code), out)
        for k in G.SIX_FIELDS:
            self.assertTrue(out.get(k), k)
        self.assertIs(out["consequence_committed"], False)
        self.assertEqual(out["lowest_supported_mode"], "E0")


class Plan(Base):
    def test_plan_declares_what_tvc_checks(self):
        out = self.go()
        self.assertEqual(out["disposition"], "ALLOW", out)
        b = out["boundary_evidence"]
        self.assertEqual((b["append_mode"], b["ledger_ref"], b["admission_manifest_sha256"]), ("FROM_HEAD", "refs/stegverse/organization-ledger", DIGEST))
        self.assertEqual((b["from_registry_generation"], b["registry_generation"]), (319, 320))
        self.assertEqual(b["genesis_request"], {"repository": self.repo, "pull_number": 300, "head_sha": HEAD})
        self.assertEqual(b["selected_tests_receipt"], {"head_sha": HEAD, "receipt_sha256": "sha256:" + hashlib.sha256(receipt()).hexdigest(),
                                                       "disposition": "ALLOW", "skipped": 0, "tests": 9, "selected_files": 1})
        self.assertEqual(b["mode"], "E0")

    def test_the_request_is_tvc_v2_2(self):
        req = json.loads(REQUEST)
        self.assertEqual(req["manifest"]["schema"], "stegverse.merge-admission-manifest/v2.2")
        self.assertEqual(DIGEST, "sha256:9f0e58ec71438b65fae7a739530ce11fd59eeca04a3e56b8243432fb24bb7217")
        self.assertEqual(G._supersedes_chain(req)[:2], ["sha256:7b7a1b74b2e164792d0b2ff66092b519e6460ee758f3d9cc1304428d416b36bc",
                                                       "sha256:7370db4088ea0fa5621f64ddd4f8c77778ce28358a1841254b3b6e28c58bf4e3"])

    def test_e1_declares_the_degraded_cross_llm_form(self):
        b = self.go(mode="E1")["boundary_evidence"]
        self.assertEqual(b["cross_llm_confirmation"], {"form": "E0_CHECKS_PLUS_LATER_RECEIPTED_REVIEW",
                                                       "later_review": {"lane": "C", "reviewer": "Claude", "receipt_sha256": "PENDING"}})
        self.refused(self.go(mode="E9"), "GENESIS_MODE_UNDECLARED")
        req = json.loads(REQUEST); req.pop("cross_llm_confirmation_at_e1"); rb = json.dumps(req).encode()
        self.refused(self.go(request=rb, fl=files(sha=ap.git_blob_sha(rb)), mode="E1"), "GENESIS_CROSS_LLM_FORM_UNDECLARED")

    def test_each_e0_gate_refuses_with_six_fields_and_writes_nothing(self):
        before = self.ledger.files()
        req = json.loads(REQUEST); req["append_mode"] = "APPEND"; bad = json.dumps(req).encode()
        cases = [
            (dict(request=b"{}"), "GENESIS_REQUEST_INVALID", "FAIL_CLOSED"),
            (dict(request=bad, fl=files(sha=ap.git_blob_sha(bad))), "GENESIS_REQUEST_INVALID", "FAIL_CLOSED"),
            (dict(p=pull(self.repo, state="closed")), "GENESIS_REQUEST_PR_NOT_OPEN", "DENY"),
            (dict(p=pull(self.repo, head={"sha": HEAD, "repo": {"full_name": "fork/.github"}})), "GENESIS_REQUEST_PR_NOT_SAME_REPOSITORY", "DENY"),
            (dict(fl=files() + [{"filename": "resident-runtime/x.py", "status": "added", "sha": "c" * 40}]), "GENESIS_REQUEST_PR_CHANGES_MORE_THAN_THE_REQUEST", "DENY"),
            (dict(fl=files(sha="d" * 40)), "GENESIS_REQUEST_BYTES_NOT_AT_HEAD", "FAIL_CLOSED"),
            (dict(rb=ORG_READBACK), "GENESIS_REGISTRY_GENERATION_NOT_OBSERVED", "FAIL_CLOSED"),
            (dict(rb=readback(self.repo, self.epoch + 1)), "GENESIS_BASE_STATE_NOT_CURRENT", "FAIL_CLOSED"),
            (dict(rb=readback("StegVerse-Labs/.github", self.epoch, sources=copy.deepcopy(LABS_ALLOW["sources"]))), "GENESIS_REGISTRY_GENERATION_NOT_OBSERVED", "FAIL_CLOSED"),
            (dict(rc=receipt(head_sha="e" * 40)), "TEST_SUITE_NOT_OBSERVED_ON_HEAD", "FAIL_CLOSED"),
            (dict(rc=receipt(counts={"tests": 9, "skipped": 1}, skipped=[{"test": "t"}])), "TEST_SUITE_SKIPPED_ON_HEAD", "FAIL_CLOSED"),
            (dict(rc=receipt(new_failures_on_head=["t"])), "TEST_SUITE_NEW_FAILURE_ON_HEAD", "FAIL_CLOSED"),
            (dict(rc=receipt(disposition="FAIL_CLOSED", refusals=[{"failure_code": "X"}])), "TEST_SUITE_NOT_OBSERVED_ON_HEAD", "FAIL_CLOSED"),
            (dict(rc=receipt(not_selected_are_not_run_for_this_verdict_and_not_reported_as_passing=False)), "TEST_SUITE_NOT_OBSERVED_ON_HEAD", "FAIL_CLOSED"),
        ]
        for kw, code, disp in cases:
            with self.subTest(code=code, kw=list(kw)):
                self.refused(self.go(G.append, **kw), code, disp)
        self.assertEqual(self.ledger.files(), before)

    def test_the_observed_org_readback_is_the_real_generation_block(self):
        out = self.go(rb=ORG_READBACK)
        # the observed receipt is FAIL_CLOSED REGISTRY_GENERATION_NOT_DECLARED (and from a superseded producer shape, so also void)
        self.assertEqual(out["readback_inner_failure_code"], "REGISTRY_GENERATION_NOT_DECLARED")
        self.assertIn(out["readback_failure_code"], ("BASE_STATE_NOT_OBSERVED", "HB_EPOCH_SOURCE_UNOBSERVED"))
        self.assertIn("Q-ORG-REGISTRY-GENERATION", out["next_attempt"])

    def test_without_lane_b_producer_on_the_base_it_is_not_pinned(self):
        G.contract = self._orig  # the real pins (Lane B #231 @b2f9fad2); this repository's main does not carry the producer
        out = self.go(root=ROOT)
        self.refused(out, "TEST_SUITE_RECEIPT_PRODUCER_NOT_PINNED")
        self.assertIn("scripts/test_suite_skip_receipt.py", out["observed"])


class Append(Base):
    def test_append_then_verify_then_replay(self):
        before = self.ledger.files()
        out = self.go(G.append)
        self.assertEqual((out["disposition"], out["appended"], out["registry_generation"]), ("ALLOW", True, 320), out)
        org = self.ledger.read(mt.store_module().receipt_key(out["organization_receipt_sha256"]))
        self.assertTrue(mt.sealed(org))
        b = mt._boundary(org)
        self.assertEqual((b["operation"], b["append_mode"], b["admission_manifest_sha256"], b["registry_generation"], b["from_registry_generation"]),
                         ("SV_CHANGE_ADMISSION_GENESIS", "FROM_HEAD", DIGEST, 320, 319))
        for name, data in before.items():
            if not name.endswith("HEAD.json"):
                self.assertEqual(self.ledger.files()[name], data, name)
        self.assertEqual(G.verify(DIGEST)["organization_receipt_sha256"], out["organization_receipt_sha256"])
        again = self.go(G.append)
        self.assertEqual((again["disposition"], again["replayed"], again["organization_receipt_sha256"]), ("ALLOW", True, out["organization_receipt_sha256"]))

    def test_a_different_unsuperseded_genesis_is_denied(self):
        self.assertEqual(self.go(G.append)["disposition"], "ALLOW")
        req = json.loads(REQUEST); req["admission_manifest_sha256"] = "sha256:" + "f" * 64; req["supersedes"] = {"admission_manifest_sha256": "sha256:" + "0" * 64}
        rb = json.dumps(req).encode()
        self.refused(self.go(G.append, request=rb, fl=files(sha=ap.git_blob_sha(rb))), "GENESIS_ALREADY_DECLARED", "DENY")
        req["supersedes"] = {"admission_manifest_sha256": DIGEST}; rb = json.dumps(req).encode()
        self.assertEqual(self.go(G.plan, request=rb, fl=files(sha=ap.git_blob_sha(rb)), rb=readback(self.repo, mt.head_epoch(mt.org_store())[0]))["disposition"], "ALLOW")

    def test_verify_without_a_genesis_is_fail_closed(self):
        self.refused(G.verify(DIGEST), "GENESIS_NOT_LEDGERED")

    def test_no_workflow_runs_the_op_yet(self):
        texts = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / ".github" / "workflows").glob("*.yml")}
        runs = [n for n, t in texts.items() if "sv_change_admission_genesis.py append" in t or "sv_change_admission_genesis.py plan" in t]
        self.assertEqual(runs, [])  # the triggering event is the undecided authorization form (Q-SV-NATIVE-BOOTSTRAP, C)
        refs = sorted(n for n, t in texts.items() if "sv_change_admission_genesis" in t)
        self.assertEqual(refs, ["sv-change-admission-genesis-validation.yml"])
        self.assertIn("contents: read", texts[refs[0]]); self.assertNotIn("contents: write", texts[refs[0]])


if __name__ == "__main__":
    unittest.main()
