# fix-preboot-probe-parity — tasks

- [ ] Apply `KAINE_REDIS_URL` override in `build_dependency_specs`: parse
      host/port/password via `urllib.parse` when set; fall back to TOML
      `[redis]` host/port; URL password takes precedence over
      `redis_password`.
- [ ] Wrap the Speaches probe: when `[audition].transcription_enabled` is
      false, return `(NOT_CONFIGURED, ...)` without probing; otherwise run
      `probe_speaches` unchanged.
- [ ] Add `tests/test_health_probe_parity.py` covering: URL override with
      password, URL override without password, TOML fallback when env unset,
      Speaches not-configured when transcription disabled, Speaches probes
      normally when enabled (no real network).
- [ ] Verify the pre-boot dry run passes on the containerized compose stack.
