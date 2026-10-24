#!/usr/bin/env python3
"""Select the tests a change needs, from a path-to-test-set map declared in this repository.

Rigel's rule (Oct 23): a pull request is admission-input-ready only when every
test it needs ran on its exact head with 0 skipped; the rule never stops work
and never blocks a pull request on tests it does not need. So the suite is
split into callable sets, selected by what the change touches, through a map
committed at data/test-selection-map.json:

- references, derived from the head's own bytes by the declared method
  (``reference_method``): repository path -> the test files that read it (a
  literal repo path containing "/" in the test, a path it joins under ROOT,
  or a Python module it imports, never resolved to a component's packaged
  payload copy; closed over this repository's own Python
  files, so a path a module the test loads names is the test's too). Derived at selection time from the
  tree being judged, so the map cannot go stale; ``--references`` prints them.
- ``rules``: declared path globs -> test globs, for what references miss.
- ``no_test_paths``: globs for paths no test reads (prose, images). A path a
  test references is selected even when it also matches here.

Selection, for each changed path, in this order: a changed test file selects
itself; a path in ``references`` selects its tests; a matching rule selects its
tests; a ``no_test_paths`` match selects nothing; any other path is unmapped
and selects the whole suite (``unmapped_path_policy``), so a gap in the map
over-selects and never under-selects. A deleted path is treated the same way.

Nothing here marks a test as bypassable. A test that is not selected is listed
as not selected for this change; it is not run for this verdict and is never
reported as passing. Deterministic: the changed-path list is an input file,
and nothing reads a clock, the network or the environment. Standard library
only. Non-authorizing.
"""
from __future__ import annotations

import argparse
import ast
from fnmatch import fnmatchcase
import json
from pathlib import Path
import re
import sys
import warnings

SCHEMA = "stegverse.test-selection-map/v1"
SELECTION_SCHEMA = "stegverse.test-selection/v1"
LITERAL = re.compile(r"""["']([A-Za-z0-9_.\-][A-Za-z0-9_.\-/]*)["']""")
JOINED = re.compile(r"""(?:/\s*["'][A-Za-z0-9_.\-][A-Za-z0-9_.\-/]*["']\s*){1,}""")
PART = re.compile(r"""["']([^"']+)["']""")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}
# A component's packaged payload (components/<id>/<version>/files/ or templates/) is bytes an
# installer copies into another tree; nothing here imports it by module name. Resolving an
# import by stem to such a copy would make every test that imports the live module
# (e.g. resident-runtime/ledger_store.py) a test of the vendored copy too. A test that names a
# payload path literally still selects it through referenced_paths.
PAYLOAD = re.compile(r"^components/.+/(?:files|templates)/")


def repo_files(root: Path) -> list[str]:
    out = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts) or not path.is_file():
            continue
        out.append(rel.as_posix())
    return sorted(out)


def test_files(files: list[str]) -> list[str]:
    return [f for f in files if f.startswith("tests/") and Path(f).name.startswith("test_")
            and f.endswith(".py")]


def imported_modules(text: str) -> set[str]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(text)
    except SyntaxError:
        return set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.update(alias.name.split("."))
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.update(node.module.split("."))
            names.update(alias.name for alias in node.names)
    return names


def referenced_paths(text: str, files: set[str], dirs: set[str]) -> set[str]:
    found = set()
    candidates = set(LITERAL.findall(text))
    for chain in JOINED.findall(text):
        candidates.add("/".join(p.strip("/") for p in PART.findall(chain)))
    for c in candidates:
        c = c.strip("/")
        if c.startswith("./"):
            c = c[2:]
        if c in files:
            found.add(c)
        elif "/" in c and c in dirs:
            found.update(f for f in files if f.startswith(c + "/"))
    return found


def generate(root: Path) -> dict:
    files = repo_files(root)
    fileset = set(files)
    dirs = {str(Path(f).parent.as_posix()) for f in files}
    dirs |= {"/".join(f.split("/")[:i]) for f in files for i in range(1, f.count("/") + 1)}
    by_stem: dict[str, list[str]] = {}
    for f in files:
        if f.endswith(".py") and not PAYLOAD.match(f):
            by_stem.setdefault(Path(f).stem, []).append(f)
    deps = {}  # every Python file: the repo modules it imports and the repo paths it names
    for f in files:
        if f.endswith(".py"):
            text = (root / f).read_text(encoding="utf-8", errors="replace")
            deps[f] = ({m for name in imported_modules(text) for m in by_stem.get(name, [])}
                       | referenced_paths(text, fileset, dirs))
    references: dict[str, set[str]] = {}
    for t in test_files(files):
        seen, stack = set(), list(deps.get(t, ()))
        while stack:  # close over this repository's own modules and the paths they name
            f = stack.pop()
            if f in seen:
                continue
            seen.add(f)
            stack.extend(deps.get(f, ()))
        for f in seen:
            if f != t:
                references.setdefault(f, set()).add(t)
    return {k: sorted(v) for k, v in sorted(references.items())}


def select(map_doc: dict, changed: list[str], all_tests: list[str]) -> dict:
    """The selected set for these changed paths. Pure: no reads."""
    references = map_doc.get("references", {})
    rules = map_doc.get("rules", [])
    no_test = map_doc.get("no_test_paths", [])
    selected: dict[str, set[str]] = {}
    unmapped, untested = [], []
    for path in sorted(set(changed)):
        why = None
        if path in all_tests:
            selected.setdefault(path, set()).add(f"changed:{path}")
            why = "self"
        if path in references:
            for t in references[path]:
                if t in all_tests:
                    selected.setdefault(t, set()).add(f"references:{path}")
            why = why or "references"
        for rule in rules:
            if any(fnmatchcase(path, g) for g in rule["paths"]):
                for t in all_tests:
                    if any(fnmatchcase(t, g) for g in rule["tests"]):
                        selected.setdefault(t, set()).add(f"rule:{rule['id']}:{path}")
                why = why or "rule"
        if why is None:
            if any(fnmatchcase(path, g) for g in no_test):
                untested.append(path)
            else:
                unmapped.append(path)
    if unmapped and map_doc.get("unmapped_path_policy", "SELECT_FULL_SUITE") == "SELECT_FULL_SUITE":
        for t in all_tests:
            selected.setdefault(t, set()).add("unmapped:" + ",".join(unmapped[:5]))
    chosen = sorted(selected)
    return {
        "schema": SELECTION_SCHEMA,
        "changed_paths": sorted(set(changed)),
        "unmapped_changed_paths": unmapped,
        "changed_paths_no_test_reads": untested,
        "selected_tests": chosen,
        "selected_because": {t: sorted(selected[t]) for t in chosen},
        "not_selected_for_this_change": [t for t in all_tests if t not in selected],
        "not_selected_are_not_run_for_this_verdict_and_not_reported_as_passing": True,
        "authority_effect": "NONE",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--root", type=Path, default=Path("."))
    p.add_argument("--map", type=Path, default=Path("data/test-selection-map.json"))
    p.add_argument("--references", action="store_true",
                   help="print the references derived from this tree and exit")
    p.add_argument("--changed", type=Path, help="file listing changed paths, one per line")
    p.add_argument("--out", type=Path)
    p.add_argument("--print-modules", action="store_true",
                   help="also print the selected test files, one per line, to stdout")
    a = p.parse_args(argv)
    root = a.root.resolve()
    map_path = a.map if a.map.is_absolute() else root / a.map
    doc = json.loads(map_path.read_text(encoding="utf-8")) if map_path.is_file() else {}
    if a.references:
        print(json.dumps(generate(root), indent=1, sort_keys=True))
        return 0
    if a.changed is None or a.out is None:
        p.error("--changed and --out are required unless --references")
    changed = [line.strip() for line in a.changed.read_text(encoding="utf-8").splitlines() if line.strip()]
    all_tests = test_files(repo_files(root))
    if doc.get("schema") != SCHEMA:
        print(f"TEST_SELECTION_MAP_UNREADABLE {map_path}: selecting the whole suite", file=sys.stderr)
        doc = {"unmapped_path_policy": "SELECT_FULL_SUITE"}
        changed = changed + ["<test-selection map unreadable>"]
    result = select(doc | {"references": generate(root)}, changed, all_tests)
    result["map"] = str(a.map)
    a.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"TEST_SELECTION changed={len(result['changed_paths'])} selected={len(result['selected_tests'])} "
          f"not_selected={len(result['not_selected_for_this_change'])} "
          f"unmapped={len(result['unmapped_changed_paths'])}", file=sys.stderr)
    if a.print_modules:
        print("\n".join(result["selected_tests"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
