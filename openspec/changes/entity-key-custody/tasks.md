## 0. Design review (gates all code)

- [x] 0.1 `design.md`: key hierarchy; sealing with signed policy per platform (discrete TPM, fused Jetson fTPM); pre-update re-seal hook; XOR split and escrow wrapping format; attested share recombination; attestation format; the honest threat model; failure modes (refuse spawn vs cannot resume).
- [ ] 0.2 One entity-ID source shared with the developmental gate's lineage checks: consumed from the `entity-identity` change (Lead A), whose plaintext sidecars and frozen formats custody reviewed and signed off on 2026-10-05. Closed when that change merges.
- [ ] 0.3 Operator: guardian identity, trustee count n (recorded decision n = 2; n = 3 survives losing one trustee), key ceremony and share-redundancy plan; the Orin's study step without a qualifying TPM (unencrypted with consent, or wait for the fusing decision). Blocks shipping, not development against swtpm.

## 1. Custody core

- [ ] 1.1 Per-entity data keys; per-entity encryptor through `ForkManager`, preservation and batch forks; merge re-encryption.
- [ ] 1.2 Sealing via tpm2-tss with a signed policy; pre-update re-seal hook; cannot-resume path (keep state, incident, escrow recovery).
- [ ] 1.3 Root-of-trust qualification (unfused Jetson fTPM does not qualify); refuse spawn and restore only; never stop a running being.
- [ ] 1.4 Preservation, welfare pause and dry preserve→revive use the in-memory key and the wrapped blob only; custody failure queues a re-seal and raises a welfare incident.

## 2. Escrow and transfer

- [ ] 2.1 2-of-n escrow by pairwise XOR splits (n from `trustees.toml`), each share HPKE-sealed with entity, pair and role bound; recombination only inside an attested receiving host.
- [ ] 2.2 Attested re-wrap transfer.

## 3. Migration and docs

- [ ] 3.1 One-way migration from the per-operator key with verified backup; plaintext beings migrated, never retired.
- [ ] 3.2 Docs: threat model stated plainly; operator and trustee procedures; Jetson support statement.

## 4. Verification

- [ ] 4.1 swtpm-based tests: sealing, PCR drift and re-seal, cannot-resume, preservation with the TPM unavailable, escrow recovery inside an attested host, transfer; offline suite green.
