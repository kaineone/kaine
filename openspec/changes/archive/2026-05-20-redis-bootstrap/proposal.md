## Why

The Redis setup workflow in `SETUP.md` §1.2 trapped the operator on first
run: `compose/.env.example` carried an *active*
`KAINE_REDIS_PASSWORD=replace-me-...` line, the documented
`echo "...=$(openssl rand -hex 32)" >> compose/.env` appended a *second*
active line, and the documented sanity-check
`grep ... | cut -d= -f2` joined both values together. The container
started with the second password (compose takes the last assignment),
but `redis-cli` got both values concatenated and the auth check failed.

Two small files create the trap; one small script removes it. This
change adds `scripts/redis-bootstrap.sh` (the atomic version of the
SETUP.md steps), corrects `compose/.env.example` so the placeholder
is commented out, and shortens `SETUP.md` §1.2 to point at the new
script as the canonical path.

## What Changes

- Add `scripts/redis-bootstrap.sh` that: generates a random password,
  writes `compose/.env` from scratch (single key, mode 600), updates
  `config/secrets.toml` so `[redis].password` matches, recreates the
  container with `docker compose -f compose/redis.yml down && up -d`,
  and confirms the ping. Idempotent — re-running rotates the password.
- Add `--keep-password` flag for re-runs that should NOT rotate (e.g.
  if the operator is migrating between hosts and wants to preserve
  the existing password).
- Edit `compose/.env.example` so the password line is commented out
  (`# KAINE_REDIS_PASSWORD=...`), with a one-line note explaining the
  trap and pointing at the bootstrap script.
- Rewrite `SETUP.md` §1.2 to lead with the bootstrap script; keep the
  manual steps below it for operators who want to read what the
  script does.

## Capabilities

### New Capabilities

None — this is operator tooling and documentation correctness, not a
behavioral change to KAINE's modules.

### Modified Capabilities

None.

## Impact

- **Operator UX:** the canonical Redis setup is now one command,
  `bash scripts/redis-bootstrap.sh`. Manual steps remain in SETUP.md
  for the curious or for environments where the script can't run.
- **Repo:** adds `scripts/redis-bootstrap.sh`, edits
  `compose/.env.example`, edits `SETUP.md` §1.2.
- **No code, no test, no audit change.** The event-bus audit posture
  shipped in `redis-auth-mandatory` stands: password required on
  every host. This change is about the workflow that produces the
  password, not the policy that requires it.
