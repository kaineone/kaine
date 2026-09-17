## Context

See `proposal.md` for the motivation. The current Nexus app is assembled in `kaine/nexus/app.py` with no authentication middleware and no Origin validation. The `PrivacyFilter` already exists in `kaine/nexus/privacy.py` and is applied at the bus-bridge boundary, but `TrajectoryRecorder` in `kaine/evaluation/trajectory.py` writes directly to its JSONL sink without passing through it. State encryption is implemented and fail-closed, but defaults to disabled. The remote bridge already supports a token, but accepts it in URL/query and subprotocol channels.

## Goals / Non-Goals

**Goals:**
- Add a single, consistent operator authentication layer to Nexus that covers state-changing POSTs and privileged read surfaces.
- Add CSRF/Origin protection that fails closed and refuses unsafe binds without explicit opt-in.
- Make persistent cognitive logging opt-in and privacy-filtered.
- Make encryption-at-rest the default when a key is available.
- Remove the plaintext `secrets/state_key` artifact from the repo tree.
- Harden remote-bridge token transmission.

**Non-Goals:**
- Replacing the tailnet ACL as the primary network boundary for the remote bridge.
- Adding a full user-management system; this remains a single-operator token.
- Encrypting data in motion over the tailnet; TLS is the tailnet's responsibility.
- Changing the privacy-filter denylist taxonomy beyond reusing the existing filter.

## Decisions

**Decision 1: Bearer-token middleware at the FastAPI app level.**
A single `Depends` auth dependency is added in `create_app` and applied to all routers. This avoids per-router drift and makes it easy to require auth on new endpoints by default. The token is read from `NexusConfig.operator_token`, which is populated from `KAINE_NEXUS_TOKEN` or `config/secrets.toml`.
- *Alternative:* Per-router auth. Rejected because it is error-prone and the existing routers already mix read and write endpoints.

**Decision 2: Origin/Host validation as a second middleware, not a single check.**
Auth and CSRF are separate concerns. The Origin middleware runs after auth and rejects cross-origin or rebinding requests with 403. It uses a strict Host allowlist derived from `config.nexus.host` plus any explicitly allowed operator origins.
- *Alternative:* SameSite cookies only. Rejected because the dashboard is primarily API-driven and cookie-based CSRF tokens add client complexity without covering the SSE path.

**Decision 3: Reuse `PrivacyFilter` for trajectory records.**
`TrajectoryRecorder.handle` will call `PrivacyFilter.filter` on each `selected` payload before writing. This keeps the privacy taxonomy in one place. The record will retain salience scores, tick metadata, and Thymos state, but drop or redact message text, memory bodies, beliefs, and affect reasons.
- *Alternative:* Maintain a separate allowlist in `TrajectoryRecorder`. Rejected because it duplicates the taxonomy and risks drift.

**Decision 4: Encryption default flips to auto-enabled when a key is present.**
`CryptoConfig.from_section` will treat a missing `enabled` key as "true if a key is resolvable, else false with a warning." Explicit `enabled = false` still works and logs a warning. This preserves backward compatibility for operators who genuinely want plaintext while making the safe posture the default.
- *Alternative:* Always default to true and fail-closed without a key. Rejected because it would break first-boot on research installs that have not yet provisioned a key.

**Decision 5: Replace `secrets/state_key` with `secrets/state_key.example`.**
The example file contains a placeholder string and a comment telling the operator to generate a 32-byte key and set it via env or keyring. The real key is removed from the repo.

**Decision 6: Remote bridge token moves to `Authorization: Bearer` header.**
Browser clients that cannot set arbitrary headers must use a small local proxy or the existing tailnet HTTPS path. Query-string and subprotocol token acceptance are removed.
- *Alternative:* Keep query-string support for convenience. Rejected because it leaks the token into logs, history, and referrers.

## Risks / Trade-offs

- **[Risk]** Adding auth breaks existing operator scripts that hit Nexus endpoints without a token.
  → **Mitigation:** Document the token setup in `docs/operations.md` and provide a one-time migration note in the changelog. The default empty token keeps existing installs in a safe-but-locked state until configured.
- **[Risk]** Origin validation can lock out legitimate reverse-proxy or tailnet-serve setups.
  → **Mitigation:** The Host allowlist is configurable; the default allows `127.0.0.1` and `localhost`, and operators can add their tailnet MagicDNS name.
- **[Risk]** Filtering trajectory records changes the research data format.
  → **Mitigation:** This is an intentional behavior change; operators who need full records can explicitly enable `workspace_trajectory` and use the raw bus archive (which remains gated by its own attestation).
- **[Risk]** Auto-enabling encryption without a key on some hosts could surprise operators.
  → **Mitigation:** The behavior is "auto-enable only if key present"; if no key is present, encryption stays off with a warning, not an error.

## Migration Plan

1. Generate a new operator token and add it to `config/secrets.toml` or the environment.
2. Add any non-loopback origins to the Nexus Host allowlist if using tailnet-serve or a reverse proxy.
3. If full workspace trajectory was relied upon, explicitly set `[evaluation].workspace_trajectory = true` after reviewing the privacy implications.
4. If plaintext state persistence was intentional, explicitly set `[security.state_encryption].enabled = false` and acknowledge the boot warning.
5. Replace `secrets/state_key` with a key generated out-of-band and stored in env/keyring.
