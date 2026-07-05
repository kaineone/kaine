## Why

`fix-chronos-user-input-stream` corrected the `audio.in.out` → `audio_in.out`
typo in `config/kaine.toml`, but the **code default** in
`kaine/modules/chronos/module.py:22` — `DEFAULT_USER_INPUT_STREAMS =
("audio.in.out",)` — still carries the same typo. Config overrides it so the
live system is unaffected, but any path that falls back to the default (config
omits `user_input_streams`, or Chronos is constructed directly) would silently
read a non-existent stream. The config-wiring test guards the config value, not
the code default.

## What Changes

- Fix `DEFAULT_USER_INPUT_STREAMS` to `("audio_in.out",)`.
- Add a test asserting the code default resolves to the real Audio In producer
  stream (`module_stream("audio_in")`), so the default cannot regress to a
  non-existent stream.

## Capabilities

### Modified Capabilities

- `chronos`: the default user-input stream (when config omits it) must be the
  real Audio In producer stream, consistent with the config fix.

## Impact

- **Code**: one tuple in `kaine/modules/chronos/module.py`.
- **Tests**: assertion in `tests/test_config_stream_wiring.py` (or chronos test).
- No behavior change for the live system (config already correct); closes the
  latent fallback bug.
