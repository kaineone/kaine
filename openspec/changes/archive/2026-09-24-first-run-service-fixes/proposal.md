## Why

A fresh install today cannot reach a working Nexus sign-in without hand-editing secrets, and several setup steps undo each other when re-run. Each defect below is verified against main:

- **No way to sign in.** Nexus refuses every login with `503 operator token not configured` until `[nexus].operator_token` exists, and nothing generates one. `config/secrets.example.toml` tells the operator to run a Python one-liner.
- **Nexus crashes on a fresh clone.** Before `scripts/redis-bootstrap.sh` has run, building the bus raises `BusConfigError`, which `kaine.nexus.__main__.main` does not catch, so the operator sees a traceback instead of the next step.
- **Login lands on a missing page.** A successful login redirects to `/`, which exists only when `[nexus].conversation_enabled` is on. It is off by default, so the default install lands on a 404.
- **Re-running Redis setup breaks Qdrant.** `redis-bootstrap.sh` writes `compose/.env` from scratch, erasing the `KAINE_QDRANT_API_KEY` that `qdrant-bootstrap.sh` put there and that `compose/kaine.yml` requires.
- **Re-running Redis setup rotates the password by default.** Every run disconnects anything holding the old password: a running Nexus, a running cycle, or a second host. Re-running setup to repair something should not change working credentials.
- **The Redis secret mirror ignores sections.** It rewrites every `password = "…"` line in `config/secrets.toml`, whichever table it is in. Today only `[redis]` has one, so this is latent.
- **The setup wizard checks the wrong Qdrant port.** `kaine/setup/dependencies.py` probes 6333, but KAINE's Qdrant listens on 6533 (`compose/qdrant.yml`, `[mnemos.qdrant].port`). A running Qdrant is reported as stopped, and one on the operator's own 6333 is reported as KAINE's. It also looks for a `qdrant` binary on `PATH`, although Qdrant runs in a container.
- **Stale guide.** `docs/getting-started.md` says Nexus has no auth, and gives `systemctl --user` commands for `speaches-stt.service` and `chatterbox-tts.service`, units the repository does not ship.

These are prerequisites for making first run approachable for non-programmers. The browser-based first run proposed separately builds on a setup that works when re-run.

## What Changes

- **One section-aware secrets writer.** A new stdlib-only module `kaine/secrets_file.py` upserts a single `KEY=value` line in `compose/.env` and a single `field = "value"` inside a named TOML table of `config/secrets.toml`. It preserves every other line, byte for byte, and writes files mode 600. The Redis and Qdrant bootstrap scripts call it with `python3 -m kaine.secrets_file`, replacing their `cat >`, `sed` and inline-Python edits.
- **Redis bootstrap keeps the password by default.** Re-running reuses the existing usable password. `--rotate` generates a new one. `--keep-password` stays accepted and changes nothing, so existing docs and scripts keep working.
- **Qdrant bootstrap keeps its API key by default, for the same reason.** Today every run rotates the key (`--keep-key` avoids it), which disconnects Mnemos and Empatheia. A no-flag run now reuses the key, `--rotate` replaces it, and `--keep-key` stays accepted. `SECURITY.md` describes rotation as explicit.
- **Setup generates the Nexus operator token.** When no token is configured, `python -m kaine.setup` writes a fresh `secrets.token_urlsafe(32)` token into `config/secrets.toml` `[nexus].operator_token` (it is at least 32 characters). An existing token, whether in the file or in `KAINE_NEXUS_TOKEN`, is never replaced. The token is not printed; setup states where it is stored.
- **Nexus explains missing setup instead of crashing.** `main` catches the bus configuration error and exits 1 with a single log line naming the setup command that fixes it.
- **Login lands on a console that exists.** Nexus redirects to `/` when the conversation console is mounted, otherwise to `/diagnostics/`. The page rail on diagnostics and evaluation stops linking the unmounted console, whose brand and "Console" links 404 today. With neither console enabled, Nexus has nothing to serve after login, so it refuses to start with a plain message.
- **Dependency probes use the configured ports.** The Qdrant probe reads `[mnemos.qdrant].port`, falling back to `[empatheia.qdrant].port`, then to 6533. The Redis probe keeps reading `[redis].port`. Container services no longer look for a host binary.
- **Guide corrected.** `docs/getting-started.md` describes Nexus sign-in with the generated token, and replaces the nonexistent unit names with the Speaches and Chatterbox launch steps that exist.

## Impact

- Modified capability `redis-bootstrap` (password kept by default, section-aware mirror, `.env` upsert).
- New capability `qdrant-bootstrap` (key kept by default, `--rotate`).
- Added requirements in `first-run-wizard` (operator token generation, configured-port probes) and `nexus-dashboard` (setup-error exit, login landing).
- Code:
  - `kaine/secrets_file.py` (new)
  - `scripts/redis-bootstrap.sh`, `scripts/qdrant-bootstrap.sh`
  - `kaine/setup/__main__.py`, `kaine/setup/dependencies.py`
  - `kaine/nexus/__main__.py`, `kaine/nexus/auth.py`, `kaine/nexus/templates/_base.html`
  - `docs/getting-started.md`, `docs/operations.md`, `SECURITY.md`, `config/secrets.example.toml`
- Out of scope:
  - The state-encryption key, which belongs to per-entity key custody (`entity-key-custody`).
  - Merging wizard answers into an existing operator override, persisting the welfare acknowledgement and wiring the accelerator-mismatch step, which are a separate change.
  - Quadlet unit paths.
- No new dependencies. Entity spawn is untouched.
