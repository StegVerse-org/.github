set -eu
python -m unittest tests.test_node_standing_ingress -v
python -m py_compile org-boundary/runtime/node_standing.py org-kernel/kernel.py \
  org-boundary/runtime/process_boundary.py \
  resident-runtime/sdk_manifest_crossing.py \
  resident-runtime/sdk_self_characterization_egress.py \
  resident-runtime/submit_org_transition_to_master_records.py
