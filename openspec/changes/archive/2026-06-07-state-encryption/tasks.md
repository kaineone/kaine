## 1. Crypto plumbing

- [x] 1.1 `kaine/security/__init__.py` + `kaine/security/crypto.py` — `CryptoConfig`, `StateEncryptor` (AES-256-GCM); load key from env var `KAINE_STATE_KEY` or Linux kernel keyring; raise `CryptoConfigError` at startup if key absent and `enabled = true`; no-op pass-through when `enabled = false`
- [x] 1.2 `[security.state_encryption]` config: `enabled` (default `false`), `key_env_var` (default `KAINE_STATE_KEY`), `algorithm` (default `aes-256-gcm`), `encrypted_paths` (list with defaults)

## 2. State file wrappers

- [x] 2.1 Wrap `state/eidolon/self_model.json` read/write with `StateEncryptor`
- [x] 2.2 Wrap `state/phantasia/` checkpoint read/write with `StateEncryptor`
- [x] 2.3 Wrap sidecar JSONL writer (in `kaine/evaluation/observers/`) with `StateEncryptor` for all observer JSONL files under `state/evaluation/observers/`

## 3. Fork/merge export encryption

- [x] 3.1 Encrypt fork export bundle before writing to `state/forks/` when `enabled`
- [x] 3.2 Decrypt on import; document out-of-band key transfer requirement for cross-host fork/merge in SECURITY.md

## 4. SECURITY.md update

- [x] 4.1 Update SECURITY.md §4 to enumerate all new v4 at-rest state files: Empatheia Qdrant collection, `state/phantasia/` checkpoints, `state/evaluation/observers/` sidecar JSONL; note protection posture for each
- [x] 4.2 Add note on Qdrant TLS + API key as transport-layer control for Empatheia/Mnemos collections (application-level field encryption deferred)
- [x] 4.3 Document key rotation, key backup, and out-of-band key transfer responsibilities in SECURITY.md Operator Responsibilities section

## 5. Tests

- [x] 5.1 `tests/test_state_encryptor.py` — encrypt/decrypt roundtrip; no-op when disabled; `CryptoConfigError` on missing key with enabled
- [x] 5.2 `tests/test_self_model_encryption.py` — `self_model.json` is unreadable without key when enabled; readable after decrypt
- [x] 5.3 `tests/test_fork_export_encryption.py` — encrypted export bundle; successful import with correct key; failure with wrong key

## 6. Verification

- [x] 6.1 Full unit suite green
- [x] 6.2 `openspec validate state-encryption --strict` clean
- [x] 6.3 Commit (Kaine.One), branch-per-change, merge, archive
