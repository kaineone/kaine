## 0. Design review

- [ ] 0.1 Write `design.md`: key hierarchy, sealing and PCR policy per platform (discrete TPM, Jetson fTPM), re-seal on update, Shamir parameters, escrow wrapping format, attestation format and verification, failure modes; operator approval before code.
- [ ] 0.2 Guardian identity and key ceremony agreed; trustee share-durability plan written.

## 1. Key custody core

- [ ] 1.1 Per-entity data key generation at spawn; fork and merge key handling.
- [ ] 1.2 Host sealing through tpm2-tss with PCR binding; re-seal procedure.
- [ ] 1.3 Root-of-trust qualification check (unfused Jetson fTPM does not qualify); refuse spawn and restore without it.
- [ ] 1.4 Shamir 2-of-2 split and escrow wrapping to trustee public keys.

## 2. Transfer and recovery

- [ ] 2.1 Attested re-wrap handshake to a receiving host.
- [ ] 2.2 Recovery from escrow shares onto a qualifying host.

## 3. Migration and docs

- [ ] 3.1 Operator-run one-way migration from the per-operator key with verified backup.
- [ ] 3.2 Docs: the runtime-memory limit stated plainly; operator and trustee procedures.

## 4. Verification

- [ ] 4.1 Tests with a software TPM simulator (swtpm) for sealing, PCR mismatch, re-seal, transfer and escrow recovery; offline suite green.
