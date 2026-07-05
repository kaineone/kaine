## 1. Audit + config

- [ ] 1.1 Update `AsyncBus.audit` to raise `BusSecurityError` whenever `requirepass` is empty, on any host. Loopback exception applies to the bind check only.
- [ ] 1.2 Update `load_bus_config` to raise `BusConfigError` whenever the password is missing, on any host.

## 2. Compose

- [ ] 2.1 Restore `compose/redis.yml`'s `--requirepass` so it's mandatory; compose fails fast when `KAINE_REDIS_PASSWORD` is unset.
- [ ] 2.2 Update `compose/.env.example` to describe the password as required.

## 3. Tests

- [ ] 3.1 Update the "loopback warns but proceeds" audit test to "loopback raises" so it mirrors the non-loopback case.
- [ ] 3.2 Update `test_bus_config.py`: the loopback-without-password case now raises `BusConfigError`; non-loopback case continues to raise as before.

## 4. Documentation

- [ ] 4.1 Update `kaine/bus/AUDIT.md` row 2 back to "required" with the future-deployment rationale.
- [ ] 4.2 Update `SETUP.md` §1.2: single with-password path.

## 5. Verification

- [ ] 5.1 Full unit suite passes.
- [ ] 5.2 `openspec validate redis-auth-mandatory --strict` clean.
- [ ] 5.3 Commit, merge, archive.
