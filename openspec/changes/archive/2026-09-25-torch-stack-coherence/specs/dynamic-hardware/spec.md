## ADDED Requirements

### Requirement: Installers keep the PyTorch stack coherent
The installers SHALL take the torch requirement from `pyproject.toml`, SHALL install `torch` and `torchvision` together from the single resolved wheel index, and SHALL pin the installed `torch`, `torchvision` and `torchaudio` versions with a constraints file passed to every subsequent `pip install` in the same run.

#### Scenario: Installer spec matches the project requirement
- **WHEN** `pyproject.toml` declares `torch>=2.14.0,<3`
- **THEN** both `scripts/install.sh` and `scripts/install.py` install torch with exactly that requirement

#### Scenario: Extras cannot swap the torch stack
- **WHEN** the installer installs KAINE and its extras after the torch step
- **THEN** each of those pip invocations carries `-c <venv>/kaine-torch-constraints.txt` naming the installed torch-stack versions

#### Scenario: Research install matches torchaudio to torch
- **WHEN** the installer runs with `--research`
- **THEN** `torchaudio` is installed from the same wheel index as torch before the perception extras

### Requirement: Installer tests never touch the developer environment
The installers SHALL honour a `KAINE_VENV_DIR` override for the virtual-environment location, and the installer test suite SHALL run them against a temporary venv location.

#### Scenario: Test run on a machine with an existing venv
- **WHEN** the installer tests run on a host whose repository already contains `.venv/`
- **THEN** no pip command runs against that `.venv/` and its contents are unchanged afterwards

### Requirement: Pre-boot check rejects an incoherent torch stack
The system SHALL provide a metadata-only torch-stack coherence check, the pre-boot sweep SHALL fail when it reports a mismatch, and the installers' verify step SHALL exit non-zero when it reports a mismatch.

#### Scenario: Companion built for a different torch
- **WHEN** installed `torchvision` declares `torch==2.11.0` but torch 2.14.0 is installed
- **THEN** the check reports the mismatch and the pre-boot CONFIG SANITY group shows FAIL

#### Scenario: Mixed CUDA builds
- **WHEN** torch is `2.14.0+cu130` and torchaudio is `2.11.0+cu128`
- **THEN** the check reports a CUDA build mismatch

#### Scenario: Coherent stack
- **WHEN** torch, torchvision and torchaudio are installed with the same local tag and torchvision's torch pin matches
- **THEN** the check reports no problems and the pre-boot check PASSes listing the versions
