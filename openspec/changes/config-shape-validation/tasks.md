## 1. Loader

- [ ] 1.1 Add `ConfigShapeError(ProfileError)` and a validator for the merged configuration (`[modules]`, `[tier]`, `[oscillator]`, `[deployment].tier`, `[security.state_encryption].enabled`); call it at the end of `load_kaine_config`.
- [ ] 1.2 Make `load_runtime_config` strict about an operator file that exists but cannot be read or parsed.
- [ ] 1.3 Log a WARNING naming the file and parse error when the tolerant path skips an unparsable operator file.

## 2. Callers

- [ ] 2.1 Nexus state-encryption reader raises on a configuration error instead of returning a disabled section.
- [ ] 2.1a When the encryption posture cannot be installed, Nexus logs an error and does not construct its fork manager.
- [ ] 2.2 Confirm the cycle and the pre-boot check report `ConfigShapeError` as a configuration error (exit codes unchanged).

## 3. Tests

- [ ] 3.1 Each shape rule: a violating operator overlay raises `ConfigShapeError` naming the key; `soma = "false"` is rejected.
- [ ] 3.2 Strict runtime loading refuses an unparsable operator file; the tolerant path logs a warning and falls back.
- [ ] 3.3 Guard: the shipped config, every profile and every tier file pass validation.
- [ ] 3.4 The Nexus state-encryption reader raises on a malformed configuration; with encryption enabled and no key, or a malformed configuration, Nexus leaves the fork manager unconstructed.
- [ ] 3.5 Pre-boot and cycle report the configuration error without a traceback.
