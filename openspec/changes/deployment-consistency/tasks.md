## 1. Quadlet volume units

- [x] 1.1 Create `quadlet/kaine-state.volume` with a `[Volume]` section and verify it parses with `podman systemd generate`.
- [x] 1.2 Create `quadlet/kaine-models.volume`, `quadlet/kaine-eval-data.volume`, `quadlet/kaine-trajectory.volume`, `quadlet/kaine-redis-data.volume`, and `quadlet/kaine-qdrant-data.volume` and verify all referenced volumes have matching files.
- [x] 1.3 Update `quadlet/README.md` install step to copy `*.volume` units alongside `*.container` and `*.network` files.

## 2. Quadlet Redis wiring

- [x] 2.1 Add `Environment=KAINE_REDIS_URL=redis://:${KAINE_REDIS_PASSWORD}@kaine-redis:6379/0` to `quadlet/kaine-cycle.container` and verify the URL is present.
- [x] 2.2 Add the same `KAINE_REDIS_URL` env var to `quadlet/kaine-nexus.container` and verify it is present.

## 3. Redis and Qdrant consistency

- [x] 3.1 Change `compose/redis.yml` Redis `--maxmemory` to `4gb` and verify it matches `compose/kaine.yml`.
- [x] 3.2 Change `quadlet/kaine-redis.container` `--maxmemory` to `4gb` and verify all three files match.
- [x] 3.3 Replace `quadlet/kaine-qdrant.container` `HealthCmd=curl ...` with `bash -c 'exec 3<>/dev/tcp/127.0.0.1/6333'` and verify no `curl` or `wget` remains.
- [x] 3.4 Update `scripts/redis-bootstrap.sh` if it sets `--maxmemory`, ensuring it matches the unified 4 gb value. (Script delegates to compose/redis.yml, so no direct change needed.)

## 4. Latent-vector stream caps and operator overlay

- [x] 4.1 Port the operator-overlay deep-merge from `fix/bus-config-operator-overlay` into `kaine/bus/config.py` and verify `load_bus_config` accepts an `operator_toml` parameter.
- [x] 4.2 Add `"topos.out" = 2000` and `"audition.out" = 2000` to `[bus.per_stream_maxlen]` in `config/kaine.toml` and verify the entries are present.
- [x] 4.3 Port or recreate the `test_operator_overlay_merges_per_stream_maxlen` test in `tests/test_bus_config.py` and verify it passes.
- [x] 4.4 Add a test that asserts the committed `config/kaine.toml` ships the latent-vector caps, so a future removal fails CI.

## 5. Validation and verification

- [x] 5.1 Run `openspec validate deployment-consistency --strict` and resolve all reported issues.
- [x] 5.2 Run `tests/test_bus_config.py`, `tests/test_container_deployment.py`, and any Quadlet-related tests and verify they pass.
- [x] 5.3 Verify `grep -h "Volume=kaine-" quadlet/*.container` shows only volume names that exist as `.volume` files.
