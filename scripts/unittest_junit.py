#!/usr/bin/env python3
"""Run tests/ (all, or the files a change selected) with the standard library's unittest; record JUnit XML.

This repository's own workflows run their tests with python -m unittest, and
pytest is not one of its CI dependencies, so the selected-tests job uses the
same runner over exactly the files select_tests_for_change.py selected for the
change (or every tests/**/test_*.py), nothing deselected or filtered. The XML
it writes is read by test_suite_skip_receipt.py, which lists every skip in the
selected set and fails closed on any.

Each skip, failure, error, expected failure and unexpected success is
recorded under the test's own id. A module that fails to import is an error
under its module name, never dropped. Standard library only; the XML carries
no timings, so the same run gives the same bytes.

Exit status: 0 when the run completed and the XML was written (its content is
judged by test_suite_skip_receipt.py, not here), 2 when it could not be.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET


CURRENT_MODULE = [""]  # the dotted module being loaded, for a module that fails to import


def split_id(test) -> tuple[str, str]:
    """(classname, name) for a test, a subtest's parent, or an _ErrorHolder."""
    if isinstance(test, unittest.case._SubTest):
        test = test.test_case
    description = getattr(test, "description", None)
    if description is not None:  # _ErrorHolder: "setUpClass (module.Class)" or a module name
        if " (" in description and description.endswith(")"):
            fixture, owner = description[:-1].split(" (", 1)
            return owner, fixture
        return "", description
    tid = test.id()
    if tid.startswith("unittest.loader._FailedTest."):
        return "", CURRENT_MODULE[0] or tid.rsplit(".", 1)[1]
    classname, _, name = tid.rpartition(".")
    return classname, name


class RecordingResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.cases: dict[tuple[str, str], dict] = {}

    def _case(self, test) -> dict:
        key = split_id(test)
        return self.cases.setdefault(key, {"outcome": "passed", "message": ""})

    def _set(self, test, outcome: str, message: str) -> None:
        case = self._case(test)
        rank = ("passed", "xfailed", "skipped", "failure", "error")
        if rank.index(outcome) >= rank.index(case["outcome"]):
            case["outcome"], case["message"] = outcome, message

    def startTest(self, test):
        super().startTest(test)
        self._case(test)

    def addError(self, test, err):
        super().addError(test, err)
        self._set(test, "error", f"{err[0].__name__}: {err[1]}")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._set(test, "failure", f"{err[0].__name__}: {err[1]}")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            failed = issubclass(err[0], test.failureException)
            self._set(test, "failure" if failed else "error", f"{subtest}: {err[0].__name__}: {err[1]}")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._set(test, "skipped", str(reason))

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._set(test, "xfailed", "expected failure")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._set(test, "failure", "unexpected success of an expectedFailure test")


def to_xml(result: RecordingResult) -> bytes:
    suites = ET.Element("testsuites")
    suite = ET.SubElement(suites, "testsuite", name="unittest")
    for (classname, name), case in sorted(result.cases.items()):
        element = ET.SubElement(suite, "testcase", classname=classname, name=name)
        outcome, message = case["outcome"], case["message"][:2000]
        if outcome == "skipped":
            ET.SubElement(element, "skipped", type="unittest.skip", message=message)
        elif outcome == "xfailed":
            ET.SubElement(element, "skipped", type="pytest.xfail", message=message)
        elif outcome in ("failure", "error"):
            ET.SubElement(element, outcome, message=message)
    return ET.tostring(suites, encoding="utf-8", xml_declaration=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tests-from", type=Path,
                        help="run only these test files (one repo-relative path per line), "
                             "as selected by select_tests_for_change.py; default: every tests/**/test_*.py")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    sys.path.insert(0, str(root))
    result = RecordingResult()
    result.buffer = True  # a test's own prints stay out of the log
    if args.tests_from is not None:
        wanted = [line.strip() for line in args.tests_from.read_text(encoding="utf-8").splitlines()
                  if line.strip()]
        paths = sorted(root / w for w in wanted if (root / w).is_file())
    else:
        paths = sorted((root / "tests").rglob("test_*.py"))
    for path in paths:
        # By dotted name, the way this repository's workflows run each module
        # (python -m unittest tests.test_x); tests/ is a namespace package, which
        # unittest discovery does not walk.
        name = ".".join(path.relative_to(root).with_suffix("").parts)
        CURRENT_MODULE[0] = name
        try:
            suite = unittest.defaultTestLoader.loadTestsFromName(name)
        except Exception as exc:  # an import that raises is an error under the module's name
            result.cases[("", name)] = {"outcome": "error", "message": f"{type(exc).__name__}: {exc}"}
            continue
        suite.run(result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(to_xml(result))
    counts = {}
    for case in result.cases.values():
        counts[case["outcome"]] = counts.get(case["outcome"], 0) + 1
    print("FULL_SUITE_UNITTEST " + " ".join(f"{k}={counts.get(k, 0)}" for k in
                                            ("passed", "failure", "error", "skipped", "xfailed")))
    return 0 if (result.cases or not paths) else 2


if __name__ == "__main__":
    sys.exit(main())
