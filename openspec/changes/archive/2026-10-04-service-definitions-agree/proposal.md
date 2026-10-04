# Service definitions agree across compose, quadlet and the native installer

## Why

The complexity audit of 2026-10-03 (W11) found Redis, Qdrant and the model server defined in several places:
- `compose/kaine.yml`, the canonical stack;
- the standalone `compose/redis.yml` and `compose/qdrant.yml`, which the docs and CONTRIBUTING reference;
- the Podman quadlet units in `quadlet/`;
- the native installer, `scripts/lib/native-services.sh`.

Nothing checked that they agree, and they had already drifted. An earlier change moved the standalone compose file and the native installer to Qdrant `v1.19.1`, and left `compose/kaine.yml` and the quadlet unit on `v1.18.0`.

## What changes

- **Alignment.** `compose/kaine.yml` and `quadlet/kaine-qdrant.container` pin Qdrant `v1.19.1`, like the standalone file and the native installer.
- **A test, `tests/test_service_definitions_agree.py`, fails when the definitions differ in:**
  - the image, for Redis, Qdrant, the model server, Speaches and Chatterbox, across the canonical compose, the standalone compose files and the quadlet units;
  - the native Qdrant version;
  - the published host and container ports, Nexus included;
  - the Redis server arguments;
  - the llama-server arguments.

  Secrets and the memory and idle settings are compared as placeholders.

The audit's other option was to generate the quadlet units from compose. That was not taken: the quadlet units carry Podman-specific wrappers, such as the Redis memory check and the systemd `$$` escapes, and keeping them hand-written with an agreement test keeps Podman users working.

## Impact

- **Behaviour:** a compose or quadlet deployment now runs Qdrant `v1.19.1` instead of `v1.18.0`, the version the native installer and the standalone file already used. Qdrant's storage format carries forward across this minor version.
- **Research:** none. No study is running. The study image and stack are built after this lands.
