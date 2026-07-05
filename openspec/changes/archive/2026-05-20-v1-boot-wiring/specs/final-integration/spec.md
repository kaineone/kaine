## ADDED Requirements

### Requirement: kaine/boot.py builds a registry from kaine.toml
`kaine/boot.py` SHALL expose `build_registry(bus, kaine_config)`
that consumes `kaine_config["modules"]` toggles and per-module
`kaine_config[<name>]` sections, producing a populated
`ModuleRegistry`. Each factory SHALL map TOML keys to constructor
kwargs explicitly so an unknown TOML key raises at boot, not at
runtime.

#### Scenario: Disabled modules are not registered
- **WHEN** `kaine_config["modules"]["soma"] == False` and
  `build_registry` runs
- **THEN** the returned registry does not contain `soma`

#### Scenario: Hypnos receives interdependency refs
- **WHEN** mnemos, nous, and thymos are all enabled and hypnos is
  also enabled
- **THEN** the constructed Hypnos instance is wired to the
  previously-constructed mnemos / nous_process / thymos instances

### Requirement: kaine/cycle/__main__.py is a real operator entrypoint
The repository SHALL ship `kaine/cycle/__main__.py` such that
`python -m kaine.cycle` loads config, builds the registry, builds
the cycle, and runs forever. The entrypoint SHALL refuse to boot
unless `KAINE_CYCLE_OPERATOR_PRESENT=1` is exported, mirroring
`scripts/first-boot.sh`'s safety gate. It SHALL handle SIGINT
gracefully by shutting down the cycle and every registered module.

#### Scenario: Refuses without operator-present env var
- **WHEN** `python -m kaine.cycle` runs without
  `KAINE_CYCLE_OPERATOR_PRESENT=1`
- **THEN** the process exits non-zero with a printed reminder

### Requirement: Nexus exposes real cycle metrics
The Nexus diagnostics page SHALL display live cycle metrics:
`processing_rate_hz`, `experiential_rate_hz`, `tick_index`, and a
per-stream error count summary. The `metrics_snapshot()` function
SHALL read these from an in-process cycle reference (when the cycle
boots Nexus) or from a JSON runtime file (when Nexus boots
standalone). The placeholder return value SHALL be removed.

#### Scenario: In-process metrics
- **WHEN** Nexus is configured with a cycle reference and
  diagnostics is requested
- **THEN** the JSON metrics endpoint returns the cycle's
  `tick_index`, `processing_rate_hz`, `experiential_rate_hz`,
  `error_counts`

### Requirement: SECURITY.md and FIRST_BOOT.md drop the AUDIT.log claim
The repository SHALL NOT reference `state/bus/AUDIT.log` in any
operator-facing document because no code writes such a file. The
Praxis audit log (`state/praxis/audit.log`) reference SHALL remain
because it is genuine.

#### Scenario: SECURITY.md is honest
- **WHEN** an operator searches `SECURITY.md` for
  `state/bus/AUDIT.log`
- **THEN** there is no match
