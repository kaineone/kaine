## Why

The post-rename test boot of 2026-10-14 preserved and stopped a research-mode entity with encryption at rest on (the shipped setting), then started the cycle with `--revive` on that bundle and the same `KAINE_STATE_KEY`. The start stopped with the revive-refused exit code 7:

```
kaine.cycle: revive refused: could not read bundle members: ReviveError: revive: could not decrypt preservation bundle tar /app/backups/preservation_dba9dacade034c1e_kaine/bundle.tar.enc (CryptoConfigError: cannot decrypt: state encryption is not configured with a key)
```

The key was present. `kaine/cycle/__main__.py` plans the revive (`prepare_revive`, which reads the bundle members) before `_boot_and_run`, and the configured state encryptor is installed only inside the boot (`install_state_encryption` in `kaine/boot/registry.py`). The bundle is therefore read with the default encryptor, which has no key. The ordering dates from #218, so the documented `python -m kaine.cycle --revive <bundle_dir>` has never revived an encrypted bundle. With the configured encryptor installed first, the same bundle decrypts, its stage reads as `development` and its identity plan builds.

The research gate's preflight round trip has the same gap. It runs before the boot as well, so its preserve and revive use the default encryptor and write and read a plaintext bundle. The gate reported the preservation path verified while the real path could not decrypt a bundle.

## What Changes

- **The encryptor is installed first.** The cycle installs the configured state encryptor before the research and unattended safety-net gates and before the revive plan, after the checks that come before them today (the operator-present refusal, the state rename, the stored stage). When encryption is enabled and no key resolves, the start stops there with exit code 1, a configuration-error message naming the variable, and no traceback; before this change it failed inside the boot. `install_state_encryption` becomes idempotent, so the call in the module registry stays for the other entrypoints and does not replace the encryptor already installed.
- **The preflight proves the encrypted path.** The research gate's round trip runs with the configured encryptor, so when encryption is required its bundle is encrypted and the revive decrypts it.
- **Tests.** The entrypoint revives an encrypted bundle with the key set and refuses it with a wrong key (exit code 7, no traceback); the preflight bundle is encrypted when encryption is required.

## Capabilities

### New Capabilities

### Modified Capabilities

- `entity-preservation`: revive at start reads an encrypted bundle with the configured key, and the research gate's round trip exercises the configured encryption.

## Impact

- **Code:** `kaine/cycle/__main__.py`, `kaine/cycle/research_gate.py`, `kaine/boot/security.py` (an idempotent install), tests in `tests/test_revive_entrypoint.py` and the research gate tests.
- **Behaviour:** a start that would have failed at boot on a missing key now fails a little earlier, with the same message. Plaintext installs are unchanged.
- **Docs:** `docs/11-preservation.md` (manual revival, research boot gate).
