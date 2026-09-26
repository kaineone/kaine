# Proposal — `native-services`

## Why

The entity's bus (Redis) and memory store (Qdrant) are only set up through Docker: `redis-bootstrap.sh` and `qdrant-bootstrap.sh` recreate containers, and `first-boot.sh` insists on them. The hosts the operator wants the entity on are:
- a Jetson Orin Nano Super, where Docker competes for 8 GB of unified memory;
- a Pixel 6a under Termux, which has no Docker at all;
- any Linux host where the operator prefers native services.

This is phase 1 of the portability program ("bootstrap Redis without Docker").

## What changes

- **`--native` for `scripts/redis-bootstrap.sh`.** It runs a user-level `redis-server` with no root and no system service. It does not use the host's system Redis, which may serve other things.
  - The server runs from `state/services/redis/`, with its own config, port 6479, bound to loopback, and the same generated `requirepass`.
  - `appendonly yes` is set, with the unified memory cap the container uses.
  - It starts under `systemd --user` when available, and otherwise as a supervised background process with a pid file.
  - It reuses the same password and secrets handling as the container path, and must reach `PONG` the same way.
- **`--native` for `scripts/qdrant-bootstrap.sh`.** It downloads the official Qdrant release binary for the host's architecture (x86_64 or aarch64 Linux).
  - The binary is pinned by version and sha256 in the script, and the release version matches the client pin; the container image's v1.18.0 drifts from the client pin ≥1.19.1 today.
  - It runs from `state/services/qdrant/` with an API key, on loopback port 6533, and is supervised the same way.
- **The bootstrap chooses.** Without a flag, the scripts use Docker when it is present and fall back to native otherwise. `--container` forces the container path.
- **`first-boot.sh`** accepts either the containers or the native services, checked by the same loopback, authentication and health rules.
- **Status.** `scripts/services.sh status|start|stop` covers both kinds.

## Out of scope

- Termux: `pkg install redis` works, but Qdrant has no Android build. On Termux the memory backend is `sqlite_vec` (phase 3), and the Qdrant step is skipped with that reason stated.

## Impact

- The bootstrap scripts, a new `scripts/services.sh`, `first-boot.sh`, and the docs.
- The container path is unchanged.
