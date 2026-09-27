# Proposal — `cycle-runtime-contract`

## Why

The import contract "Modules must not import the cycle runtime" lists the forbidden `kaine.cycle` submodules by name, and says a new runtime submodule must be added by hand. Thirteen were never added: `access_rate`, `affect_state`, `caretaker`, `caretaker_runtime`, `caretaker_state`, `fork_timing`, `gestation`, `input_check`, `spot_selftest`, `unattended_gate`, `womb_presence`, `womb_watch` and the package itself. A module could import any of them and the contract would stay green. A test with `import kaine.cycle.gestation` in `kaine/modules/nous/module.py` confirms it: the contract is KEPT.

## What changes

- The contract forbids the whole `kaine.cycle` package and ignores imports of `kaine.cycle.types`, the one declared exception. Every runtime submodule, present and future, is covered with no list to maintain.
- The spec's layering requirement says so.

## Impact

- `pyproject.toml` only. All eight contracts stay kept. The same test import now breaks the contract.
