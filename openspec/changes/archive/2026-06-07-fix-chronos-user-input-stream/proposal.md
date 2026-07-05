## Why

`config/kaine.toml:86` configures Chronos with
`user_input_streams = ["audio.in.out"]` (dots), but the Audio In module
publishes transcriptions to `audio_in.out` (underscore — its module name is
`audio_in`, and producer streams are `<module>.out`). The names never match, so
**Chronos never receives user-interaction events**: its user-input timing
channel is silently empty, breaking interaction-timing anomaly detection and
starving the social-interaction signal that should feed Thymos. Found in the
architecture audit; it is a one-character typo with real behavioral impact, and
nothing guards against this class of mismatch.

## What Changes

- Fix `config/kaine.toml [chronos].user_input_streams` to `["audio_in.out"]`.
- Add a regression test that every stream name referenced in `config/kaine.toml`
  (Chronos `user_input_streams`; Thymos `soma_stream`/`chronos_stream`/
  `mnemos_stream`; Eidolon `internal_speech_stream`; Audio Out
  `lingua_external_stream`/`thymos_state_stream`; Soma `cycle_stream`) resolves
  to a real producer stream — so future wiring typos fail loudly in CI.

## Capabilities

### Modified Capabilities

- `chronos`: the user-interaction input stream Chronos consumes must be the
  actual Audio In producer stream; configured stream references must resolve to
  real producers.

## Impact

- **Config**: one value in `config/kaine.toml`.
- **Tests**: new `tests/test_config_stream_wiring.py`.
- **Behavior**: Chronos begins receiving user-interaction events; the
  interaction signal reaches Thymos as designed. No code changes to modules.
