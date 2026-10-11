## 1. Hypnos

- [x] 1.1 Remove `nous_process` and `nous_step_burst` from Hypnos, its factory and the registry
- [x] 1.2 Delete `revise_beliefs` and `_SupportsStep` from the sleep phases
- [x] 1.3 The factory ignores `[hypnos].nous_step_burst` with a warning

## 2. Thymos

- [x] 2.1 Remove `social_drive_time_scale_s` from Thymos
- [x] 2.2 The factory ignores `[thymos].social_drive_time_scale_s` and `[thymos.coupling].coupling_max_rate_per_s` with a warning

## 3. Environment and probe

- [x] 3.1 Remove `KAINE_MODEL_SERVER_URL` from the organ-host compose override
- [x] 3.2 The host probe names `KAINE_TIER`

## 4. Configuration, docs and tests

- [x] 4.1 Remove both keys from `config/kaine.toml` and the configuration and module docs
- [x] 4.2 Tests: retired keys boot with a warning, Hypnos has no Nous argument, the probe names `KAINE_TIER`
