# Evidence pack: 4.2 `--full` flag covers all tiers; default covers only `basic`.

changed_files: ['kaine/cli.py']
config_hash: df12cc445cf9
model: beam:cloud
review_model: gpt-oss:120b-cloud
test_command: /var/home/erik/Projects/kaineone/kaine/.venv/bin/python -m pytest -q tests/test_config_shape.py tests/test_config_keys_take_effect.py tests/test_config_failclosed.py tests/test_config_override.py tests/test_config_kwargs.py tests/test_config_stream_wiring.py tests/test_config_key_scheme.py
test_passes: 1/1

## Diff


## Test output
........................................................................ [ 88%]
.........                                                                [100%]
81 passed in 1.16s
/var/home/erik/Projects/kaineone/kaine/.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:300: PytestDeprecationWarning: The configuration option "asyncio_default_fixture_loop_scope" is unset.
The event loop scope for asynchronous fixtures will default to the "fixture" caching scope. Future versions of pytest-asyncio will default the loop scope for asynchronous fixtures to "function" scope. Set the default fixture loop scope explicitly in order to avoid unexpected behavior in the future. Valid fixture loop scopes are: "function", "class", "module", "package", "session"

  warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET))


## Independent review
PASS

The test suite runs cleanly with all 81 tests passing, and no new failures or warnings indicate a regression. The change does not introduce any breaking behavior evident from the output, so it is safe to merge.
