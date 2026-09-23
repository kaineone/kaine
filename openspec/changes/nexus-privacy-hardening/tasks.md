## 1. Nexus authentication layer

- [ ] 1.1 Add `operator_token` field to `NexusConfig` loaded from `KAINE_NEXUS_TOKEN` env or `config/secrets.toml`, and verify `kaine/nexus/config.py` parses it without logging the value.
- [x] 1.2 Create `kaine/nexus/auth.py` with a FastAPI `Depends` callable that validates `Authorization: Bearer <token>` and returns 401 when the token is missing or mismatched; verify with unit tests for missing, wrong, and valid tokens.
- [x] 1.3 Apply the auth dependency to all state-changing routers in `kaine/nexus/app.py` (`cycle_control`, `perception`, diagnostics forks/merges/rates endpoints) and verify unauthenticated POSTs return 401.
- [x] 1.4 Apply the auth dependency to privileged read surfaces when `conversation_enabled` or `dev_content_override` is true (conversation router, diagnostics SSE) and verify unauthenticated requests return 401.
- [x] 1.5 Update `kaine/nexus/__main__.py` to fail closed if a non-loopback bind is requested without a configured token, and verify the exit path with a unit test.

## 2. Nexus CSRF/Origin protection

- [x] 2.1 Create `kaine/nexus/csrf.py` middleware that validates Origin against a configured allowlist or strict Host header, returning 403 for cross-origin/rebinding requests; verify with unit tests for same-origin, cross-origin, and missing Origin cases.
- [x] 2.2 Add `allowed_origins` and `host_allowlist` to `NexusConfig` with sensible defaults (`127.0.0.1`, `localhost`) and verify config parsing.
- [x] 2.3 Mount the CSRF middleware in `create_app` after auth and verify state-changing endpoints reject cross-origin requests even with a valid token.
- [x] 2.4 Add a non-loopback bind opt-in flag to `NexusConfig` and enforce it in `kaine/nexus/__main__.py`; verify that `host=0.0.0.0` without opt-in exits and with opt-in starts.

## 3. Evaluation trajectory privacy

- [x] 3.1 Modify `kaine/evaluation/trajectory.py` to inject the shared `PrivacyFilter` and call `filter()` on each `selected` payload before writing; verify that internal speech and memory text are redacted while salience metadata remains.
- [x] 3.2 Set `[evaluation].workspace_trajectory = false` in `config/kaine.toml` and verify that running with the shipped config produces no trajectory output.
- [x] 3.3 Add a test that enables `workspace_trajectory = true` and confirms filtered records are written.

## 4. State encryption defaults

- [x] 4.1 Update `kaine/security/crypto.py` so that `CryptoConfig.from_section` treats a missing `enabled` as true when a key is resolvable, and false otherwise with a warning; verify with unit tests for key-present, key-absent, and explicit false cases.
- [ ] 4.2 Add a boot-time warning in `kaine/boot.py` when encryption is explicitly disabled, and verify the warning appears in logs.
- [x] 4.3 Update `config/kaine.toml` comments to reflect the new default behavior without changing the explicit shipped value.

## 5. Secrets and remote bridge hardening

- [ ] 5.1 Remove `secrets/state_key` from the repo, add `secrets/state_key.example` with a placeholder and instructions, and verify `git status` no longer shows a real key.
- [x] 5.2 Update `kaine/remote/bridge.py` to reject token-in-query and token-in-subprotocol connections, accept only `Authorization: Bearer <token>`, and verify with unit tests.
- [x] 5.3 Add a fail-closed check in the bridge startup that refuses non-loopback binds when the token is empty, and verify with a unit test.

## 6. Documentation and validation

- [x] 6.1 Update `docs/operations.md` with the new Nexus token setup, Origin allowlist, and non-loopback opt-in flag.
- [x] 6.2 Update `docs/security-and-privacy.md` to describe the new encryption default, trajectory opt-in, and remote-bridge token posture.
- [x] 6.3 Update `docs/configuration.md` with the new `[nexus]` auth fields and `[security.state_encryption]` default semantics.
- [x] 6.4 Run `openspec validate nexus-privacy-hardening --strict` and resolve all reported issues.
- [x] 6.5 Run the affected test suites (`tests/test_nexus_*.py`, `tests/test_state_encryptor.py`, `tests/test_evaluation_config.py`, `tests/test_remote_bridge.py`) and ensure they pass or are updated to match the new behavior.

## Review status (2026-09-22)

An adversarial review found these tasks only partly done, so they are unticked:
1.1 (the operator token is read from `KAINE_NEXUS_TOKEN` or `kaine.toml`, not from `config/secrets.toml`),
4.2 (the warning lives in `kaine/security/crypto.py`, not `kaine/boot.py`),
5.1 (the premise was wrong: `secrets/state_key` was gitignored and never in the repository; deleting it removed the only copy of the operator's state key. Key custody moves to a per-entity design).
The review also found that the dashboard JavaScript and the SSE stream cannot send the Bearer token, and that the containerised Nexus refuses its `0.0.0.0` bind. This change stays open until those are fixed.
