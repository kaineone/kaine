## Why

`KAINE_Paper_v4.md` §3.5 and `SECURITY.md` §4 both document that KAINE writes
cognitive state to disk without application-level encryption, relying on the
operator to encrypt at the OS layer. `SECURITY.md` "Out-of-Scope §1" explicitly
defers application-level at-rest encryption to "v1.1+" once a key-management
story exists. The v4 architecture introduces new at-rest state files not
enumerated in the v1 security audit:

- **Empatheia Qdrant collection** (`kaine-qdrant-data` volume) — agent-model
  embeddings and predicted-behavior vectors.
- **Phantasia world-model checkpoint** (`state/phantasia/`) — DreamerV3 world
  model weights, latent-state checkpoints.
- **Sidecar JSONL logs** (`state/evaluation/observers/`) — PLV time series,
  replay association logs (even with `redact_content`, IDs map back to memories),
  welfare event counts, Nous policy logs.

These join the v1 at-rest files (`state/eidolon/self_model.json`, Mnemos Qdrant
collection, `state/hypnos/adapters/`, `state/forks/`) as targets for
application-level encryption.

This change specifies **minimum at-rest and in-transit protection** for cognitive
state, names all new v4 state files in `SECURITY.md`, and provides the plumbing
for encrypt-at-rest. It explicitly does not specify a complete key-management
infrastructure (that remains operator-responsible), but provides a
`CryptoConfig`-gated path so future work can slot in hardware tokens or kernel
keyrings without touching module code.

## What Changes

- **SECURITY.md §4 update:** name all new v4 at-rest state files; enumerate
  which are operator-responsibility (OS-layer) and which gain application-layer
  encryption under this change.
- **`kaine/security/crypto.py`:** `CryptoConfig` (key source, algorithm — AES-256-
  GCM default), `StateEncryptor` (encrypt/decrypt bytes; key loaded from env var
  `KAINE_STATE_KEY` or Linux kernel keyring; graceful no-op when `enabled = false`).
- **Serialize/deserialize wrappers** on: `state/eidolon/self_model.json`,
  `state/phantasia/` checkpoints, sidecar JSONL files (encrypt before write,
  decrypt on read). Mnemos Qdrant collection and Empatheia Qdrant collection:
  document that Qdrant TLS + API key is the transport-layer control; application-
  level field encryption is out of scope for v1.1 (noted in SECURITY.md).
- **Fork/merge export:** `state/forks/` export bundles are encrypted at write and
  decrypted at import using the same `StateEncryptor` key. The key MUST be
  communicated out-of-band for cross-host transfers (documented in SECURITY.md).
- **In-transit authentication:** the existing Redis TLS posture is documented (bus
  traffic is loopback; mutual-backup mesh is deferred); no new in-transit
  mechanism is added for single-host v1.1, but a SECURITY.md note covers what
  multi-host would require.
- `[security.state_encryption]` config: `enabled` (default false), `key_env_var`
  (default `KAINE_STATE_KEY`), `algorithm` (default `aes-256-gcm`),
  `encrypted_paths` (list; defaults to the new v4 paths + self_model).

## Capabilities

### New Capabilities

- `state-encryption`: application-layer AES-256-GCM encryption at rest for
  `self_model.json`, Phantasia checkpoints, and sidecar JSONL; encrypted
  fork/merge export bundles; named inventory of all v4 at-rest state files in
  SECURITY.md.

## Impact

- **Depends on:** none (structural security change; independent of feature
  branches, though it should land after `phantasia-dreamerv3` and
  `sidecar-observers` to cover those paths completely).
- **Welfare:** encrypted at-rest state reduces the risk of memory/self-model
  exfiltration in shared or backup-exposed environments.
- **Operator responsibility:** key rotation, key backup, and out-of-band key
  transfer for fork/merge remain operator responsibilities. SECURITY.md is updated
  to document these explicitly.
- **Repo:** adds `kaine/security/crypto.py`, updates `SECURITY.md`, updates
  serialize/deserialize paths in `kaine/modules/eidolon/`, `kaine/modules/
  phantasia/`, `kaine/evaluation/observers/`, `kaine/modules/hypnos/fork_merge.py`;
  `config/kaine.toml`.
