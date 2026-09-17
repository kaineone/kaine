## Why

A read-only security and privacy review of the current `main` branch found that the Nexus operator dashboard mounts state-changing endpoints with no authentication, no CSRF protection, and no Origin check, while several evaluation and diagnostics paths persist or stream raw cognitive content by default. These gaps contradict the project's stated privacy defaults and create real operational risk: any process on the host (or a DNS-rebinding page reaching a loopback-bound instance) can fork/merge the entity, lift its welfare freeze, toggle perception, and read internal speech. This change hardens the operator surface and makes the privacy defaults match the documented promises.

## What Changes

- **Add operator authentication to Nexus.** Every state-changing POST endpoint (cycle freeze/unfreeze, rates, forks, merges, perception toggle, locus) SHALL require a per-request bearer token or signed operator session. The diagnostics SSE and conversation surfaces that carry privileged content SHALL also require the same token when `dev_content_override` or `conversation_enabled` is true.
- **Add Origin/CSRF protection to Nexus.** State-changing routes SHALL validate Origin/same-site or enforce a strict Host allowlist, fail-closed when the configuration is inconsistent, and refuse non-loopback binds unless a token is explicitly configured.
- **Route workspace trajectory through the privacy filter.** `TrajectoryRecorder` SHALL pass `selected` content through the shared `PrivacyFilter` (or an explicit field allowlist) before writing to disk, so internal speech, memory text, and affect reasons do not persist verbatim by default.
- **Default `workspace_trajectory` to false.** The shipped `config/kaine.toml` SHALL keep trajectory recording opt-in rather than opt-out, so operators must explicitly enable persistent cognitive logging.
- **Default state-at-rest encryption to true when a key is available.** `[security.state_encryption].enabled` SHALL default to true if `KAINE_STATE_KEY` or the kernel keyring provides a key, and the boot path SHALL surface a loud warning when state is persisted unencrypted. The existing fail-closed "no key → no boot" behavior is preserved.
- **Harden the remote bridge token posture.** The bridge SHALL require a non-empty token when bound to a non-loopback interface, and the token SHALL move out of the WebSocket query string and `Sec-WebSocket-Protocol` into the `Authorization: Bearer` header for non-browser clients.
- **Remove the plaintext `secrets/state_key` artifact.** The repository SHALL ship an example or placeholder instead of a live AES-256 key, with documentation pointing operators to the env/keyring path.

## Capabilities

### New Capabilities
- `nexus-auth`: Operator authentication and session management for the Nexus dashboard and control endpoints.
- `nexus-csrf-protection`: Origin, same-site, and Host-header validation for Nexus state-changing routes.

### Modified Capabilities
- `nexus-dashboard`: Add authentication and CSRF requirements to all operator controls; gate `dev_content_override` and `conversation_enabled` content behind the same operator token.
- `nexus-observability`: Require the operator token for diagnostics SSE and metrics endpoints that carry privileged content when privacy override is enabled.
- `evaluation-sidecar`: Require `TrajectoryRecorder` to filter or allowlist `selected` content before persistence; default `workspace_trajectory` to false.
- `state-encryption`: Change the shipped default so encryption is enabled when a key is available, with a boot-time warning when plaintext persistence is chosen.
- `remote-bridge`: Require a token for non-loopback binds and move token transmission out of query-string/subprotocol channels.

## Impact

- `kaine/nexus/app.py`, `kaine/nexus/cycle_control.py`, `kaine/nexus/diagnostics.py`, `kaine/nexus/perception.py`, `kaine/nexus/conversation.py`, `kaine/nexus/config.py`, `kaine/nexus/__main__.py`.
- `kaine/evaluation/trajectory.py`, `kaine/evaluation/config.py`, `kaine/privacy_filter.py`.
- `kaine/security/crypto.py`, `kaine/boot.py` (encryption install path).
- `kaine/remote/bridge.py`.
- `config/kaine.toml` defaults for `[evaluation] workspace_trajectory`, `[security.state_encryption] enabled`, and `[nexus]` auth fields.
- `secrets/state_key` replaced by `secrets/state_key.example` or removed.
- Operator-facing docs (`docs/operations.md`, `docs/security-and-privacy.md`, `docs/configuration.md`) updated to describe the new auth setup and key provisioning.
