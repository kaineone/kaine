# Kaine

KAINE is a Python 3.12 research system. The repository holds the application,
its OpenSpec changes, and the operational docs under `docs/`.

## Setup

Run the installer from the repository root:

```sh
bash scripts/install.sh --research --no-wizard
```

The installer selects a torch wheel for the host and creates a virtual
environment (set `KAINE_VENV_DIR` to place it outside the tree, for example on a
persistent bulk drive).

## Configuration

All per-instance values live in `config/kaine.toml` plus `config/kaine.user.toml`.
The first-run wizard writes the user file. Secrets are loaded from
`compose/.env`.

```sh
source compose/.env
.venv/bin/python -m kaine.setup
```

## Preboot check

```sh
set -a; source compose/.env; set +a
.venv/bin/python -m kaine.preboot
```

PASS means the entity can proceed to boot.

## Running tests

```sh
set -a; source compose/.env; set +a
.venv/bin/python -m pytest -q
```

Targeted suites save time, for example:

```sh
.venv/bin/python -m pytest -q tests/test_welfare_signal_unblended.py tests/test_staged_adapter_promotion.py
```

## Paper and research tracking

Paper-facing change notes are kept in `docs/records/paper-update-queue.md`.
OpenSpec changes live under `openspec/changes/` and can be validated with:

```sh
openspec validate <change-name> --strict
```

## Recent direction

The current branch work concentrates on a single shipped configuration profile,
per-entity key custody (including the software-only post-quantum escrow path),
unblended welfare readings based on the processor's own prediction error, and
atomic adapter promotion for voice alignment. For branch progress, run `git status` or inspect `docs/records/paper-update-queue.md`.
