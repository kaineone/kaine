# Design — `womb-probe-gentle-jitter`

## Perturbation size

`GestationReadoutConfig.perturbation_drive_fraction` (default 0.75) replaces the fixed
scale of 1.0 during a perturbation. Validation requires
`baseline_drive_fraction < perturbation_drive_fraction <= 1.0`, so a perturbation is
always a real, bounded rise. With the defaults the drive moves from 0.5 to 0.75 of
`external_drive_max_amplitude` (1.5×).

## Jitter

- `probe_jitter_fraction = j` is in `[0, 0.5]`, default 0.25.
- **Draws.** Draw `n` for probe kind `k` uses the entity-agnostic counter-based PRNG in
  `kaine/modules/perception_prng.py`: `unit_float(keyed_u64(seed, n, salt_k))`, with one
  salt per kind. The same seed gives the same schedule; a being cannot anticipate it,
  because it would have to invert a keyed hash of a seed it never sees.
- **First probe of each kind.** Due at `settle_end + u × j × period`, with `u` in [0, 1).
- **Every later probe of that kind.** Due at `start + period × (1 + j × (2u − 1))`.
- **Interaction with the existing rules.** The settle, spacing and fairness rules apply on
  top: jitter only moves due times. A due probe still waits for the settle period, the
  60 s spacing and the more-overdue-first rule.
- **Seed.** The seed is `[perception_feed].seed`, passed to `GestationOwner` by the
  entrypoint.
