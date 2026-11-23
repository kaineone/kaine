# Entity-key custody: software-only post-quantum escrow

## Why
Task 1.2 (TPM sealing) is operator-deferred. The software-only path already
refuses to spawn on no-TPM hosts per the design, which blocks all deploys. The
existing pairwise-XOR + X25519 escrow (`kaine/security/custody/escrow.py`)
is also classical-only (ECDH, broken by Shor). This change implements the
no-TPM, post-quantum alternative approved as the interim path: Shamir secret
sharing over GF(2^8) (information-theoretic, PQ-indifferent) plus ML-KEM-768
(FIPS 203, Kyber) key transport and AES-256-GCM share sealing, with durable
storage on GitHub private repos (free tier, append-only, trustee-operated).

## What changes
- `kaine/security/custody/shamir.py` (new): pure-stdlib Shamir (split/combine).
- `kaine/security/custody/pq_escrow.py` (new): ML-KEM-768 + HKDF + AES-256-GCM
  per-trustee share wrapping, `gen_trustee_keypair`, `open_share`,
  `recover_dek`, serialize/deserialize, `publish_to_github`.
- `kaine/security/custody/__main__.py`: `gen-keypair`, `escrow`, `recover`,
  `publish` subcommands.
- `config/trustees.example.toml`.
- `tests/test_shamir_pq.py`, `tests/test_pq_escrow.py`.
- GitHub repos `kaineone/escrow-kaineone` and `kaineone/escrow-guardian`
  (private, secret scanning + push protection, signed commits, 1 review,
  no force push/deletion, weekly escrow-health workflow).

## Security posture (honest)
- No root-on-host trust (already).
- Operator holds no share; 2-of-n (configurable) trustee recovery.
- PQ-resistant: Shamir (information-theoretic) + ML-KEM + AES-256-GCM.
- Weaker than TPM: host root can still read process memory; trustee keys live
  offline.
EOF