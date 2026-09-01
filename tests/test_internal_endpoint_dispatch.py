from __future__ import annotations
import importlib.util, json, tempfile, textwrap, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("org_kernel",ROOT/"org-kernel/kernel.py")
K=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(K)

class InternalEndpointDispatchTests(unittest.TestCase):
    def test_internal_endpoint_dispatch_and_response(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/"org-boundary/registry").mkdir(parents=True)
            (root/"org-boundary/runtime").mkdir(parents=True)
            registry={"organization":"Target-Org","services":[{"service_id":"target.endpoint","boundary_role":"INTERNAL_ENDPOINT","endpoint_adapter":"adapter.py"}]}
            (root/"org-boundary/registry/services.json").write_text(json.dumps(registry))
            processor=root/"org-boundary/runtime/process_boundary.py"
            processor.write_text(textwrap.dedent("""
                import argparse, json
                from pathlib import Path
                ap=argparse.ArgumentParser(); ap.add_argument("--envelope"); ap.add_argument("--out"); a=ap.parse_args()
                packet=json.loads(Path(a.envelope).read_text())
                Path(a.out).write_text(json.dumps({"service_id":packet["destination"]["service"],"consumed":True,"application_result":{"ok":True},"authority_effect":"NONE","receipts":[],"reconstruction":{"status":"PENDING_MASTER_RECORDS"}}))
            """))
            packet=K.build_packet(origin_org="Source-Org",origin_service="source.sdk",destination_org="Target-Org",destination_service="target.endpoint",payload={"request":{"bindings":{"manifest_sha256":"a"*64}}})
            result=K.dispatch(root,packet)
            self.assertTrue(result["consumed"])
            self.assertEqual(result["service_id"],"target.endpoint")
            response=K.build_endpoint_response(packet,result)
            self.assertEqual(response["destination"]["org"],"Source-Org")
            self.assertEqual(response["destination"]["service"],"source.sdk")
            self.assertEqual(response["payload"]["response_to_packet_id"],packet["packet_id"])
            self.assertEqual(response["payload"]["request_manifest_sha256"],"a"*64)
            self.assertFalse(response["payload"]["authority_transfer"])

if __name__=="__main__": unittest.main()
