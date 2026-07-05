## Why

KAINE's modules cannot exist in isolation — the entire architecture rests on
every module reading from and writing to a single shared substrate every
cycle (`docs/kaine-paper.md` §2.1). Without a bus, the system has no
connective tissue and no recurrent dynamics; the modules collapse to a set of
unrelated functions. This change introduces the substrate first because
every other Phase 1 piece (the cognitive cycle, Syneidesis, the module
pattern, and the dummy echo test) needs to publish or subscribe to it.

We are doing it now because the operator just confirmed Redis hardening
(Option A — system Redis with `requirepass` + AOF persistence), the only
remaining blocker for landing the bus.

## What Changes

- Introduce the `kaine.bus` Python package as the canonical entry point
  every module uses to talk to the event bus.
- Define the canonical event schema with strict validation: `source: str`,
  `type: str`, `payload: dict`, `salience: float in [0,1]`, `timestamp:
  ISO-8601`, `causal_parent: Optional[str]`. Events that fail validation
  are rejected at publish time, not at consume time.
- Use Redis Streams (one stream per module's output channel, plus a
  `workspace.broadcast` stream owned by Syneidesis) so consumers can replay
  history, range-scan by timestamp, and use consumer groups when multiple
  consumers process the same stream.
- Configuration lives in `config/kaine.toml` (host, port, db, stream
  retention) and `config/secrets.toml` (Redis password, gitignored). Env
  vars (`KAINE_REDIS_URL`, `KAINE_REDIS_PASSWORD`) override.
- Ship a publish/subscribe roundtrip integration test that requires a
  password-authed Redis. Unit tests use `fakeredis` so they run on any
  machine.
- Document the Redis configuration audit (loopback bind, requirepass set,
  AOF persistence enabled, dangerous commands disabled in production) in
  `kaine/bus/AUDIT.md`.

## Capabilities

### New Capabilities

- `event-bus`: Redis Streams substrate plus the `kaine.bus` Python client
  enforcing the canonical event schema. Owns connection management,
  serialization, validation, and the per-module stream naming convention.

### Modified Capabilities

None — this is the first capability KAINE ships.

## Impact

- **Repo:** adds `kaine/bus/`, `kaine/bus/AUDIT.md`, `config/kaine.toml`,
  `config/secrets.example.toml`, `tests/test_bus.py`,
  `tests/integration/test_bus_roundtrip.py`, and a `pyproject.toml`
  pinning `redis>=5`, `pydantic>=2`, `tomli` (only on Python <3.11),
  `fakeredis>=2.21` for tests.
- **Operator dependency:** Redis hardening (SETUP.md §1.2) must be complete
  and the password placed at `config/secrets.toml` or exported as
  `KAINE_REDIS_PASSWORD`.
- **Downstream:** unblocks `cognitive-cycle`, `syneidesis`, `module-pattern`,
  and every module change after that. None of them can be implemented or
  tested without this substrate.
- **No runtime impact** — nothing in this change starts a cycle or
  allocates module state. The bus exists, modules just don't use it yet.
