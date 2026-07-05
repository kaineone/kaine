## Why

The cognitive cycle cannot complete a first boot with the guide's recommended
module set. `kaine/cycle/__main__.py` `_load_kaine_config()` loads only
`config/kaine.toml` and never merges `config/secrets.toml`, so the Qdrant API
key the `mnemos` capability already mandates living in `secrets.toml [qdrant]`
never reaches Mnemos. Mnemos correctly refuses to connect without a key, and
the live Qdrant genuinely enforces auth (`GET /collections` → 401), so **any**
boot with `mnemos = true` + `backend = "qdrant"` raises during
`build_registry` before the first tick. This blocks the v1 operator first-boot
procedure in `FIRST_BOOT.md`.

## What Changes

- The cycle's config loader SHALL merge `config/secrets.toml` into the loaded
  configuration before the module registry is built, mirroring the Redis
  secrets handling already present in `load_bus_config()`
  (`kaine/bus/config.py`).
- The Qdrant API key SHALL be resolved with the same precedence convention used
  for Redis: `KAINE_QDRANT_API_KEY` env var first, then `secrets.toml`
  `[qdrant].api_key`. The resolved key SHALL be injected into the in-memory
  `[mnemos.qdrant]` config so `make_mnemos` forwards it.
- The key SHALL NOT be required to live in the git-tracked `config/kaine.toml`;
  secrets-file hygiene (the existing world/group-readable mode warning) SHALL be
  honored.
- A regression test SHALL prove a qdrant-backed Mnemos boots when the key is
  present only in `secrets.toml` (or only in the env var), and that a clear
  error still results when the key is absent everywhere.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `cognitive-cycle`: adds a requirement that the cycle's boot-time config
  assembly merges `config/secrets.toml` (with env-var precedence) into the
  configuration consumed by the module registry — at minimum the Qdrant API
  key into `[mnemos.qdrant]`.

## Impact

- **Code**: `kaine/cycle/__main__.py` (`_load_kaine_config`). Possibly a small
  shared helper if reused. No change to `kaine/boot.py make_mnemos` (it already
  forwards `qdrant.api_key` when present) or to `kaine/modules/mnemos/`.
- **Config/secrets**: no schema change — `secrets.toml [qdrant].api_key` and
  `KAINE_QDRANT_API_KEY` are already the documented conventions (see the
  `mnemos` spec and `redis-bootstrap`).
- **Operator procedure**: `FIRST_BOOT.md` Step 3 begins to succeed for the
  recommended module set; no doc change strictly required, but the boot path is
  unblocked.
- **Tests**: new regression coverage under `tests/` for the cycle config merge.
