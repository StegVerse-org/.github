#!/usr/bin/env python3
import argparse, json, subprocess, sys, tempfile
from pathlib import Path
from org_boundary_runtime import build_egress, validate_org_crossing
# The boundary processor and its registry are addressed from the repository root,
# so resolve it here rather than inheriting whatever directory the caller is in.
ROOT=Path(__file__).resolve().parents[1]
BOUNDARY_WRITE_FAULT_EXIT=75
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--ingress",required=True); ap.add_argument("--egress",required=True); a=ap.parse_args()
 ingress=json.loads(Path(a.ingress).read_text()); validate_org_crossing(ingress,"INGRESS")
 with tempfile.TemporaryDirectory() as td:
  p=Path(td)/"execution.json"; completed=subprocess.run(["python3",str(ROOT/"org-boundary/runtime/process_boundary.py"),"--envelope",str(Path(a.ingress).resolve()),"--registry",str(ROOT/"org-boundary/registry/services.json"),"--out",str(p)],cwd=str(ROOT),capture_output=True,text=True,check=False)
  # PB-EXIT-SPLIT, every outcome six-field (resident-runtime/writer_cli.py): the
  # boundary's own write fault (75) is a non-terminal WRITE_FAILED, exit 75; any
  # other non-zero exit, a crash, or a result that is missing or not a JSON
  # object is a terminal refusal, exit 1. Never a traceback.
  detail=(completed.stderr or completed.stdout or "").strip().splitlines()
  last=detail[-1][:200] if detail else ""
  if completed.returncode==BOUNDARY_WRITE_FAULT_EXIT:
   raise RuntimeError("PROCESS_BOUNDARY_WRITE_FAULT: "+last)
  if completed.returncode!=0:
   raise SystemExit("PROCESS_BOUNDARY_REFUSED: exit "+str(completed.returncode)+": "+last)
  try:
   result=json.loads(p.read_text(encoding="utf-8"))
  except (OSError,UnicodeDecodeError,ValueError,RecursionError,MemoryError) as exc:
   raise SystemExit("PROCESS_BOUNDARY_RESULT_UNREADABLE: "+type(exc).__name__)
  if not isinstance(result,dict):
   raise SystemExit("PROCESS_BOUNDARY_RESULT_UNREADABLE: "+type(result).__name__)
 egress=build_egress(ingress,result); validate_org_crossing(egress,"EGRESS"); Path(a.egress).parent.mkdir(parents=True,exist_ok=True); Path(a.egress).write_text(json.dumps(egress,indent=2,sort_keys=True)+"\n")
 print(json.dumps({"status":"PASS","packet_id":ingress["packet_id"],"egress_packet_id":egress["packet_id"],"consumed":result["consumed"],"reconstruction":result["reconstruction"]["status"]}))
if __name__=="__main__":
 import importlib.util as _writer_util
 _writer_spec=_writer_util.spec_from_file_location("writer_cli",Path(__file__).resolve().parent/"writer_cli.py")
 _writer=_writer_util.module_from_spec(_writer_spec); _writer_spec.loader.exec_module(_writer)
 sys.exit(_writer.run(main,"resident-runtime/run_once.py",inputs=("--ingress",)))
