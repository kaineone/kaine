## 1. Audit + config

- [x] 1.1 Update `kaine/bus/client.py` `AsyncBus.audit` so missing requirepass on a loopback host logs a warning and returns; non-loopback hosts still raise
- [x] 1.2 Update `kaine/bus/config.py` `load_bus_config` so missing password on a loopback host returns `password=None` instead of raising; non-loopback hosts still raise

## 2. Compose

- [x] 2.1 Update `compose/redis.yml` to make `--requirepass` conditional on `KAINE_REDIS_PASSWORD` being set; when unset, the container starts unauthenticated
- [x] 2.2 Update `compose/.env.example` to note the password is optional

## 3. Tests

- [x] 3.1 Update existing audit tests: split the "missing requirepass" case into loopback (warns, proceeds) and non-loopback (raises)
- [x] 3.2 Add `test_bus_config.py` cases: loopback host with no password loads cleanly; non-loopback host with no password still raises

## 4. Documentation

- [x] 4.1 Update `kaine/bus/AUDIT.md` row 2 and threat-model paragraph
- [x] 4.2 Update `SETUP.md` §1.2 with the two operator paths (default no-password, optional with-password)

## 5. Verification

- [x] 5.1 Full unit suite passes (169 passed)
- [ ] 5.2 `openspec validate redis-loopback-no-password --strict` clean
- [ ] 5.3 Commit, merge, archive change
