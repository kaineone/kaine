## ADDED Requirements

### Requirement: Phase 9 ships an unbooted full-stack integration test
The repository SHALL include
`tests/test_phase_9_integration.py` that registers all twelve
canonical module names (via test fakes), runs the cycle for at least
50 ticks against fakeredis, snapshots the entire registry through
ForkManager, and asserts no module error counts and a non-empty
broadcast on at least one experiential tick. The test SHALL NOT
initialize any module's entity state (no Eidolon self-model, no
Mnemos memories, no Hypnos adapters).

#### Scenario: Full stack ticks unbooted
- **WHEN** the full-stack integration test runs
- **THEN** the cycle produces 50 ticks with `cycle.error_counts ==
  {}`, ForkManager.snapshot() captures every registered module, and
  the snapshot can be restored into fresh module instances

### Requirement: Cycle rate stays within 25% of target
The cycle SHALL hold its processing rate within 25% of the
configured target across 50 ticks at 1 Hz, 3.333 Hz, and 10 Hz.

#### Scenario: 3.333 Hz target holds
- **WHEN** the cycle runs 50 ticks at processing_rate_hz=3.333
- **THEN** the average measured ticks-per-second is within 25% of
  3.333

### Requirement: No external-network runtime calls outside allowlist
The repository SHALL ship
`tests/test_phase_9_no_runtime_external_calls.py` that asserts every
runtime use of `httpx.AsyncClient` or `httpx.Client` in `kaine/`
targets a loopback host (`127.0.0.1` or `localhost`) per the module
config defaults shipped in `config/kaine.toml`. The allowlist SHALL
be: Lingua's chat_url, Audio-Out's chatterbox_url, Audio-In's
speaches_url.

#### Scenario: Defaults all point to loopback
- **WHEN** the shipped `config/kaine.toml` is parsed
- **THEN** every URL key under `[lingua]`, `[audio_in]`,
  `[audio_out]` resolves to `127.0.0.1` or `localhost`

### Requirement: first-boot.sh refuses to run without operator-present flag
`scripts/first-boot.sh` SHALL exit non-zero with a printed reminder
unless `KAINE_FIRST_BOOT_OPERATOR_PRESENT=1` is exported.

#### Scenario: Accidental invocation is a no-op
- **WHEN** `scripts/first-boot.sh` is invoked without
  `KAINE_FIRST_BOOT_OPERATOR_PRESENT=1`
- **THEN** the script exits non-zero and prints a line containing
  "operator must be present"

### Requirement: SECURITY.md, ARCHITECTURE.md, FIRST_BOOT.md exist
The repository SHALL ship three operator-facing documents:
`SECURITY.md` (audit conclusions), `ARCHITECTURE.md` (module-by-
module mapping from paper to code), `FIRST_BOOT.md` (operator first-
boot procedure).

#### Scenario: Documents exist
- **WHEN** an operator checks out v1.0-ready
- **THEN** `SECURITY.md`, `ARCHITECTURE.md`, and `FIRST_BOOT.md` are
  present at the repo root
