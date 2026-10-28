set -euo pipefail
# Pinned SDK verification inputs (StegVerse-org/.github#163, P1). Every pin that a `pinned_source` input of the spec
# declares (.stegverse/verification-inputs/stegverse-sdk.json: repository, commit, tree, module paths, sha256 per
# file) is fetched at its exact commit with one anonymous git fetch (StegVerse-org/StegVerse-SDK is public; no
# credential, no package index, nothing installed). Only the declared modules are extracted, and every file is
# re-hashed. A pin that does not verify is printed as six fields and its env is left unset, so the selector reports
# exactly the sets that need it as REQUIRED_VERIFICATION_INPUT_UNAVAILABLE (owner #163) and blocks only the changes
# that select them. The pin's exports (PYTHONPATH, STEGVERSE_SDK_SOURCE_ROOT) reach only that pin's run group.
# A pass here is CI-class evidence only (TEST_ONLY; authority_effect NONE). PII and credentials live only in the SKAP
# Vault inside KV, and TV/TVC is the authority; nothing in this step reads, stores or routes either.
python "$LABS/scripts/pinned_source_input.py" declared --root . --spec .stegverse/test-set-spec.json \
  --dest-root "$RUNNER_TEMP/pinned-inputs" --env-out "$GITHUB_ENV" --retry-entrypoint "$WORKFLOW_REF"
