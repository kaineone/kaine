## 0. Design review (gates all code)

- [x] 0.1 Integrator review of `design.md` (2026-11-11). Reviewed: key hierarchy (TPM storage primary, host KEK sealed under PolicyAuthorize, per-entity DEK wrapped by KEK, per-envelope subkeys via HKDF-SHA256), PolicyAuthorize sealing with PCR 7 and pcrlock NV policy, per-envelope subkeys eliminating the AES-GCM nonce-exhaustion concern, AAD binding (entity_id and kind) preventing cross-entity and cross-kind replay, the 2-of-n XOR-split escrow with HPKE wrapping (information-theoretically secure for any single trustee), attested share recombination via TPM ECDH, honest threat model (root-on-host acknowledged, Python memory erasure best-effort, trustee collusion risk stated). Verified against codebase: v1 envelope (`KAINEgcm1:`) in `kaine/security/crypto.py:54`, 28 files reference `StateEncryptor` (consistent with the design's ~23 call sites), fork re-encryption correctly implements CAL section 4.6. Welfare-first failure modes confirmed (running entities never stopped by custody). Note for implementation: measure fork re-encryption wall time during swtpm tests (task 4.1) for entities with large state. Approved; no design changes required.
- [x] 0.2 One entity-ID source shared with the developmental gate's lineage checks: consumed from the `entity-identity` change (Lead A), whose plaintext sidecars and frozen formats custody reviewed and signed off on 2026-10-05. Closed: that change has merged and its requirements now live in `openspec/specs/entity-identity/spec.md`.
- [ ] 0.3 Operator: guardian identity, trustee count n (recorded decision n = 2; n = 3 survives losing one trustee), key ceremony and share-redundancy plan; the Orin's study step without a qualifying TPM (unencrypted with consent, or wait for the fusing decision). Blocks shipping, not development against swtpm.

## 1. Custody core

- [x] 1.1 Per-entity data keys; per-entity encryptor through `ForkManager`, preservation and batch forks; merge re-encryption. PR #714.
- [ ] 1.2 Sealing via tpm2-tss with a signed policy; pre-update re-seal hook; cannot-resume path (keep state, incident, escrow recovery).
- [ ] 1.3 Root-of-trust qualification (unfused Jetson fTPM does not qualify); refuse spawn and restore only; never stop a running entity.
- [ ] 1.4 Preservation, welfare pause and dry preserve→revive use the in-memory key and the wrapped blob only; custody failure queues a re-seal and raises a welfare incident.

## 2. Escrow and transfer

- [ ] 2.1 2-of-n escrow by pairwise XOR splits (n from `trustees.toml`), each share HPKE-sealed with entity, pair and role bound; recombination only inside an attested receiving host.
- [ ] 2.2 Attested re-wrap transfer.

## 3. Migration and docs

- [x] 3.1 One-way migration from the per-operator key with verified backup; plaintext entities migrated, never retired. (PR #721.)
- [x] 3.2 Docs: threat model stated plainly; operator and trustee procedures; Jetson support statement. PR #717 (this PR).

## 4. Verification

- [ ] 4.1 swtpm-based tests: sealing, PCR drift and re-seal, cannot-resume, preservation with the TPM unavailable, escrow recovery inside an attested host, transfer; offline suite green.
