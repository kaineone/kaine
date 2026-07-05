## Why

A new operator who enables modules still has to discover, by trial and error,
which external services those modules need (Redis, Ollama, Qdrant, Speaches,
Chatterbox) and whether they are running. The first-run wizard scans hardware and
writes config but says nothing about the services the chosen modules depend on.

The operator asked that the installer/wizard detect missing dependencies and
install them on consent. The honest form of that distinguishes two cases:

- Services with a one-command provision (Redis/Qdrant via the repo's own vetted
  bootstrap scripts; Ollama via its official installer) can be **shown and run on
  explicit consent**.
- The heavy GPU Python services (Speaches, Chatterbox) are a clone + venv +
  multi-GB model download. A one-click "install" of those would lie about what it
  did, so the wizard **prints real setup steps and a docs link** and runs nothing.

## What Changes

- New `kaine/setup/dependencies.py`: a dependency registry + real detection
  (`shutil.which` for binaries, a TCP connect for running services) and
  `implied_external_deps()` mapping enabled modules to their services.
- The wizard adds a dependency step after the extras step: for each service the
  enabled modules need, it reports whether it is already running; offers a shown,
  consented command for the command-provisionable ones; and prints setup guidance
  for the guide-only ones. It never installs without explicit consent and never
  crashes the wizard on a provisioning failure.
- `scripts/install.sh` notes that the wizard performs this detection.
- `docs/getting-started.md` documents the dependency step.

No pretend work: detection is real, the printed commands/steps are real and shown
before anything runs, and a guide-only service is never reported as installed.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `first-run-wizard`: adds external-service dependency detection and honest,
  consent-gated provisioning (command-run for bootstrap/installer deps;
  print-guidance for heavy GPU services).

## Impact

- **Code (new):** `kaine/setup/dependencies.py`; `tests/test_dependencies.py`.
- **Code (edit):** `kaine/setup/__main__.py` (`_provision_dependencies` step),
  `scripts/install.sh` (note).
- **Docs:** `docs/getting-started.md` (wizard dependency step).
- **Safety:** nothing installs without explicit consent; failures never crash the
  wizard; no service is started silently; guide-only services are never auto-run.
