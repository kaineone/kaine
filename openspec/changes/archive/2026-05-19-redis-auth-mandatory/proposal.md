## Why

The `redis-loopback-no-password` change relaxed `requirepass` to optional
on loopback hosts on the rationale that Docker port mapping already
enforces network isolation. That argument is technically defensible for
a single-user single-machine deployment today, but it drifted from the
build prompt §1.1 ("Security audit Redis config (no external access,
auth enabled, persistence configured)") — and KAINE entities will
eventually be internet-exposed (the operator's words: "I do want kaine
entities to have full internet access eventually"). Defenses that don't
matter on a loopback-only box today are load-bearing the moment the
same code is shipped onto a network-attached host.

Walking the relaxation back to the strict build-prompt posture: auth
required everywhere. This change MODIFIES the event-bus audit spec
again, restores the compose `--requirepass`, and updates docs to a
single with-password path.

## What Changes

- **MODIFIED** `event-bus`'s "Startup audit of Redis configuration"
  requirement: `requirepass` is mandatory on **all** hosts. The
  loopback exception for the `bind` check stays (transport isolation is
  enforced by the port mapping, so the bind value inside the container
  doesn't matter), but the password check applies regardless of host.
- Restore `AsyncBus.audit` to raise `BusSecurityError` when
  `requirepass` is empty, on any host.
- Restore `load_bus_config` to raise `BusConfigError` when no password
  is found, on any host.
- Restore `compose/redis.yml` `--requirepass` as mandatory: the
  compose fails fast at parse time when `KAINE_REDIS_PASSWORD` is
  unset (the `${VAR:?msg}` form).
- Update `compose/.env.example` and `SETUP.md` §1.2: single
  with-password path, document it as the safe default that travels
  with the code to any future deployment.
- Update `kaine/bus/AUDIT.md` row 2 back to "required for all hosts"
  with the rationale paragraph explaining why we tightened rather than
  leaving the loopback exception.
- Update tests: the previous loopback-warns-only audit case becomes a
  loopback-raises case (mirroring non-loopback). Two corresponding
  config-loader tests flip back.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `event-bus`: re-tightens the password portion of the "Startup audit
  of Redis configuration" requirement. The loopback exception for the
  bind check is preserved.

## Impact

- **Operator UX:** running `docker compose -f compose/redis.yml up -d`
  now requires `KAINE_REDIS_PASSWORD` to be set, the same way the
  `redis-containerization` change shipped originally. One generated
  password used by both compose and `config/secrets.toml`.
- **Repo:** `kaine/bus/client.py` (audit), `kaine/bus/config.py`
  (loader), `compose/redis.yml`, `compose/.env.example`, `SETUP.md`,
  `kaine/bus/AUDIT.md`, `tests/test_bus_client.py`,
  `tests/test_bus_config.py`.
- **No runtime impact** on the cognitive cycle. Phase 2 modules and
  capabilities are untouched.
- **Future deployment safety:** the same KAINE checkout deployed onto
  a non-loopback host (a fork of the codebase shipped to a remote
  machine, a future network bridge for inter-instance mesh per paper
  §5.2) starts with the audit enforced.
