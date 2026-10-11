## 1. Workflows
- [x] 1.1 Add the `merge_group` trigger to the codeql, import-boundary, redteam, ruff and tests workflows.
- [x] 1.2 Remove the pull-request path filter from the tests workflow; keep the push filter.
- [x] 1.3 Make the slow lane diff a merge-queue batch against `merge_group.base_sha`.
- [x] 1.4 Test that pull requests and merge-queue batches always start the suite, and that the slow lane handles a batch; mutation-check both.

## 2. Repository settings (integrator, after merge)
- [x] 2.1 Create a ruleset on `main` that enables the merge queue (squash merges, all-green grouping) and requires `analyze (python)`, `lint-imports`, `redteam` and the three pytest jobs.
- [x] 2.2 Turn off "require branches to be up to date" in the classic branch protection, and keep its required checks.
- [x] 2.3 Run one pull request through the queue end to end, and confirm a red required check removes it from the queue.
