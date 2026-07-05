## Context

The bus already merges secrets correctly: `load_bus_config()`
(`kaine/bus/config.py:56-117`) reads both `kaine.toml` and `secrets.toml`,
resolves the Redis password with precedence
`KAINE_REDIS_PASSWORD` env → `secrets[redis]` → `kaine[redis]`, and refuses to
run unauthenticated. The cycle's separate config path,
`_load_kaine_config()` (`kaine/cycle/__main__.py:95-99`), does `tomllib.loads`
on `kaine.toml` alone. The dict it returns is handed to `build_registry`,
where `make_mnemos` (`kaine/boot.py:157-170`) forwards
`section["qdrant"]["api_key"]` only if present. Because secrets are never
merged in, the key is never present, and `Mnemos.__init__`
(`kaine/modules/mnemos/module.py:79-84`) raises.

The `mnemos` capability already requires the operator to hold the Qdrant key in
`secrets.toml [qdrant]` (mirrored from `KAINE_QDRANT_API_KEY` by the bootstrap),
and the live Qdrant enforces it (401 without a key). So the secret is in the
right place; only the cycle-side merge is missing.

## Goals / Non-Goals

**Goals:**
- The cycle's boot-time config includes the Qdrant API key sourced from the
  environment or `secrets.toml`, never from the git-tracked `kaine.toml`.
- Resolution precedence matches the established Redis convention
  (`KAINE_QDRANT_API_KEY` env → `secrets.toml [qdrant].api_key`).
- The existing clear error survives when no key exists anywhere.

**Non-Goals:**
- No change to Mnemos, `make_mnemos`, or the Qdrant client.
- No new config schema, no new secret keys (reuse existing `[qdrant].api_key`).
- Not building a general-purpose deep secrets-merge framework; scope is the
  Qdrant key the first boot needs. The helper may be written to extend later,
  but only the Qdrant key is wired now.
- Nexus config loading is out of scope (it has its own loader; this change is
  the cycle path that the entity boots through).

## Decisions

- **Merge in `_load_kaine_config`, not in `make_mnemos`.** Keeping the merge at
  config-assembly time mirrors `load_bus_config` and keeps module factories
  pure (they read an already-complete config). Alternative — having Mnemos read
  `os.environ`/`secrets.toml` itself — was rejected: it scatters secret-loading
  across modules and breaks the "config dict is the single source of truth for
  the registry" pattern.
- **Reuse `secrets.toml` reading, don't duplicate the parser.** Read the
  secrets doc the same way `load_bus_config` does (tolerant of a missing file)
  and emit the same world/group-readable mode warning if the file exists, so
  behavior is consistent across both loaders. Factor a tiny shared reader if it
  avoids copy-paste; otherwise inline the few lines.
- **Inject into `config["mnemos"]["qdrant"]["api_key"]`, creating nested dicts
  if absent.** This is exactly the shape `make_mnemos` reads. Only inject when a
  key is actually resolved, so the absent-everywhere case still falls through to
  Mnemos's existing, clearer error rather than a silent empty string.
- **Env var name `KAINE_QDRANT_API_KEY`.** Already the documented convention in
  the `mnemos`/`redis-bootstrap` specs and `compose/.env`; no new name invented.

## Risks / Trade-offs

- [A merged key could leak into logs or runtime.json] → Inject only into the
  in-memory dict consumed by the registry; `_write_runtime_state` already
  serializes only pid/ticks/rates/module-names, never config. Add no logging of
  the key value.
- [Two divergent config loaders (bus vs cycle) drift over time] → This change
  narrows the gap by giving the cycle loader the same secrets-awareness; a
  future change could unify them, tracked as an open question, not done here.
- [Operator has key only in `kaine.toml` from a prior workaround] → Still works:
  an explicit `[mnemos.qdrant].api_key` already present in `kaine.toml` is left
  intact; the merge only fills it in when absent. (We do not encourage this —
  `kaine.toml` is tracked — but we don't break it.)

## Migration Plan

No data migration. The fix is backward compatible: existing deployments that
somehow already had the key in `kaine.toml` keep working; deployments relying on
`secrets.toml`/env (the documented path) start working. Rollback is reverting
the single-file change; the entity simply returns to being unbootable with
qdrant-backed Mnemos, the pre-change state.

## Open Questions

- Should the bus and cycle eventually share one `load_full_config()` that
  returns both `BusConfig` and the module config dict with all secrets merged?
  Out of scope here; worth a follow-up to prevent future drift.
