# Tasks — fix-empatheia-qdrant-secret

## 1. Generalize the secrets merge

- [ ] 1.1 In `kaine/cycle/__main__.py`, refactor `_merge_qdrant_secret` to
      resolve the key once (env → secrets.toml) and inject it into every
      qdrant-backed consumer section that lacks an explicit key. Cover
      `[mnemos.qdrant]` and `[empatheia.qdrant]`. Preserve the existing
      semantics: explicit key wins, no empty-value injection, secrets-file
      mode warning.

## 2. Tests

- [ ] 2.1 Empatheia receives the key from `secrets.toml` only (env unset,
      no key in kaine.toml).
- [ ] 2.2 Env var takes precedence for `[empatheia.qdrant]`.
- [ ] 2.3 Key absent everywhere → no empty value injected into
      `[empatheia.qdrant]`; a qdrant-backed Empatheia still raises its
      explicit missing-key error.
- [ ] 2.4 Existing Mnemos secrets-merge tests still pass (no regression).
- [ ] 2.5 Full-registry dry build with all modules on + the merge constructs
      all 16 modules without raising.

## 3. Live validation (operator-supervised, with the brain running)

- [ ] 3.1 Boot with mnemos + empatheia enabled (qdrant backend); confirm both
      connect to the live Qdrant without the missing-key error. (Deferred to
      the supervised first boot.)
