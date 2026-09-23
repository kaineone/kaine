## 1. Loader

- [x] 1.1 Add `ConfigShapeError(ProfileError)` and a validator for the merged configuration (`[modules]`, `[tier]`, `[oscillator]`, `[deployment].tier`, `[security.state_encryption].enabled`); call it at the end of `load_kaine_config`.
- [x] 1.2 Make `load_runtime_config` strict about an operator file that exists but cannot be read or parsed.
- [x] 1.3 Log a WARNING naming the file and parse error when the tolerant path skips an unparsable operator file.

## 2. Callers

- [x] 2.1 Nexus state-encryption reader raises on a configuration error instead of returning a disabled section.
- [x] 2.1a When the encryption posture cannot be installed, Nexus logs an error and does not construct its fork manager.
- [x] 2.2 Confirm the cycle and the pre-boot check report `ConfigShapeError` as a configuration error (exit codes unchanged).

## 3. Tests

- [x] 3.1 Each shape rule: a violating operator overlay raises `ConfigShapeError` naming the key; `soma = "false"` is rejected.
- [x] 3.2 Strict runtime loading refuses an unparsable operator file; the tolerant path logs a warning and falls back.
- [x] 3.3 Guard: the shipped config, every profile and every tier file pass validation.
- [x] 3.4 The Nexus state-encryption reader raises on a malformed configuration; with encryption enabled and no key, or a malformed configuration, Nexus leaves the fork manager unconstructed.
- [x] 3.5 Pre-boot and cycle report the configuration error without a traceback.

## 4. Second-review fixes

- [x] 4.1 Research CLI reports a configuration error and exits non-zero instead of continuing with `{}`.
- [x] 4.2 `[security]` and `[deployment]` must be tables.
- [x] 4.3 Decommission CLI loads the merged configuration strictly, installs the encryption posture, and refuses before assessing, backing up or deleting when either fails.
- [x] 4.4 Nexus `/forks.json` reports unavailability with the reason when the fork manager is unconstructed.
- [x] 4.5 The bus configuration and the model-server setup log a warning when they skip an unparsable operator file or a configuration they cannot load.
- [x] 4.6 Test: encryption enabled with no key leaves the Nexus fork manager unconstructed.

