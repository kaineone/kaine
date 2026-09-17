## Why

The production Quadlet deployment path is non-functional as shipped: it references Podman volume units that do not exist, omits the Redis URL the cycle and Nexus need to reach the bus, uses a healthcheck command the Qdrant image lacks, and caps the Redis event bus at different memory limits across deployment files. In addition, the latent-vector stream caps that prevent a Redis out-of-memory crash (`topos.out` and `audition.out`) are present only on an unmerged branch and missing from `main`. This change makes the production deployment consistent and crash-resistant.

## What Changes

- **Add missing Quadlet `.volume` units.** Create `kaine-state.volume`, `kaine-models.volume`, `kaine-eval-data.volume`, `kaine-trajectory.volume`, `kaine-redis-data.volume`, and `kaine-qdrant-data.volume` under `quadlet/`.
- **Wire `KAINE_REDIS_URL` into Quadlet cycle and Nexus units.** Set the env var so the in-container processes reach the Redis service by container name, matching `compose/kaine.yml`.
- **Unify Redis `--maxmemory` across deployment files.** Set the same cap (4 gb) in `compose/kaine.yml`, `compose/redis.yml`, and `quadlet/kaine-redis.container`.
- **Fix the Quadlet Qdrant healthcheck.** Replace the `curl`-based probe with the `bash /dev/tcp` probe that works in the minimal Qdrant image, matching `compose/kaine.yml`.
- **Restore latent-vector stream caps on `main`.** Set `[bus.per_stream_maxlen]` defaults for `topos.out` and `audition.out` to 2000 entries, and wire the operator-overlay deep-merge into `load_bus_config()` so operator overrides are honored.
- **Update `quadlet/README.md`** to mention copying `.volume` units alongside `.container` and `.network` files.

## Capabilities

### New Capabilities
- `quadlet-volumes`: Podman Quadlet volume units for durable KAINE state and evaluation data.

### Modified Capabilities
- `distributed-deployment`: Add Quadlet production-path requirements for volume units, Redis URL wiring, and memory/healthcheck consistency.
- `event-bus`: Add per-stream maxlen defaults for latent-vector streams and operator-overlay merge behavior.
- `redis-bootstrap`: Unify Redis memory cap and healthcheck strategy across deployment files.

## Impact

- `quadlet/*.volume` (new files).
- `quadlet/kaine-cycle.container`, `quadlet/kaine-nexus.container`.
- `quadlet/kaine-redis.container`, `quadlet/kaine-qdrant.container`.
- `quadlet/README.md`.
- `compose/redis.yml`.
- `config/kaine.toml` `[bus.per_stream_maxlen]`.
- `kaine/bus/config.py` operator-overlay merge.
- `tests/test_bus_config.py` for the overlay/maxlen tests.
