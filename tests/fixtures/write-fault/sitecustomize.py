"""Write-fault injection for writer CLI tests (F-WRITER-TRACE, B-P36q).

Loaded by the interpreter at startup when this directory is on PYTHONPATH.
With STEGVERSE_TEST_FAULT_HEAD_ONCE set to a marker file path, the first
os.replace onto a HEAD.json raises OSError and creates the marker, so a
second process runs clean. Nothing else is changed.
"""
import os

_marker = os.environ.get("STEGVERSE_TEST_FAULT_HEAD_ONCE")
if _marker:
    _real_replace = os.replace

    def _faulting_replace(src, dst, *args, **kwargs):
        if str(dst).endswith("HEAD.json") and not os.path.exists(_marker):
            open(_marker, "w").close()
            raise OSError(5, "Input/output error (injected)", str(dst))
        return _real_replace(src, dst, *args, **kwargs)

    os.replace = _faulting_replace
