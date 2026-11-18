# Evidence pack: 6.1 Note in operator/audition docs that `--renderer sam` requires v2 checkpoint and applies no implicit watermark.

changed_files: ['docs/operator/audition.md']
config_hash: ae38d556b538
model: beam:cloud
review_model: gpt-oss:120b-cloud
test_command: /var/home/erik/Projects/kaineone/kaine/.venv/bin/python -m pytest -q tests/test_maternal_sam_backend_smoke.py tests/test_maternal_voice_sam_conversion.py
test_passes: 1/1

## Diff


## Test output
...............                                                          [100%]
15 passed in 0.28s
/var/home/erik/Projects/kaineone/kaine/.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:300: PytestDeprecationWarning: The configuration option "asyncio_default_fixture_loop_scope" is unset.
The event loop scope for asynchronous fixtures will default to the "fixture" caching scope. Future versions of pytest-asyncio will default the loop scope for asynchronous fixtures to "function" scope. Set the default fixture loop scope explicitly in order to avoid unexpected behavior in the future. Valid fixture loop scopes are: "function", "class", "module", "package", "session"

  warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET))


## Independent review
PASS

The only modification is to a documentation file (`docs/operator/audition.md`). There are no changes to code, logic, or test expectations. The existing test suite runs successfully (15 passed), and the change does not introduce any runtime behavior modifications or break compatibility. Therefore, merging this documentation update is safe.
