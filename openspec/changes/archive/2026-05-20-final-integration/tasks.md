## 1. Integration tests

- [x] 1.1 `tests/test_phase_9_integration.py` — full-stack fakeredis tick + fork roundtrip
- [x] 1.2 `tests/test_phase_9_cycle_rate_stability.py` — rate-stability across 1/3.333/10 Hz
- [x] 1.3 `tests/test_phase_9_no_runtime_external_calls.py` — loopback-only URL invariant

## 2. Security audit + docs

- [x] 2.1 Run security-audit subagent over kaine/, config/, compose/, scripts/
- [x] 2.2 `SECURITY.md` — audit conclusions

## 3. Architecture + first-boot docs

- [x] 3.1 `ARCHITECTURE.md` — module → code mapping + bus topology
- [x] 3.2 `FIRST_BOOT.md` — operator procedure (DO NOT RUN unattended)
- [x] 3.3 README update (status → v1.0-ready, first boot pending operator)

## 4. First-boot script

- [x] 4.1 `scripts/first-boot.sh` with KAINE_FIRST_BOOT_OPERATOR_PRESENT=1 gate
- [x] 4.2 Make script executable

## 5. Verification

- [x] 5.1 Full suite passes (624 / 8 skipped)
- [x] 5.2 `openspec validate final-integration --strict` clean
- [ ] 5.3 Commit, merge, archive, tag v1.0-ready
