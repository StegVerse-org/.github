set -eu
python -m unittest tests.test_internal_endpoint_dispatch -v
python -m py_compile org-boundary/runtime/process_boundary.py org-kernel/kernel.py
