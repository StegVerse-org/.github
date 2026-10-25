python - <<'PY'
import importlib.util, json, os
from pathlib import Path
from stegverse.manifest_builder import build_manifest
spec = importlib.util.spec_from_file_location(
    "ingress", "resident-runtime/organization_manifest_ingress.py")
ingress = importlib.util.module_from_spec(spec); spec.loader.exec_module(ingress)

# Each refused submission is one refusal receipt at each ledger level.
# A route-related refusal also records its disposition delivery, so
# the count below is the submission's own refusal, not every receipt.
def receipts(variable, schema, transition_class=None):
    found = [json.loads(p.read_text()) for p in Path(os.environ[variable]).rglob("*.json")
             if json.loads(p.read_text()).get("schema") == schema]
    if transition_class is not None:
        found = [r for r in found if r.get("transition_class") == transition_class]
    return found

# A capability no organization service admits. Governance is admitted
# now, so a governance manifest no longer exercises the refusal.
unadmitted = json.loads(Path("tests/fixtures/sdk-manifest-build-spec.json")
                        .read_text())["manifests"]["unadmitted-capability-to-task-registry-disclosure"]

def governed(output_id):
    return build_manifest(
        data=unadmitted["data"], source_framework="organization-boundary-ci",
        source_output_id=output_id, process=unadmitted["process"],
        processor_request=unadmitted["processor_request"],
        created_at="2026-10-03T00:00:00Z")

genesis = {"mode": "ESTABLISH_GENESIS", "node_ref": "ci", "predecessor": None}
registry = json.loads(Path("org-boundary/registry/services.json").read_text())
out = ingress.receive(governed("unadmitted-capability-ci"), registry=registry,
                      packet_id="ci-unadmitted", hb_epoch=32, standing=genesis)
assert out["disposition"] == "FAIL_CLOSED"
assert out["received"] is False
# The submission arrived, so its disposition is a transition and is recorded.
assert out["refusal_recorded"] is True
assert out["refusal_transition_class"] == "ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED"
assert out["refusal_repository_receipt_sha256"].startswith("sha256:")
assert out["refusal_organization_receipt_sha256"].startswith("sha256:")
# And never as an admission: this means an admitted crossing was observed.
assert out["organization_receipt_observed"] is False
assert "organization_receipt_sha256" not in out
# D7: the route binds execute_manifest and no service admits the pair,
# so the ingress fails it closed before any crossing, stored as FAIL_CLOSED.
assert out["failure_code"] == "PROCESSING_SERVICE_NOT_DECLARED_FOR_CONSUMER_ROUTE", out
assert out["failed_predicate"] == "CONSUMER_ROUTE_RESOLVES_TO_A_DECLARED_PROCESSING_SERVICE", out
assert out["owning_existing_goal"] == "INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001", out
assert out["refusal_stored_disposition"] == "FAIL_CLOSED", out
assert "crossing" not in out and "resolved_service_id" not in out, out

# A manifest the crossing cannot drive at all used to leave by exception.
# An admitted manifest, so the crossing itself refuses it, and its six
# fields are passed through rather than overwritten by the ingress.
build = json.loads(Path("tests/fixtures/sdk-manifest-build-spec.json").read_text())
def admitted(output_id):
    return build_manifest(**{"data": build["data"], "processor_request": build["processor_request"],
                             **build["common"],
                             **build["manifests"]["task-registry-disclosure"],
                             "source_output_id": output_id})
raised = ingress.receive(admitted("no-declared-standing-ci"), registry=registry,
                         packet_id="ci-no-standing", hb_epoch=32, standing=None)
assert raised["failed_predicate"] == "CROSSING_STANDING_IS_DERIVED_FROM_THE_MANIFEST_OR_DECLARED", raised
assert raised["failure_code"] == "CROSSING_REQUIRES_DECLARED_STANDING", raised
assert raised["retry_entrypoint"] == "resident-runtime/sdk_manifest_crossing.py::cross", raised
# A defect of the submission: DENY, and the returned disposition is the stored one.
assert raised["disposition"] == "DENY", raised
assert raised["refusal_stored_disposition"] == "DENY", raised
assert raised["refusal_recorded"] is True

# Two refusals, recorded at both levels, the organization consuming the
# repository receipt rather than authoring its own.
repository = receipts("STEGVERSE_REPO_LEDGER_ROOT",
                      "stegverse.repo-transition-receipt/v1",
                      "ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED")
organization = [r for r in receipts("STEGVERSE_ORG_LEDGER_ROOT",
                                    "stegverse.organization-transition-receipt/v1")
                if (r.get("boundary_evidence") or {}).get("receiving_operation")
                == "ORGANIZATION_SDK_MANIFEST_INGRESS"]
assert len(repository) == 2, len(repository)
assert len(organization) == 2, len(organization)
assert all(r["transition_class"] == "ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED"
           for r in repository), [r["transition_class"] for r in repository]
carried = {o["repo_receipt_sha256"] for o in organization}
assert carried == {r["receipt_sha256"] for r in repository}
assert all(o["source_repository"] == "StegVerse-org/.github" for o in organization)
assert all(o["org_transition_class"] == "REPO_STATE_PROPAGATION" for o in organization)
# The disposition is keyed on (failure_code, failed_predicate): D7 is
# FAIL_CLOSED, the submission defect is DENY, each stored as returned.
stored = {(r["evidence"]["failure_code"], r["evidence"]["failed_predicate"]): r["evidence"]["disposition"]
          for r in repository}
d7 = ("PROCESSING_SERVICE_NOT_DECLARED_FOR_CONSUMER_ROUTE",
      "CONSUMER_ROUTE_RESOLVES_TO_A_DECLARED_PROCESSING_SERVICE")
standing_gap = ("CROSSING_REQUIRES_DECLARED_STANDING",
                "CROSSING_STANDING_IS_DERIVED_FROM_THE_MANIFEST_OR_DECLARED")
assert stored == {d7: "FAIL_CLOSED", standing_gap: "DENY"}, stored
assert stored == {pair: ingress.REFUSAL_DISPOSITIONS[pair] for pair in stored}, stored
assert stored[standing_gap] == raised["disposition"]
assert stored[d7] == out["disposition"]
for r in repository:
    record = r["evidence"]
    assert record["intended_action"] == "RECEIVE_A_SUBMITTED_SDK_MANIFEST"
    assert record["transition_is_the_disposition_of_the_intended_action"] is True
    assert "resolved_service_id" not in record
print("REFUSED_SUBMISSION_IS_RECORDED=PASS", out["failed_predicate"])
PY
