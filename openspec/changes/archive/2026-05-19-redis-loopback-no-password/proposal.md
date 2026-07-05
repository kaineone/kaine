## Why

The Phase 0 / `redis-containerization` decision put KAINE's Redis in a
container with `127.0.0.1:6479:6379` port mapping. The mapping itself is
what enforces network isolation — nothing outside the host can reach the
bus. The previously-required `requirepass` was defense-in-depth against
other local processes on the host and a literal reading of build-prompt
§1.1's "auth enabled" line. On a single-user single-machine deployment
that defense buys little, and forces the operator to manage a password
they have no realistic threat against. The operator's note:

> "I thought redis didn't need a password anymore if we went with option b
> of a standalone redis container, which we agreed on."

They are right that on a loopback-bound containerized Redis, network
isolation is already done by the port mapping. The audit should reflect
that.

## What Changes

- **MODIFIED** the `event-bus`'s "Startup audit of Redis configuration"
  requirement: for loopback hosts the audit treats `requirepass` as
  *recommended* rather than *required*. When absent, the audit logs a
  one-line warning and proceeds. For non-loopback hosts the password
  remains required (network isolation is no longer guaranteed by
  transport, so auth is the only defense).
- Update `kaine.bus.config.load_bus_config` so missing-password no longer
  fails fast when the host is loopback. It still fails fast on
  non-loopback hosts.
- Update `compose/redis.yml` so `--requirepass` is appended only when
  `KAINE_REDIS_PASSWORD` is set in the env. When unset, the container
  starts without auth and the operator's `compose/.env` is optional.
- Update `kaine/bus/AUDIT.md` table: row 2 now reads "required for
  non-loopback hosts; recommended for loopback hosts" with a paragraph
  on the threat model exclusion.
- Update `SETUP.md` §1.2: split the loopback-host quick start into two
  paths — "no password" (default, the new shortest path) and "with
  password" (operator opt-in for defense-in-depth or multi-user hosts).
- Update tests: the audit test that previously asserted
  "BusSecurityError when requirepass empty on loopback host" is split
  into two cases — loopback host without password warns and proceeds;
  non-loopback host without password still raises.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `event-bus`: the "Startup audit of Redis configuration" requirement
  relaxes its password requirement for loopback hosts.

## Impact

- **Operator UX:** `docker compose -f compose/redis.yml up -d` now works
  with no env var set. `config/secrets.toml` is no longer required for
  a default single-user deployment.
- **Threat-model note documented** in AUDIT.md so an operator deploying
  in a multi-user environment knows when to opt back into the password.
- **Repo:** `kaine/bus/client.py` (audit logic), `kaine/bus/config.py`
  (password-required logic), `kaine/bus/AUDIT.md`, `compose/redis.yml`,
  `compose/.env.example`, `SETUP.md`, `tests/test_bus_client.py`,
  `tests/test_bus_config.py`.
- **No runtime impact** on the cognitive cycle.
