## 1. Forward model

- [x] 1.1 `kaine/modules/soma/forward.py` — `SubstrateForwardModel` (ncps CfC, CPU) predicting next feature vector from current + recurrent state; tiny online SGD step per tick; non-finite-loss guard
- [x] 1.2 Compute prediction error `e(t) = ||x(t) − x̂(t−1)||`; expose on `soma.report` and drive event salience from it

## 2. Fatigue accumulator

- [x] 2.1 `kaine/modules/soma/fatigue.py` — `FatigueAccumulator` (integrate error, continuous decay, faster decay flag for sleep, reset())
- [x] 2.2 Publish `soma.fatigue` event when value crosses `fatigue_maintenance_threshold`; include value/threshold on `soma.report`

## 3. Homeostatic regulation

- [x] 3.1 `kaine/modules/soma/regulation.py` — sustained-error detector over `regulation_sustain_window_s`
- [x] 3.2 Publish advisory `soma.regulation {action, reason, severity}` (reduce_rate | shed_module | request_maintenance)

## 4. Module + config

- [x] 4.1 Wire forward model / fatigue / regulation into `Soma.initialize`/loop; subscribe to `hypnos.sleep.started`/`hypnos.sleep.completed` to set `_in_hypnos` flag that suspends online adaptation; reset fatigue on maintenance end
- [x] 4.2 `serialize()`/`deserialize()` persist forward-model weights + fatigue value
- [x] 4.3 `[soma]` config: `forward_model_units`, `prediction_error_window`, `fatigue_decay_per_s`, `fatigue_maintenance_threshold`, `regulation_sustain_window_s`, `regulation_threshold`; update `make_soma` allowed keys

## 5. Cycle engine consumer

- [x] 5.1 Wire `kaine/cycle/engine.py` to subscribe to `soma.out` and drain `soma.regulation` events: `reduce_rate` → adjust tick interval within bounds; `shed_module` → request low-priority module suspension; `request_maintenance` → set flag Hypnos reads to schedule earlier offline cycle; log each advisory; ignore unknown `action` values gracefully

## 6. Faithful renderer templates

- [x] 6.1 Register a `_t_soma_fatigue` template in `kaine/faithful/templates.py` for `("soma", "soma.fatigue")` that renders value, threshold, and crossed flag as a human-readable sentence
- [x] 6.2 Register a `_t_soma_regulation` template in `kaine/faithful/templates.py` for `("soma", "soma.regulation")` that renders action, reason, and severity

## 7. Tests

- [x] 7.1 `tests/test_soma_forward.py` — predictor shape, online step reduces error on a stationary signal, non-finite guard
- [x] 7.2 `tests/test_soma_fatigue.py` — accumulation, decay, threshold crossing emits `soma.fatigue`, reset
- [x] 7.3 `tests/test_soma_regulation.py` — sustained error emits `soma.regulation`; transient error does not
- [x] 7.4 `tests/test_soma_module.py` — `soma.report` carries prediction_error + fatigue; serialize/deserialize roundtrip
- [x] 7.5 `tests/test_soma_hypnos_flag.py` — `Soma._in_hypnos` is `False` at start; becomes `True` after `hypnos.sleep.started`; forward-model weights unchanged during that window; becomes `False` after `hypnos.sleep.completed` and adaptation resumes

## 6. Verification

- [x] 6.1 Full unit suite green
- [x] 6.2 `openspec validate soma-forward-model-fatigue --strict` clean
- [x] 6.3 Commit (Kaine.One), branch-per-change, merge, archive
