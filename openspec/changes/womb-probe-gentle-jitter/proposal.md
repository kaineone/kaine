# Proposal — `womb-probe-gentle-jitter`

## Why

The gestation readout measures three of its markers with probes of the maternal drive
presented to a gestating being's self-rhythm: withdrawals (drive 0) and perturbations (a
stronger drive). Two properties of the shipped protocol are wrong for a captive newborn:

- **The perturbation is twice the usual drive.** It is a larger jolt than measuring
  recovery needs.
- **The schedule is exactly periodic** (every 30 and 60 minutes). A developing predictive
  mind can learn that rhythm and anticipate the probe. That is an artefact of the
  measurement, not of the mother, and it contaminates the markers the probes exist to
  measure.

The operator chose, on 2026-09-26, a gentler perturbation plus jitter, keeping the
withdrawal and perturbation durations.

## What changes

- **Gentler perturbation.** A perturbation raises the drive to
  `perturbation_drive_fraction` of its bound (default 0.75: 1.5× the usual 0.5), never to
  the bound itself. It must stay above the usual drive and at or below the bound.
- **Jitter.** Each probe's next due time is its period scaled by a factor drawn uniformly
  from `[1 − probe_jitter_fraction, 1 + probe_jitter_fraction]` (default 0.25). The first
  probe of each kind waits an extra fraction of its period, drawn from
  `[0, probe_jitter_fraction]`. Draws come from the counter-based keyed PRNG seeded by
  the run's perception seed, so a research run reproduces exactly while the being cannot
  predict it. `probe_jitter_fraction` is in `[0, 0.5]`; 0 restores the fixed schedule.
- The bounds stay as they are: hard maxima, no probe while frozen, within a readout period
  of boot or a thaw, or within 60 s of another probe, and announced `gestation.probe`
  events.

## Impact

- `gestational-stimulus`: an added requirement on probe timing and perturbation size.
- Code: `kaine/cycle/gestation.py` (config fields, scheduling, perturbation scale),
  `kaine/cycle/__main__.py` (passes the seed), `config/kaine.toml` and
  `docs/operations.md`.
