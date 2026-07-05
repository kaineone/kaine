## 1. Compose service

- [x] 1.1 Add `compose/redis.yml` defining `kaine-redis` on `redis:7.2-alpine`, host-loopback port mapping `127.0.0.1:6479:6379`, AOF, fsync everysec, maxmemory 1gb, password from `${KAINE_REDIS_PASSWORD}` with `:?` fail-fast, healthcheck, named volume `kaine-redis-data`, `restart: unless-stopped`
- [x] 1.2 Add `compose/.env.example` showing the env vars compose reads
- [x] 1.3 Update `.gitignore` to ignore `compose/.env`

## 2. Config

- [x] 2.1 Update `config/kaine.toml` `[redis]` `port = 6479`
- [x] 2.2 Sanity-check `config/secrets.example.toml` still matches the new port (no change needed — only password lives there)

## 3. Audit relaxation

- [x] 3.1 Update `kaine/bus/client.py` `AsyncBus.audit` to skip the `bind` check when `self._config.host` is `127.0.0.1`, `::1`, or `localhost`
- [x] 3.2 Update `kaine/bus/AUDIT.md` documenting the conditional and what the operator must verify manually for containerized deployments

## 4. Tests

- [x] 4.1 Add `tests/test_bus_client.py` cases: audit accepts `bind 0.0.0.0` when host is loopback; audit rejects `bind 0.0.0.0` when host is non-loopback; audit rejects missing requirepass even on loopback; audit accepts loopback bind on loopback host
- [x] 4.2 Run the full unit suite; all pass (85 passed, 3 integration skipped 2026-05-19)

## 5. Documentation

- [x] 5.1 Update `SETUP.md` §1.2 to reflect Option B, the new commands, and the corrected rationale
- [x] 5.2 Update `DEPENDENCIES.md` to swap "system Redis reuse" for "KAINE-owned Redis container"

## 6. Verification

- [ ] 6.1 `openspec validate redis-containerization --strict` clean
- [ ] 6.2 Commit, merge to `main`, drop the branch
- [ ] 6.3 `openspec archive redis-containerization` so the updated event-bus spec lands in `openspec/specs/event-bus/spec.md`
