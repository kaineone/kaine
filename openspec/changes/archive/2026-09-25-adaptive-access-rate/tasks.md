## 1. Drive computation

- [x] 1.1 `kaine/cycle/access_rate.py`: config dataclass (`enabled`, `salience_floor`, `phasic_decay_s`, `baseline_arousal`) with validation, and a pure `AccessRateController` computing tonic, phasic (held decaying peak in subjective time) and drive, and the effective rate within [resting, processing]. Cite the neuroscience at the code site and state the linear map as a modelling assumption.
- [x] 1.2 Unit tests: calm → resting; arousal 1 → ceiling; salience spike → drive 1 then decay by `exp(−Δt/τ)`; `cycle`/`syneidesis` sources ignored; disabled → drive 0; bounds; config validation.

## 2. Engine

- [x] 2.1 `CognitiveCycle`: optional controller and arousal provider; compute the effective rate each tick before `_advance_experiential`; `set_experiential_rate` sets the resting rate only; the accumulator keeps its fractional carry (fixes the clamp that made 3.333 Hz run at 2.5 Hz) and still allows at most one broadcast per tick.
- [x] 2.2 `cycle.tick` payload gains `experiential_rate_hz` (effective) and `access_drive`; runtime state gains `experiential_rate_effective_hz` and `access_drive`.
- [x] 2.3 Engine tests with the spec's scenarios (broadcast counts at rest, at full arousal, after a spike, disabled, operator resting-rate change, deterministic repeat).

## 3. Wiring and config

- [x] 3.1 `kaine/cycle/__main__.py`: build the controller from `[cycle.access_rate]` (baseline defaulting to `[thymos].baseline_arousal`) and pass an arousal provider from the `AffectStateProvider`; the affect snapshot is refreshed each tick when adaptation is enabled.
- [x] 3.2 `config/kaine.toml`: `[cycle.access_rate]` with defaults and the neuroscience in the comment; replace the "future work" note.
- [x] 3.3 Nexus shows the effective rate beside the resting rate.

## 4. Docs

- [x] 4.1 `docs/processes/cognitive-cycle.md`, `docs/configuration.md`, `docs/modules/chronos.md` describe the adaptive rate as current behaviour.
- [x] 4.2 Tell the paper and poster owners that only the conscious-access rate adapts; the processing-rate claim is an open question.
