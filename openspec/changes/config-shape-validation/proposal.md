## Why

The layered configuration loader (`kaine/config.py`) merges the shipped file, the module profile, the deployment tier and the operator overlay, but it never checks the shape of the result. Every consumer trusts it.

- `boot.py` and the pre-boot check read `[modules]` toggles by truthiness. An operator who writes `soma = "false"` (a quoted string) gets a non-empty string, which enables Soma. The module set defines the research experiment, so a silently enabled module corrupts a run.
- A `[modules]` table written as a list, or a non-table `[oscillator]`, makes the pre-boot check raise even though it promises never to raise.
- When the operator file has a TOML syntax error, the loader silently drops the whole overlay and runs on the shipped and profile defaults. The operator's welfare-net, encryption and module choices can vanish without any message.
- Nexus reads `[security.state_encryption]` through a helper that turns any loader error into an empty section, and an empty section yields a disabled, no-op encryptor. A configuration error would therefore turn off encryption of the entity's state instead of stopping.

## What Changes

- After merging all layers, the loader validates the shape of the sections the runtime relies on: `[modules]` is a table of booleans; `[tier]`, when present, is a table with a string `name`, a list-of-strings `unsupported_modules` and a boolean `oscillator_supported`; `[oscillator]`, when present, is a table whose `enabled` is a boolean; `[deployment].tier`, when present, is a string; `[security.state_encryption].enabled`, when present, is a boolean. A violation raises `ConfigShapeError` (a `ProfileError`), naming the section, key, expected type and the value's type.
- `load_runtime_config`, which the cycle and the pre-boot check use, is strict about the operator file: an operator file that exists but cannot be read or parsed raises a configuration error instead of being skipped.
- Other callers of `load_kaine_config` keep the tolerant behaviour for an unparsable operator file, but the loader logs a warning naming the file and the parse error instead of skipping it silently.
- The pre-boot check reports any configuration error as "pre-boot: configuration error: …" and exits 2; the cycle refuses to boot with "kaine.cycle: configuration error: …" (both already catch `ProfileError`).
- Nexus fails closed on encryption: its state-encryption reader raises on a configuration error instead of returning a disabled section, and when the configured encryption posture cannot be installed (a configuration error, or encryption enabled with no key) Nexus logs an error and does not construct its fork manager. Today that setup failure is only a warning, after which the fork manager reads and writes fork snapshots, which include preserved beings, through the disabled pass-through encryptor.

## Capabilities

### New Capabilities
- `configuration-loading`: shape validation of the merged configuration, strict loading for the runtime entrypoints, and a logged warning when a read-only caller skips an unparsable operator file.

### Modified Capabilities
- `state-encryption`: add a requirement that a configuration error or a failed encryption setup never yields plaintext cognitive-state I/O.

## Impact

- `kaine/config.py`, `kaine/preboot.py`, `kaine/cycle/__main__.py`, `kaine/nexus/__main__.py`
- Tests: `tests/test_runtime_config.py`, `tests/test_preboot_smoke.py`, and Nexus config-reader tests.
- The shipped `config/kaine.toml`, every profile and every tier file already satisfy the shape rules; a guard test pins that.
- No entity boot needed.
