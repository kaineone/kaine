## 1. Backend

- [x] 1.1 Implement `WetwareTimingModel` satisfying Chronos' forward-model client
      interface — matches `CfCNetwork.tick(feature_vec) -> hidden` plus `units`,
      `input_size`, `reset`, `state_dict` — `kaine_cl1/backends/chronos.py`.
- [x] 1.2 Encoder: temporal feature → population stim on the Chronos territory
      (`PopulationEncoder`; feature projected + squashed to per-channel amplitudes).
- [x] 1.3 Decoder: territory spikes → hidden state (`FiringRateDecoder`, scaled).
      Chronos' own prediction head + error machinery run on this hidden state.

## 2. Wiring

- [x] 2.1 Injection seam confirmed at the pinned commit: `Chronos(bus, network=…)`
      uses the injected network and only builds the silicon `CfCNetwork` when it is
      `None` (`kaine/modules/chronos/module.py`). No upstream change needed —
      `WetwareTimingModel` is a drop-in for `network=`.
- [x] 2.2 No missing seam ⇒ no upstream PR / subclass override required for Chronos.
- [x] 2.3 Live wiring `Chronos(bus, network=WetwareTimingModel(...))` runs against
      the **real** installed `kaine` (pinned commit) over a fakeredis bus, via
      `kaine_cl1.boot.wetware_injection("chronos", …)` →
      `tests/test_chronos_integration.py`. `has_network` is True; the biological
      network drives the module.

## 3. Acceptance (simulator)

- [x] 3.1 `chronos.out` schema-equality between `cl1` and silicon — executed:
      wetware-backed and silicon-backed Chronos publish `chronos.report` with
      identical payload keys (`test_event_schema_matches_silicon`).
- [x] 3.2 Cadence: Chronos runs its forward path each `on_workspace` through the
      broker's cognitive-tick drive and publishes without error over multiple
      ticks (`test_wetware_network_injects_into_real_chronos`). Full autonomous
      cognitive-cycle participation lands with the multi-module boot.
- [x] 3.3 **Predictive-work criterion** (the load-bearing test): on a structured
      (periodic) feature sequence the prediction error is materially lower than on
      a scrambled one — measured ~0.39 vs ~1.60 (4× margin) on the simulator.
      `tests/test_chronos_wetware.py::test_predictive_work_structured_vs_scrambled`.
      Also: hidden state reflects the encoded input; interface matches `CfCNetwork`.
- [x] 3.4 `openspec validate chronos-on-wetware --strict` passes.
