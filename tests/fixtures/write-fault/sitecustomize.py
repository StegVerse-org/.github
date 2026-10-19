"""Write-fault injection for writer CLI tests (F-WRITER-TRACE, B-P36q).

Loaded by the interpreter at startup when this directory is on PYTHONPATH.
With STEGVERSE_TEST_FAULT_HEAD_ONCE set to a marker file path, the first
os.replace onto a HEAD.json raises OSError and creates the marker, so a
second process runs clean. With STEGVERSE_TEST_FAULT_AFTER_HEAD_ONCE, the
first such replace completes -- HEAD is committed -- and then raises, as a
failed directory fsync would (F-POST-HEAD). Nothing else is changed.
"""
import os

_before = os.environ.get("STEGVERSE_TEST_FAULT_HEAD_ONCE")
_after = os.environ.get("STEGVERSE_TEST_FAULT_AFTER_HEAD_ONCE")
if _before or _after:
    _real_replace = os.replace
    _marker = _before or _after

    def _faulting_replace(src, dst, *args, **kwargs):
        if str(dst).endswith("HEAD.json") and not os.path.exists(_marker):
            open(_marker, "w").close()
            if _after:
                _real_replace(src, dst, *args, **kwargs)
            raise OSError(5, "Input/output error (injected)", str(dst))
        return _real_replace(src, dst, *args, **kwargs)

    os.replace = _faulting_replace
