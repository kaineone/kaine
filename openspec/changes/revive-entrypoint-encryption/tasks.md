## 1. Order

- [ ] 1.1 Install the configured state encryptor once, after the configuration loads and before the supervision gates and `prepare_revive`; the boot reuses it.
- [ ] 1.2 The research gate's preflight round trip uses the configured encryptor.

## 2. Tests

- [ ] 2.1 The entrypoint revives an encrypted bundle with the key set; a wrong key refuses with exit code 7 and no traceback.
- [ ] 2.2 The preflight bundle is encrypted when encryption is required, and its revive decrypts it.
- [ ] 2.3 Mutation-check both.

## 3. Docs

- [ ] 3.1 `docs/11-preservation.md`: manual revival and the research boot gate.
- [ ] 3.2 `openspec validate revive-entrypoint-encryption --strict`.
