## 1. Repo plumbing

- [x] 1.1 Add `pyproject.toml` declaring the `kaine` package, Python ≥ 3.11, and runtime deps `redis>=5,<6`, `pydantic>=2.6,<3`, plus test deps `fakeredis>=2.21`, `pytest>=8`, `pytest-asyncio>=0.23`
- [x] 1.2 Add `kaine/__init__.py`, `kaine/bus/__init__.py`, `tests/__init__.py`, `tests/integration/__init__.py`
- [x] 1.3 Add `config/kaine.toml` with `[redis]` host/port/db/maxlen defaults and `[bus]` stream-naming knobs
- [x] 1.4 Add `config/secrets.example.toml` (committed) and document that `config/secrets.toml` is gitignored
- [x] 1.5 Add the `kaine/bus/AUDIT.md` audit checklist

## 2. Schema and errors

- [x] 2.1 Implement `kaine/bus/schema.py` with the `Event` pydantic v2 model and validators per the spec's first requirement
- [x] 2.2 Implement `kaine/bus/errors.py` with `EventValidationError`, `ReservedStreamError`, `BusConfigError`, `BusSecurityError`
- [x] 2.3 Write `tests/test_bus_schema.py` covering valid event, out-of-range salience, missing source, non-UTC timestamp, oversize payload

## 3. Config loader

- [x] 3.1 Implement `kaine/bus/config.py` that reads `kaine.toml` via `tomllib`, then layers `secrets.toml`, then env vars, returning a `BusConfig` dataclass
- [x] 3.2 Write `tests/test_bus_config.py` covering env-var override, missing-password failure, secrets file permissions warning

## 4. Async client

- [x] 4.1 Implement `kaine/bus/client.py` with `AsyncBus` wrapping `redis.asyncio.Redis`; methods `publish`, `read`, `range`, `trim`, `subscribe_workspace`, `publish_workspace`, `close`
- [x] 4.2 Enforce module name → `<module>.out` mapping and reserve `workspace.broadcast` for Syneidesis only
- [x] 4.3 Implement startup audit (`CONFIG GET bind`, `CONFIG GET requirepass`) with the warning-on-permission-denied fallback
- [x] 4.4 Implement `get_bus()` singleton with thread-safe lazy init
- [x] 4.5 MAXLEN trim on every publish using `redis-py`'s `xadd(..., maxlen=N, approximate=True)`

## 5. Tests

- [x] 5.1 Write `tests/test_bus_client.py` using `fakeredis.aioredis.FakeRedis` for unit-level coverage of publish, read, reserved-stream rejection, MAXLEN trim, singleton behavior
- [x] 5.2 Write `tests/integration/test_bus_roundtrip.py` marked `@pytest.mark.integration` requiring the live authenticated Redis: publish→read→deserialize equality, nested payload, float precision, audit pass
- [x] 5.3 Add `pytest.ini` or `pyproject.toml [tool.pytest.ini_options]` configuring the `integration` marker, asyncio mode, and that integration tests are skipped when `KAINE_REDIS_PASSWORD` is unset

## 6. Verification

- [x] 6.1 Run unit tests; all pass (22 passed, 3 integration skipped 2026-05-18)
- [ ] 6.2 With the operator's hardened Redis live, run integration tests; all pass
- [ ] 6.3 Commit on branch `phase-1.1-event-bus`, open and merge to `main`
- [ ] 6.4 `openspec validate event-bus` returns clean, then `openspec archive event-bus` moves the spec into `openspec/specs/event-bus/spec.md`
