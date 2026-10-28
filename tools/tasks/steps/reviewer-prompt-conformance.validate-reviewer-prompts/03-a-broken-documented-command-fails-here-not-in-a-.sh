python - <<'PY'
import pathlib, shutil, subprocess, sys, tempfile

# A conformance job that cannot fail proves nothing, so it is made to
# fail on purpose: a documented entry-point subcommand is renamed in
# a scratch copy and the suite must notice.
source = pathlib.Path("org-boundary/runtime/node_standing.py")
backup = pathlib.Path(tempfile.mkdtemp()) / "node_standing.py"
shutil.copy2(source, backup)
try:
    text = source.read_text(encoding="utf-8")
    broken = text.replace('sub.add_parser("readiness"',
                          'sub.add_parser("readiness_renamed"', 1)
    assert broken != text, "the injection no longer matches; revisit it"
    source.write_text(broken, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "unittest",
         "tests.test_reviewer_prompt_conformance"],
        capture_output=True, text=True)
    assert result.returncode != 0, (
        "a renamed documented subcommand did not fail the suite; "
        "the conformance check is not holding the prompts")
    assert "documents a command that fails" in result.stderr, result.stderr
    print("INJECTION_CAUGHT=PASS a renamed documented subcommand fails the suite")
finally:
    shutil.copy2(backup, source)

# And the restored tree passes again, so the proof left nothing behind.
clean = subprocess.run(
    [sys.executable, "-m", "unittest",
     "tests.test_reviewer_prompt_conformance"],
    capture_output=True, text=True)
assert clean.returncode == 0, clean.stderr
print("RESTORED=PASS the suite is green again")
PY
