# Security and Nexus

Use the `[nexus]` and `[security.state_encryption]` sections to secure the operator console and encrypt persisted cognitive state. Operators who run Nexus or keep entity state on disk need these keys.

## Nexus

The Nexus web console is described in [Nexus, the dashboard](../05-nexus.md). The tables below list the configuration keys.

### Surfaces and privacy boundary

| Key | Type | Default | Description |
|---|---|---|---|
| `host` | string | `"127.0.0.1"` | Bind address. Loopback-only by default. |
| `port` | integer | `8088` | HTTP port. |
| `conversation_enabled` | boolean | `false` | Enable the conversation surface at `/`. The shipped config disables it; leave it disabled for base-thesis runs so no external input reaches the language organ, and enable it only for interactive configurations. |
| `diagnostics_enabled` | boolean | `true` | Enable the diagnostics surface. |
| `conversation_history_lookback` | integer | `50` | Maximum number of older conversation entries returned on initial conversation load. Older entries are reachable with `?since=<id>`. |
| `dev_content_override` | boolean | `false` | When `true`, the diagnostics surface shows raw cognitive content (message text, beliefs, memory bodies, internal speech, affect reasons) and displays a "dev mode" banner. **Keep this `false` in production.** |

### Operator authentication

`[nexus].access` chooses whether a token is required:

- `"open"` (shipped default): no sign-in. Anyone who can reach the address can view and control the entity. Nexus only listens on loopback by default, so "anyone" means programs and people on this computer — plus the operator's tailnet if they choose to serve it there. The Host allowlist and Origin checks still apply.
- `"token"`: an operator token is required. Use it whenever Nexus is reachable by anyone you do not fully trust. Override per launch with `KAINE_NEXUS_ACCESS=token`.

In token mode, the operator token must be at least 32 characters and must live only in `KAINE_NEXUS_TOKEN` or in `config/secrets.toml` under `[nexus] operator_token`. Nexus refuses to start if a non-empty token appears in `config/kaine.toml` or `config/kaine.operator.toml` ([`kaine/nexus/config.py`](../../kaine/nexus/config.py)). If no token is configured in token mode, privileged endpoints return 401.

A browser signs in once at `/login`. The session cookie authorizes page loads and reads, and every state-changing request also carries the per-session `X-Nexus-Session-Key` header that the login page stores. Scripts can send `Authorization: Bearer <token>` instead.

| Key | Type | Default | Description |
|---|---|---|---|
| `operator_token` | string | `""` | Token for token mode. Read only from `KAINE_NEXUS_TOKEN` or `config/secrets.toml` `[nexus] operator_token`. Must be at least 32 characters. |
| `access` | string | `"open"` | `"open"` or `"token"`. |
| `session_idle_minutes` | integer | `720` | Minutes a session can be idle before expiry. |
| `session_max_hours` | integer | `24` | Maximum session lifetime, regardless of activity. |
| `login_max_failures` | integer | `5` | Failed login attempts allowed within `login_failure_window_s`. |
| `login_failure_window_s` | integer | `300` | Window for counting failed login attempts. |
| `login_block_delay_s` | float | `2.0` | Delay applied to login attempts from a client that has already exceeded the failure limit. |

See [the configuration overview](./README.md) for how `config/secrets.toml` is loaded.

### Read-only view

`[nexus].read_only = true` (or `KAINE_NEXUS_READ_ONLY=1`) makes Nexus a viewer only: every control request is refused with 403, and a banner says so. Use it whenever Nexus watches a research run, because some controls act on the running entity through its event bus, and any change to a running study makes it inadmissible. The study-view overlay sets it.

| Key | Type | Default | Description |
|---|---|---|---|
| `read_only` | boolean | `false` | When `true`, refuse every request except `GET`/`HEAD`/`OPTIONS` with 403. |

### Host and origin protection

| Key | Type | Default | Description |
|---|---|---|---|
| `host_allowlist` | list or comma-separated string | `["127.0.0.1", "localhost", "::1"]` | Allowed `Host` header values. The check runs on every request ([`kaine/nexus/csrf.py`](../../kaine/nexus/csrf.py)). Setting this key replaces the default, so keep the loopback names when adding a reverse-proxy hostname or tailnet host. |
| `allowed_origins` | list or comma-separated string | Derived from the final port after environment and overlay overrides; includes `http://127.0.0.1:<port>`, `http://localhost:<port>` and `http://[::1]:<port>` | Allowed `Origin` values for state-changing requests ([`kaine/nexus/config.py`](../../kaine/nexus/config.py)). Setting this key replaces the default. |
| `non_loopback_allowed` | boolean | `false` | Explicit opt-in required to bind a non-loopback interface. When `false`, `python -m kaine.nexus` exits if `host` is not loopback. |

To add a tailnet host or reverse-proxy hostname, include it in both `host_allowlist` and `allowed_origins`, or set `KAINE_NEXUS_EXTRA_HOSTS` to a comma-separated list; the loader appends those hosts to `host_allowlist` and derives matching origins from the final port.

### Environment overrides

These environment variables override the matching TOML keys. Boolean overrides accept `1`, `true`, `yes` or `on` (case-insensitive); everything else is `false`.

| Variable | Key / effect |
|---|---|
| `KAINE_NEXUS_HOST` | `host` |
| `KAINE_NEXUS_PORT` | `port` (also rebuilds the default `allowed_origins`) |
| `KAINE_NEXUS_CONVERSATION_ENABLED` | `conversation_enabled` |
| `KAINE_NEXUS_NON_LOOPBACK_ALLOWED` | `non_loopback_allowed` |
| `KAINE_NEXUS_READ_ONLY` | `read_only` |
| `KAINE_NEXUS_ACCESS` | `access` (`open` or `token`) |
| `KAINE_NEXUS_ALLOWED_ORIGINS` | `allowed_origins`; comma-separated, replaces the list |
| `KAINE_NEXUS_EXTRA_HOSTS` | Comma-separated list of extra hosts added to `host_allowlist` and used to derive origins |
| `KAINE_NEXUS_TOKEN` | `operator_token`; takes priority over `config/secrets.toml` |

### Loading scope

Nexus loads only `config/kaine.toml`, `config/kaine.operator.toml` and `config/secrets.toml`. The profile, tier and `KAINE_DATA_ROOT` path normalisation used by the rest of KAINE do not apply to Nexus configuration.

### Related security settings

Nexus also reads these sections, so their keys affect what the dashboard can do:

- `[perception_preview].port` — requires `KAINE_PERCEPTION_PREVIEW=1` in both processes.
- `[lifecycle]` — `adapter_merger`, `adapter_merge`; a legacy `max_snapshots_retained` value logs a warning.
- `[remote_bridge].token`
- `[caretaker.tokens]`

## State encryption at rest

The `[security.state_encryption]` section applies AES-256-GCM encryption to persisted cognitive state: the Eidolon self-model, fork/merge snapshot bundles, the sidecar observer JSONL, and Phantasia world-model checkpoints when the real backend writes them. The full at-rest inventory is in [Security and privacy](../13-security-and-privacy.md).

The shipped file sets `enabled = true`. If the key is omitted entirely, encryption is on when a key is resolvable and off with a warning when no key is present. With `enabled = true` and no resolvable key, the entity refuses to boot (fail-closed). With `enabled = false`, the entity logs a warning that state will be plaintext. A non-boolean value for `enabled` is rejected at boot.

The key is read in this order:

1. The environment variable named by `key_env_var` (default `KAINE_STATE_KEY`).
2. The Linux kernel user keyring, description `kaine:state_key`.

Supply 32 raw bytes, or base64/hex encoding of 32 bytes. Never commit the key. The repository ships `secrets/state_key.example` as a placeholder; generate a real key out of band.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `true` | Encryption master gate. Omitting the key produces the dynamic default described above. |
| `key_env_var` | string | `"KAINE_STATE_KEY"` | Environment variable that holds the key. |
| `algorithm` | string | `"aes-256-gcm"` | Encryption algorithm. Only `"aes-256-gcm"` is supported; any other value raises `CryptoConfigError` at boot ([`kaine/security/crypto.py`](../../kaine/security/crypto.py)). |

On-disk framing is `KAINE_MAGIC || nonce(12 bytes) || ciphertext+tag`, base64-encoded. The magic prefix lets the reader distinguish encrypted blobs from legacy plaintext, so a disabled reader transparently passes plaintext through.
