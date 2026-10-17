## Why

The integration test boot of main 3ce0bbfa (2026-10-16/17) could not start the cycle container against the operator's real `config/secrets.toml`: it exited with `PermissionError: [Errno 13] Permission denied: '/app/config/secrets.toml'`. `scripts/redis-bootstrap.sh` and `scripts/qdrant-bootstrap.sh` write the file through `kaine.secrets_file._write_private`, mode 0600 and owned by the host user (uid 1000). `compose/kaine.yml` bind-mounts it read-only into `kaine-dashboard`, `kaine-cycle` and `kaine-study`, which run as the image user `kaine` (uid 10001), and the quadlet units mount it the same way under rootless Podman, where uid 10001 maps to a subordinate uid. So after any bootstrap or `--rotate`, no container can read it. The test boot ran only because it mounted an empty throwaway file and every Redis and Qdrant secret also came from the environment.

Every reader opens the file whenever it exists, even when the environment already holds the value: `kaine.bus.config.load_secrets_doc` (bus config and `resolve_redis_auth`), the cycle's `_merge_qdrant_secret`, `kaine.dashboard.health.config`, and the dashboard token loader when `KAINE_DASHBOARD_TOKEN` is empty. A file that exists but cannot be opened is fatal.

## Does the environment cover the secrets the containers need?

| Secret (`config/secrets.toml`) | Environment override | Passed by compose | Covered |
|---|---|---|---|
| `[redis].password`, `[redis].url` | `KAINE_REDIS_PASSWORD`, `KAINE_REDIS_URL` | yes (cycle, dashboard, study) | yes |
| `[redis].username` | `KAINE_REDIS_USERNAME` | no, and the compose Redis uses no ACL user | yes for compose |
| `[qdrant].api_key` | `KAINE_QDRANT_API_KEY` | yes | yes |
| `[dashboard].operator_token` | `KAINE_DASHBOARD_TOKEN` (legacy `KAINE_NEXUS_TOKEN`) | yes for compose, empty by default; not for quadlet | only if the operator puts it in `compose/.env`; `python -m kaine.setup` writes it only to `config/secrets.toml`, and `compose/.env.example` does not list it |
| `[caretaker.tokens].<name>` (not in the example file; documented in `docs/11-preservation.md`) | none | no | no |

The environment does not cover every secret, so dropping the mount or treating an unreadable file as absent would, on its own, leave the HTTP caretaker channel without its bearer token (gate condition 7 then fails for an unattended boot) and leave a default install's dashboard without its sign-in token. This change is therefore a design for review; nothing is implemented.

## What Changes (proposed)

- **One reader, unreadable means absent.** `load_secrets_doc` becomes the only reader of `config/secrets.toml`. A file that exists but cannot be opened is treated as absent, with one warning per process that names the file by role and says the values must come from the environment. A readable file behaves exactly as today, so native runs do not change. The dashboard config and health config, `kaine.cycle.caretaker.load_token` and the decommission and recovery paths read through it.
- **Close the two gaps through the environment.**
  - Caretaker: `load_token` reads `KAINE_CARETAKER_TOKEN_<NAME>` (the channel's `token_name`, upper-cased; names limited to letters, digits and underscores) before the file.
  - Dashboard: the setup wizard also writes the token it generates to `compose/.env` as `KAINE_DASHBOARD_TOKEN`, and `compose/.env.example` lists it.
  - Compose passes both to the services that need them. Because caretaker token names are operator-chosen, the cycle and study services gain an optional `env_file` entry, `compose/caretaker.env` (mode 0600, `required: false`), and the quadlet cycle units gain the matching `EnvironmentFile=` under `[Container]`.
- **Drop the mount.** Once every secret comes from the environment, compose and the quadlet units stop mounting `config/secrets.toml`. The file stays the native-run source.
- **The file mode is never loosened.** No `chmod`, group, ACL or ownership change on `config/secrets.toml`.

## Alternatives considered

- **Run the containers as the host user** (`user: "${KAINE_UID}:${KAINE_GID}"`, or `UserNS=keep-id` for quadlet). This keeps the mount but breaks the volumes that `compose-state-mount-ownership` gave to uid 10001, so every existing state volume would need a `chown`.
- **Compose `secrets:`.** Outside Swarm, file secrets are plain bind mounts with the host owner and mode, so they fail the same way.

## Capabilities

### Modified Capabilities

- `containerized-deployment`: containers no longer read `config/secrets.toml`; every secret reaches them through the environment.

## Impact

- **Code (proposed):** `kaine/bus/config.py`, `kaine/cycle/__main__.py`, `kaine/cycle/caretaker.py`, `kaine/dashboard/config.py`, `kaine/dashboard/health/config.py`, `kaine/setup/dashboard_token.py`, `compose/kaine.yml`, `compose/.env.example`, `quadlet/kaine-*.container`.
- **Docs (proposed):** `docs/04-getting-started/services.md`, `docs/07-deployment/containers.md`, `docs/07-deployment/headless-host.md`, `docs/11-preservation.md` (caretaker token), `config/secrets.example.toml`.
- **Operators:** an existing install moves its caretaker token, if it has one, into `compose/caretaker.env`, and its dashboard token into `compose/.env`, before upgrading.
