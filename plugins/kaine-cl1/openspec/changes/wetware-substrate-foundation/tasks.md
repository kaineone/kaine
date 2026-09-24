## 1. Substrate session

- [x] 1.1 Implement `SubstrateSession` owning one `cl.open()` for the process;
      resolve `SubstrateConfig` from `[substrate]` and set the SDK env knobs
      (`CL_SDK_ACCELERATED_TIME`, `CL_SDK_REPLAY_PATH`, `CL_SDK_RANDOM_SEED`,
      visualisation off) — `kaine_cl1/substrate/session.py`; loader in
      `kaine_cl1/config.py`.
- [x] 1.2 Target the simulator unless an explicit `[substrate].target = "hardware"`
      opt-in is set — `SubstrateSession.open()` refuses when target≠hardware and
      `cl.is_simulator()` is False.
- [x] 1.3 Deterministic-run test: verified reproducible via the deterministic
      `ReferenceCulture` source — `test_reference_source_is_deterministic`,
      `test_broker_is_deterministic`. (Finding: the SDK's *default* random source
      is only reproducible across fresh processes; its in-process re-open
      continues the timeline. Our source removes that dependency.)

## 2. Substrate broker

- [x] 2.1 `SubstrateBroker.allocate(module, count)` leases disjoint channels;
      raises `OversubscribedError` on sum > usable — `substrate/broker.py`.
- [x] 2.2 `run_cognitive_tick()`: delivers queued stim, drives the single
      `neurons.loop()`, splits spikes by territory into `TerritoryObservation`s.
      (Aggregates by exact timestamp span + spillover buffer — the reproducible
      unit — rather than counting nondeterministically-sized loop ticks.)
- [x] 2.3 `territory_map()` exposes the lease map for the run manifest.
      (Manifest file emission lands with the boot in §5.)
- [x] 2.4 Isolation + oversubscription tests —
      `test_broker_territory_isolation_and_stim_response`,
      `test_oversubscription_fails_at_allocation`, `test_route_isolates_by_territory`.
      Also reserves channel 0, which the simulator cannot stimulate
      (`test_channel_zero_is_unstimulable`).

## 3. Cadence bridging

- [x] 3.1 `nesting_factor_for(ticks_per_second, cognitive_rate)` enforces an
      integer nesting — `test_nesting_factor`.
- [x] 3.2 Aggregate the sub-ticks in one cognitive tick into one per-territory
      observation — `test_cognitive_tick_aggregates_subticks`.
- [ ] 3.3 Non-blocking guarantee: accelerated-time covers offline/sim runs today;
      the background-thread path for real-time hardware lands with hardware work.
      (Starvation probe deferred to the hardware phase.)

## 4. Codecs

- [x] 4.1 Rate / population encoders clamp+validate to SDK limits at construction
      — `RateEncoder`, `PopulationEncoder`; `test_encoder_never_exceeds_limits`.
      (Temporal encoder lands with Chronos, which needs it.)
- [x] 4.2 Decoders: `FiringRateDecoder` (per-channel scalar) and `SurpriseDecoder`
      (Lempel-Ziv disorder vs rolling baseline → [0,1]). Functional-connectivity
      decoder deferred to the module that first needs it (Empatheia/Nous).
- [x] 4.3 Property tests: encoder safety, LZ orders disorder, surprise rises for
      disordered vs quiet responses — pure and on live sim spikes
      (`test_surprise_*`).

## 5. Downstream boot

- [x] 5.1 Downstream injection seam implemented and tested against real `kaine`
      (the full multi-module registry is the remaining part):
      `kaine_cl1/boot.py:wetware_injection(module, broker, territory)` returns the
      `(constructor_kwarg, injected_object)` for a converted module (Chronos →
      `("network", WetwareTimingModel)`), shared broker + session. The full
      multi-module `build_wetware_registry` over an `OverlayConfig` generalises
      this once Soma/Oscillator/Nous land.
      Done as a kaine plugin (change `kaine-plugin-package`): kaine's own
      `build_registry` constructs Chronos with the plugin's network
      (`tests/test_kaine_boot.py`); further modules add rows to `WETWARE_BACKENDS`.
- [ ] 5.2 For any module lacking an injection seam, open an upstream PR adding a
      **vendor-neutral** seam (silicon default unchanged); until merged, use a
      pinned subclass override in this repo — never edit the kaine dependency.
- [ ] 5.3 Preserve KAINE's boot gating (operator-supervised / verified safety
      net); the overlay must not loosen it.

## 6. Validation

- [x] 6.1 `openspec validate wetware-substrate-foundation --strict` passes.
- [x] 6.2 Real-KAINE integration proven for the reference conversion: stock
      Chronos with the injected wetware network publishes the same `chronos.out`
      contract as silicon (`tests/test_chronos_integration.py`). The zero-converted
      inertness check lands with the full `build_wetware_registry`.
- [x] 6.3 Reproduction + findings documented — `docs/foundation-results.md`.
