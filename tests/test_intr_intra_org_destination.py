"""StegVerse-org/.github#237, declared form: only an organization's .github is an InTr destination.

The org/.github -> LLM-adapter edge (and any intra-organization or repository-to-repository destination) is refused
fail-closed with six fields; every declared mesh path between two organizations' .github is answered ALLOW by the
rule. Clock-free, network-free; nothing is appended.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("intr_intra_org_destination",
                                              ROOT / "resident-runtime" / "intr_intra_org_destination.py")
rule = importlib.util.module_from_spec(spec)
sys.modules["intr_intra_org_destination"] = rule
spec.loader.exec_module(rule)
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
       "owning_existing_goal", "next_attempt")


class IntraOrgDestination(unittest.TestCase):
    def assertSix(self, result):
        self.assertEqual(result["disposition"], "FAIL_CLOSED")
        for field in SIX:
            self.assertTrue(isinstance(result[field], str) and result[field].strip(), field)

    def test_the_llm_adapter_edge_is_refused_as_undeclared(self):
        result = rule.judge("StegVerse-org/.github", "StegVerse-org/LLM-adapter")
        self.assertSix(result)
        self.assertEqual(result["failure_code"], "INTR_INTRA_ORG_DESTINATION_UNDECLARED")
        self.assertEqual(result["failed_predicate"], "INTR_PATH_IS_BETWEEN_DISTINCT_ORGANIZATIONS")

    def test_any_intra_org_pair_is_refused_even_between_dot_github_names(self):
        for source, destination in (("StegVerse-org/LLM-adapter", "StegVerse-org/.github"),
                                    ("StegVerse-org/.github", "StegVerse-org/.github"),
                                    ("StegVerse-Labs/.github", "StegVerse-Labs/TVC")):
            self.assertEqual(rule.judge(source, destination)["failure_code"], "INTR_INTRA_ORG_DESTINATION_UNDECLARED")

    def test_a_repository_endpoint_across_organizations_is_refused(self):
        for source, destination in (("StegVerse-org/.github", "SV-LLM/sandbox"),
                                    ("StegVerse-org/LLM-adapter", "StegVerse-Labs/.github")):
            result = rule.judge(source, destination)
            self.assertSix(result)
            self.assertEqual(result["failure_code"], "INTR_REPOSITORY_DESTINATION_UNDECLARED")

    def test_every_declared_mesh_path_is_allowed_and_an_undeclared_pair_is_not(self):
        paths = rule._transfer().declared_paths()
        self.assertTrue(paths)
        for p in paths:
            got = rule.judge(p["source"] + "/.github", p["destination"] + "/.github", paths)
            self.assertEqual((got["disposition"], got["path_id"]), ("ALLOW", p["path_id"]))
        self.assertEqual(rule.judge("StegVerse-org/.github", "No-Such-Org/.github", paths)["failure_code"],
                         "INTR_PATH_UNDECLARED")

    def test_every_citation_resolves_to_its_committed_line(self):
        cited = rule.citations()
        self.assertEqual(len(cited), len(rule.CITATIONS))
        for (rel, phrase), ref in zip(rule.CITATIONS, cited):
            path, line = ref.rsplit(":", 1)
            self.assertEqual(path, rel)
            self.assertIn(phrase, (ROOT / rel).read_text(encoding="utf-8").splitlines()[int(line) - 1])

    def test_nothing_declares_or_appends_an_intra_org_crossing(self):
        self.assertFalse((ROOT / ".stegverse" / "intr-path-transfer" / "intra-org-transfers.json").exists())
        transfer = (ROOT / "resident-runtime" / "intr_path_transfer.py").read_text(encoding="utf-8")
        self.assertNotIn("intr_intra_org_destination", transfer)
        tree = ast.parse((ROOT / "resident-runtime" / "intr_intra_org_destination.py").read_text(encoding="utf-8"))
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertFalse(imported & {"socket", "urllib", "http", "subprocess", "time", "datetime", "os"})


if __name__ == "__main__":
    unittest.main()
