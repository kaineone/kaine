## Why

A cap that fires in the middle of a run either halts the entity or silently
removes part of its memory. Both have happened or can happen today:

- Redis runs with `--maxmemory 4gb` and `noeviction`. When the bus filled, a live
  entity halted. The limit is hardcoded in four deployment files, so a host with
  more memory cannot raise it without editing tracked files.
- `ForkManager` deletes the oldest snapshot directories under `state/forks/` once
  there are more than `[lifecycle].max_snapshots_retained` (64). That directory
  holds preserved beings and Spot escalation snapshots. Infrastructure must never
  delete an entity. Deletion is the CAL-gated decommission path only.
- `[eidolon].identity_history_cap = 256` truncates the entity's self-model
  identity history, which is entity memory.
- The evaluation logs, the curated research event log and the raw archive purge
  files older than 30 days, so a long study loses its own records.
- `topos.out` and `audition.out` keep 2000 entries, about 3 minutes at 10 Hz. An
  observer or archive restart that takes longer than that loses research records.

The operator principle: raise caps rather than let entities hit them, keep an
eye on disk space on small devices, and never let an entity's memory break
because a store was culled or hit a cap. Resource limits are checked before boot
instead of being enforced by deleting data during a run.

## What Changes

- **No infrastructure deletion of snapshots.** `ForkManager` has no count-based
  eviction. `[lifecycle].max_snapshots_retained` is gone from the shipped config.
  An operator config that still sets it is accepted. A positive value logs a
  warning that the key is ignored; nothing is deleted.
- **Unbounded identity history by default.** `[eidolon].identity_history_cap`
  ships as `0`, meaning no cap. A positive value still keeps the most recent N
  entries. A negative value is rejected.
- **Learned voice state is kept.** `[eidolon].voice_observations_cap` ships
  as `0` (no cap) with the same rules as `identity_history_cap`.
  `[hypnos.voice_alignment].adapter_retention` ships as `0`, keeping every
  accepted adapter; a positive value still evicts the oldest beyond N and a
  negative value is rejected. Adapters are large: disk is protected by the
  pre-boot disk rows, not by deletion.
- **Research records are kept.** `retention_days` ships as `0` (keep) in
  `[evaluation.paths]`, `[research_event_log]` and
  `[research_event_log.raw_archive]`, and the matching dataclass defaults are 0.
  A positive value still purges older daily files.
- **Longer bus lookback.** `[bus.per_stream_maxlen]` ships `topos.out = 12000`,
  `audition.out = 12000` and `workspace.broadcast = 100000`. `default_maxlen`
  stays 100000.
- **Host-configurable Redis memory.** `KAINE_REDIS_MAXMEMORY` (default `4gb`) sets
  `--maxmemory` in `compose/kaine.yml`, `compose/redis.yml`, the Quadlet unit
  (through its existing `EnvironmentFile`, with a unit-level default) and the
  native `redis.conf` writer. `noeviction` stays.
- **Pre-boot resource rows.** `python -m kaine.preboot` gains a RESOURCES group:
  - **Bus budget:** for each stream the enabled modules produce, maxlen × a
    typical event size from a table in `kaine/bus/config.py`, doubled for
    AOF-rewrite headroom, compared with the server's `CONFIG GET maxmemory`.
    FAIL above maxmemory, WARN above 70%, WARN when maxmemory cannot be read.
  - **Disk free:** for the state root, the data root and the native Redis data
    directory, FAIL below max(10 GB, 5%) free and WARN below 20 GB. The
    thresholds and roots are keys in a new `[preboot]` table.
  - The report gains a WARN status. WARN does not fail the gate.
- **Docstring fix.** The Hypnos light-consolidation docstring says what
  `consolidate_now()` does: it moves short-term entries to episodic memory and
  drops nothing.

## Capabilities

### New Capabilities
- `preboot-resources`: bus memory budget and disk-free rows in the pre-boot gate,
  and the WARN status.

### Modified Capabilities
- `entity-preservation`: infrastructure never deletes fork snapshots.
- `eidolon`: identity history and voice observations are unbounded by default.
- `voice-alignment-training`: accepted adapters are kept by default.
- `research-event-log`: research records are kept by default.
- `event-bus`: longer per-stream lookback and typical event sizes for budgeting.
- `distributed-deployment`: the Redis memory cap is set by one host variable.
- `redis-bootstrap`: the native path honors the same variable.

## Impact

- `kaine/lifecycle/manager.py`, `kaine/nexus/__main__.py`
- `kaine/modules/eidolon/module.py`
- `kaine/modules/hypnos/voice_alignment.py`, `kaine/modules/hypnos/unsloth_trainer.py`, `kaine/boot.py`
- `kaine/evaluation/config.py`
- `kaine/bus/config.py`, `kaine/bus/client.py`
- `kaine/preboot.py`
- `kaine/modules/hypnos/phases.py`
- `config/kaine.toml`
- `compose/kaine.yml`, `compose/redis.yml`, `compose/.env.example`,
  `quadlet/kaine-redis.container`, `scripts/lib/native-services.sh`
- Docs: configuration, operations, fork/merge lifecycle, entity preservation,
  deployment containers and topologies, Eidolon module page.
- Operator overlays that repeat the old per-stream caps
  (`config/kaine.operator.toml`) keep those values until the operator raises
  them. That file is operator-owned and is not edited by this change.
- Memory and disk use grow over a long run. The pre-boot rows report this before
  boot rather than letting the run hit a limit.
