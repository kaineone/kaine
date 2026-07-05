## 1. Bootstrap script

- [ ] 1.1 Write `scripts/redis-bootstrap.sh` — Bash, idempotent, generates a password (or reuses existing with `--keep-password`), writes `compose/.env` from scratch, updates `config/secrets.toml`, restarts the container, pings to confirm.
- [ ] 1.2 Make the script executable.

## 2. Example file fix

- [ ] 2.1 Edit `compose/.env.example`: comment out the placeholder line so a `cp` followed by `echo >>` no longer produces a duplicate key.

## 3. Documentation

- [ ] 3.1 Rewrite `SETUP.md` §1.2 to lead with `bash scripts/redis-bootstrap.sh`. Keep the manual steps below it as a "what the script does" reference.

## 4. Verification

- [ ] 4.1 Run the script on this host; confirm `redis-cli -h 127.0.0.1 -p 6479 -a "$KAINE_REDIS_PASSWORD" ping` returns `PONG`.
- [ ] 4.2 Confirm `config/secrets.toml`'s `[redis].password` matches `compose/.env`.
- [ ] 4.3 Run full test suite; all pass.
- [ ] 4.4 `openspec validate redis-bootstrap --strict` clean — no spec deltas, validation should still pass because this change introduces no capability work.
- [ ] 4.5 Commit, merge, archive.
