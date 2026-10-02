## 1. Fix
- [x] 1.1 `kaine/cycle/__main__.py`: `_boot_and_run` takes an optional keyword `kaine_config`. When it is given, it is used as is; when it is `None`, `_boot_and_run` loads with `_load_kaine_config()` as before.
- [x] 1.2 `main()` passes the `config` it loaded (and that the gates evaluated) to `_boot_and_run` through `kwargs["kaine_config"]`.

## 2. Tests
- [x] 2.1 Regression: `main(["--profile", "<p>"])` with `KAINE_PROFILE` unset hands `_boot_and_run` the same configuration object the gate path loaded with that profile, and `_load_kaine_config` is called exactly once.
- [x] 2.2 `_boot_and_run()` with no `kaine_config` still loads the configuration itself.
- [x] 2.3 The existing cycle entrypoint, revive, unattended, plugin and tier tests pass.
