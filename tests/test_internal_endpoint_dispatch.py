from __future__ import annotations
import importlib.util, json, shutil, subprocess, tempfile, textwrap, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
# Every covered ingress class requires canonical node standing, so a packet
# declares its chain position or it does not cross. `predecessor` is present
# and null: explicit genesis, not a default.
CONTRACT = "docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json"

GENESIS = {"mode": "ESTABLISH_GENESIS", "node_ref": "test-node", "predecessor": None}

SPEC=importlib.util.spec_from_file_location("org_kernel",ROOT/"org-kernel/kernel.py")
K=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(K)

ADAPTER=textwrap.dedent("""
    import argparse, json
    from pathlib import Path
    ap=argparse.ArgumentParser(); ap.add_argument("--envelope"); ap.add_argument("--out"); a=ap.parse_args()
    packet=json.loads(Path(a.envelope).read_text())
    Path(a.out).write_text(json.dumps({"adapter_service":packet["destination"]["service"],"ok":True}))
""")

class InternalEndpointDispatchTests(unittest.TestCase):
    def fixture_root(self, td: str, *, service_id: str="target.endpoint", adapter: str|None="adapter.py") -> Path:
        root=Path(td)
        (root/"org-boundary/registry").mkdir(parents=True)
        (root/"org-boundary/runtime").mkdir(parents=True)
        service={"service_id":service_id,"boundary_role":"INTERNAL_ENDPOINT"}
        if adapter is not None:
            service["endpoint_adapter"]=adapter
            service["endpoint_adapter_disposition"]="ALLOW_DECLARED_ADAPTER"
        registry={"organization":"Target-Org","services":[service]}
        (root/"org-boundary/registry/services.json").write_text(json.dumps(registry))
        # The boundary runtime is two files: the dispatcher and the module that
        # selects processing from the manifest rather than from the addressed row.
        for name in ("process_boundary.py", "manifest_selection.py", "node_standing.py"):
            shutil.copy2(ROOT/"org-boundary/runtime"/name, root/"org-boundary/runtime"/name)
        # Standing semantics come from the contract, so the root needs it.
        (root/"docs").mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/CONTRACT, root/CONTRACT)
        return root

    def packet(self, service_id: str="target.endpoint"):
        return K.build_packet(
            origin_org="Source-Org",
            origin_service="source.sdk",
            destination_org="Target-Org",
            destination_service=service_id,
            payload={"request":{"bindings":{"manifest_sha256":"a"*64}}}, standing=GENESIS,)

    def test_registered_non_sdk_internal_endpoint_executes_production_adapter_path(self):
        with tempfile.TemporaryDirectory() as td:
            root=self.fixture_root(td)
            (root/"adapter.py").write_text(ADAPTER)
            result=K.dispatch(root,self.packet())
            self.assertTrue(result["consumed"])
            self.assertEqual(result["service_id"],"target.endpoint")
            self.assertEqual(result["application_result"]["adapter_service"],"target.endpoint")
            response=K.build_endpoint_response(self.packet(),result)
            self.assertEqual(response["destination"]["org"],"Source-Org")
            self.assertEqual(response["payload"]["request_manifest_sha256"],"a"*64)
            self.assertFalse(response["payload"]["authority_transfer"])

    def test_existing_sdk_service_id_still_executes_through_same_generic_path(self):
        with tempfile.TemporaryDirectory() as td:
            root=self.fixture_root(td,service_id="stegverse-org.stegverse-sdk")
            (root/"adapter.py").write_text(ADAPTER)
            result=K.dispatch(root,self.packet("stegverse-org.stegverse-sdk"))
            self.assertEqual(result["application_result"]["adapter_service"],"stegverse-org.stegverse-sdk")

    def test_unknown_service_remains_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=self.fixture_root(td)
            (root/"adapter.py").write_text(ADAPTER)
            with self.assertRaisesRegex(ValueError,"unknown_service"):
                K.dispatch(root,self.packet("missing.endpoint"))

    def test_registered_internal_endpoint_without_adapter_remains_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=self.fixture_root(td,adapter=None)
            with self.assertRaisesRegex(ValueError,"endpoint_adapter_not_installed"):
                K.dispatch(root,self.packet())

    def test_adapter_outside_organization_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            external=Path(outside)/"adapter.py"; external.write_text(ADAPTER)
            root=self.fixture_root(td,adapter=str(external))
            with self.assertRaisesRegex(ValueError,"endpoint_adapter_execution_failed"):
                K.dispatch(root,self.packet())

    def test_adapter_execution_failure_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=self.fixture_root(td)
            (root/"adapter.py").write_text("raise SystemExit(7)\n")
            with self.assertRaisesRegex(ValueError,"endpoint_adapter_execution_failed"):
                K.dispatch(root,self.packet())

    def test_boundary_local_diagnostic_behavior_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/"org-boundary/registry").mkdir(parents=True)
            (root/"org-boundary/runtime").mkdir(parents=True)
            registry={"organization":"Target-Org","services":[{"service_id":"target.diag","boundary_role":"BOUNDARY_LOCAL_DIAGNOSTIC"}]}
            (root/"org-boundary/registry/services.json").write_text(json.dumps(registry))
            # Boundary-local selects no processor, but the result still records
            # that it did not, so the selection module is required here too.
            shutil.copy2(ROOT/"org-boundary/runtime/manifest_selection.py",root/"org-boundary/runtime/manifest_selection.py")
            # Standing is an ingress precondition, so it is required on the
            # boundary-local path too -- it gates every role, not one of them.
            shutil.copy2(ROOT/"org-boundary/runtime/node_standing.py",root/"org-boundary/runtime/node_standing.py")
            (root/"docs").mkdir(parents=True,exist_ok=True); shutil.copy2(ROOT/CONTRACT, root/CONTRACT)
            packet=K.build_packet(origin_org="Source-Org",origin_service="source.sdk",destination_org="Target-Org",destination_service="target.diag",payload={"hello":"world"}, standing=GENESIS)
            result=K.dispatch(root,packet)
            self.assertEqual(result["application_result"]["echo"],{"hello":"world"})

if __name__=="__main__": unittest.main()
