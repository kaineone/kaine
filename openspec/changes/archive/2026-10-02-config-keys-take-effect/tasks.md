## 1. Wiring
- [x] 1.1 `make_hypnos`: pass `requested_rest_min_interval_s` (float > 0, else configuration error).
- [x] 1.2 `_resolve_trainer(voice_config, kaine_config)` and `_resolve_job_queue_trainer(voice_config, kaine_config)`: take the merged configuration as a parameter; organ key = `[lingua].api_key` or `KAINE_MODEL_SERVER_API_KEY`; remove the `NameError` fallback.
- [x] 1.3 `make_topos`: `habituator=RollingMeanHabituator(window=int(habituation_window))` when set (int >= 2, else configuration error).
- [x] 1.4 `make_topos`: `encoder_revision` other than `PINNED_REVISION` raises a configuration error naming both.
- [x] 1.5 Cycle: apply `[logging].level` to the root logger after the configuration loads; invalid value exits 1 with `kaine.cycle: configuration error: ...`.
- [x] 1.6 `make_mundus`: route `expose_<name>` by the adapter's `capabilities()`; unknown names raise a configuration error.

## 2. Tests
- [x] 2.1 Hypnos built from config honours a non-default interval (a request inside it is refused `too_soon`, one after it accepted); invalid values refused.
- [x] 2.2 Job-queue trainer receives `[lingua].api_key` from config; env used only when config is empty.
- [x] 2.3 Topos habituator window follows config; invalid window refused; a non-pinned `encoder_revision` refused; the pinned value accepted.
- [x] 2.4 `[logging].level = "DEBUG"` sets the root level; `"LOUD"` exits 1 without a traceback.
- [x] 2.5 Mundus: `expose_drive = true` exposes the `drive` channel; `expose_say = false` hides the `say` family; `expose_nonsense` refused.
- [x] 2.6 Mutation-check each new test against the old wiring.

## 3. Docs
- [x] 3.1 Remove the "accepted but ignored" notes from the configuration appendix, Topos, Hypnos and Mundus pages; describe the new refusals.
