# Merge queue

## Why
Branch protection on `main` requires every pull request to be up to date with `main` before it merges. Each merge therefore forces the next pull request to update and run all of CI again, about 15–20 minutes, so merges happen strictly one at a time. Three teams now deliver in parallel, and that serial wait has become the limit on throughput.

The test suite is also not a required check. A pull request with a red suite can merge, and once did. Only the merge scripts' own wait for every check prevents it.

## What changes
- Every required workflow (CodeQL, import-boundary, red-team, ruff and tests) also runs on the `merge_group` event. GitHub's merge queue can then test batches of approved pull requests together and merge them in order, without each one first catching up with `main`.
- The tests workflow drops its path filter for pull requests, so the suite always starts and can be a required check. Pushes to `main` keep their path filter.
- The slow lane diffs a merge-queue batch against the batch's base, just as it diffs a pull request against the pull request's base.
- Outside the repository, as a repository setting: a ruleset on `main` turns on the merge queue (squash merges) and requires the pytest jobs alongside the existing checks. The classic rule requiring branches to be up to date is turned off. Required checks stay required, and administrators still cannot bypass them.

## Impact
- Specs: `test-lanes`.
- Code: `.github/workflows/{codeql,import-boundary,redteam,ruff,tests}.yml` and `tests/test_slow_lane.py`.
- Every pull request now runs the suite, including pull requests that change only OpenSpec files. Actions minutes on this public repository cost nothing.
- Research impact: none. No module, instrument or entity path changes.
