## Context

See `proposal.md` for motivation. The Quadlet units reference named volumes that do not exist, the cycle/Nexus units lack the Redis URL env var, the Qdrant healthcheck uses `curl` which is absent from the image, and the Redis memory cap differs across files. The latent-vector stream caps and operator-overlay merge are implemented on branch `fix/bus-config-operator-overlay` but not on `main`.

## Goals / Non-Goals

**Goals:**
- Make the Quadlet production path start successfully on a fresh rootless Podman host.
- Prevent Redis out-of-memory crashes with consistent, low caps on latent-vector streams.
- Honor operator overrides of bus config.
- Keep deployment files internally consistent.

**Non-Goals:**
- Changing the compose path's behavior or defaults.
- Adding new services or containers.
- Modifying the Redis authentication model.

## Decisions

**Decision 1: Add `.volume` units rather than host paths.**
Named Podman volumes are simpler for operators and match the compose path. Host paths would require SELinux relabeling and uid mapping that the compose path avoids with named volumes.

**Decision 2: Use `kaine-redis:6379/0` in `KAINE_REDIS_URL`.**
This matches the compose service name resolution inside the Podman network. The password is interpolated from the existing `KAINE_REDIS_PASSWORD` env var.

**Decision 3: Unify on 4 gb `--maxmemory`.**
The compose topology-of-record uses 4 gb. The 1 gb settings in `compose/redis.yml` and `quadlet/kaine-redis.container` are lower and risk `noeviction` write failures. Unifying on 4 gb removes the discrepancy.

**Decision 4: Port the operator-overlay merge from `fix/bus-config-operator-overlay`.**
The implementation is already reviewed and tested on that branch. Porting it to `main` restores the latent-vector caps and the override behavior.

## Risks / Trade-offs

- **[Risk]** Adding `.volume` units changes the documented install step.
  → **Mitigation:** Update `quadlet/README.md` to include `*.volume` in the copy command.
- **[Risk]** Raising the Redis cap in `compose/redis.yml` increases memory usage on small hosts.
  → **Mitigation:** The latent-vector stream caps are the primary memory control; 4 gb is the existing topology-of-record value and is already used by the main compose file.
- **[Risk]** The operator-overlay merge changes config precedence.
  → **Mitigation:** It is a deep merge that only overrides keys present in the operator file; base config values remain unchanged otherwise.
