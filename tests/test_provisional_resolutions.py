"""Provisional E1 resolutions of the two class C joint items (Lane C, #164), each with a PENDING C-review.

Q-ORG-REGISTRY-GENERATION: ORG_REGISTRY_GENERATION_GENESIS declares the org registry's genesis generation (0) by a
sealed organization-ledger receipt bound to the exact registry blob a sealed readback observed; the registry file is
never edited. SV_CHANGE_ADMISSION_GENESIS then reads from 0 and appends at 1.
Q-SV-NATIVE-BOOTSTRAP: append runs only on the declared pull_request event (tested in test_sv_change_admission_genesis).

Temp ledgers are copies of the pinned merge-transfer ledger tip. The FAIL_CLOSED readback below is synthetic and
well-shaped (the observed org main 40a5d235 one is a superseded producer shape, so it stays void: tested).
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import test_sv_change_admission_genesis as T  # noqa: E402

G, mt, ap = T.G, T.mt, T.ap
RG = G.rg
RES = json.loads((ROOT / "data/sv-merge-admission/provisional-resolutions.json").read_text(encoding="utf-8"))
BLOB = "de0f66b149fa2df9f837ebcbcfdb14596fe30d90"  # orchestration/task-registry.json as observed at org main 40a5d235


def undeclared(repo, blob=BLOB, **over):
    r = {k: v for k, v in copy.deepcopy(T.LABS_ALLOW).items() if k != "result_sha256"}
    r.update({"repository": repo, "disposition": "FAIL_CLOSED", "failure_code": "REGISTRY_GENERATION_NOT_DECLARED",
              "failed_predicate": "REGISTRY_DECLARES_GENERATION", "base_ref": {"registry_generation": None, "ledger_head": None},
              "hb_epoch": None, "cross_checked": False, "joint_item": "Q-ORG-REGISTRY-GENERATION"})
    r.pop(ap.READBACK_SUPPLIED_FIELD, None)
    r["sources"][0] = {"file": "orchestration/task-registry.json", "blob_sha": blob}
    r.update(over)
    return ap.seal(r)


class Records(unittest.TestCase):
    def test_both_resolutions_are_provisional_e1_with_a_pending_c_review(self):
        for q in ("Q-ORG-REGISTRY-GENERATION", "Q-SV-NATIVE-BOOTSTRAP"):
            r = RES["resolutions"][q]
            self.assertEqual((r["class"], r["provisional_mode"], r["status"]), ("C", "E1", "PROVISIONAL"), q)
            cr = r["c_review"]
            self.assertEqual((cr["status"], cr["receipt_sha256"], cr["reviewers"]), ("PENDING", "PENDING", ["Claude", "ChatGPT"]), q)
            self.assertIn("supersedes", cr["supersedable_by"])
            self.assertTrue(r["e0_checks"])
        ev = RES["resolutions"]["Q-SV-NATIVE-BOOTSTRAP"]["event"]
        self.assertEqual(ev["event_name"], "pull_request")
        self.assertTrue((ROOT / ev["workflow_path"]).is_file())
        text = (ROOT / ev["workflow_path"]).read_text(encoding="utf-8")
        self.assertIn("contents: read", text); self.assertNotIn("contents: write", text)  # no writer job in this draft
        self.assertNotIn("workflow_dispatch", text); self.assertNotIn("schedule", text)

    def test_every_predicate_degrades_to_e0(self):
        for name, p in RG.PREDICATES.items():
            self.assertEqual(p["lowest_supported_mode"], "E0", name)
            self.assertTrue(p["degraded_to_E0"], name)


class RegistryGeneration(T.Base):
    def refused_rg(self, out, code, disposition="FAIL_CLOSED"):
        self.assertEqual((out["disposition"], out["failure_code"]), (disposition, code), out)
        for k in RG.SIX_FIELDS:
            self.assertTrue(out.get(k), k)
        self.assertIs(out["consequence_committed"], False)
        self.assertEqual(out["lowest_supported_mode"], "E0")

    def test_e0_with_a_pending_review_refuses_and_e1_plans(self):
        self.refused_rg(RG.plan(undeclared(self.repo), "E0"), "PROVISIONAL_RESOLUTION_NOT_ADMITTED_AT_E0")
        out = RG.plan(undeclared(self.repo), "E1")
        self.assertEqual(out["disposition"], "ALLOW", out)
        b = out["boundary_evidence"]
        self.assertEqual((b["registry"], b["registry_generation"]),
                         ({"repository": self.repo, "file": "orchestration/task-registry.json", "blob_sha": BLOB}, 0))
        self.assertEqual(b["resolution"]["c_review"]["receipt_sha256"], "PENDING")

    def test_a_filled_review_receipt_admits_it_at_e0(self):
        r = copy.deepcopy(RES["resolutions"]["Q-ORG-REGISTRY-GENERATION"]); r["c_review"]["receipt_sha256"] = "sha256:" + "1" * 64
        self.assertEqual(RG.plan(undeclared(self.repo), "E0", r=r)["disposition"], "ALLOW")

    def test_each_e0_check_refuses_with_six_fields_and_writes_nothing(self):
        before = self.ledger.files()
        void = dict(T.ORG_READBACK)  # observed org main receipt: superseded producer shape, void
        cases = [(void, "REGISTRY_UNDECLARED_STATE_NOT_OBSERVED"),
                 (T.readback(self.repo, self.epoch), "REGISTRY_UNDECLARED_STATE_NOT_OBSERVED"),  # ALLOW: already declared
                 (undeclared("StegVerse-Labs/.github"), "REGISTRY_UNDECLARED_STATE_NOT_OBSERVED"),
                 (dict(undeclared(self.repo), failure_code="X"), "REGISTRY_UNDECLARED_STATE_NOT_OBSERVED")]  # seal breaks
        for rb, code in cases:
            with self.subTest(code=code):
                self.refused_rg(RG.append(rb, "E1"), code)
        self.refused_rg(RG.append(undeclared(self.repo), "E9"), "REGISTRY_GENERATION_MODE_UNDECLARED")
        self.assertEqual(self.ledger.files(), before)

    def test_append_verify_replay_then_one_genesis_only(self):
        out = RG.append(undeclared(self.repo), "E1")
        self.assertEqual((out["disposition"], out["appended"], out["registry_generation"]), ("ALLOW", True, 0), out)
        self.assertEqual(RG.verify(self.repo, "orchestration/task-registry.json", BLOB)["organization_receipt_sha256"], out["organization_receipt_sha256"])
        again = RG.append(undeclared(self.repo), "E1")
        self.assertEqual((again["replayed"], again["organization_receipt_sha256"]), (True, out["organization_receipt_sha256"]))
        self.refused_rg(RG.append(undeclared(self.repo, blob="f" * 40), "E1"), "REGISTRY_GENERATION_GENESIS_ALREADY_DECLARED", "DENY")

    def test_admission_genesis_reads_generation_zero_and_appends_at_one(self):
        rb = undeclared(self.repo)
        self.refused(self.go(rb=rb), "GENESIS_REGISTRY_GENERATION_GENESIS_NOT_LEDGERED")
        self.assertEqual(RG.append(rb, "E1")["disposition"], "ALLOW")
        out = self.go(G.append, rb=rb)
        self.assertEqual((out["disposition"], out["registry_generation"]), ("ALLOW", 1), out)
        b = mt._boundary(self.ledger.read(mt.store_module().receipt_key(out["organization_receipt_sha256"])))
        self.assertEqual((b["from_registry_generation"], b["registry_generation"]), (0, 1))

    def test_the_registry_file_is_never_edited(self):
        src = (ROOT / "resident-runtime" / "org_registry_generation_genesis.py").read_text(encoding="utf-8")
        self.assertNotIn("write_text", src.split("def main")[0])  # the only write is main's --out result file
        self.assertNotIn("write_bytes", src)
        self.assertNotIn('open(', src.replace("open(\"", ""))


if __name__ == "__main__":
    unittest.main()
