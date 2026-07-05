## ADDED Requirements

### Requirement: build_registry logs device assignment per module
`kaine.boot.build_registry` SHALL emit one log line per
GPU-or-CPU-pinned module (Topos, Mnemos, Chronos, AudioInput's
emotion classifier, Hypnos training device) of the form
`"device assignment: <module> → <device>"` after the registry is
built and before the function returns. Operators reading the cycle
startup log SHALL see at a glance where each module landed.

#### Scenario: Topos pinned to cuda:1 is logged
- **WHEN** `[topos].device = "cuda:1"` and `build_registry` runs
- **THEN** the log contains `"device assignment: topos → cuda:1"`

### Requirement: Cycle entrypoint tunes CPU threads on boot
`kaine.cycle.__main__.main` SHALL call
`kaine.hardware.tune_cpu_threads()` once before constructing the
registry. The setting SHALL be applied before any module's
`initialize()` runs.

#### Scenario: Thread count constrained before module init
- **WHEN** the cycle entrypoint starts on a 32-thread host
- **THEN** `torch.get_num_threads()` is at most 16 by the time the
  first module is constructed
