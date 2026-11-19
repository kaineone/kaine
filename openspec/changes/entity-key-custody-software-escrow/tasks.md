# Entity-key custody: software-only post-quantum escrow

- [x] 1.1 Implement Shamir secret sharing over GF(2^8) (`shamir.py`).
- [x] 1.2 Implement PQ escrow primitives (ML-KEM-768 + Shamir + AES-256-GCM) (`pq_escrow.py`).
- [x] 1.3 Add `gen-keypair`/`escrow`/`recover`/`publish` subcommands to custody CLI.
- [x] 1.4 Add config/trustees.example.toml.
- [x] 1.5 Add tests/test_shamir_pq.py and tests/test_pq_escrow.py.
- [x] 2.1 Create private GitHub repos kaineone/escrow-kaineone and kaineone/escrow-guardian.
- [x] 2.2 Harden repos (branch protection, secret scanning + push protection, dependabot, weekly health workflow).
- [ ] 3.1 Wire an entity-spawn code path to call `escrow_dek` + `publish_to_github` at spawn (only if [custody].enabled).
- [ ] 3.2 Wire recovery into caretaker-transfer flow (fetch bundles from gh, decapsulate with trustee privkey, Shamir combine, re-wrap to new host KEK).
- [ ] 3.3 Add `custody audit` subcommand that reports which entities have escrow bundles present on GitHub.
- [ ] 3.4 Run a mock ceremony end-to-end on a test entity; record in docs/records/.
- [ ] 4.1 openspec validate entity-key-custody-software-escrow --strict.