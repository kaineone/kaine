## Why

In the Phase 0 install gap list, SETUP.md §1.2 offered two paths for
hardening the event bus's Redis substrate: (A) tighten the operator's
existing system Redis, or (B) run a KAINE-owned Redis in a container.
Option A was recommended on the rationale that B was "harder to share."
After review, that rationale was wrong. KAINE's sovereignty
(`docs/kaine-paper.md` §5.1) explicitly *does not want* its bus state
shared with arbitrary other applications on the host — sharing is a
vulnerability surface, not a feature. Option B is the correct choice on
the merits: full isolation, reproducible from the repo, pinned version,
audit surface owned end-to-end by KAINE.

This change implements Option B. The operator's existing system Redis
on `127.0.0.1:6379` is left untouched.

## What Changes

- Add `compose/redis.yml`: a Docker Compose service running
  `redis:7.2-alpine` exposed on `127.0.0.1:6479` (avoids the system
  Redis on 6379), with persistent volume `kaine-redis-data`, AOF
  enabled, `appendfsync everysec`, `maxmemory 1gb`,
  `maxmemory-policy noeviction`, and password from
  `${KAINE_REDIS_PASSWORD}` set via env or `compose/.env`.
- Add `compose/.env.example` and gitignore `compose/.env`.
- Update `config/kaine.toml` default `[redis]` port from 6379 to 6479.
- **MODIFIED** `event-bus`'s "Startup audit of Redis configuration"
  requirement: when the configured Redis host is loopback
  (`127.0.0.1`, `::1`, `localhost`), the bus SHALL skip the `bind`
  check, because Docker port mapping (`127.0.0.1:6479:6379`) enforces
  network isolation regardless of what Redis binds inside the
  container. The `requirepass` check still applies in all cases.
- Update `kaine/bus/AUDIT.md` documenting why the bind check is
  conditional and what the operator must verify manually for
  containerized deployments (the port mapping must be loopback).
- Update `SETUP.md` §1.2 to reflect the operator's switch to Option B
  and retract the weak "harder to share" rationale, and §1.4 GPU
  assignment is unaffected.
- Update `DEPENDENCIES.md` to add the redis container image and remove
  the system-Redis-reuse note.

## Capabilities

### New Capabilities

None — this change reuses the existing `event-bus` capability.

### Modified Capabilities

- `event-bus`: the "Startup audit of Redis configuration" requirement
  now has a loopback-host exception for the `bind` portion of the
  audit. All other event-bus requirements are unchanged.

## Impact

- **Repo:** adds `compose/redis.yml`, `compose/.env.example`, updates
  `config/kaine.toml`, `kaine/bus/client.py` (audit logic),
  `kaine/bus/AUDIT.md`, `SETUP.md`, `DEPENDENCIES.md`,
  `tests/test_bus_client.py` (audit cases). Updates `.gitignore` for
  `compose/.env`.
- **Operator action:** set `KAINE_REDIS_PASSWORD`, run
  `docker compose -f compose/redis.yml up -d`, then run the live
  integration tests in `tests/integration/test_bus_roundtrip.py`. The
  existing system Redis on 6379 is not touched and stays available
  for the operator's other workloads.
- **Cleanup:** any half-done `/etc/redis/redis.conf` edits from the
  earlier Option A flow can be reverted; KAINE no longer uses the
  system Redis.
- **No runtime impact** on the cognitive cycle. Nothing boots.
