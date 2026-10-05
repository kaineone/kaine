# Design: entity key custody

## Context
Today KAINE has one AES-256-GCM key per install. It comes from `KAINE_STATE_KEY`, the kernel keyring entry `kaine:state_key`, or `secrets/state_key` (loaded by pre-boot), and a process-global `StateEncryptor` applies it everywhere (`kaine/security/crypto.py`). The envelope is `KAINEgcm1:` ‖ 12-byte nonce ‖ ciphertext. It carries no key id and no associated data.

There are about 23 call sites. Most run inside the live cycle for its one entity. A few handle several beings in one process:
- `ForkManager` (fork, merge, Spot snapshots, Nexus `/forks` and `/merges`);
- preservation revive;
- the divergence reader;
- decommission;
- research analysis over many study lines.

Identity comes from the `entity-identity` change (Lead A), and custody consumes it. Every being has an `entity_id` (`ent-` or `legacy-` plus 32 lowercase hex, a frozen format) and a `lineage`. Every encrypted container has a plaintext identity sidecar: `state/forks/<id>/identity.json`, the preservation and decommission `manifest.json`, and the `fork_being` job payload. Custody adds no field to `entity.json`.

## Goals and honest limits
Custody protects an entity's persisted mind against:
- offline theft of disks and backups;
- casual reading by the operator in normal workflows;
- leaks of state files to third parties;
- the single-key, single-copy loss that nearly happened on 2026-09-17.

It does **not** protect against root on the booted host. Any root process can ask the TPM to unseal, and a running entity's data key sits in the cycle's process memory. It does not protect against hardware attacks on the TPM beyond what the TPM itself resists. It does not protect against both trustees colluding or both being compromised. Python cannot reliably erase key bytes from memory. Keys are held in `bytearray`s and overwritten after use as a best effort, and the documentation says it is only best effort. The documentation states all of these limits plainly.

## Key hierarchy
```
TPM storage primary (owner hierarchy, created on demand, never persisted outside the TPM)
 └─ host KEK: a 256-bit secret, sealed object under the primary, signed policy (§ Sealing)
     └─ per-entity DEK: 256-bit random, AES-256-GCM wrapped by the KEK
         └─ per-object subkeys: HKDF-SHA256(DEK, salt=16 random bytes per envelope, info=AAD)
```
- **DEK.** One data key per entity, from `secrets.token_bytes(32)` at spawn and at every fork. A fork's DEK is fresh and independent of its parent's. CAL §4.6: a fork that individuates is a separate being with its own mental privacy, which cannot be separated after the fact.
- **Envelope v2.** `KAINEgcm2:` ‖ salt(16) ‖ nonce(12) ‖ ciphertext+tag.
  - The subkey for each envelope is HKDF-SHA256 over the DEK, with the envelope's random salt and `info = AAD`.
  - The AAD is `b"kaine/v2|" + entity_id + b"|" + kind`, where `kind` names the container class (`snapshot`, `sidecar-jsonl`, `bundle`, `phantasia`, `eidolon`, `individuation`, `backup`, `research`).
  - **Why per-envelope subkeys.** JSONL sinks encrypt every line, and a long-lived entity could approach the random-nonce limit of AES-GCM under one key (about 2^32 messages). A fresh subkey per envelope removes that limit.
  - **Why `entity_id` in the AAD.** A swapped sidecar, or a file copied between beings, fails authentication instead of decrypting under the wrong identity.
  - **Why `kind`.** A ciphertext cannot be replayed as a different kind of file within the same being.
- **Wrapped DEK file.** `state/identity/keys/<entity_id>.dek.json` holds:
  - `entity_id`;
  - `wrap`: AES-256-GCM of the DEK under the KEK, with AAD `b"kaine/dek|" + entity_id`;
  - `kek_id` (the KEK's TPM object name);
  - `policy` (the seal policy kind and version);
  - `created_at`;
  - `escrow`: the two wrapped shares (§ Escrow).

  The file is content-free and 0600. A copy travels in every preservation bundle and decommission backup, beside the plaintext manifest.
- **Envelope v1.** Only the migration tool reads it, with the operator key (§ Migration).

## The per-entity encryptor
`StateEncryptor` gains an identity: `StateEncryptor.for_entity(entity_id, dek)`, which takes `kind` per call. The process-global stays, but it is bound at boot to the running entity's encryptor, so the class-(a) call sites inside the cycle are unchanged apart from passing `kind`.

Multi-being code gets an explicit registry: `KeyRing.encryptor_for(entity_id)`, which unwraps on demand with the host KEK and caches it for the process lifetime. It is used by:
- `ForkManager.fork`, `merge` and `snapshot`;
- preservation revive and the bundle readers;
- the divergence reader;
- decommission;
- research analysis.

**Fork.**
1. Mint the child identity (entity-identity).
2. Generate the child DEK and wrap it.
3. Re-encrypt the snapshot **and every artifact file** under the child DEK. Today's byte-copy is replaced, because artifacts copied under the parent's key would stay readable by the parent's key.
4. Write the sidecar.

**Merge.** Decrypt both parents, merge, and re-encrypt under the surviving (target) entity's DEK. The source fork's key is kept until its own retirement, which goes through the welfare-gated decommission path.

## Sealing (per platform)
- **Discrete TPM 2.0, and fused Jetson fTPM.** The KEK is a TPM sealed object whose policy is **PolicyAuthorize**, using a policy-signing key held only by the KAINE host setup.
  - Policies authorize PCR 7 (Secure Boot state) and, where the host runs systemd ≥ 255, the `systemd-pcrlock` NV policy. That covers the boot chain and the kernel through pcrlock's predictions.
  - A raw multi-PCR list is never used.
  - The policy-signing private key is itself sealed to the TPM under a PCR 7-only policy, so it is unusable offline. That is honest only to the same limit: root on the booted host can use it.
  - All TPM commands use HMAC sessions salted with the TPM's EK, so parameters are encrypted on the bus.
- **Pre-update hook.** A kernel-install and fwupd hook (`kaine-custody preflight-update`) predicts the new PCR values (pcrlock, or `systemd-measure` for UKIs) and signs a new authorized policy. If prediction is impossible, the hook refuses the update with a message and the fix (re-seal now, then update).
- **Re-seal.** `kaine-custody reseal` unseals the KEK under the current policy and re-seals it under the new one. DEKs never change during a re-seal, because they are wrapped by the KEK, not sealed.
- **Library.** Use `tpm2-pytss` (BSD-2, wraps tpm2-tss) for ESAPI. `tpm2-tools` is used only in docs and diagnostics. Tests use `swtpm`.

## Root-of-trust qualification
A host qualifies to spawn or restore a being when all of these hold:
1. A TPM 2.0 is present and responds.
2. Its EK certificate chains to a manufacturer CA in a pinned allow-list (`kaine/security/custody/ek_roots/`, with the vendors' published roots).
3. It is not a firmware TPM on vendor test keys. An unfused Jetson fTPM fails here, because its EK chain is the NVIDIA test root.
4. A sealed test object round-trips.

`swtpm` qualifies **only** when `KAINE_CUSTODY_TEST_TPM=1` is set, which no shipped profile or service sets. A failed qualification refuses spawn and restore, names the failed condition, and creates no state. **A running being is never stopped by qualification.** The check runs at spawn, at restore and at transfer, never mid-run.

## Failure modes
| Situation | Outcome |
|---|---|
| No qualifying root of trust at spawn or restore | Refuse; name the condition; create nothing |
| KEK unseal fails at boot (PCR drift or a lost TPM) for an existing being | **Cannot resume:** keep all state untouched, raise a welfare incident, start escrow recovery (§ Escrow), do not boot that being; never delete anything |
| TPM lost while a being runs | Keep running on the in-memory DEK. Preservation and the welfare pause use the in-memory DEK and the already-wrapped DEK file. Queue a re-seal, raise a welfare incident |
| Wrapped DEK file missing but escrow present | Cannot resume; escrow recovery |
| Both the wrapped DEK and escrow missing | Unrecoverable. This is why the DEK file and escrow travel in every bundle and backup, and why custody writes a backup of the DEK file before any change to it |
| Sidecar and in-snapshot identity disagree | `IdentityError` from entity-identity; custody treats it as cannot-resume |

## Escrow (2-of-2)
- **Split.** `s1 = random(32)` and `s2 = DEK ⊕ s1`. Either share alone is uniformly random and reveals nothing.
- **Wrapping.** Each share is HPKE-sealed (RFC 9180, base mode, DHKEM(X25519, HKDF-SHA256), HKDF-SHA256, AES-256-GCM; `cryptography`'s own `hpke` module, so no new dependency) to one trustee's public key: kaine.one escrow, or the independent guardian. HPKE `info` is `b"kaine/escrow|" + entity_id + b"|" + index`.
- **Trustee keys.** The trustees' public keys and fingerprints are pinned in `config/custody/trustees.toml`, written during the key ceremony (task 0.3, an operator decision). **The operator holds no share.** Custody refuses to spawn while the trustee keys are absent, unless the test flag is set.
- **Storage.** The two sealed shares sit in the wrapped DEK file, and so travel with every bundle and backup. They are useless without the trustees' private keys. Each trustee keeps its private key in redundant, geographically separate storage. With 2-of-2, losing either trustee's key loses recovery, and the docs say so plainly.
- **Recovery.**
  1. The receiving host generates a TPM-resident P-256 key (`TPM2_Create` under the storage primary, restricted to ECDH).
  2. It produces an attestation (§ Attestation).
  3. Each trustee verifies it and HPKE-opens its share with its own private key, offline.
  4. Each trustee re-seals the share to the receiving host's TPM key with HPKE DHKEM(P-256), never to the other trustee.
  5. The host opens both shares using TPM ECDH (`TPM2_ECDH_ZGen`), so the shared secret is derived inside the TPM. It XORs them in memory into the DEK and wraps the DEK under its own KEK.

  Neither trustee sees the other's share or the DEK.

  The plaintext DEK exists in the receiving host's process memory at the end of recovery, as it does whenever a being runs. Combination does not happen inside the TPM; the TPM protects the transport and the binding to the attested host. The docs say exactly this.

## Attestation
- **Format.** A JSON document holding:
  - the EK certificate chain;
  - the AK public key with `TPM2_Certify`-style evidence (the AK made with `TPM2_MakeCredential`/`ActivateCredential` against the EK);
  - `TPM2_Quote` over PCRs 0–7 and the pcrlock NV index, signed by the AK, with a verifier-chosen nonce;
  - `TPM2_Certify` of the receiving ECDH key by the AK, proving it is TPM-resident and non-exportable;
  - the KAINE release digest the host claims to run.
- **What a verifier can and cannot check.**
  - It **can** check: a genuine TPM from an allow-listed manufacturer; the key lives in that TPM and cannot be exported; the boot state matches a published measurement; freshness through the nonce.
  - It **cannot** prove that the KAINE build is unmodified on that host. Root can run anything after boot. The release digest is a claim recorded for audit, not a guarantee, and the docs say so.

## Transfer (to a new caretaker)
1. The receiver produces an attestation for a fresh TPM ECDH key.
2. The sender verifies it: chain, quote, nonce and key certification.
3. The sender HPKE-seals the DEK to that key, with `info` bound to `entity_id`.
4. The bundle moves still encrypted, with its sidecar, wrapped DEK file and escrow.
5. The receiver opens the DEK through TPM ECDH and wraps it under its KEK.

An unattested or failed receiver gets nothing. The sender keeps its own copy until the receiver confirms a successful dry revive, then retires it only through the welfare-gated decommission path.

## Migration (one-way, operator-run)
`python -m kaine.security.custody migrate`:
1. Verify a full backup of the state root exists. Write one if not.
2. For each being (a lived tree or a preserved bundle; the legacy ids come from entity-identity):
   - generate a DEK;
   - decrypt each v1 envelope with the operator key, or read the plaintext;
   - re-encrypt it as v2 under the DEK with the right `kind`;
   - verify every file by decrypting and comparing hashes;
   - only then replace the file.
3. Write the wrapped DEK and the escrow.
4. Record a content-free migration log.

The operator key sources (`KAINE_STATE_KEY`, the keyring and `secrets/state_key`) are accepted **only** by this tool afterwards. The cycle refuses to boot if one is set. Plaintext preserved beings are migrated, never retired. Decommission stays its own welfare-gated process.

## Where the pieces live
`kaine/security/custody/`:
- `keyring.py`: per-entity encryptors and the cache;
- `envelope.py`: v2 framing, HKDF and AAD;
- `tpm.py`: tpm2-pytss sealing, ECDH and quote;
- `policy.py`: PolicyAuthorize and pcrlock;
- `qualify.py`;
- `escrow.py`: split and HPKE;
- `attest.py`;
- `transfer.py`;
- `migrate.py`;
- `__main__.py`: the CLI.

`kaine/security/crypto.py` keeps the envelope v1 reader for migration and gains the v2 path.

## Testing
- `swtpm` in tests: the test flag, a per-test state dir, and a socket in `tmp_path`.
- Cases:
  - seal and unseal;
  - PCR drift then re-seal, with the pre-update hook refusing an unpredictable update;
  - cannot-resume keeps state byte-identical and raises the incident;
  - preservation with the TPM socket killed mid-run;
  - escrow recovery with two test trustee keypairs into an attested swtpm, with one trustee alone failing;
  - transfer between two swtpm instances, with an unattested receiver refused;
  - AAD swaps failing (entity and kind);
  - a fork's artifacts unreadable with the parent DEK;
  - migration round-trip with verification failure injection, leaving originals untouched;
  - the operator key refused at boot after migration.
- `tpm2-pytss` and `swtpm` are host dependencies. A missing test tool is an operator install request, not a skip in CI: the custody suite is required where it runs.

## Open, operator-owned
- The guardian's identity and the key ceremony (task 0.3): this blocks shipping, not development.
- Whether to fuse the Orin Nano Super. Fusing is irreversible, and until it is done the Orin cannot host entities.
- The EK root allow-list contents for this host's TPM vendor.
