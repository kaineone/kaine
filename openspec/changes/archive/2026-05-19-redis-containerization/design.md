## Context

The event-bus capability shipped in Phase 1 with the assumption that
the operator would harden the system Redis (Option A). The operator has
elected Option B instead — a KAINE-owned Redis in a Docker container —
and asked for the rationale clarification. This change implements that
switch with the smallest surface area: a compose file, a port change, a
narrow audit relaxation, and documentation.

Constraints:
- All-local: the container runs on the host with port mapping to host
  loopback only.
- Reproducible: the compose file pins the image tag and bakes in the
  hardening config so cloning the repo and running compose-up
  reproduces the same Redis.
- Sovereignty: nothing on the host (other operator workloads, other
  users) should be able to read KAINE's bus state.

Stakeholders: the bus audit logic, every Phase 1 test, the operator
running the deployment.

## Goals / Non-Goals

**Goals:**
- KAINE talks to a Redis it provisioned, on a port distinct from any
  pre-existing Redis on the host.
- Port mapping uses `127.0.0.1:<host_port>:<container_port>` so the
  service is unreachable from outside the host.
- AOF persistence on, fsync everysec, maxmemory bounded.
- Password required, sourced from environment / `compose/.env`.
- The bus audit accepts a containerized Redis without manual override.

**Non-Goals:**
- Migrating any data from the operator's existing system Redis.
- A KAINE-specific Redis image. Stock `redis:7.2-alpine` with command
  flags is enough.
- TLS to Redis. Loopback-only port mapping makes it unnecessary.
- Sentinel / Cluster. KAINE is single-host.

## Decisions

**Use stock `redis:7.2-alpine` with command-line flags rather than a
mounted `redis.conf`.** Single-file compose is easier to reason about;
no need to track a separate config artifact. All hardening lives in the
`command:` section of `compose/redis.yml`.

**Host port 6479.** Distinct from the system Redis (6379) so the two
can coexist. Configurable via `compose/.env` for operators with a
collision.

**Inside the container, bind 0.0.0.0 with `protected-mode yes` and
`requirepass`.** Docker bridge networking requires the container to
listen on its bridge interface; `127.0.0.1` inside the container would
make it unreachable. `protected-mode yes` plus `requirepass` means the
only path in is authenticated connections, and the Docker port mapping
restricts those to host loopback.

**Audit's bind check becomes conditional on the configured host.** If
KAINE's `bus.config.host` is loopback (`127.0.0.1`, `::1`, `localhost`),
the audit accepts whatever bind Redis reports. The reasoning: KAINE's
own connection arrives via loopback; the rest of the network is
unreachable by transport, not by Redis config. The `requirepass` check
remains unconditional — auth is enforced for every connection,
containerized or not.

**Compose file location: `compose/redis.yml`.** Matches the Phase 0
directory layout. Future Phase 3.2 will add `compose/qdrant.yml`
alongside.

**Use `${KAINE_REDIS_PASSWORD:?…}` in the compose command so the
container refuses to start without a password.** Same fail-fast posture
as `BusConfig` itself.

**Healthcheck via `redis-cli ping` with the password.** Compose can
wait for it to be healthy before starting dependent services. KAINE
uses this when later phases add modules that need the bus from the
moment compose comes up.

## Risks / Trade-offs

- **Port collision on 6479.** → Documented in `compose/.env.example`;
  operator overrides via env.
- **`docker compose up` requires the password to be in env or .env.**
  → Same secret as KAINE consumes; documenting both reads of the same
  source is straightforward.
- **AOF growth between rest cycles.** → AOF rewrite cadence is left to
  Redis defaults; Phase 6 Hypnos can trigger explicit BGREWRITEAOF in
  the maintenance phase.
- **Audit bind relaxation could mask a misconfigured non-containerized
  Redis bound to 0.0.0.0 on loopback host.** → Accepted; the operator
  who reaches loopback from a misconfigured non-loopback Redis is
  outside the threat model. Documenting in AUDIT.md.

## Migration Plan

1. Operator sets `KAINE_REDIS_PASSWORD` env var (or fills
   `compose/.env`).
2. Operator runs `docker compose -f compose/redis.yml up -d`.
3. Operator runs `KAINE_REDIS_PASSWORD=<value> .venv/bin/python -m pytest tests/integration/`.
   The three skipped integration tests now run against the containerized
   Redis and pass.
4. Any earlier draft edits to `/etc/redis/redis.conf` may be reverted.

Rollback: `docker compose -f compose/redis.yml down` and revert this
commit. The system Redis was never touched.

## Open Questions

- Whether to ship a `scripts/redis-up.sh` and `scripts/redis-down.sh`
  thin wrapper for ergonomics. Deferring until Phase 9 packages the
  full operator script set.
