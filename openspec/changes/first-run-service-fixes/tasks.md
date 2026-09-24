## 1. Secrets writer

- [x] 1.1 Add `kaine/secrets_file.py`, stdlib-only, with `upsert_env(path, key, value)` and `upsert_toml_field(path, table, field, value)`. Each preserves every other line unchanged, creates the file when absent, rejects values containing a quote, backslash or newline, and leaves the file mode 600.
- [x] 1.2 Add a `python -m kaine.secrets_file` command-line interface that takes `env PATH KEY VALUE` or `toml PATH TABLE FIELD VALUE`, reading VALUE from stdin when it is `-` so that secrets stay out of the process list.
- [x] 1.3 Tests:
  - A same-named field in another table is untouched.
  - An unrelated `.env` key survives.
  - Upserting twice leaves one line.
  - A value containing a quote is rejected.
  - A new file is created mode 600.

## 2. Bootstrap scripts

- [x] 2.1 `redis-bootstrap.sh`:
  - Reuse the existing usable password by default.
  - Rotate only with `--rotate`.
  - Accept `--keep-password` as a no-op.
  - Upsert through `kaine.secrets_file`.
  - Update the header comment and `--help` text.
- [x] 2.2 `qdrant-bootstrap.sh`:
  - Replace the inline Python and `sed` with `kaine.secrets_file`.
  - Keep the key by default, rotate only with `--rotate`, and accept `--keep-key` as a no-op.
- [x] 2.3 Script tests (Docker is stubbed on `PATH`):
  - Running Qdrant setup, then Redis setup, keeps `KAINE_QDRANT_API_KEY`.
  - A Qdrant re-run keeps the key, and `--rotate` changes it.
  - A Redis re-run keeps the password.
  - `--rotate` changes it.

## 3. Setup wizard

- [x] 3.1 Generate `[nexus].operator_token` when neither the secrets file nor `KAINE_NEXUS_TOKEN` provides one. Never overwrite an existing token, and never print it.
- [x] 3.2 Probe Qdrant on the configured port (mnemos, then empatheia, then 6533). Give Qdrant `binary=None`, like Redis.
- [x] 3.3 Tests:
  - The token is generated once and is at least 32 characters.
  - An existing token or environment token is kept.
  - A configured Qdrant port is probed.
  - The default port is 6533.

## 4. Nexus

- [x] 4.1 `main` catches `BusConfigError` and exits 1 with a message naming `bash scripts/redis-bootstrap.sh`.
- [x] 4.2 The login redirect goes to `/` when conversation is enabled, otherwise to `/diagnostics/`. The shared page rail links only mounted consoles. Nexus refuses to start when neither console is enabled.
- [x] 4.3 Tests:
  - Missing Redis password exits 1 without a traceback.
  - The login redirect for each console combination.
  - Refusal with both consoles disabled.

## 5. Docs

- [x] 5.1 `docs/getting-started.md`:
  - Nexus sign-in with the generated token.
  - Remove the nonexistent `systemctl --user` unit commands in favour of the real launch steps.
  - Describe the Redis bootstrap's keep-by-default behaviour and `--rotate`.
- [x] 5.2 `SECURITY.md` and `docs/operations.md`: rotation is explicit (`--rotate`); a re-run keeps credentials.
- [x] 5.3 `config/secrets.example.toml`: say that `python -m kaine.setup` generates the operator token.
- [x] 5.4 `openspec validate first-run-service-fixes --strict` passes.
