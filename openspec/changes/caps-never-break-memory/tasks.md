## 1. Fork snapshots are never deleted by infrastructure

- [ ] 1.1 Remove count-based eviction (`_enforce_retention` and the `max_snapshots_retained` parameter) from `ForkManager` in `kaine/lifecycle/manager.py`.
- [ ] 1.2 Remove `max_snapshots_retained` from `[lifecycle]` in `config/kaine.toml`; have the Nexus fork-manager builder log a warning when a config still sets it above 0.
- [ ] 1.3 Replace the eviction tests with: more than 64 snapshots are all kept; a set key warns and deletes nothing. Mutation-check by reintroducing deletion.

## 2. Eidolon identity history

- [ ] 2.1 Treat `identity_history_cap = 0` as no cap in `kaine/modules/eidolon/module.py`; reject negative values; default the constructor to 0.
- [ ] 2.2 Ship `identity_history_cap = 0` in `config/kaine.toml` with a comment.
- [ ] 2.3 Tests: cap 0 keeps more than 256 entries; cap 4 keeps the last 4; -1 is rejected.

## 3. Research record retention

- [ ] 3.1 Set `retention_days = 0` in `[evaluation.paths]`, `[research_event_log]` and `[research_event_log.raw_archive]` with comments.
- [ ] 3.2 Default the three dataclass fields in `kaine/evaluation/config.py` to 0.
- [ ] 3.3 Tests for the shipped values and the dataclass defaults.

## 4. Bus lookback

- [ ] 4.1 Set `topos.out = 12000`, `audition.out = 12000` and `workspace.broadcast = 100000` in `[bus.per_stream_maxlen]`; keep `default_maxlen = 100000`.
- [ ] 4.2 Add the typical event size table and lookup to `kaine/bus/config.py`.
- [ ] 4.3 Tests for the shipped caps and the size lookup.

## 5. Host-configurable Redis memory

- [ ] 5.1 Use `${KAINE_REDIS_MAXMEMORY:-4gb}` in `compose/kaine.yml` and `compose/redis.yml`.
- [ ] 5.2 In `quadlet/kaine-redis.container`, read `${KAINE_REDIS_MAXMEMORY}` in `Exec=` with `Environment=KAINE_REDIS_MAXMEMORY=4gb` in `[Service]` ahead of the existing `EnvironmentFile`.
- [ ] 5.3 In `scripts/lib/native-services.sh`, write `maxmemory ${KAINE_REDIS_MAXMEMORY:-4gb}`.
- [ ] 5.4 Document the variable in `compose/.env.example` and the deployment docs.
- [ ] 5.5 Extend the container, Quadlet and native bootstrap tests (hermetic: HOME/XDG_CONFIG_HOME in tmp, stubbed service tools).

## 6. Pre-boot resource rows

- [ ] 6.1 Add the WARN status to `kaine/preboot.py` (verdict counts it; it does not fail the gate).
- [ ] 6.2 Add `AsyncBus.server_maxmemory()` in `kaine/bus/client.py`.
- [ ] 6.3 Add the RESOURCES group: the bus budget row and the disk-free rows, run from `run_async_checks`.
- [ ] 6.4 Add the `[preboot]` table to `config/kaine.toml`.
- [ ] 6.5 Tests: bus budget PASS/WARN/FAIL with a fake bus, unreadable maxmemory → WARN, maxmemory 0 → WARN; disk rows PASS/WARN/FAIL with a fake disk usage; unknown `[preboot]` key → FAIL.

## 7. Docs and cleanup

- [ ] 7.1 Fix the light-consolidation docstring in `kaine/modules/hypnos/phases.py`.
- [ ] 7.2 Update the configuration reference, operations, fork/merge lifecycle, entity preservation, deployment and Eidolon docs.
- [ ] 7.3 Run ruff and the affected tests.
