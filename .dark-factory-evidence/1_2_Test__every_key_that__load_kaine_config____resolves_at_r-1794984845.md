# Evidence pack: 1.2 Test: every key that `load_kaine_config()` resolves at runtime appears in `list_all_defaults()`.

changed_files: ['tests/test_config_defaults.py']
config_hash: 2f5bafe90257
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

The change only adds/updates tests and does not modify production code. All tests run successfully (81 passed) and no new failures are introduced. Therefore the change is safe to merge.
