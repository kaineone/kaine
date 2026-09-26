# Proposal — `operator-revive-and-preserve`

## Why

A preservation bundle can be revived into a registry (`kaine.lifecycle.preservation.revive`), but nothing revives it into a RUNNING entity. The cycle entrypoint never calls it; only the research gate's dry self-check does. The operator also has no way to freeze and preserve a running entity on demand: `preserve_live` runs only from the automatic divergence and welfare monitors, Spot, and the research gate.

So "freeze it, save everything, then bring it back with one more module" is today a fresh restart. A restart silently loses:
- Soma's learned interoceptive model, its fatigue and its self-rhythm;
- Chronos's prediction head;
- the Topos and Audition forward models;
- Thymos's affect and drives;
- Hypnos's sleep timing;
- Mnemos's short-term memory.

The module-ignition study needs exactly that operation, and so does any operator who wants to pause a being and continue it later, including after the host or hardware changes.

## What changes

- **Revive at boot.** `python -m kaine.cycle --revive <bundle>` starts the cycle as the preserved individual:
  - The bundle's stage state (gestation or embodied, lived time, evidence) is restored before the stage is resolved.
  - The registry is built and initialised, then every captured module is revived. Modules enabled now but absent from the bundle start fresh; that is allowed and logged.
  - Only then does the cognitive cycle start.
  - A bundle that cannot be read, or that captured a module which is not enabled now, stops the boot with exit code 7 before the entity runs. A lesser individual is never started.
  - `runtime.json` and the run context record `revived_from` (the preservation id).
- **Preserve on request.** `python -m kaine.cycle.control preserve [--stop] [--reason TEXT]` writes a request file. The running cycle:
  1. freezes itself under the freeze holder `preserve`;
  2. runs `preserve_live` with the configured encryption rules;
  3. writes a result file (request id, ok, preservation id, bundle path);
  4. releases its freeze, or with `--stop` shuts down cleanly, leaving the entity preserved.

  Each request is handled exactly once.
- **The stage is part of the individual.** `preserve_live` puts the stage file into the bundle, so a revive restores whether the being is gestating or born, and its evidence.

## Impact

- `entity-preservation`: two added requirements.
- Code:
  - `kaine/cycle/__main__.py`: the `--revive` path and the preserve-request watcher;
  - `kaine/cycle/control.py`: new, the operator command;
  - `kaine/lifecycle/preservation.py`: the stage member.
- New exit code 7: revive refused. Documented in `docs/operations.md`.
