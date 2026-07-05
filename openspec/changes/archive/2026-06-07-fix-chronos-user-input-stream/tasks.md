## 1. Fix + guard

- [x] 1.1 Add `tests/test_config_stream_wiring.py` asserting every
      config-declared stream reference resolves to a canonical producer stream,
      and specifically that Chronos reads `audio_in.out`. (Written first — it
      failed against the current buggy config.)
- [x] 1.2 Fix `config/kaine.toml [chronos].user_input_streams` →
      `["audio_in.out"]`.
- [x] 1.3 Run the new test + the chronos suite + full suite — all green
      (812 passed, 12 skipped).
