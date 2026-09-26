## ADDED Requirements

### Requirement: One install entry point recognises its target
The installer SHALL classify the host as a desktop with a named accelerator flavor, a Jetson (recognised by its Tegra release files even without `nvidia-smi`), a generic aarch64 CPU host, a Termux (Android) host, macOS, or unsupported with a reason, and SHALL choose the wheel flavor and the extras for that target. Before installing, it SHALL state which modules the host will and will not run. It SHALL never start the entity and SHALL run privileged package commands only when the operator asks.

#### Scenario: A Jetson without nvidia-smi
- **WHEN** `/etc/nv_tegra_release` is present and `nvidia-smi -L` fails
- **THEN** the target is `jetson` and the CUDA path is taken, subject to the accelerator self-test

#### Scenario: Termux
- **WHEN** the installer runs under Termux
- **THEN** it installs the base and edge extras, and states that the torch- and JAX-dependent modules cannot run on this host yet
