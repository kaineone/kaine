# Redis bus — security audit checklist

This checklist is enforced both by `kaine.bus.AsyncBus.audit()` (which
refuses to start the bus when the Redis it can introspect is misconfigured)
and by this document for the parts that `CONFIG GET` cannot detect on a
hardened Redis.

KAINE's reference deployment puts Redis in a Docker container brought up
by `compose/redis.yml`. The container exposes its port to the host as
`127.0.0.1:6479:6379` and listens on `0.0.0.0` *inside* the container —
that combination is safe because the Docker port mapping is what
restricts external reach, not Redis's own `bind`.

| # | Setting | Required value | How `audit()` checks it | How to set it (containerized) | How to set it (system Redis) |
|---|---|---|---|---|---|
| 1 | network isolation | reachable only from host loopback | `audit()` skips its own `bind` query when the configured host is loopback (`127.0.0.1`, `::1`, `localhost`), since the port mapping enforces isolation; for non-loopback hosts it falls back to `CONFIG GET bind` and refuses `0.0.0.0` / `*` | `ports: 127.0.0.1:6479:6379` in `compose/redis.yml` | `bind 127.0.0.1 -::1` in `/etc/redis/redis.conf` |
| 2 | `requirepass` | **required on every host** (loopback or not) | `CONFIG GET requirepass`; refuses to start when empty | `--requirepass ${KAINE_REDIS_PASSWORD}` in compose; password from `compose/.env` | `requirepass <strong random>` in `/etc/redis/redis.conf` |
| 3 | `protected-mode` | `yes` | not directly checked | `--protected-mode yes` in compose | `protected-mode yes` in `/etc/redis/redis.conf` |
| 4 | `appendonly` | `yes` | not directly checked | `--appendonly yes` in compose | `appendonly yes` in `/etc/redis/redis.conf` |
| 5 | `appendfsync` | `everysec` | not directly checked | `--appendfsync everysec` in compose | `appendfsync everysec` in `/etc/redis/redis.conf` |
| 6 | Dangerous commands disabled | recommend renaming `FLUSHALL`, `FLUSHDB`, `CONFIG` for production | not checked; disabling `CONFIG` would cause this audit to fall back to warnings, which is acceptable | not yet enforced in compose; documented for hardening | rename-command lines in `/etc/redis/redis.conf` |
| 7 | `maxmemory` | sized to host RAM minus other workloads | not checked | `--maxmemory 1gb` in compose | `maxmemory <bytes>` in `/etc/redis/redis.conf` |
| 8 | `maxmemory-policy` | `noeviction` (the bus relies on `MAXLEN` trimming, not LRU) | not checked | `--maxmemory-policy noeviction` in compose | `maxmemory-policy noeviction` in `/etc/redis/redis.conf` |

When Redis answers `(error) ERR ...` to `CONFIG GET` (a common production
hardening), `audit()` logs a warning naming the unverified setting and
continues. Operators running with `CONFIG` disabled are responsible for
verifying rows 1, 2, 3, 4, 5 by inspecting the compose file or Redis
config.

The audit runs once per process on the first call to `get_bus()`.
Subsequent calls are no-ops.

## Threat model

The audit's only relaxation is the `bind` check on loopback hosts:
Docker port mapping (`127.0.0.1:6479:6379`) enforces network
isolation regardless of what Redis binds inside the container. The
`requirepass` check is **not** relaxed — it applies to every host —
because KAINE entities are expected to eventually run on
network-attached hosts (the paper's §5.2 mutual-backup mesh, future
internet-exposed deployments), and the same checkout must be safe to
ship there.

A loopback-only deployment where the operator trusts every local
process technically doesn't need the password. We require it anyway
for three reasons:

1. **Travel safety.** The same code shipped to a network-attached
   host is no longer loopback-only. If the password were optional,
   forgetting to flip it on becomes a deployment-time vulnerability.
2. **Defense in depth.** Even on a single-user box, a compromised
   process inside the trust boundary can read/write the bus state
   without auth. The password reduces the blast radius.
3. **Spec adherence.** Build prompt §1.1 mandates "auth enabled."
   The audit enforces what the spec promises.

To bring the bus up: put `KAINE_REDIS_PASSWORD=<random>` in
`compose/.env` and mirror it into `config/secrets.toml` under
`[redis].password`. `docker compose -f compose/redis.yml up -d`
refuses to start without the env var.
