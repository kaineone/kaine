## Why

Four configuration leftovers describe behaviour KAINE does not have.

- `[hypnos].nous_step_burst` is accepted and stored on the sleep module but never read.
  It sized a belief-revision burst that stepped the planning module during sleep. The paper's
  sleep has no such phase (§3.5: memory replay, synaptic downscaling,
  associative replay, voice adaptation, then the affective reset), and the planning module now
  updates on replayed traces in the ordinary cycle. The sleep module's `nous_process`
  argument is stored and never read for the same reason, and boot always passes
  `None`. The only code that used either is `revise_beliefs` in
  `kaine/modules/sleep/phases.py`, a legacy function that no sleep calls.
- `[thymos].social_drive_time_scale_s` is accepted and validated but unused. In
  the paper the social drive builds at its build rate once the entity has heard
  a voice and is relieved each time it hears one again (§3.5, A.4, Table A1:
  build, decay and relief per interaction). No time scale enters it.
- `KAINE_MODEL_SERVER_URL` is set in `compose/kaine.organ-host.yml` and read by
  nothing. The host organ is reached through `[lingua].chat_url`, as that
  file's header already says.
- `scripts/probe-host` tells the operator to apply its recommendation with
  `KAINE_PROFILE=tier1` or `--profile tier1`. Those select a module profile and
  do not apply a tier; the tier is applied with `KAINE_TIER` or
  `[deployment].tier`.

## What Changes

- The sleep module loses its `nous_process` and `nous_step_burst` arguments, the sleep module
  factory and the registry stop passing them, and `revise_beliefs` with its
  `_SupportsStep` protocol is deleted.
- The affect module loses its `social_drive_time_scale_s` argument and its validation.
- Both keys leave `config/kaine.toml`, the configuration reference, the module
  pages and the specs.
- An operator file that still sets a removed key keeps booting. The factory
  accepts the key, ignores it and logs a warning naming it, so the operator
  learns it can be deleted. This follows the existing treatment of
  `[thymos.coupling].coupling_max_rate_per_s`, which was ignored silently and
  now logs the same warning through a shared helper in `kaine/boot/errors.py`.
- `KAINE_MODEL_SERVER_URL` leaves the organ-host compose override.
- The probe's docstring and its printed advice name `KAINE_TIER`.
- Two stale spec passages that listed a belief-revision sleep phase now list
  the phases the sleep module runs.

## Capabilities

### Modified Capabilities

- `hypnos`: default configuration without `nous_step_burst`, the real phase
  list, and retired keys ignored with a warning.
- `hypnos-consolidation`: The sleep module takes no planning module collaborator.
- `thymos`: retired keys ignored with a warning.
- `host-probe`: the probe names the tier selector.
- `voice-alignment-training`: the missing-extras scenario lists the real phases.

## Impact

- `kaine/modules/sleep/module.py`, `kaine/modules/sleep/phases.py`,
  `kaine/modules/affect/module.py`, `kaine/boot/errors.py`,
  `kaine/boot/factories/sleep.py`, `kaine/boot/factories/affect.py`,
  `kaine/boot/registry.py`, `scripts/probe-host`,
  `compose/kaine.organ-host.yml`, `config/kaine.toml`, tests, and the docs
  pages that listed the keys.
- No behaviour of a running entity changes. An operator file that sets a
  removed key boots as before, with one warning per key.
