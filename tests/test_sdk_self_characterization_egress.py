import hashlib, importlib.util, json, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("eg",ROOT/"resident-runtime/sdk_self_characterization_egress.py")
M=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)
def canon(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
class EgressTests(unittest.TestCase):
  def request(self):
    manifest={
      "schema":"stegverse.external_organization.interaction_manifest.v1","manifest_id":"SDK-SV002-FIRST-SELF-CHARACTERIZATION-001",
      "experiment_id":M.EXPERIMENT_ID,"source_organization":{"organization_id":M.SOURCE,"role":"EXTERNAL_EVALUATOR_ORGANIZATION"},
      "target":{"entity_id":M.TARGET_ENTITY,"relationship_at_manifest_creation":"EXTERNAL_NOT_SELF"},"operation":M.OPERATION,"objective":M.OBJECTIVE,
      "interaction_instructions":{"request_is_manifest_receipt_bound":True,"transport":"InTr","response_instruction":"Return your completed response through this bound Interlock using the manifest/receipt interaction contract.","response_must_bind_request_manifest":True,"response_transport_receipts_required":True,"master_records_custody_required":True},
      "knowledge_policy":{"prescribe_self_ontology":False,"prescribe_formalism":False,"prescribe_transition_elements":False,"prescribe_external_followup":False,"prescribe_admissible_existence_connection":False},
      "authority_transfer":False,"authority_effect_resolution":"DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS"}
    manifest["manifest_sha256"]=hashlib.sha256(canon(manifest)).hexdigest()
    return {"schema_version":"stegverse.external_organization.interlock_request.v1","request_class":"EXTERNAL_ORGANIZATION_INTERACTION","operation":M.OPERATION,"authority_ref":"TV/TVC:test","transport":"InTr","payload":{"manifest":manifest},"bindings":{"experiment_id":M.EXPERIMENT_ID,"source_organization_id":M.SOURCE,"target_entity_id":M.TARGET_ENTITY,"manifest_id":manifest["manifest_id"],"manifest_sha256":manifest["manifest_sha256"]},"authority_transfer":False,"sdk_mints_intr_receipt":False,"sdk_claims_delivery":False,"authority_effect_resolution":"DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS"}
  def test_exact_route(self):
    p=M.build_packet(self.request()); self.assertEqual(p["origin"]["org"],"StegVerse-org"); self.assertEqual(p["destination"]["org"],"StegVerse-002"); self.assertEqual(p["destination"]["service"],"stegverse-002.self-characterization")
  def test_changed_objective_fails(self):
    r=self.request(); r["payload"]["manifest"]["objective"]="changed"
    with self.assertRaises(ValueError): M.build_packet(r)
if __name__=="__main__": unittest.main()
