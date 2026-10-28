# `git apply --check` needs the peer's tree and cannot run here, but
# a malformed diff is catchable without one: numstat parses the patch
# and reports its paths, and fails on a corrupt hunk header.
for patch in docs/migrations/*.patch; do
  echo "== $patch"
  git apply --numstat "$patch"
done
