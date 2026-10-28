python -m py_compile resident-runtime/organization_ledger_ingest.py resident-runtime/aggregate_repo_transition.py \
  resident-runtime/organization_ledger_readback.py resident-runtime/merge_transfer.py tools/tasks/writer_plan.py
python -m unittest tests.test_organization_ledger_ingest tests.test_writer_plan tests.test_git_ledger_store \
  tests.test_organization_role_runtime_reality_deployment -v 2>&1 | tee "$RUNNER_TEMP/ingest-unit.log"
status=${PIPESTATUS[0]}
if grep -Eq '(skipped|expected failure)' "$RUNNER_TEMP/ingest-unit.log"; then
  echo '{"disposition":"FAIL_CLOSED","failure_code":"INGEST_TESTS_SKIPPED","failed_predicate":"ZERO_SKIPPED_ON_THE_EXACT_HEAD","required_evidence_or_repair":"every selected test runs; none is skipped or expected to fail","retry_entrypoint":"tools/tasks/task_catalog.json group organization-ledger-ingest-validation.unit","owning_existing_goal":"StegVerse-org/.github#162 P0-runtime-and-custody","next_attempt":"push a head on which no ingest test is skipped"}' >&2
  exit 1
fi
exit "$status"
