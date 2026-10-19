## Why

The pre-conference audit of 2026-10-10 ran the full gate on a maintainer's host and found it RED with 11 failures, none of them code regressions:

- Nine research and Claude-science CLI tests (`tests/test_research_submission.py`, `tests/test_claude_science_export.py`) run from the repository root, so the loader's working-directory-relative `config/kaine.operator.toml` picks up the maintainer's git-ignored overlay. That overlay turns on state encryption, the CLI exits with "state encryption is enabled but its key is unavailable", and the tests fail. CI has no overlay, so CI is green. Other tests in the same file already isolate themselves by changing to `tmp_path`.
- Two real-weight audio encoder tests (`tests/test_audition_ssl_encoders.py`) decide whether to skip by checking the weights under the real data root at collection time, but the autouse per-test data root points at `tmp_path` at run time, so the load fails with a missing file.

## What Changes

- The nine CLI tests change to `tmp_path` before running, as their neighbours do, so the operator overlay never applies.
- The two real-weight encoder tests carry `@pytest.mark.no_data_root`, so they load from the same data root their skip condition checked.

## Capabilities

### Modified Capabilities

- `test-lanes`: tests are isolated from a maintainer's local operator overlay.

## Impact

- Tests only. No runtime code changes.
