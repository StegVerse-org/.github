from __future__ import annotations
import importlib.util, json, shutil, subprocess, tempfile, textwrap, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
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
        registry={"organization":"Target-Org","services":[service]}
        (root/"org-boundary/registry/services.json").write_text(json.dumps(registry))
        shutil.copy2(ROOT/"org-boundary/runtime/process_boundary.py",root/"org-boundary/runtime/process_boundary.py")
        return root

    def packet(self, service_id: str="target.endpoint"):
        return K.build_packet(
            origin_org="Source-Org",
            origin_service="source.sdk",
            destination_org="Target-Org",
            destination_service=service_id,
            payload={"request":{"bindings":{"manifest_sha256":"a"*64}}},
        )

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
            registry={"organization":"Target-Org","services":[{"service_id":"target.diag","boundary_role":"BOUNDARY_LOCAL_DIAGNOSTIC"}]}
            (root/"org-boundary/registry/services.json").write_text(json.dumps(registry))
            packet=K.build_packet(origin_org="Source-Org",origin_service="source.sdk",destination_org="Target-Org",destination_service="target.diag",payload={"hello":"world"})
            result=K.dispatch(root,packet)
            self.assertEqual(result["application_result"]["echo"],{"hello":"world"})

if __name__=="__main__": unittest.main()
