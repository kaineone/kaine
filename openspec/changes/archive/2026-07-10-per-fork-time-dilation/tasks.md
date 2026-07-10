# Tasks — per-fork subjective-time profile (Phase 4)

## 1. Profile model (lifecycle)
- [x] 1.1 Add a typed `ForkTimingProfile` + `fork_timing_profile(snapshot) ->
      ForkTimingProfile | None` that parses/validates `metadata["timing"]`
      (`time_scale` required-if-present and > 0; optional `processing_rate_hz`,
      `experiential_rate_hz`, `vision_sample_hz`; invalid → loud error). Lives in
      the lifecycle layer next to ForkSnapshot; boundary-safe.
- [x] 1.2 Confirm `ForkManager.fork(...)` round-trips the `timing` metadata
      (it already accepts `metadata`); add a small helper/overload if it makes
      attaching a profile cleaner, but do NOT change the merge/assimilation logic.

## 2. Apply-at-spawn seam (runtime)
- [x] 2.1 `apply_fork_timing_profile(profile, entity_clock, cycle) -> dict`:
      set `entity_clock.scale`, apply rate overrides via the existing
      `cycle.set_processing_rate` / `set_rates` path and the Topos
      `vision_sample_hz` knob; return a summary. No-op when profile is None.
- [x] 2.2 Wire it where a fork is restored-to-run in the cycle runtime, AFTER
      `ForkManager.restore(...)`. Behavior-preserving when no profile.
      NOTE: no existing "restore a fork into the running cycle to RUN at its own
      speed" call site exists today (the one `ForkManager.restore` site is Spot's
      crash-recovery last-good restore, where applying a timing profile would be
      WRONG). Per design.md, the seam is exposed as a public, unit-tested function
      (`kaine.cycle.fork_timing.apply_fork_timing_profile`) that drops into the
      `distributed-substrate` runtime later; no fake call site was invented.

## 3. API + surfacing
- [x] 3.1 `ForkRequestBody` (`kaine/nexus/diagnostics.py`) gains optional
      `time_scale` + rate overrides; `create_fork` packs them into
      `metadata["timing"]` and calls the existing `fork(metadata=...)`.
- [x] 3.2 `GET /forks.json` surfaces a fork's `timing` profile (read-only).

## 4. Tests
- [x] 4.1 Profile parse/validate (valid / absent→None / time_scale<=0 runnable→error).
- [x] 4.2 `fork()` round-trips a timing profile through metadata.
- [x] 4.3 `apply_fork_timing_profile` sets clock scale + cycle rates via injected
      fakes; no-op for a profile-less fork.
- [x] 4.4 `POST /forks` with `time_scale` stores it; `GET /forks.json` surfaces it.
- [x] 4.5 Behavior-preserving: profile-less fork changes neither clock nor rates.

## 5. Verify
- [x] 5.1 `openspec validate per-fork-time-dilation --strict`.
- [x] 5.2 Full suite green; `lint-imports` green; no entity booted.
- [x] 5.3 No change to the fork/merge/assimilation system itself (diff is additive).
