## Why

The boot-time secrets merge added by `cycle-secrets-merge` resolves the Qdrant
API key (env var → `config/secrets.toml [qdrant].api_key`) and injects it into
`[mnemos.qdrant].api_key`, so a qdrant-backed Mnemos can construct. But Mnemos
is no longer the only Qdrant consumer: **Empatheia** (added by the v4 build)
also ships `backend = "qdrant"` and a `[empatheia.qdrant]` section that shares
the same single `[qdrant]` secret, and its constructor fail-closes with
`Empatheia backend=qdrant requires qdrant_api_key` when the key is absent.

Because `_merge_qdrant_secret` only touches `[mnemos.qdrant]`, **any boot with
`empatheia = true` + `backend = "qdrant"` crashes during `build_registry`**
before the first tick — exactly the all-modules-on configuration of the
operator first boot. This was caught by a zero-cost full-registry dry build
(all 16 modules constructed): Mnemos passed, Empatheia raised.

## What Changes

- The cycle's boot-time secrets merge SHALL inject the resolved Qdrant API key
  into **every qdrant-backed consumer section** that lacks an explicit key —
  at minimum `[mnemos.qdrant]` and `[empatheia.qdrant]` — applying the same
  semantics already specified for Mnemos (env-var precedence, explicit-key
  wins, no empty-value injection).
- A regression test SHALL prove a qdrant-backed Empatheia receives the key when
  it is present only in `secrets.toml` (or only in the env var), and that an
  absent key still yields Empatheia's explicit error rather than a silent empty
  value.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `cognitive-cycle`: broadens the existing "Boot-time secrets merge for the
  cycle config" requirement so the resolved Qdrant key reaches all qdrant-backed
  consumers (Mnemos and Empatheia), not Mnemos alone.
