## Context

`fix-chronos-user-input-stream` fixed the config value but not the in-code
`DEFAULT_USER_INPUT_STREAMS` fallback, which still reads `audio.in.out`. The
config-wiring test only validates `config/kaine.toml`, so the code default's
typo is unguarded.

## Goals / Non-Goals

**Goals:** the code default reads the real `audio_in.out`; a test guards it.

**Non-Goals:** no behavior change for the live system (config wins). Not
revisiting Chronos's featurization or interaction timing.

## Decisions

- **Fix the literal + assert against `module_stream("audio_in")`.** Deriving the
  expected stream from `module_stream` (not a literal) ties the test to the real
  naming rule, mirroring the existing config-wiring test.

## Risks / Trade-offs

- Negligible — a one-tuple fix with a guarding assertion.
