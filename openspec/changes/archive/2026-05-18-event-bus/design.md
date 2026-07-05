## Context

KAINE Phase 1.1. The operator already runs a system Redis 7.0.15 on
`127.0.0.1:6379`. SETUP.md §1.2 chose Option A — system Redis hardened
with `requirepass` and AOF persistence — so the bus reuses the running
instance rather than running its own container. The bus is the connective
tissue from `docs/kaine-paper.md` §2.1: a recurrent dynamical system where
each module's output becomes input for every other module on the next
cycle. Every module in every future phase depends on this substrate.

Constraints:
- All-local: no remote registries or services at runtime.
- Reproducible: connection settings load from `config/kaine.toml` and a
  gitignored `config/secrets.toml`, with env-var overrides for CI.
- Sovereignty: no event content leaks outside the bus; Redis must bind
  loopback only and require a password.

Stakeholders: every later module, the cognitive cycle, Syneidesis, the
Nexus diagnostics view (rates only, not content).

## Goals / Non-Goals

**Goals:**
- A single canonical event schema validated at publish time.
- A thin Python client (`kaine.bus`) wrapping Redis Streams primitives
  (`XADD`, `XREAD`, `XRANGE`, optional consumer groups via `XGROUP`).
- One stream per module output channel (`<module>.out`) plus a reserved
  `workspace.broadcast` stream owned by Syneidesis.
- Stream retention by approximate length so the bus does not grow
  unbounded between operator-supervised maintenance windows.
- Async API everywhere (`redis.asyncio`) so the cognitive cycle can stay
  on one event loop.
- Fast unit tests via `fakeredis` and a separately-marked integration
  test against the live authenticated Redis.

**Non-Goals:**
- Cross-host replication, sharding, or HA. KAINE is single-host.
- A pub/sub abstraction richer than Redis Streams (no Kafka emulation,
  no transactional semantics across streams).
- Replacing Redis with an in-process queue for minimal deployments —
  that is documented in §6.2 of the paper as a future variant and lives
  behind the same `Bus` protocol but ships in a later change.
- Persistence policy beyond "AOF on, fsync everysec" — backup is owned
  by Phase 9 maintenance scripts.

## Decisions

**Use Redis Streams over Redis pub/sub.** Pub/sub is fire-and-forget; if
the cycle is paused or a module is slow, events are lost. Streams keep
history, support replay, and let consumer groups acknowledge what they
processed. Lost events would corrupt the recurrent dynamics — Mnemos
would miss episodes, Chronos would miss temporal patterns. Replay also
makes the fork-merge semantics (§4.3) tractable.

**One stream per producer, named `<module>.out`.** Alternative: a single
`bus` stream with every event tagged by source. Per-stream gives O(1)
filtering by source, lets a consumer skip whole streams it does not need,
and matches the §2.4 "publishes its outputs to its own named stream"
language. Cost: more `XREAD` arguments per cycle, negligible on a single
Redis. `workspace.broadcast` is the one exception — owned by Syneidesis
and consumed by all modules.

**Pydantic v2 for schema validation, not JSON Schema.** Pydantic gives
the same validation guarantees plus a typed Python class every module
interacts with. JSON Schema would require a separate type definition. The
canonical event lives at `kaine/bus/schema.py` and the same model
serializes to and deserializes from Redis stream entries.

**Serialize event payloads as JSON inside a single `payload` field; store
metadata (source, type, salience, timestamp, causal_parent) as separate
fields in the Redis stream entry.** Alternative: serialize the whole
event as JSON in one field. Splitting metadata lets `XRANGE` filters and
future diagnostics scan by source/type/salience without parsing every
payload. Floats and timestamps are stored as their string
representations to avoid Redis's lack of native numeric types.

**Configuration loader uses TOML (stdlib `tomllib` on Python ≥3.11).**
Single `config/kaine.toml` per the build prompt. Secrets split into
`config/secrets.toml` (gitignored, mode 600) plus env-var overrides
(`KAINE_REDIS_PASSWORD`, `KAINE_REDIS_URL`). The loader pattern
established here is reused by every later module.

**Stream retention by `MAXLEN ~ N`.** Approximate-length trimming is
O(1) amortized and is the standard Redis Streams idiom. Default
N=100000 per stream; configurable. Time-based retention is left for a
later maintenance script.

**Connection pool, single Redis client per process.** `kaine.bus`
exposes a module-level singleton `get_bus()` that lazy-initializes one
client. The cycle and all modules share it. This matches Redis's
recommendation against thrashing connections and keeps the audit
surface small.

**Audit guarantees encoded in code, not just docs.** On startup the bus
calls `CONFIG GET bind` and `CONFIG GET requirepass` and refuses to
proceed if either fails the audit. This shifts the security gate from
"operator remembered to harden" to "system refuses to run otherwise."

## Risks / Trade-offs

- **Redis is a single point of failure.** → Mitigation: AOF persistence
  on, snapshot path in `kaine.toml`, Phase 9 maintenance script does
  periodic `BGSAVE`. Acceptable for single-host KAINE; documented in
  §5.2 (distributed resilience) as a future mesh concern.
- **Stream growth between maintenance windows.** → Mitigation: MAXLEN
  trim on every publish; documented default and configurable.
- **Pydantic v2 import cost on cold start.** → Acceptable: cycle is
  long-lived, cold start happens once at boot.
- **fakeredis lag behind real Redis Streams behavior.** → Mitigation:
  integration test runs against the real Redis when present; CI uses
  fakeredis only for unit-level schema and serialization tests.
- **`CONFIG GET` may be disabled on hardened Redis instances.** →
  Mitigation: the audit check is best-effort and emits a warning
  rather than hard-failing when `CONFIG GET` returns an error;
  documented in `kaine/bus/AUDIT.md`.

## Migration Plan

This is the first change; no migration. Rollback is `git revert` of the
single Phase 1.1 commit before any later module depends on it.

## Open Questions

- Whether the bus should also expose a Redis pub/sub channel for "ephemeral
  notifications" (e.g. Soma temperature alerts) that do not warrant stream
  storage. Deferring until Phase 2.1 lands and we see whether Soma actually
  produces enough volume to want one. Default for now: everything goes
  through Streams.
