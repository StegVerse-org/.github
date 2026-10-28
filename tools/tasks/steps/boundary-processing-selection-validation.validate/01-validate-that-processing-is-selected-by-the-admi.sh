set -eu
python -m unittest tests.test_boundary_processing_selection -v
python -m unittest tests.test_governed_ingress_census -v
python -m py_compile org-boundary/runtime/manifest_selection.py \
  org-boundary/runtime/process_boundary.py org-kernel/kernel.py
