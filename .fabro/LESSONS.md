# Factory lessons for Kaine

Carried over from the retired dark-factory controller (its state and lessons files
are archived under `/run/media/erik/2TBm2Store/kaine/backups/retired-dark-factory-2026-11-22/`).

- 2026-11-19, task 1.1 (`gpu_inventory()` in `kaine.hardware`): the worker wrote a
  placeholder line ("(Existing content of the file, if any, is unchanged)") into
  `kaine/hardware.py` instead of the file body. `kaine/__init__.py` imports that
  module, so every test failed at conftest import, and three heal attempts made no
  progress because each one saw the same import error. A plan for this repo should
  ask for complete file bodies, and a run that fails at collection is a broken edit,
  not a failing test: read the first error, not the summary.
- Earlier agent runs (#826, #829, #834) damaged guard tests, shipped config and
  accepted specs while reporting success. Those paths are now in `protected_globs`.
