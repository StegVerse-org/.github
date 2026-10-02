"""An external interaction's identity comes from its manifest, not from this runtime.

Seven module-level constants in `resident-runtime/sdk_self_characterization_egress.py`
used to be the StegVerse-002 self-characterization query, and four of them --
the far side's organization and service, the transition referenced, and the
packet-id prefix -- were values no manifest declared at all. Asking a second
question meant editing the runtime, which is processing selected by something
other than the admitted manifest.

The manifest contract is owned by `StegVerse-org/StegVerse-SDK`. Its
`…interaction_manifest.v2` declares all of it, and these cases cover this
organization's consumption of that declaration: read it, refuse what is
missing, and never complete a gap against a constant.

The finished first generation is covered too, as the separate contract it is.
Its four undeclared values are projected for its schema alone, the result says
so rather than letting a projection read as a declaration, and a v2 manifest
gets no such projection.

Source validation only. No authority effect is claimed.
"""
import hashlib, importlib.util, json, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "eg", ROOT / "resident-runtime/sdk_self_characterization_egress.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)

OBJECTIVE = ("Determine what constitutes the entity identified as StegVerse-002 and produce "
             "a representation sufficient for another system to evaluate and reconstruct "
             "your conclusion.")
GENERIC_OBJECTIVE = ("Return the current task registry generation and the artifacts the "
                     "current task names.")


def canon(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sealed(body):
    """Freeze a manifest the way its owner does: a digest over its own body."""
    return {**body, "manifest_sha256": hashlib.sha256(canon(body)).hexdigest()}


def instructions():
    return {"request_is_manifest_receipt_bound": True, "transport": "InTr",
            "response_instruction": "Return your completed response through this bound Interlock using the manifest/receipt interaction contract.",
            "response_must_bind_request_manifest": True,
            "response_transport_receipts_required": True,
            "master_records_custody_required": True}


def neutral_policy():
    return {key: False for key in M.NON_PRESCRIPTIVE}


def first_generation_manifest(**overrides):
    body = {
        "schema": M.FIRST_GENERATION_MANIFEST,
        "manifest_id": "SDK-SV002-FIRST-SELF-CHARACTERIZATION-001",
        "experiment_id": "STEGVERSE-002-SELF-CHARACTERIZATION-001",
        "source_organization": {"organization_id": "StegVerse-SDK-Evaluator",
                                "role": "EXTERNAL_EVALUATOR_ORGANIZATION"},
        "target": {"entity_id": "StegVerse-002",
                   "relationship_at_manifest_creation": "EXTERNAL_NOT_SELF"},
        "operation": "REQUEST_SELF_CHARACTERIZATION",
        "objective": OBJECTIVE,
        "interaction_instructions": instructions(),
        "knowledge_policy": neutral_policy(),
        "authority_transfer": False,
        "authority_effect_resolution": "DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS"}
    body.update(overrides)
    return sealed(body)


def generic_manifest(**overrides):
    body = {
        "schema": M.GENERIC_MANIFEST,
        "manifest_id": "SDK-TASK-REGISTRY-DISCLOSURE-001",
        "experiment_id": "TASK-REGISTRY-DISCLOSURE-001",
        "generation": 1,
        "predecessor": None,
        "source_organization": {"organization_id": "StegVerse-SDK-Evaluator",
                                "role": "EXTERNAL_EVALUATOR_ORGANIZATION"},
        "target": {"entity_id": "StegVerse-org", "organization": "StegVerse-org",
                   "service": "stegverse-org.llm-adapter",
                   "relationship_at_manifest_creation": "EXTERNAL_NOT_SELF"},
        "operation": "REQUEST_CURRENT_TASK_REGISTRY",
        "objective": GENERIC_OBJECTIVE,
        "transition_reference": "svorg.task-registry.disclosure.v1",
        "packet_id_prefix": "taskreg-disclosure-",
        "interaction_instructions": instructions(),
        "knowledge_policy": neutral_policy(),
        "authority_transfer": False,
        "authority_effect_resolution": "DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS"}
    body.update(overrides)
    return sealed(body)


def request(manifest):
    return {"schema_version": "stegverse.external_organization.interlock_request.v1",
            "request_class": "EXTERNAL_ORGANIZATION_INTERACTION",
            "operation": manifest["operation"],
            "authority_ref": "TV/TVC:test",
            "transport": "InTr",
            "payload": {"manifest": manifest},
            "bindings": {"experiment_id": manifest["experiment_id"],
                         "source_organization_id": manifest["source_organization"]["organization_id"],
                         "target_entity_id": manifest["target"]["entity_id"],
                         "manifest_id": manifest["manifest_id"],
                         "manifest_sha256": manifest["manifest_sha256"]},
            "authority_transfer": False,
            "sdk_mints_intr_receipt": False,
            "sdk_claims_delivery": False,
            "authority_effect_resolution": "DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS"}


class ManifestDeclaredRouteTests(unittest.TestCase):
    """The generic contract: every identity is read from the manifest."""

    def test_the_far_side_is_the_one_the_manifest_declared(self):
        packet = M.build_packet(request(generic_manifest()))
        self.assertEqual(packet["destination"]["org"], "StegVerse-org")
        self.assertEqual(packet["destination"]["service"], "stegverse-org.llm-adapter")

    def test_a_different_declared_far_side_reaches_a_different_surface(self):
        """The point of the change: a second question needs no edit to this runtime."""
        target = {"entity_id": "StegVerse-002", "organization": "StegVerse-002",
                  "service": "stegverse-002.self-characterization",
                  "relationship_at_manifest_creation": "EXTERNAL_NOT_SELF"}
        packet = M.build_packet(request(generic_manifest(target=target)))
        self.assertEqual(packet["destination"]["org"], "StegVerse-002")
        self.assertEqual(packet["destination"]["service"], "stegverse-002.self-characterization")

    def test_the_transition_and_packet_name_come_from_the_manifest(self):
        manifest = generic_manifest()
        packet = M.build_packet(request(manifest))
        self.assertEqual(packet["transition"]["reference"], "svorg.task-registry.disclosure.v1")
        self.assertEqual(packet["packet_id"],
                         "taskreg-disclosure-" + manifest["manifest_sha256"][:24])

    def test_the_result_says_the_route_was_declared_rather_than_projected(self):
        _, transport = M.validate_request(request(generic_manifest()))
        self.assertEqual(transport["contract"], "MANIFEST_DECLARED")

    def test_the_crossing_claims_no_authority(self):
        packet = M.build_packet(request(generic_manifest()))
        self.assertEqual(packet["transition"]["authority_effect"], "NONE_REQUEST_ONLY")


class NothingIsDefaultedTests(unittest.TestCase):
    """An omitted declaration is refused, never completed against a constant."""

    def test_a_manifest_declaring_no_far_side_service_is_refused(self):
        target = {"entity_id": "StegVerse-org", "organization": "StegVerse-org",
                  "relationship_at_manifest_creation": "EXTERNAL_NOT_SELF"}
        with self.assertRaisesRegex(ValueError, "manifest.target.service"):
            M.build_packet(request(generic_manifest(target=target)))

    def test_a_manifest_declaring_no_far_side_organization_is_refused(self):
        target = {"entity_id": "StegVerse-org", "service": "stegverse-org.llm-adapter",
                  "relationship_at_manifest_creation": "EXTERNAL_NOT_SELF"}
        with self.assertRaisesRegex(ValueError, "manifest.target.organization"):
            M.build_packet(request(generic_manifest(target=target)))

    def test_a_manifest_declaring_no_transition_reference_is_refused(self):
        body = {k: v for k, v in generic_manifest().items()
                if k not in ("transition_reference", "manifest_sha256")}
        with self.assertRaisesRegex(ValueError, "manifest.transition_reference"):
            M.build_packet(request(sealed(body)))

    def test_a_manifest_declaring_no_packet_id_prefix_is_refused(self):
        body = {k: v for k, v in generic_manifest().items()
                if k not in ("packet_id_prefix", "manifest_sha256")}
        with self.assertRaisesRegex(ValueError, "manifest.packet_id_prefix"):
            M.build_packet(request(sealed(body)))

    def test_an_unknown_manifest_schema_is_refused_rather_than_guessed(self):
        with self.assertRaisesRegex(ValueError, "unsupported manifest schema"):
            M.build_packet(request(generic_manifest(schema="something.else.v9")))

    def test_a_changed_objective_still_fails_the_digest(self):
        req = request(generic_manifest())
        req["payload"]["manifest"]["objective"] = "changed"
        with self.assertRaisesRegex(ValueError, "manifest hash mismatch"):
            M.build_packet(req)

    def test_an_operation_the_manifest_did_not_declare_is_refused(self):
        req = request(generic_manifest())
        req["operation"] = "REQUEST_SOMETHING_ELSE"
        with self.assertRaisesRegex(ValueError, "operation does not match"):
            M.build_packet(req)

    def test_a_prescriptive_knowledge_policy_is_refused(self):
        policy = {**neutral_policy(), "prescribe_formalism": True}
        with self.assertRaisesRegex(ValueError, "prescriptive"):
            M.build_packet(request(generic_manifest(knowledge_policy=policy)))

    def test_a_request_that_mints_its_own_receipt_is_not_this_contract(self):
        req = request(generic_manifest())
        req["sdk_mints_intr_receipt"] = True
        with self.assertRaisesRegex(ValueError, "sdk_mints_intr_receipt"):
            M.build_packet(req)

    def test_a_rebound_manifest_digest_is_refused(self):
        req = request(generic_manifest())
        req["bindings"]["manifest_sha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "bindings.manifest_sha256"):
            M.build_packet(req)


class ChainOfGenerationsTests(unittest.TestCase):
    """Augment-and-repeat is verifiable, not asserted."""

    def binding(self, predecessor, result, epoch=4096):
        body = {k: v for k, v in predecessor.items() if k != "manifest_sha256"}
        return {"generation": predecessor["generation"],
                "manifest_sha256": hashlib.sha256(canon(body)).hexdigest(),
                "result_sha256": hashlib.sha256(canon(result)).hexdigest(),
                "heartbeat_epoch": epoch}

    def test_a_successor_carries_the_predecessor_it_reviewed(self):
        first = generic_manifest()
        binding = self.binding(first, {"state": "RESPONSE_PERSISTED"})
        second = generic_manifest(generation=2, predecessor=binding,
                                  manifest_id="SDK-TASK-REGISTRY-DISCLOSURE-002")
        packet = M.build_packet(request(second))
        carried = packet["payload"]["request"]["payload"]["manifest"]["predecessor"]
        self.assertEqual(carried["manifest_sha256"], first["manifest_sha256"])
        self.assertEqual(carried["generation"], 1)

    def test_a_first_generation_declares_no_predecessor(self):
        with self.assertRaisesRegex(ValueError, "first generation declares no predecessor"):
            M.build_packet(request(generic_manifest(
                predecessor=self.binding(generic_manifest(), {}))))

    def test_a_later_generation_must_declare_the_one_it_continues(self):
        with self.assertRaisesRegex(ValueError, "declares the predecessor it continues"):
            M.build_packet(request(generic_manifest(generation=2, predecessor=None)))

    def test_an_absent_predecessor_key_is_not_read_as_a_first_generation(self):
        body = {k: v for k, v in generic_manifest().items()
                if k not in ("predecessor", "manifest_sha256")}
        with self.assertRaisesRegex(ValueError, "predecessor must be declared"):
            M.build_packet(request(sealed(body)))

    def test_a_predecessor_generation_that_does_not_precede_is_refused(self):
        binding = self.binding(generic_manifest(), {})
        binding["generation"] = 5
        with self.assertRaisesRegex(ValueError, "predecessor.generation"):
            M.build_packet(request(generic_manifest(generation=2, predecessor=binding)))

    def test_a_predecessor_reference_that_is_not_a_digest_is_refused(self):
        for field in ("manifest_sha256", "result_sha256"):
            with self.subTest(field=field):
                binding = self.binding(generic_manifest(), {})
                binding[field] = "not-a-digest"
                with self.assertRaisesRegex(ValueError, field):
                    M.build_packet(request(generic_manifest(generation=2, predecessor=binding)))

    def test_order_is_an_oscillator_count_this_heartbeat_can_place(self):
        """An epoch below the HB anchor is no observation, not an earlier one."""
        binding = self.binding(generic_manifest(), {}, epoch=M.K.HB_ANCHOR_EPOCH - 1)
        with self.assertRaisesRegex(ValueError, "heartbeat_epoch"):
            M.build_packet(request(generic_manifest(generation=2, predecessor=binding)))

    def test_a_generation_below_one_is_refused(self):
        with self.assertRaisesRegex(ValueError, "manifest.generation"):
            M.build_packet(request(generic_manifest(generation=0)))


class FinishedFirstGenerationTests(unittest.TestCase):
    """The completed interaction stays re-derivable, as its own contract."""

    def test_the_recorded_route_is_still_reached(self):
        packet = M.build_packet(request(first_generation_manifest()))
        self.assertEqual(packet["origin"]["org"], "StegVerse-org")
        self.assertEqual(packet["destination"]["org"], "StegVerse-002")
        self.assertEqual(packet["destination"]["service"], "stegverse-002.self-characterization")

    def test_the_recorded_packet_name_and_transition_are_unchanged(self):
        manifest = first_generation_manifest()
        packet = M.build_packet(request(manifest))
        self.assertEqual(packet["transition"]["reference"], "sv002.self-characterization.request.v0.2")
        self.assertEqual(packet["packet_id"], "sv002-self-char-" + manifest["manifest_sha256"][:24])

    def test_the_result_names_the_route_as_projected_not_declared(self):
        """A projection must not read as something the manifest said."""
        _, transport = M.validate_request(request(first_generation_manifest()))
        self.assertEqual(transport["contract"], "FIRST_GENERATION_PROJECTED")

    def test_a_changed_objective_fails(self):
        req = request(first_generation_manifest())
        req["payload"]["manifest"]["objective"] = "changed"
        with self.assertRaises(ValueError):
            M.build_packet(req)

    def test_the_finished_contract_is_not_asked_for_a_chain_it_never_had(self):
        """It declares no generation, and is not refused for that."""
        manifest = first_generation_manifest()
        self.assertNotIn("generation", manifest)
        M.build_packet(request(manifest))

    def test_the_generic_contract_gets_no_projection(self):
        """Nothing a v2 manifest omits is supplied from the finished interaction."""
        target = {"entity_id": "StegVerse-002",
                  "relationship_at_manifest_creation": "EXTERNAL_NOT_SELF"}
        with self.assertRaisesRegex(ValueError, "manifest.target.organization"):
            M.build_packet(request(generic_manifest(target=target)))


if __name__ == "__main__":
    unittest.main()
