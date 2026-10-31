"""InTr protocol v1: the canonical contract and its offline conformance validator."""
from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "tests" / "fixtures" / "intr-protocol" / "destinations" / "manifest.json"
spec = importlib.util.spec_from_file_location("intr_protocol", ROOT / "org-runtime" / "intr_protocol.py")
intr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(intr)

ORGS = ["StegVerse-org", "StegVerse-Labs", "SV-011", "GCAT-BCAT-Engine",
        "Admissible-Existence", "StegGhost", "StegVerse-002", "SV-LLM",
        "AaCT-E", "AdmittedCode", "Data-Continuation", "ECAT-ICAT-Formal", "Triad-Test",
        "Infrastructure-Continuity-Ventures", "formalism-tests", "master-records"]
# All sixteen organizations of the federation directory (org-boundary/registry/federation.json, denominator 16)
# installed the component: Infrastructure-Continuity-Ventures, formalism-tests and master-records snapshots
# refreshed from their main (StegVerse-org/.github#162 Lane B).
UNINSTALLED = []
EXPECTED = {org: ("ALLOW", None) for org in ORGS}
EXPECTED.update({org: ("FAIL_CLOSED", "PEER_ADDRESS_FORM_IS_SLUG_DOT_PROFILE") for org in UNINSTALLED})


def snapshot(org):
    manifest = json.loads(SNAPSHOT.read_text())
    row = next(r for r in manifest["destinations"] if r["organization"] == org)
    base = SNAPSHOT.parent
    return (json.loads((base / row["interlock"]["file"]).read_text()),
            json.loads((base / row["services"]["file"]).read_text()))


def message(**overrides):
    payload = {"message_class": "ecosystem.communication", "communication_id": "intr-test-1",
               "body": {"schema": "stegverse.org-intr-destination-diagnostic/v1"}}
    payload.update(overrides)
    return payload


class ContractShape(unittest.TestCase):
    def test_contract_is_versioned_and_names_six_fields(self):
        contract = intr.load_contract()
        self.assertEqual(contract["protocol"], "stegverse.intr-protocol/v1")
        self.assertEqual(contract["protocol_version"], 1)
        self.assertEqual(tuple(contract["non_allow_fields"]),
                         ("failure_code", "failed_predicate", "required_evidence_or_repair",
                          "retry_entrypoint", "owning_existing_goal", "next_attempt"))
        self.assertEqual(contract["dispositions"], ["ALLOW", "DENY", "FAIL_CLOSED"])
        ids = [p["id"] for key in ("interlock_predicates", "binding_predicates", "service_predicates")
               for p in contract["destination_capability"][key]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_contract_agrees_with_the_destination_operation(self):
        ing = importlib.util.spec_from_file_location(
            "intr_destination_ingress_proto", ROOT / "resident-runtime" / "intr_destination_ingress.py")
        module = importlib.util.module_from_spec(ing)
        ing.loader.exec_module(module)
        contract = intr.load_contract()
        dest = contract["destination_capability"]
        binding = {p["id"]: p["equals"] for p in dest["binding_predicates"]}
        self.assertEqual(dest["profile_id"], module.PROFILE_ID)
        self.assertEqual(binding["BINDING_PROFILE_NAME"], module.PROFILE_NAME)
        self.assertEqual(binding["BINDING_OPERATION"], module.OPERATION)
        self.assertEqual(binding["BINDING_PAYLOAD_SCHEMA"], module.PAYLOAD_SCHEMA)
        self.assertEqual(contract["message"]["message_class"], module.COMMUNICATION_CLASS)
        self.assertEqual(tuple(contract["non_allow_fields"]), module.SIX_FIELDS)

    def test_address_uses_the_kernel_slug(self):
        contract = intr.load_contract()
        self.assertEqual(intr.destination_address("StegVerse-Labs", contract),
                         "stegverse-labs.intr-destination")
        self.assertEqual(intr.destination_address("SV-011", contract), "sv-011.intr-destination")


class MeshSnapshot(unittest.TestCase):
    def test_every_destination_matches_its_pinned_result(self):
        report = intr.conform_mesh(SNAPSHOT)
        got = {r["subject"]["organization"]: (r["disposition"], r.get("failed_predicate"))
               for r in report["results"]}
        self.assertEqual(got, EXPECTED)
        self.assertEqual(report["counts"], {"ALLOW": 16, "DENY": 0, "FAIL_CLOSED": 0})
        for row in report["results"]:
            if row["disposition"] != "ALLOW":
                for field in intr.load_contract()["non_allow_fields"]:
                    self.assertTrue(row.get(field), field)

    def test_snapshot_covers_the_federation_directory(self):
        federation = json.loads((ROOT / "org-boundary" / "registry" / "federation.json").read_text())
        manifest = json.loads(SNAPSHOT.read_text())
        declared = sorted(o["organization"] for o in federation["organizations"])
        self.assertEqual(len(declared), federation["denominator"])
        self.assertEqual(sorted(r["organization"] for r in manifest["destinations"]), declared)
        self.assertEqual(sorted(ORGS + UNINSTALLED), declared)

    def test_mesh_report_is_deterministic(self):
        self.assertEqual(intr.canon(intr.conform_mesh(SNAPSHOT)), intr.canon(intr.conform_mesh(SNAPSHOT)))

    def test_tampered_snapshot_bytes_fail_closed(self):
        import tempfile, shutil
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            for f in SNAPSHOT.parent.iterdir():
                shutil.copy(f, dst / f.name)
            path = dst / "StegGhost.services.json"
            path.write_text(path.read_text() + "\n")
            report = intr.conform_mesh(dst / "manifest.json")
            row = next(r for r in report["results"] if r["subject"]["organization"] == "StegGhost")
            self.assertEqual(row["disposition"], "FAIL_CLOSED")
            self.assertEqual(row["failure_code"], "INTR_PROTOCOL_DOCUMENT_UNOBSERVED")

    def test_this_repository_conforms_live(self):
        live_i = json.loads((ROOT / "org-runtime" / "interlock-intr.json").read_text())
        live_s = json.loads((ROOT / "org-boundary" / "registry" / "services.json").read_text())
        self.assertEqual(intr.conform_destination("StegVerse-org", live_i, live_s)["disposition"], "ALLOW")


class Refusals(unittest.TestCase):
    def assertRefusal(self, result, disposition, code, predicate):
        self.assertEqual(result["disposition"], disposition, result)
        self.assertEqual(result["failure_code"], code)
        self.assertEqual(result["failed_predicate"], predicate)
        for field in intr.load_contract()["non_allow_fields"]:
            self.assertTrue(result.get(field), field)
        self.assertEqual(result["owning_existing_goal"], "StegVerse-org/.github#162")

    def binding(self, interlock):
        return next(b for b in interlock["ingress"]["capability_endpoint_bindings"]
                    if b["profile_id"] == "intr-destination")

    def test_unknown_interlock_version_fails_closed(self):
        i, s = snapshot("StegGhost")
        i["schema"] = "stegverse.organization-interlock-intr-boundary/v2"
        self.assertRefusal(intr.conform_destination("StegGhost", i, s),
                           "FAIL_CLOSED", "INTR_PROTOCOL_VERSION_UNKNOWN", "INTERLOCK_SCHEMA_IS_V1")

    def test_wrong_organization_is_denied(self):
        i, s = snapshot("StegGhost")
        self.assertRefusal(intr.conform_destination("StegVerse-002", i, s),
                           "DENY", "INTR_PROTOCOL_VALUE_MISMATCH", "INTERLOCK_IS_THIS_ORGANIZATION")

    def test_github_token_authority_is_denied(self):
        i, s = snapshot("StegGhost")
        self.binding(i)["receiving_operation"]["github_token_runtime_authority"] = "WRITE"
        self.assertRefusal(intr.conform_destination("StegGhost", i, s), "DENY",
                           "INTR_PROTOCOL_VALUE_MISMATCH", "RECEIVER_GITHUB_TOKEN_HAS_NO_RUNTIME_AUTHORITY")

    def test_host_address_is_denied(self):
        i, s = snapshot("SV-LLM")
        self.binding(i)["receiving_operation"]["host_required"] = True
        self.assertRefusal(intr.conform_destination("SV-LLM", i, s), "DENY",
                           "INTR_PROTOCOL_VALUE_MISMATCH", "RECEIVER_NEEDS_NO_HOST")

    def test_address_not_derived_from_organization_is_denied(self):
        i, s = snapshot("GCAT-BCAT-Engine")
        self.binding(i)["receiving_operation"]["addressed_service"] = "gcat.intr-destination"
        self.assertRefusal(intr.conform_destination("GCAT-BCAT-Engine", i, s), "DENY",
                           "INTR_PROTOCOL_VALUE_MISMATCH", "RECEIVER_ADDRESS_DERIVES_FROM_ORGANIZATION")

    def test_missing_binding_fails_closed_and_duplicate_is_denied(self):
        i, s = snapshot("StegVerse-002")
        rows = i["ingress"]["capability_endpoint_bindings"]
        dup = copy.deepcopy(i)
        dup["ingress"]["capability_endpoint_bindings"] = rows + [copy.deepcopy(self.binding(i))]
        i["ingress"]["capability_endpoint_bindings"] = [b for b in rows if b["profile_id"] != "intr-destination"]
        self.assertRefusal(intr.conform_destination("StegVerse-002", i, s), "FAIL_CLOSED",
                           "INTR_PROTOCOL_DESTINATION_BINDING_UNOBSERVED", "EXACTLY_ONE_INTR_DESTINATION_BINDING")
        self.assertRefusal(intr.conform_destination("StegVerse-002", dup, s), "DENY",
                           "INTR_PROTOCOL_DESTINATION_BINDING_AMBIGUOUS", "EXACTLY_ONE_INTR_DESTINATION_BINDING")

    def test_unserved_address_fails_closed(self):
        i, s = snapshot("Admissible-Existence")
        s["services"] = [r for r in s["services"] if r.get("service_id") != "admissible-existence.intr-destination"]
        self.assertRefusal(intr.conform_destination("Admissible-Existence", i, s), "FAIL_CLOSED",
                           "INTR_PROTOCOL_DESTINATION_NOT_SERVED", "REGISTRY_SERVES_THE_DERIVED_ADDRESS_ONCE")

    def test_service_not_accepting_payload_is_denied(self):
        i, s = snapshot("StegVerse-Labs")
        row = next(r for r in s["services"] if r.get("service_id") == "stegverse-labs.intr-destination")
        row["accepts"] = ["ecosystem.communication"]
        self.assertRefusal(intr.conform_destination("StegVerse-Labs", i, s), "DENY",
                           "INTR_PROTOCOL_VALUE_MISMATCH", "SERVICE_ACCEPTS_DESTINATION_PAYLOAD")

    def test_absent_documents_fail_closed(self):
        i, _ = snapshot("StegGhost")
        self.assertRefusal(intr.conform_destination("StegGhost", i, None), "FAIL_CLOSED",
                           "INTR_PROTOCOL_DOCUMENT_UNOBSERVED", "SERVICES_DOCUMENT_IS_AN_OBJECT")
        self.assertRefusal(intr.conform_destination("", i, {}), "FAIL_CLOSED",
                           "INTR_PROTOCOL_SUBJECT_UNOBSERVED", "SUBJECT_NAMES_AN_ORGANIZATION")


class Messages(unittest.TestCase):
    def test_well_formed_message_routes_to_derived_address(self):
        result = intr.conform_message(message(), "SV-LLM")
        self.assertEqual(result["disposition"], "ALLOW")
        self.assertEqual(result["subject"]["destination_address"], "sv-llm.intr-destination")
        self.assertEqual(result["authority_effect"], "NONE_CONFORMANCE_EVIDENCE_ONLY")

    def test_message_refusals(self):
        cases = [
            (message(message_class="request"), "DENY", "MESSAGE_DECLARES_ITS_CLASS"),
            ({k: v for k, v in message().items() if k != "message_class"}, "FAIL_CLOSED", "MESSAGE_DECLARES_ITS_CLASS"),
            (message(communication_id=None), "FAIL_CLOSED", "MESSAGE_CARRIES_A_COMMUNICATION_ID"),
            (message(communication_id="has space"), "DENY", "MESSAGE_CARRIES_A_COMMUNICATION_ID"),
            (message(body={}), "FAIL_CLOSED", "MESSAGE_BODY_DECLARES_ITS_SCHEMA"),
            (message(body={"schema": "other/v1"}), "DENY", "MESSAGE_BODY_DECLARES_ITS_SCHEMA"),
            (message(host="example.invalid"), "DENY", "ROUTE_IS_ADDRESS_NOT_HOST_OR_CREDENTIAL"),
            ("not an object", "FAIL_CLOSED", "MESSAGE_IS_AN_OBJECT"),
        ]
        for payload, disposition, predicate in cases:
            with self.subTest(predicate=predicate, disposition=disposition):
                result = intr.conform_message(payload, "StegGhost")
                self.assertEqual((result["disposition"], result["failed_predicate"]), (disposition, predicate))
                for field in intr.load_contract()["non_allow_fields"]:
                    self.assertTrue(result.get(field), field)
        self.assertEqual(intr.conform_message(message(), None)["failed_predicate"],
                         "ROUTE_NAMES_A_DESTINATION_ORGANIZATION")


if __name__ == "__main__":
    unittest.main()
