## ADDED Requirements

### Requirement: A host installs only what its modules need
The base installation SHALL contain only the dependencies every entity uses, and heavy or host-specific dependencies SHALL be in named extras. When an enabled module or service needs an extra that is not installed, the start SHALL stop before any module is built with one message naming each missing import, the extra that provides it and the install command, and SHALL NOT fail later with an import traceback.

#### Scenario: A module whose extra is missing
- **WHEN** Soma is enabled on a host without the `core` extra
- **THEN** the start stops before building modules, and the message names torch and ncps and the `core` extra

#### Scenario: A lean host
- **WHEN** only the base and the extras for the enabled modules are installed
- **THEN** the start proceeds without any other heavy package present

## MODIFIED Requirements

### Requirement: torch dependency declared without index pin
`pyproject.toml` SHALL declare torch as a tested version range (currently
`torch>=2.9.1,<2.15`) and `ncps>=1.0,<2` under the `core` optional-dependency
extra, not the base `[project.dependencies]`, with no index URL in the
declaration. The install script is the only place the wheel source and exact
version are chosen. Automated dependency updates SHALL NOT change the torch,
torchvision or torchaudio range; the range changes only through a change whose
CI passes the offline suite at both ends of the new range on the CPU index and
whose accelerator smoke tests are recorded.

#### Scenario: pyproject.toml stays portable
- **WHEN** an operator inspects `pyproject.toml`
- **THEN** the `torch` entry is a bounded tested range in the `core` extra and does not embed a
  PyPI index URL or a hardware-specific marker

#### Scenario: Dependabot proposes a torch bump
- **WHEN** a new torch release is published
- **THEN** no automated pull request changes the torch range
