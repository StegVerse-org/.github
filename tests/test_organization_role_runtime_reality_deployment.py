"""ORGANIZATION-ROLE-RUNTIME-REALITY-DEPLOYMENT-001 source regressions.

Source validation only. Nothing here claims runtime observation, InTr admission,
an emitted organization receipt, Master Records reconstruction, or any authority
effect.
"""
import hashlib
import importlib.util
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = ROOT / "data" / "organization-role-runtime-reality-deployment.json"
REGISTER = ROOT / "data" / "organization-role-exemption-register.json"
CONTRACT = ROOT / ".stegverse" / "transition-ledger" / "org-contract.json"
DOC = ROOT / "docs" / "ORGANIZATION_ROLE_RUNTIME_REALITY_DEPLOYMENT.md"
EMITTER = ROOT / "resident-runtime" / "aggregate_repo_transition.py"

MASTER_RECORDS_ROLE = "RELEASED_ORGANIZATION_BATCH_RECEIPT_RECORDER"
ORGANIZATION = "StegVerse-org"
CANONICAL = "stegverse.canonical-state-transition-receipt/v1"
REPO = "stegverse.repo-transition-receipt/v1"

spec = importlib.util.spec_from_file_location("org_append_role", EMITTER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def repo_receipt(number=1):
    body = {
        "schema": REPO,
        "repository": ORGANIZATION + "/StegVerse-SDK",
        "transition_id": "repo-" + str(number),
    }
    return {**body, "receipt_sha256": module.sha(body)}


def canonical_receipt(number=1, **overrides):
    """A canonical governed state transition carrying exact inline evidence."""
    transition_id = "CANONICAL-STATE-TRANSITION-" + str(number)
    content = {"transition_id": transition_id, "element": "governed-closure"}
    receipt = {
        "schema": CANONICAL,
        "transition_id": transition_id,
        "transition_sequence": number,
        "subject_or_correlation_id": "subject-" + str(number),
        "transition_outcome": "OBSERVED",
        "required_evidence_manifest": [
            {
                "evidence_id": "governed_transition_elements",
                "evidence_type": "CANONICAL_STATE_TRANSITION_ELEMENTS",
                "origin_transition_id": transition_id,
                "encoding": "canonical-json",
                "content": content,
                "sha256": hashlib.sha256(module.canon(content)).hexdigest(),
            }
        ],
    }
    receipt.update(overrides)
    return receipt


class DeclarationTests(unittest.TestCase):
    def test_declaration_grants_no_authority_and_claims_only_source_evidence(self):
        declaration = load_json(DECLARATION)
        self.assertEqual(declaration["authority_effect"], "NONE_DECLARATION_ONLY")
        self.assertEqual(declaration["evidence_class"], "SOURCE_IMPLEMENTED")
        self.assertEqual(declaration["completion_evidence_contract_version"], "v1")
        for prohibition in (
            "MUTATE_ANY_CANONICAL_TASK_RECORD",
            "CLOSE_ANY_GOAL",
            "CLAIM_RUNTIME_OBSERVATION",
            "CLAIM_INTR_ADMISSION",
            "CLAIM_AN_EMITTED_ORGANIZATION_RECEIPT",
            "CLAIM_MASTER_RECORDS_RECONSTRUCTION",
            "GRANT_TRANSITION_EXECUTION_CUSTODY_OR_CREDENTIAL_AUTHORITY",
            "REQUIRE_AN_EXTERNAL_MACHINE_OR_SECOND_DEVICE",
        ):
            self.assertIn(prohibition, declaration["this_declaration_does_not"])
        self.assertEqual(declaration["role_change"]["previous_value"], "Master Records")
        self.assertEqual(declaration["role_change"]["current_value"], "Organization")

    def test_declaration_is_deployed_per_organization_not_system_wide(self):
        declaration = load_json(DECLARATION)
        self.assertEqual(declaration["organization"], ORGANIZATION)
        self.assertEqual(
            declaration["deployment_scope"],
            "THIS_ORGANIZATION_ONLY_EACH_ORGANIZATION_DEPLOYS_IN_ITS_OWN_DOT_GITHUB",
        )

    def test_master_records_is_restated_without_reality_authority(self):
        restated = load_json(DECLARATION)["master_records_restated_role"]
        self.assertEqual(restated["role"], MASTER_RECORDS_ROLE)
        self.assertEqual(restated["runtime_reality_authority"], "NONE")
        self.assertEqual(restated["transition_authority"], "NONE")
        self.assertIs(restated["may_gate_organization_runtime_reality"], False)
        self.assertIs(restated["may_be_awaited_by_a_transition"], False)
        self.assertEqual(
            restated["release_predecessor_required"],
            "VERIFIED_ORGANIZATION_RECEIPT_CHAIN_SEGMENT",
        )
        for retained in ("CUSTODY", "RECONSTRUCTION", "CROSS_ORGANIZATION_HISTORY"):
            self.assertIn(retained, restated["retained_capabilities"])

    def test_authorities_this_deployment_does_not_move_are_restated(self):
        unchanged = load_json(DECLARATION)["unchanged_authorities"]
        self.assertEqual(unchanged["transition_authority"], "Interlock/InTr")
        self.assertEqual(unchanged["worker_claim_authority"], "WorkerCoordinator")
        self.assertEqual(unchanged["credential_authority"], "TV/TVC")
        self.assertEqual(unchanged["user_verification_authority"], "KV/SKAP Vault")

    def test_manifest_bound_state_transition_standard_is_declared(self):
        standard = load_json(DECLARATION)["conformance_standard"]
        self.assertIs(standard["actions_by_manifest_required"], True)
        self.assertIs(standard["state_transition_dependent"], True)
        self.assertIs(standard["external_machine_awaiting_allowed"], False)
        self.assertIs(standard["destination_liveness_is_transition_predicate"], False)
        self.assertIs(standard["always_on_receiver_required"], False)
        self.assertIs(standard["post_closure_authentic_observer_gate_allowed"], False)
        self.assertEqual(
            standard["receiver_unavailable_disposition"],
            "DURABLE_QUEUE_OR_EVENT_EPHEMERAL_MATERIALIZATION",
        )
        self.assertEqual(
            standard["destination_sufficiency_rule"],
            "MANIFEST_DETERMINES_THE_DESTINATION_AND_AN_EXISTING_DESTINATION_IS_SUFFICIENT_FOR_INGRESS_AND_EGRESS",
        )

    def test_completion_evidence_class_vocabulary_is_explicitly_unchanged(self):
        vocabulary = load_json(DECLARATION)["deferred_record_side_reconciliation"][
            "completion_evidence_class_vocabulary"
        ]
        self.assertEqual(vocabulary["key"], "MASTER_RECORDS_RECONSTRUCTED")
        self.assertEqual(vocabulary["disposition"], "UNCHANGED_IN_THIS_DECLARATION")


class ExemptionRegisterTests(unittest.TestCase):
    def test_non_conforming_surface_must_hold_a_registered_exemption(self):
        standard = load_json(DECLARATION)["conformance_standard"]
        self.assertEqual(standard["non_conforming_surface_disposition"],
                         "DECLARED_EXEMPTION_REQUIRED")
        self.assertEqual(standard["non_conforming_surface_failure_code"],
                         "ORGANIZATION_ROLE_CONFORMANCE_NOT_DECLARED")
        register = load_json(REGISTER)
        self.assertIs(register["silent_non_conformance_allowed"], False)
        self.assertIs(register["exemption_grants_authority"], False)
        self.assertIs(register["exemption_may_satisfy_a_terminal_predicate"], False)
        self.assertEqual(register["authority_effect"], "NONE_REGISTER_ONLY")

    def test_register_refuses_the_justifications_the_standard_forbids(self):
        prohibited = set(load_json(REGISTER)["prohibited_justifications"])
        for refused in (
            "AN_EXTERNAL_MACHINE_MUST_BE_RUNNING",
            "A_SECOND_USER_OPERATED_DEVICE_IS_REQUIRED",
            "A_REMOTE_COMPUTER_IS_UNAVAILABLE",
            "EVIDENCE_REACHABILITY_IS_PENDING",
            "A_RECEIVER_IS_NOT_ALWAYS_ON",
            "AN_AUTHENTIC_OBSERVER_HAS_NOT_YET_LOOKED",
        ):
            self.assertIn(refused, prohibited)

    def test_register_opens_empty_and_is_reachable_from_the_declaration(self):
        register = load_json(REGISTER)
        declaration = load_json(DECLARATION)
        self.assertEqual(register["exemptions"], [])
        self.assertIs(declaration["exemption_path"]["register_opens_empty"], True)
        self.assertEqual(register["declaration"], declaration["declaration_id"])
        self.assertTrue((ROOT / declaration["exemption_path"]["register"]).is_file())
        # Every field the declaration requires of an exemption is required by the
        # register itself, so neither surface can drift into a weaker demand.
        self.assertEqual(sorted(register["required_fields"]),
                         sorted(declaration["exemption_path"]["required_fields"]))

    def test_every_registered_exemption_carries_an_actionable_disposition(self):
        """An exemption is a non-ALLOW disposition, never a bare blocker."""
        register = load_json(REGISTER)
        required = set(register["required_fields"])
        prohibited = set(register["prohibited_justifications"])
        for exemption in register["exemptions"]:
            missing = required - set(exemption)
            self.assertEqual(missing, set(), "exemption missing required fields")
            self.assertNotIn(
                exemption["why_manifest_bound_state_transition_is_not_yet_possible"],
                prohibited,
            )


class SupersededProseTests(unittest.TestCase):
    def test_superseded_prose_inventory_is_measured_and_still_exact(self):
        """The enumerated supersession set must match what the tree actually says.

        This organization measures empty. The emptiness is asserted by the same
        measurement that would enumerate a non-empty set, so a Master Records
        reality-authority statement added later fails here rather than passing
        silently.
        """
        inventory = load_json(DECLARATION)["superseded_prose_statements"]
        self.assertIs(inventory["cross_owner_edit_performed"], False)
        self.assertEqual(inventory["comparison_key"], "PATH_AND_STATEMENT_TEXT")
        self.assertIs(inventory["line_numbers_are_provenance_only"], True)
        occurrences = inventory["occurrences"]
        self.assertEqual(inventory["count"], len(occurrences))
        pattern = re.compile(
            r"Master Records\s*(?:remains|is|=)\s*[^.;]*?"
            r"(?:observed[- ]reality|runtime[- ]reality|observed runtime reality)[^.;]*[.;]?"
        )
        measured = []
        for path in [ROOT / "README.md"] + sorted((ROOT / "docs").glob("*.md")):
            if path == DOC:
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                for match in pattern.finditer(line):
                    measured.append((str(path.relative_to(ROOT)), match.group(0).strip()))
        declared = [(entry["path"], entry["statement"]) for entry in occurrences]
        self.assertEqual(sorted(measured), sorted(declared),
                         "the superseded-prose set has drifted from the tree; "
                         "re-measure it in "
                         "data/organization-role-runtime-reality-deployment.json")
        self.assertEqual(inventory["files"],
                         sorted({entry["path"] for entry in occurrences}))
        if not occurrences:
            self.assertIn("measured_empty_reason", inventory)

    def test_retained_custody_only_statements_are_not_claimed_as_superseded(self):
        retained = load_json(DECLARATION)["retained_statements"]
        self.assertIn("CUSTODY_RECONSTRUCTION_ONLY", retained["rule"])
        for example in retained["examples_in_this_organization"]:
            self.assertTrue((ROOT / example).is_file())


class LedgerContractTests(unittest.TestCase):
    def test_organization_ledger_contract_declares_the_reality_locus(self):
        contract = load_json(CONTRACT)
        self.assertEqual(contract["organization"], ORGANIZATION)
        self.assertIs(contract["ledger_root_is_organization_runtime_reality_locus"], True)
        self.assertEqual(contract["runtime_reality_authority"], "Organization")
        self.assertEqual(contract["ledger_lock"], "ORGANIZATION_LEDGER_LOCK")
        self.assertEqual(contract["write_mode"], "MANIFEST_DIRECTED_APPEND")
        self.assertEqual(contract["propagation_role"], MASTER_RECORDS_ROLE)
        self.assertIs(contract["propagation_gates_organization_runtime_reality"], False)
        self.assertIs(contract["always_on_receiver_required"], False)
        self.assertEqual(contract["propagation_receiver_unavailable_disposition"],
                         "DURABLE_QUEUE_OR_EVENT_EPHEMERAL_MATERIALIZATION")
        self.assertEqual(contract["authority_effect"], "NONE_CONTRACT_ONLY")
        self.assertEqual(contract["declaration"], load_json(DECLARATION)["declaration_id"])

    def test_contract_consumes_a_canonical_state_transition_not_only_a_repo_receipt(self):
        """The organization scope rule needs a path for a governed transition."""
        contract = load_json(CONTRACT)
        consumes = contract["consumes"]
        self.assertIsInstance(consumes, list)
        self.assertIn(REPO, consumes)
        self.assertIn(CANONICAL, consumes)
        self.assertEqual(
            contract["organization_scope_rule"],
            "EVERY_STATE_TRANSITION_OCCURRING_WITHIN_THE_ORGANIZATION_EMITS_AN_ORGANIZATION_RECEIPT",
        )
        self.assertIs(contract["preserves_source_transition_receipt"], True)
        self.assertIs(contract["preserves_repo_receipt"], True)

    def test_declaration_generalization_block_agrees_with_the_contract(self):
        block = load_json(DECLARATION)["organization_scope_rule_path_generalization"]
        self.assertIs(block["due_independently_of_the_role_change"], True)
        self.assertIs(block["canonical_state_transition_relabelled_as_repository_transition"],
                      False)
        self.assertEqual(block["canonical_state_transition_binding"],
                         "BOUND_BY_ITS_OWN_CANONICAL_DIGEST")
        self.assertEqual(sorted(block["consumes"]), sorted(load_json(CONTRACT)["consumes"]))
        self.assertTrue((ROOT / block["emitter"]).is_file())


class EmitterAdmissionTests(unittest.TestCase):
    """The emitter's admission gate is the contract, not a hard-coded schema."""

    def test_a_repo_receipt_still_binds_its_repository_transition(self):
        source = module.verify_source(repo_receipt(1))
        self.assertEqual(source["source_receipt_schema"], REPO)
        self.assertEqual(source["source_repository"], ORGANIZATION + "/StegVerse-SDK")
        self.assertEqual(source["repo_transition_id"], "repo-1")
        self.assertEqual(source["repo_receipt_sha256"], source["source_transition_sha256"])
        self.assertIsNone(source["canonical_state_transition_receipt_sha256"])

    def test_a_canonical_state_transition_is_bound_by_its_own_digest(self):
        receipt = canonical_receipt(1)
        source = module.verify_source(receipt)
        self.assertEqual(source["source_receipt_schema"], CANONICAL)
        self.assertEqual(source["source_transition_sha256"], module.sha(receipt))
        self.assertEqual(source["canonical_state_transition_receipt_sha256"],
                         module.sha(receipt))
        self.assertEqual(source["source_transition_id"], receipt["transition_id"])
        self.assertEqual(source["subject_or_correlation_id"], "subject-1")
        # It is not relabelled as a repository transition it is not.
        self.assertIsNone(source["source_repository"])
        self.assertIsNone(source["repo_receipt_sha256"])
        self.assertIsNone(source["repo_transition_id"])

    def test_a_schema_outside_the_contract_consumes_list_is_refused(self):
        with self.assertRaisesRegex(SystemExit, "source receipt schema mismatch"):
            module.verify_source({"schema": "stegverse.not-consumed/v1",
                                  "transition_id": "x"})

    def test_a_canonical_transition_without_inline_evidence_bytes_is_refused(self):
        receipt = canonical_receipt(1)
        receipt.pop("required_evidence_manifest")
        with self.assertRaisesRegex(SystemExit, "required evidence manifest missing"):
            module.verify_source(receipt)

    def test_a_canonical_evidence_digest_mismatch_is_refused(self):
        receipt = canonical_receipt(1)
        receipt["required_evidence_manifest"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(SystemExit, "required evidence digest mismatch"):
            module.verify_source(receipt)

    def test_canonical_evidence_must_bind_its_own_origin_transition(self):
        receipt = canonical_receipt(1)
        receipt["required_evidence_manifest"][0]["origin_transition_id"] = "other"
        with self.assertRaisesRegex(SystemExit, "transition binding invalid"):
            module.verify_source(receipt)

    def test_a_repo_receipt_outside_this_organization_is_still_refused(self):
        receipt = repo_receipt(1)
        receipt["repository"] = "Other-org/Thing"
        receipt["receipt_sha256"] = module.sha(
            {k: v for k, v in receipt.items() if k != "receipt_sha256"})
        with self.assertRaisesRegex(SystemExit, "repo outside organization"):
            module.verify_source(receipt)

    def test_an_inadmissible_receipt_never_creates_the_ledger_root(self):
        """Admission is decided before the append lock is taken."""
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "ledger"
            with patch.dict(os.environ, {"STEGVERSE_ORG_LEDGER_ROOT": str(root)}):
                with self.assertRaises(SystemExit):
                    module.append({"schema": "stegverse.not-consumed/v1",
                                   "transition_id": "x"},
                                  "ORGANIZATION_STATE_TRANSITION",
                                  "before", "after", {}, "NONE")
            self.assertFalse(root.exists())


class EmitterAppendTests(unittest.TestCase):
    def test_a_canonical_state_transition_emits_an_organization_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {"STEGVERSE_ORG_LEDGER_ROOT": root}):
                receipt = canonical_receipt(1)
                record = module.append(receipt, "ORGANIZATION_STATE_TRANSITION",
                                       "before", "after", {}, "NONE")
                self.assertEqual(record["schema"],
                                 "stegverse.organization-transition-receipt/v1")
                self.assertEqual(record["organization"], ORGANIZATION)
                self.assertEqual(record["source_receipt_schema"], CANONICAL)
                self.assertEqual(record["canonical_state_transition_receipt_sha256"],
                                 module.sha(receipt))
                self.assertIsNone(record["source_repository"])
                self.assertEqual(record["authority_effect"], "NONE")
                head = json.loads((Path(root) / "HEAD.json").read_text())
                self.assertEqual(head["receipt_sha256"], record["receipt_sha256"])

    def test_both_consumed_schemas_append_onto_one_organization_chain(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {"STEGVERSE_ORG_LEDGER_ROOT": root}):
                first = module.append(repo_receipt(1), "REPO_STATE_PROPAGATION",
                                      "before", "after", {}, "NONE")
                second = module.append(canonical_receipt(2),
                                       "ORGANIZATION_STATE_TRANSITION",
                                       "before", "after", {}, "NONE")
                self.assertIsNone(first["previous_receipt_sha256"])
                self.assertEqual(second["previous_receipt_sha256"],
                                 first["receipt_sha256"])
                receipts = sorted((Path(root) / "receipts").glob("*.json"))
                self.assertEqual(len(receipts), 2)


class DeclarationDocTests(unittest.TestCase):
    def test_declaration_doc_states_the_change_and_the_exemption_path(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("runtime_reality_authority:  Master Records  ->  Organization", text)
        self.assertIn("recorder of released organization batch receipts", text)
        self.assertIn("data/organization-role-exemption-register.json", text)
        self.assertIn("SOURCE_IMPLEMENTED", text)
        self.assertIn("MASTER_RECORDS_RECONSTRUCTED", text)
        self.assertIn(CANONICAL, text)
        self.assertIn(ORGANIZATION, text)


if __name__ == "__main__":
    unittest.main()
