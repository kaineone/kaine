## Why

The integration test boot of main 3ce0bbfa (2026-10-16/17) could not start the cycle container against the operator's real `config/secrets.toml`: it exited with `PermissionError: [Errno 13] Permission denied: '/app/config/secrets.toml'`. `scripts/redis-bootstrap.sh` and `scripts/qdrant-bootstrap.sh` write the file through `kaine.secrets_file._write_private`, mode 0600 and owned by the host user (uid 1000). `compose/kaine.yml` bind-mounts it read-only into `kaine-dashboard`, `kaine-cycle` and `kaine-study`, which run as the image user `kaine` (uid 10001), and the quadlet units mount it the same way under rootless Podman, where uid 10001 maps to a subordinate uid. So after any bootstrap or `--rotate`, no container can read it. The test boot ran only because it mounted an empty throwaway file and every Redis and Qdrant secret also came from the environment.

Every reader opens the file whenever it exists, even when the environment already holds the value: `kaine.bus.config.load_secrets_doc` (bus config and `resolve_redis_auth`), the cycle's `_merge_qdrant_secret`, `kaine.dashboard.health.config`, and the dashboard token loader when `KAINE_DASHBOARD_TOKEN` is empty. A file that exists but cannot be opened is fatal.

## Does the environment cover the secrets the containers need?

| Secret (`config/secrets.toml`) | Environment override | Passed by compose | Covered |
|---|---|---|---|
| `[redis].password`, `[redis].url` | `KAINE_REDIS_PASSWORD`, `KAINE_REDIS_URL` | yes (cycle, dashboard, study) | yes |
| `[redis].username` | `KAINE_REDIS_USERNAME` | no, and the compose Redis uses no ACL user | yes for compose |
| `[qdrant].api_key` | `KAINE_QDRANT_API_KEY` | yes | yes |
| `[dashboard].operator_token` | `KAINE_DASHBOARD_TOKEN` (or its deprecated name) | yes for compose, empty by default; not for quadlet | only if the operator puts it in `compose/.env`; `python -m kaine.setup` writes it only to `config/secrets.toml`, and `compose/.env.example` does not list it |
| `[caretaker.tokens].<name>` (not in the example file; documented in `docs/11-preservation.md`) | none | no | no |

The environment does not cover every secret, so dropping the mount or treating an unreadable file as absent would, on its own, leave the HTTP caretaker channel without its bearer token (gate condition 7 then fails for an unattended boot) and leave a default install's dashboard without its sign-in token. The change therefore closes both gaps through the environment before it drops the mounts. The lead approved this design on 2026-10-17.

## What Changes

- **One reader, unreadable means absent.** `kaine.secrets_file.load_secrets_doc` becomes the only reader of `config/secrets.toml`; `kaine.bus.config.load_secrets_doc` delegates to it and `read_toml_field` reads through it. A file that exists but cannot be opened is treated as absent, with one warning per process and path saying the values must come from the environment. A readable file behaves exactly as today (including the group/world-readable warning), so native runs do not change, and a malformed file is still an error. The bus config, the cycle's Qdrant merge, the dashboard config and health config, the caretaker token loader, setup's token helper and the decommission and recovery paths all read through it. Setup's own reads keep raising on an unreadable file, so it still reports the problem instead of generating a second token.
- **Close the two gaps through the environment.**
  - Caretaker: `load_token` reads `KAINE_CARETAKER_TOKEN_<NAME>` (the channel's `token_name`, upper-cased; names limited to letters, digits and underscores) before the file.
  - Dashboard: setup also writes the token it generates or keeps to `compose/.env` as `KAINE_DASHBOARD_TOKEN`, unless that file already sets `KAINE_DASHBOARD_TOKEN` or its deprecated name. The env file is found from the checkout layout (`config/secrets.toml` beside `compose/.env`). `compose/.env.example` lists the key, and the quadlet dashboard unit passes it.
  - Compose passes both to the services that need them. Because caretaker token names are operator-chosen, the cycle and study services gain an optional `env_file` entry, `compose/caretaker.env` (mode 0600, `required: false`, Docker Compose 2.24 or newer), and the quadlet cycle units gain the matching `EnvironmentFile=` under `[Container]`. `scripts/install-quadlet.sh` creates an empty `compose/caretaker.env` (mode 0600) when it is missing, because Podman refuses a missing env file, and no longer requires `config/secrets.toml`. `compose/caretaker.env.example` documents the format, and `.dockerignore`/`.containerignore` exclude `compose/*.env`.
- **Drop the mount.** Once every secret comes from the environment, compose and the quadlet units stop mounting `config/secrets.toml`. The file stays the native-run source.
- **The file mode is never loosened.** No `chmod`, group, ACL or ownership change on `config/secrets.toml`.

## Alternatives considered

- **Run the containers as the host user** (`user: "${KAINE_UID}:${KAINE_GID}"`, or `UserNS=keep-id` for quadlet). This keeps the mount but breaks the volumes that `compose-state-mount-ownership` gave to uid 10001, so every existing state volume would need a `chown`.
- **Compose `secrets:`.** Outside Swarm, file secrets are plain bind mounts with the host owner and mode, so they fail the same way.

## Capabilities

### Modified Capabilities

- `containerized-deployment`: containers no longer read `config/secrets.toml`; every secret reaches them through the environment.

## Impact

- **Code:** `kaine/bus/config.py`, `kaine/cycle/__main__.py`, `kaine/cycle/caretaker.py`, `kaine/dashboard/config.py`, `kaine/dashboard/health/config.py`, `kaine/setup/dashboard_token.py`, `kaine/secrets_file.py`, `compose/kaine.yml`, `compose/.env.example`, `compose/caretaker.env.example`, `quadlet/kaine-*.container`, `scripts/install-quadlet.sh`, `.dockerignore`, `.containerignore`. `kaine/cycle/__main__.py` needs no change: its Qdrant merge already calls the bus loader.
- **Docs:** `docs/04-getting-started/services.md`, `docs/07-deployment/containers.md`, `docs/07-deployment/headless-host.md`, `docs/11-preservation.md` (caretaker token), `docs/05-dashboard.md`, `docs/04-getting-started/README.md`, `docs/appendix-a-configuration/README.md`, `docs/appendix-a-configuration/security-and-dashboard.md`, `config/secrets.example.toml`.
- **Operators:** an existing install moves its caretaker token, if it has one, into `compose/caretaker.env`, and its dashboard token into `compose/.env`, before upgrading.
