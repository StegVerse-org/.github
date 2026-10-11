#!/usr/bin/env python3
"""Bind a materializer-supplied federation mesh locator to the repository a run can publish.

`organization-ledger-transition.yml` receives the mesh location as the
`workflow_dispatch` input `mesh_root`, in the form `git+<repository>#refs/<name>`
(StegVerse-org/.github#23, SVORG-MESH-LOCATION-BINDING-001). The kernel's
`GitStateStore` writes frames on a ref of a *local* repository, and a run holds
credentials for exactly one repository: its own checkout. So a locator that names
this repository (by slug, by workspace path, or as `.`) is materialized on the
checkout and its ref is fetched before and pushed after the transition; any other
repository is refused with all six fields, and no credential is inferred for it.

Nothing here designates a mesh. It only says whether the designated one can be
published by this run, and how.
"""
import argparse
import json
import sys
from pathlib import Path

OWNING_EXISTING_GOAL = "SVORG-MESH-LOCATION-BINDING-001"
RETRY_ENTRYPOINT = ".github/workflows/organization-ledger-transition.yml (workflow_dispatch: mesh_root)"
SCHEMA = "stegverse.mesh-locator-binding/v1"


def _refused(failure_code, failed_predicate, repair, next_attempt, **detail):
    return {
        "schema": SCHEMA,
        "disposition": "FAIL_CLOSED",
        "failure_code": failure_code,
        "failed_predicate": failed_predicate,
        "required_evidence_or_repair": repair,
        "retry_entrypoint": RETRY_ENTRYPOINT,
        "owning_existing_goal": OWNING_EXISTING_GOAL,
        "next_attempt": next_attempt,
        **detail,
    }


def parse_locator(locator):
    """Split `git+<repository>#<ref>`; a malformed locator raises ValueError."""
    if not isinstance(locator, str) or not locator.startswith("git+"):
        raise ValueError("mesh_locator_must_start_with_git+")
    repository, separator, ref = locator[4:].partition("#")
    if not separator or not repository or not ref:
        raise ValueError("mesh_locator_must_name_repository_and_ref")
    if not ref.startswith("refs/") or ref.endswith("/") or "//" in ref or ".." in ref.split("/"):
        raise ValueError("mesh_ref_must_be_a_qualified_git_ref")
    if any(c.isspace() for c in ref) or ":" in ref:
        raise ValueError("mesh_ref_must_be_a_qualified_git_ref")
    return repository, ref


def _names_this_checkout(repository, repository_slug, workspace):
    if repository == ".":
        return True
    if repository_slug and repository.lower() == repository_slug.lower():
        return True
    try:
        return Path(repository).resolve() == Path(workspace).resolve()
    except (OSError, RuntimeError):
        return False


def bind(locator, *, repository_slug, workspace):
    """Resolve a designated locator to what this run can materialize and publish.

    ALLOW carries `mesh_root` (the local locator to hand the ingress) and
    `publish_ref` (the ref the run fetches first and pushes fast-forward after).
    """
    try:
        repository, ref = parse_locator(locator)
    except ValueError as exc:
        return _refused(
            "MESH_LOCATOR_INVALID", "MESH_LOCATOR_IS_A_QUALIFIED_GIT_REF_OF_A_NAMED_REPOSITORY",
            "supply mesh_root as git+<repository>#refs/<name>",
            "rerun the dispatch with a well-formed locator",
            detail=str(exc), locator=locator)
    if not _names_this_checkout(repository, repository_slug, workspace):
        return _refused(
            "MESH_REPOSITORY_NOT_MATERIALIZABLE_FROM_THIS_RUN",
            "DESIGNATED_MESH_REPOSITORY_IS_ONE_THIS_RUN_CAN_PUBLISH",
            "this run holds credentials for " + str(repository_slug) + " only; designate a ref of that "
            "repository, or materialize the node from a run that holds credentials for " + repository
            + " (none is inferred here)",
            "rerun from the designated repository's own transition workflow, or redesignate",
            designated_repository=repository, designated_ref=ref, this_repository=repository_slug)
    return {
        "schema": SCHEMA,
        "disposition": "ALLOW",
        "designated_repository": repository,
        "designated_ref": ref,
        "this_repository": repository_slug,
        "mesh_root": "git+" + str(workspace) + "#" + ref,
        "publish_ref": ref,
        "publish": "fetch +" + ref + ":" + ref + " before the transition; push " + ref + ":" + ref
                   + " (fast-forward only) before the ledger ref is published",
        "authority_effect": "NONE_BINDING_ONLY",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--locator", required=True, help="materializer-supplied git+<repository>#refs/<name>")
    parser.add_argument("--repository", required=True, help="this run's repository slug (GITHUB_REPOSITORY)")
    parser.add_argument("--workspace", required=True, type=Path, help="this run's checkout (GITHUB_WORKSPACE)")
    args = parser.parse_args(argv)
    result = bind(args.locator, repository_slug=args.repository, workspace=args.workspace)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["disposition"] == "ALLOW" else 1


if __name__ == "__main__":
    sys.exit(main())
