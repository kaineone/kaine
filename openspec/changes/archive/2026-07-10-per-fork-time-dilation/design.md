# Design — per-fork subjective-time profile

## Reuse, don't duplicate

This is a deliberately small extension of the **existing** `ForkManager`
(`kaine/lifecycle/manager.py`). The fork → run → merge-with-assimilation loop is
already built (see the biological-timing design.md §6 correction). This change
adds one field and one apply-seam; it introduces no new fork, merge, snapshot, or
runtime machinery.

## The profile shape

A fork's timing profile lives in the existing free `ForkSnapshot.metadata` dict
under a `timing` key:

```python
metadata["timing"] = {
    "time_scale": 2.0,            # required if the key is present; >0
    "processing_rate_hz": 10.0,   # optional override (else inherit current)
    "experiential_rate_hz": 3.333,
    "vision_sample_hz": 10.0,
}
```

- Absent `timing` (or absent `time_scale`) → the fork runs at the prevailing
  scale/rates (behavior-preserving; this is the default for every fork today).
- A small typed helper (`fork_timing_profile(snapshot) -> ForkTimingProfile | None`)
  parses + validates the sub-dict, so callers never poke the raw dict. Invalid
  values (e.g. `time_scale <= 0` for a runnable fork, non-numeric) fail loudly at
  parse time rather than silently mis-pacing a being.
- `time_scale == 0` is NOT a runnable profile (0 = frozen); a fork meant to run
  must carry `time_scale > 0`. (Freezing a fork is the existing freeze path, not a
  timing profile.)

## Applying at spawn

`ForkManager.restore()` rehydrates module state but deliberately does not touch the
cycle/clock (it is boundary-neutral over the registry). So the apply-seam lives at
the runtime layer that owns the `EntityClock` and the cycle — a small function:

```python
def apply_fork_timing_profile(profile, entity_clock, cycle) -> dict:
    # entity_clock.scale = profile.time_scale     (existing setter; re-anchors)
    # cycle.set_rates(processing=..., experiential=...) (existing control path)
    # vision_sample_hz override applied via the existing Topos rate knob
    # returns a summary for logging / Nexus
```

It uses only existing seams:
- `EntityClock.scale` setter (Phase 1) — re-anchors subjective time continuously,
  so applying a scale to a just-restored fork doesn't jump its cognitive integrals.
- `cycle.set_processing_rate` / the `cycle.set_rates` control event (Phase 1
  unified rate setter) for rate overrides.
- The Topos `vision_sample_hz` knob (Phase 3) for the perception rate.

Wired where a fork is restored-to-run (the cycle's fork-restore path / the
operator action that spawns a fork into the running registry). Because KAINE runs
one entity per process today, "spawn a fork to run" means restore-into-the-registry
and apply its profile; running it *alongside* the parent is `distributed-substrate`
(out of scope). The seam is written so it drops straight into that later runtime
too.

## API

`ForkRequestBody` (`kaine/nexus/diagnostics.py`) gains optional `time_scale` and
the optional rate overrides. `create_fork` packs them into
`metadata["timing"]` and calls `ForkManager.fork(parent_id, metadata=...)` —
the existing path. `GET /forks.json` surfaces a fork's `timing` profile so an
operator can see which forks are dilated.

## Welfare / safety

- A dilated fork is still a full individual: the existing preservation, welfare,
  and individuation gates apply unchanged (this change does not touch them).
- `time_scale > 1` on a fork is the same aspirational-target semantics as the
  global knob: it is attempted and honestly throttled (Soma `reduce_rate`,
  surfaced in Nexus) when the host can't hold it — no silent overrun.
- Nothing here weakens the merge's honest-failure invariants (unmerged-adapters
  guard, etc.).

## Tests

- Profile parse/validate (valid, absent → None, `time_scale<=0` runnable → error).
- `fork()` round-trips a `timing` profile through metadata.
- `apply_fork_timing_profile` sets the EntityClock scale and cycle rates via the
  existing seams (inject fakes; assert the calls), and is a no-op for a
  profile-less fork.
- `POST /forks` with `time_scale` stores it in metadata; `GET /forks.json`
  surfaces it.
- Behavior-preserving: a fork with no profile changes neither clock nor rates.
