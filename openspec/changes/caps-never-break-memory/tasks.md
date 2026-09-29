## 1. Fork snapshots are never deleted by infrastructure

- [x] 1.1 Remove count-based eviction (`_enforce_retention` and the `max_snapshots_retained` parameter) from `ForkManager` in `kaine/lifecycle/manager.py`.
- [x] 1.2 Remove `max_snapshots_retained` from `[lifecycle]` in `config/kaine.toml`; have the Nexus fork-manager builder log a warning when a config still sets it above 0.
- [x] 1.3 Replace the eviction tests with: more than 64 snapshots are all kept; a set key warns and deletes nothing. Mutation-check by reintroducing deletion.

## 2. Eidolon identity history

- [x] 2.1 Treat `identity_history_cap = 0` as no cap in `kaine/modules/eidolon/module.py`; reject negative values; default the constructor to 0.
- [x] 2.2 Ship `identity_history_cap = 0` in `config/kaine.toml` with a comment.
- [x] 2.3 Tests: cap 0 keeps more than 256 entries; cap 4 keeps the last 4; -1 is rejected.

## 2b. Learned voice state

- [x] 2b.1 `voice_observations_cap`: default 0 (no cap) in `kaine/modules/eidolon/module.py` and `config/kaine.toml`; a positive value keeps the newest N; negative raises.
- [x] 2b.2 `adapter_retention`: default 0 (keep every accepted adapter) in `VoiceAlignmentConfig`, `kaine/boot.py` and `config/kaine.toml`; the trainer prunes only when it is positive; negative raises.
- [x] 2b.3 Tests and a mutation check for each; docs updated.

## 3. Research record retention

- [x] 3.1 Set `retention_days = 0` in `[evaluation.paths]`, `[research_event_log]` and `[research_event_log.raw_archive]` with comments.
- [x] 3.2 Default the three dataclass fields in `kaine/evaluation/config.py` to 0.
- [x] 3.3 Tests for the shipped values and the dataclass defaults.

## 4. Bus lookback

- [x] 4.1 Set `topos.out = 12000`, `audition.out = 12000` and `workspace.broadcast = 100000` in `[bus.per_stream_maxlen]`; keep `default_maxlen = 100000`.
- [x] 4.2 Add the typical event size table and lookup to `kaine/bus/config.py`.
- [x] 4.3 Tests for the shipped caps and the size lookup.

## 5. Host-configurable Redis memory

- [x] 5.1 Use `${KAINE_REDIS_MAXMEMORY:-4gb}` in `compose/kaine.yml` and `compose/redis.yml`.
- [x] 5.2 In `quadlet/kaine-redis.container`, read `${KAINE_REDIS_MAXMEMORY}` in `Exec=` with `Environment=KAINE_REDIS_MAXMEMORY=4gb` in `[Service]` ahead of the existing `EnvironmentFile`.
- [x] 5.3 In `scripts/lib/native-services.sh`, write `maxmemory` from `KAINE_REDIS_MAXMEMORY` (environment, else `compose/.env`, else `4gb`), refusing a value that is not a Redis memory size.
- [x] 5.4 Document the variable in `compose/.env.example` and the deployment docs.
- [x] 5.5 Extend the container, Quadlet and native bootstrap tests (hermetic: HOME/XDG_CONFIG_HOME in tmp, stubbed service tools).

## 6. Pre-boot resource rows

- [x] 6.1 Add the WARN status to `kaine/preboot.py` (verdict counts it; it does not fail the gate).
- [x] 6.2 Add `AsyncBus.server_maxmemory()` in `kaine/bus/client.py`.
- [x] 6.3 Add the RESOURCES group: the bus budget row and the disk-free rows, run from `run_async_checks`.
- [x] 6.4 Add the `[preboot]` table to `config/kaine.toml`.
- [x] 6.5 Tests: bus budget PASS/WARN/FAIL with a fake bus, unreadable maxmemory → WARN, maxmemory 0 → WARN; disk rows PASS/WARN/FAIL with a fake disk usage; unknown `[preboot]` key → FAIL.

## 7. Docs and cleanup

- [x] 7.1 Fix the light-consolidation docstring in `kaine/modules/hypnos/phases.py`.
- [x] 7.2 Update the configuration reference, operations, fork/merge lifecycle, entity preservation, deployment and Eidolon docs.
- [x] 7.3 Run ruff and the affected tests.

## 8. Second review

- [x] 8.1 Eidolon records drift as episodes (one entry per contiguous alert run, summarising every alert), updates the list in place, and saves compact JSON with the C encoder; older per-alert and indented files still load.
- [x] 8.2 The bus budget samples per-entry sizes from the live bus, FAILS only on measured sizes, and WARNS naming the streams at the 2 KB estimate; docs and `compose/.env.example` say a full study needs `KAINE_REDIS_MAXMEMORY=12gb` or more.
- [x] 8.3 Disk rows cover every configured durable path, grouped per filesystem.
- [x] 8.4 `native-services.sh` parses `compose/.env` the way compose does (spaces, `export`, quotes, inline comment), keeping the anchored validation.
- [x] 8.5 The Quadlet unit starts Redis through an `sh` wrapper that defaults an unset or empty value to `4gb` and refuses a malformed one.
- [x] 8.6 Tests and mutation checks for 8.1 and 8.2.
